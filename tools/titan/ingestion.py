#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Titan Ingestion Pipeline - The Architect

Extracts CLAIMS (not facts!) from text.

Epistemological distinction:
- A fact is objectively true
- A claim is something asserted to be true
- All ingested content is treated as claims with confidence levels

Database: <AICORE_BASE>/database/titan.db
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from .storage import (
    SQLiteStore, VectorStore, KnowledgeGraph,
    Node, Edge, Claim, TITAN_DB, DB_DIR
)

LOG = logging.getLogger("titan.ingestion")


# Confidence levels by origin
ORIGIN_CONFIDENCE = {
    "user": 0.8,       # User stated explicitly
    "code": 0.95,      # From code analysis
    "inference": 0.5,  # AI inference
    "observation": 0.7, # Observed behavior
    "memory": 0.6,     # From memory recall
}


@dataclass
class ExtractedClaim:
    """A claim extracted from text."""
    subject: str
    predicate: str
    obj: str  # 'object' is reserved
    confidence: float
    source_text: str = ""

    def to_triple(self) -> Tuple[str, str, str]:
        return (self.subject, self.predicate, self.obj)

    def claim_id(self) -> str:
        """Generate unique ID for this claim."""
        return hashlib.sha256(
            f"{self.subject}:{self.predicate}:{self.obj}".encode()
        ).hexdigest()[:16]


@dataclass
class ExtractionResult:
    """Result of claim extraction."""
    claims: List[ExtractedClaim] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    raw_text: str = ""
    event_id: str = ""


class ClaimExtractor:
    """
    Extracts claims from text using pattern matching.

    Uses heuristic patterns rather than LLM to maintain
    local, deterministic operation.
    """

    # Relation patterns (subject, relation, object)
    RELATION_PATTERNS = [
        # "X is Y" patterns
        (r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+is\s+(?:a|an|the)\s+(.+?)(?:\.|,|$)", "is_a"),
        (r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+is\s+(.+?)(?:\.|,|$)", "is"),

        # "X has Y" patterns
        (r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+has\s+(?:a|an|the)\s+(.+?)(?:\.|,|$)", "has"),

        # "X uses Y" patterns
        (r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+uses?\s+(.+?)(?:\.|,|$)", "uses"),

        # "X prefers Y" patterns
        (r"(?:I|[A-Z][a-z]+)\s+prefer(?:s)?\s+(.+?)(?:\s+over\s+(.+?))?(?:\.|,|$)", "prefers"),

        # "X lives in Y" patterns
        (r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+lives?\s+in\s+(.+?)(?:\.|,|$)", "lives_in"),

        # "X works at/for Y" patterns
        (r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+works?\s+(?:at|for)\s+(.+?)(?:\.|,|$)", "works_at"),

        # "X likes Y" patterns
        (r"(?:I|[A-Z][a-z]+)\s+(?:like|love|enjoy)s?\s+(.+?)(?:\.|,|$)", "likes"),

        # "X hates Y" patterns
        (r"(?:I|[A-Z][a-z]+)\s+(?:hate|dislike)s?\s+(.+?)(?:\.|,|$)", "dislikes"),

        # "X contains Y" patterns
        (r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+contains?\s+(.+?)(?:\.|,|$)", "contains"),

        # "X depends on Y" patterns
        (r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+depends?\s+on\s+(.+?)(?:\.|,|$)", "depends_on"),

        # Location patterns
        (r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+is\s+located\s+(?:in|at)\s+(.+?)(?:\.|,|$)", "located_in"),

        # Technical patterns
        (r"(\b[a-z_]+(?:\.[a-z_]+)*)\s+(?:calls?|invokes?)\s+(\b[a-z_]+(?:\.[a-z_]+)*)(?:\.|,|$)", "calls"),
        (r"(\b[a-z_]+(?:\.[a-z_]+)*)\s+(?:imports?|requires?)\s+(\b[a-z_]+(?:\.[a-z_]+)*)(?:\.|,|$)", "imports"),
    ]

    # Entity patterns
    ENTITY_PATTERNS = [
        # Proper nouns (capitalized words)
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b",
        # Technical identifiers
        r"\b([a-z_]+\.[a-z_]+(?:\.[a-z_]+)*)\b",
        # Paths
        r"(/[a-z0-9_\-/]+(?:\.[a-z]+)?)",
        # URLs
        r"(https?://[^\s]+)",
    ]

    # Topic indicators
    TOPIC_INDICATORS = [
        "about", "regarding", "concerning", "topic", "subject",
        "related to", "discussing", "focus on"
    ]

    def __init__(self):
        self._compiled_relations = [
            (re.compile(p, re.IGNORECASE), rel)
            for p, rel in self.RELATION_PATTERNS
        ]
        self._compiled_entities = [
            re.compile(p) for p in self.ENTITY_PATTERNS
        ]

    def extract_claims(self, text: str, origin: str = "user") -> List[ExtractedClaim]:
        """Extract claims from text."""
        claims = []
        base_confidence = ORIGIN_CONFIDENCE.get(origin, 0.5)

        # Split into sentences
        sentences = re.split(r'[.!?]+', text)

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 5:
                continue

            for pattern, relation in self._compiled_relations:
                matches = pattern.findall(sentence)
                for match in matches:
                    if isinstance(match, tuple) and len(match) >= 2:
                        subject = self._normalize_entity(match[0])
                        obj = self._normalize_entity(match[1])

                        if subject and obj and subject != obj:
                            claims.append(ExtractedClaim(
                                subject=subject,
                                predicate=relation,
                                obj=obj,
                                confidence=base_confidence,
                                source_text=sentence
                            ))

        return claims

    def extract_entities(self, text: str) -> List[str]:
        """Extract named entities from text."""
        entities = set()

        for pattern in self._compiled_entities:
            matches = pattern.findall(text)
            for match in matches:
                entity = self._normalize_entity(match)
                if entity and len(entity) >= 3:
                    entities.add(entity)

        return list(entities)

    def extract_topics(self, text: str) -> List[str]:
        """Extract topics from text."""
        topics = []
        text_lower = text.lower()

        for indicator in self.TOPIC_INDICATORS:
            if indicator in text_lower:
                # Find what comes after the indicator
                idx = text_lower.find(indicator) + len(indicator)
                remaining = text[idx:idx + 50].strip()
                if remaining:
                    # Take first few words
                    words = remaining.split()[:3]
                    topic = " ".join(words).strip(".,!?")
                    if topic and len(topic) >= 3:
                        topics.append(topic)

        return topics

    def _normalize_entity(self, entity: str) -> str:
        """Normalize an entity name."""
        if not entity:
            return ""

        # Strip whitespace and punctuation
        entity = entity.strip().strip(".,!?:;\"'")

        # Skip very short entities
        if len(entity) < 2:
            return ""

        # Skip common words
        common_words = {"the", "a", "an", "is", "are", "was", "were", "be", "been"}
        if entity.lower() in common_words:
            return ""

        return entity


class Architect:
    """
    The Architect - Main ingestion pipeline.

    Processes text -> extracts claims -> stores in Titan.
    """

    def __init__(self, sqlite: SQLiteStore, vectors: VectorStore,
                 graph: KnowledgeGraph):
        self.sqlite = sqlite
        self.vectors = vectors
        self.graph = graph
        self.extractor = ClaimExtractor()

    def ingest(self, text: str, origin: str = "user",
               confidence: float = None) -> ExtractionResult:
        """
        Ingest text into memory.

        Returns extraction result with claims, entities, topics.
        """
        if not text or not text.strip():
            return ExtractionResult()

        # Generate event ID
        event_id = hashlib.sha256(
            f"{text}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]

        # Base confidence from origin
        base_confidence = confidence or ORIGIN_CONFIDENCE.get(origin, 0.5)

        # Store raw event
        self.sqlite.add_event(event_id, text, origin)

        # Extract claims
        claims = self.extractor.extract_claims(text, origin)

        # Extract entities
        entities = self.extractor.extract_entities(text)

        # Extract topics
        topics = self.extractor.extract_topics(text)

        # Store claims
        now = datetime.now().isoformat()
        for claim in claims:
            # Store in claims table
            self.sqlite.add_claim(Claim(
                subject=claim.subject,
                predicate=claim.predicate,
                object=claim.obj,
                confidence=claim.confidence,
                origin=origin,
                timestamp=now,
                source_event_id=event_id
            ))

            # Add to knowledge graph
            self.graph.add_relation(
                subject=claim.subject,
                predicate=claim.predicate,
                obj=claim.obj,
                confidence=claim.confidence,
                origin=origin
            )

        # Store entities as nodes
        for entity in entities:
            node_id = hashlib.sha256(entity.encode()).hexdigest()[:16]
            if not self.sqlite.get_node(node_id):
                self.sqlite.add_node(Node(
                    id=node_id,
                    type="entity",
                    label=entity,
                    created_at=now,
                    protected=False,
                    metadata={"origin": origin}
                ))
                # Add to vector store
                self.vectors.add(node_id, entity)

        # Store memory chunk (protected for 24h to survive first maintenance cycle)
        chunk_id = f"chunk_{event_id}"
        self.sqlite.add_node(Node(
            id=chunk_id,
            type="memory",
            label=text[:100],
            created_at=now,
            protected=True,
            metadata={
                "origin": origin,
                "confidence": max(base_confidence, 0.8),
                "full_text": text,
                "event_id": event_id,
                "unprotect_after": (datetime.now() + timedelta(hours=24)).isoformat(),
            }
        ))
        self.sqlite.index_for_fts(chunk_id, text, {"origin": origin})
        self.vectors.add(chunk_id, text)

        # Link entities to memory chunk (verify both nodes exist first)
        for entity in entities:
            entity_id = hashlib.sha256(entity.encode()).hexdigest()[:16]
            if self.sqlite.get_node(entity_id) and self.sqlite.get_node(chunk_id):
                self.graph.add_relation(
                    subject=chunk_id,
                    predicate="mentions",
                    obj=entity_id,
                    confidence=base_confidence,
                    origin=origin
                )

        LOG.debug(f"Ingested text: {len(claims)} claims, {len(entities)} entities")

        return ExtractionResult(
            claims=claims,
            entities=entities,
            topics=topics,
            raw_text=text,
            event_id=event_id
        )

    def ingest_code(self, code: str, filepath: str) -> ExtractionResult:
        """
        Ingest code with higher confidence.

        Code is considered more reliable than user statements.
        """
        # Create code-specific text
        text = f"Code at {filepath}: {code[:500]}"

        result = self.ingest(text, origin="code", confidence=0.95)

        # Store code node
        code_id = hashlib.sha256(filepath.encode()).hexdigest()[:16]
        now = datetime.now().isoformat()

        self.sqlite.add_node(Node(
            id=code_id,
            type="code",
            label=filepath,
            created_at=now,
            protected=True,  # Code is protected by default
            metadata={
                "filepath": filepath,
                "content_hash": hashlib.sha256(code.encode()).hexdigest()[:16]
            }
        ))

        return result

    def add_counter_hypothesis(self, claim_id: str, counter_text: str,
                                origin: str = "inference") -> bool:
        """
        Add a counter-hypothesis to an existing claim.

        This is how Titan handles uncertainty - by storing
        alternative explanations.
        """
        counter_id = f"counter_{claim_id}_{hashlib.sha256(counter_text.encode()).hexdigest()[:8]}"
        now = datetime.now().isoformat()

        # Store counter-hypothesis
        self.sqlite.add_node(Node(
            id=counter_id,
            type="counter_hypothesis",
            label=counter_text[:100],
            created_at=now,
            protected=False,
            metadata={"full_text": counter_text, "origin": origin}
        ))

        # Link to original claim
        self.graph.add_relation(
            subject=counter_id,
            predicate="contradicts",
            obj=claim_id,
            confidence=0.5,
            origin=origin
        )

        return True


# Singleton architect instance
_architect: Optional[Architect] = None


def get_architect(sqlite: SQLiteStore, vectors: VectorStore,
                  graph: KnowledgeGraph) -> Architect:
    """Get or create architect instance."""
    global _architect
    if _architect is None:
        _architect = Architect(sqlite, vectors, graph)
    return _architect
