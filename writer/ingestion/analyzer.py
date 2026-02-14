"""
AI-powered Document Analyzer for Frank Writer
Uses Frank AI for intelligent document analysis
"""

import logging
import re
import json
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DocumentAnalysis:
    """Result of document analysis"""
    # Summary
    summary: str = ""
    abstract: str = ""

    # Keywords and topics
    keywords: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)

    # Structure analysis
    structure: Dict[str, Any] = field(default_factory=dict)
    sections: List[Dict[str, Any]] = field(default_factory=list)
    word_count: int = 0
    paragraph_count: int = 0
    sentence_count: int = 0

    # Style analysis
    tone: str = ""  # formal, informal, technical, casual, academic
    reading_level: str = ""  # basic, intermediate, advanced, expert
    language: str = ""  # detected language (en, de, etc.)

    # Quality metrics
    clarity_score: float = 0.0  # 0.0 to 1.0
    coherence_score: float = 0.0  # 0.0 to 1.0
    suggestions: List[str] = field(default_factory=list)

    # Metadata extracted
    title: str = ""
    author: str = ""
    date: str = ""
    references: List[str] = field(default_factory=list)


@dataclass
class StyleAnalysis:
    """Result of style analysis"""
    formality: str = "neutral"  # formal, informal, neutral
    technicality: str = "general"  # technical, general, casual
    tone: str = "neutral"  # academic, professional, conversational, creative
    voice: str = "active"  # active, passive, mixed
    complexity: str = "medium"  # simple, medium, complex

    # Statistics
    avg_sentence_length: float = 0.0
    avg_word_length: float = 0.0
    passive_voice_ratio: float = 0.0
    technical_term_ratio: float = 0.0


class DocumentAnalyzer:
    """
    AI-powered document analyzer using Frank AI

    Provides intelligent analysis of documents including:
    - Content summarization
    - Keyword extraction
    - Structure analysis
    - Style detection
    - Quality assessment
    """

    def __init__(self, ai_bridge=None, config=None):
        """
        Initialize document analyzer

        Args:
            ai_bridge: Optional FrankBridge instance for AI features
            config: Optional configuration object
        """
        self.ai_bridge = ai_bridge
        self.config = config
        self._ai_available = ai_bridge is not None

    def analyze(self, content: str, file_format=None) -> DocumentAnalysis:
        """
        Analyze document content

        Args:
            content: Document content as string
            file_format: Optional FileFormat enum for format-specific analysis

        Returns:
            DocumentAnalysis with all analysis results
        """
        analysis = DocumentAnalysis()

        if not content or not content.strip():
            logger.warning("Empty content provided for analysis")
            return analysis

        # Basic statistics (always available)
        analysis.word_count = self._count_words(content)
        analysis.paragraph_count = self._count_paragraphs(content)
        analysis.sentence_count = self._count_sentences(content)

        # Structure analysis
        analysis.structure = self._analyze_structure(content)
        analysis.sections = self._extract_sections(content)

        # Extract basic metadata
        analysis.title = self._extract_title(content)

        # Keyword extraction (rule-based fallback)
        analysis.keywords = self.extract_keywords(content)

        # Style detection (rule-based)
        style = self.detect_style(content)
        analysis.tone = style.tone
        analysis.reading_level = self._estimate_reading_level(content)

        # Language detection
        analysis.language = self._detect_language(content)

        # AI-powered analysis if available
        if self._ai_available:
            self._enhance_with_ai(content, analysis)

        return analysis

    def extract_keywords(self, content: str, max_keywords: int = 10) -> List[str]:
        """
        Extract key terms from content

        Uses AI if available, otherwise falls back to TF-IDF-like extraction

        Args:
            content: Document content
            max_keywords: Maximum number of keywords to return

        Returns:
            List of keyword strings
        """
        if self._ai_available:
            keywords = self._ai_extract_keywords(content, max_keywords)
            if keywords:
                return keywords

        # Rule-based extraction as fallback
        return self._rule_based_keywords(content, max_keywords)

    def detect_style(self, content: str) -> StyleAnalysis:
        """
        Detect writing style characteristics

        Args:
            content: Document content

        Returns:
            StyleAnalysis with style metrics
        """
        style = StyleAnalysis()

        if not content:
            return style

        sentences = self._split_sentences(content)
        words = content.split()

        # Calculate basic metrics
        if sentences:
            style.avg_sentence_length = len(words) / len(sentences)

        if words:
            style.avg_word_length = sum(len(w) for w in words) / len(words)

        # Detect formality
        style.formality = self._detect_formality(content)

        # Detect technicality
        style.technicality = self._detect_technicality(content)

        # Detect tone
        style.tone = self._detect_tone(content)

        # Detect voice
        style.voice, style.passive_voice_ratio = self._detect_voice(content)

        # Detect complexity
        style.complexity = self._detect_complexity(style.avg_sentence_length, style.avg_word_length)

        return style

    def summarize(self, content: str, max_length: int = 200) -> str:
        """
        Generate summary of content

        Args:
            content: Document content
            max_length: Maximum length of summary

        Returns:
            Summary string
        """
        if self._ai_available:
            summary = self._ai_summarize(content, max_length)
            if summary:
                return summary

        # Fallback: extract first paragraph or sentences
        return self._extractive_summary(content, max_length)

    def get_suggestions(self, content: str) -> List[str]:
        """
        Get improvement suggestions for the document

        Args:
            content: Document content

        Returns:
            List of suggestion strings
        """
        suggestions = []

        if not content:
            suggestions.append("Document is empty. Start writing!")
            return suggestions

        # Basic checks
        word_count = self._count_words(content)
        if word_count < 100:
            suggestions.append("Consider expanding the document with more details.")

        sentences = self._split_sentences(content)
        if sentences:
            avg_len = word_count / len(sentences)
            if avg_len > 30:
                suggestions.append("Some sentences are quite long. Consider breaking them up for clarity.")
            if avg_len < 8:
                suggestions.append("Sentences are very short. Consider combining related ideas.")

        # Check for structure
        if not any(line.startswith('#') for line in content.split('\n')):
            suggestions.append("Consider adding headings to organize your content.")

        # Check for passive voice
        passive_phrases = self._count_passive_phrases(content)
        if passive_phrases > len(sentences) * 0.3:
            suggestions.append("High use of passive voice detected. Consider using more active voice.")

        # AI suggestions if available
        if self._ai_available:
            ai_suggestions = self._ai_suggestions(content)
            if ai_suggestions:
                suggestions.extend(ai_suggestions)

        return suggestions

    # --- Private methods for rule-based analysis ---

    def _count_words(self, content: str) -> int:
        """Count words in content"""
        return len(content.split())

    def _count_paragraphs(self, content: str) -> int:
        """Count paragraphs (separated by blank lines)"""
        paragraphs = re.split(r'\n\s*\n', content)
        return len([p for p in paragraphs if p.strip()])

    def _count_sentences(self, content: str) -> int:
        """Count sentences"""
        return len(self._split_sentences(content))

    def _split_sentences(self, content: str) -> List[str]:
        """Split content into sentences"""
        # Simple sentence splitting
        sentences = re.split(r'[.!?]+(?=\s|$)', content)
        return [s.strip() for s in sentences if s.strip()]

    def _analyze_structure(self, content: str) -> Dict[str, Any]:
        """Analyze document structure"""
        lines = content.split('\n')
        structure = {
            'has_title': False,
            'has_headings': False,
            'has_lists': False,
            'has_code_blocks': False,
            'has_links': False,
            'has_images': False,
            'heading_count': 0,
            'list_count': 0,
            'code_block_count': 0,
        }

        in_code_block = False
        for line in lines:
            stripped = line.strip()

            # Code blocks
            if stripped.startswith('```'):
                in_code_block = not in_code_block
                if not in_code_block:
                    structure['code_block_count'] += 1
                    structure['has_code_blocks'] = True
                continue

            if in_code_block:
                continue

            # Headings
            if stripped.startswith('#'):
                structure['has_headings'] = True
                structure['heading_count'] += 1
                if stripped.startswith('# ') and not structure['has_title']:
                    structure['has_title'] = True

            # Lists
            if re.match(r'^[-*+]\s|^\d+\.\s', stripped):
                structure['has_lists'] = True
                structure['list_count'] += 1

            # Links
            if re.search(r'\[.+\]\(.+\)', stripped):
                structure['has_links'] = True

            # Images
            if re.search(r'!\[.+\]\(.+\)', stripped):
                structure['has_images'] = True

        return structure

    def _extract_sections(self, content: str) -> List[Dict[str, Any]]:
        """Extract document sections from headings"""
        sections = []
        lines = content.split('\n')
        current_section = None
        section_start = 0

        for i, line in enumerate(lines):
            if line.startswith('#'):
                # Save previous section
                if current_section:
                    current_section['end_line'] = i - 1
                    current_section['content'] = '\n'.join(lines[section_start:i])
                    sections.append(current_section)

                # Start new section
                level = len(line) - len(line.lstrip('#'))
                title = line.lstrip('#').strip()
                current_section = {
                    'level': level,
                    'title': title,
                    'start_line': i,
                    'end_line': len(lines) - 1,
                    'content': ''
                }
                section_start = i + 1

        # Add last section
        if current_section:
            current_section['content'] = '\n'.join(lines[section_start:])
            sections.append(current_section)

        return sections

    def _extract_title(self, content: str) -> str:
        """Extract document title from first heading"""
        for line in content.split('\n'):
            if line.startswith('# '):
                return line[2:].strip()
        return ""

    def _rule_based_keywords(self, content: str, max_keywords: int) -> List[str]:
        """Extract keywords using rule-based approach"""
        # Clean and tokenize
        text = re.sub(r'[^\w\s]', ' ', content.lower())
        words = text.split()

        # Filter stop words
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'must', 'can', 'this', 'that',
            'these', 'those', 'it', 'its', 'they', 'them', 'their', 'we', 'us',
            'our', 'you', 'your', 'he', 'him', 'his', 'she', 'her', 'as', 'if',
            'when', 'where', 'why', 'how', 'what', 'which', 'who', 'whom', 'not',
            'no', 'so', 'up', 'out', 'about', 'into', 'over', 'after', 'before',
            'between', 'under', 'again', 'further', 'then', 'once', 'here', 'there',
            'all', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'than',
            'too', 'very', 'just', 'also', 'now', 'only',
            # German stop words
            'der', 'die', 'das', 'ein', 'eine', 'und', 'oder', 'aber', 'in', 'auf',
            'an', 'zu', 'fur', 'von', 'mit', 'bei', 'aus', 'ist', 'sind', 'war',
            'waren', 'sein', 'haben', 'hat', 'hatte', 'wird', 'werden', 'kann',
            'konnen', 'muss', 'mussen', 'soll', 'sollen', 'darf', 'durfen', 'dies',
            'diese', 'dieser', 'es', 'sie', 'er', 'wir', 'ihr', 'als', 'wenn',
            'wie', 'was', 'wer', 'wo', 'warum', 'nicht', 'noch', 'nur', 'auch',
        }

        # Count word frequencies
        word_freq = {}
        for word in words:
            if len(word) > 2 and word not in stop_words:
                word_freq[word] = word_freq.get(word, 0) + 1

        # Sort by frequency and return top keywords
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [word for word, _ in sorted_words[:max_keywords]]

    def _detect_formality(self, content: str) -> str:
        """Detect formality level"""
        content_lower = content.lower()

        informal_markers = ['gonna', "gotta", "wanna", "kinda", "sorta", "stuff",
                           "things", "guy", "guys", "cool", "awesome", "yeah",
                           "ok", "okay", "hey", "wow", "!", "lol", "btw"]
        formal_markers = ['therefore', 'furthermore', 'moreover', 'hence',
                         'consequently', 'nevertheless', 'notwithstanding',
                         'accordingly', 'subsequently', 'henceforth']

        informal_count = sum(1 for m in informal_markers if m in content_lower)
        formal_count = sum(1 for m in formal_markers if m in content_lower)

        if formal_count > informal_count + 2:
            return "formal"
        elif informal_count > formal_count + 2:
            return "informal"
        return "neutral"

    def _detect_technicality(self, content: str) -> str:
        """Detect technical level"""
        # Look for technical indicators
        technical_patterns = [
            r'\b(algorithm|function|variable|parameter|API|database|server|client)\b',
            r'\b(equation|theorem|hypothesis|coefficient|integral|derivative)\b',
            r'\b(implementation|architecture|framework|protocol|interface)\b',
            r'\b(config|setup|install|deploy|compile|debug|test)\b',
        ]

        technical_count = sum(
            len(re.findall(pattern, content, re.IGNORECASE))
            for pattern in technical_patterns
        )

        words = len(content.split())
        if words == 0:
            return "general"

        ratio = technical_count / words
        if ratio > 0.05:
            return "technical"
        elif ratio > 0.02:
            return "semi-technical"
        return "general"

    def _detect_tone(self, content: str) -> str:
        """Detect writing tone"""
        content_lower = content.lower()

        # Academic tone indicators
        academic_markers = ['research', 'study', 'findings', 'methodology',
                           'hypothesis', 'analysis', 'literature', 'evidence',
                           'conclusion', 'abstract', 'references']
        # Professional tone
        professional_markers = ['please', 'thank you', 'regards', 'sincerely',
                               'meeting', 'schedule', 'deadline', 'project',
                               'team', 'stakeholder', 'deliverable']
        # Conversational tone
        conversational_markers = ["i'm", "you're", "we're", "let's", "here's",
                                  "that's", "it's", 'hey', 'so', 'well',
                                  'basically', 'actually']
        # Creative tone
        creative_markers = ['imagine', 'dream', 'wonder', 'beautiful', 'mysterious',
                           'adventure', 'journey', 'discover', 'explore']

        counts = {
            'academic': sum(1 for m in academic_markers if m in content_lower),
            'professional': sum(1 for m in professional_markers if m in content_lower),
            'conversational': sum(1 for m in conversational_markers if m in content_lower),
            'creative': sum(1 for m in creative_markers if m in content_lower),
        }

        max_tone = max(counts, key=counts.get)
        if counts[max_tone] < 2:
            return "neutral"
        return max_tone

    def _detect_voice(self, content: str) -> tuple:
        """Detect active vs passive voice"""
        passive_count = self._count_passive_phrases(content)
        sentences = self._split_sentences(content)
        total = len(sentences) if sentences else 1

        ratio = passive_count / total

        if ratio > 0.4:
            return "passive", ratio
        elif ratio < 0.15:
            return "active", ratio
        return "mixed", ratio

    def _count_passive_phrases(self, content: str) -> int:
        """Count passive voice constructions"""
        passive_patterns = [
            r'\b(is|are|was|were|been|being)\s+\w+ed\b',
            r'\b(is|are|was|were|been|being)\s+\w+en\b',
            r'\bby\s+(the|a|an)\s+\w+\b',
        ]
        count = 0
        for pattern in passive_patterns:
            count += len(re.findall(pattern, content, re.IGNORECASE))
        return count

    def _detect_complexity(self, avg_sentence_length: float, avg_word_length: float) -> str:
        """Detect text complexity"""
        if avg_sentence_length > 25 and avg_word_length > 5.5:
            return "complex"
        elif avg_sentence_length < 12 and avg_word_length < 4.5:
            return "simple"
        return "medium"

    def _estimate_reading_level(self, content: str) -> str:
        """Estimate reading level"""
        words = content.split()
        sentences = self._split_sentences(content)

        if not words or not sentences:
            return "unknown"

        avg_word_len = sum(len(w) for w in words) / len(words)
        avg_sent_len = len(words) / len(sentences)

        # Simplified Flesch-Kincaid approximation
        score = 0.39 * avg_sent_len + 11.8 * (avg_word_len / 5) - 15.59

        if score < 6:
            return "basic"
        elif score < 10:
            return "intermediate"
        elif score < 14:
            return "advanced"
        return "expert"

    def _detect_language(self, content: str) -> str:
        """Detect content language"""
        content_lower = content.lower()

        # Simple language detection based on common words
        english_words = {'the', 'is', 'are', 'and', 'of', 'to', 'in', 'that', 'it', 'for'}
        german_words = {'der', 'die', 'das', 'und', 'ist', 'sind', 'von', 'zu', 'in', 'ein'}

        words = set(re.findall(r'\b\w+\b', content_lower))

        en_count = len(words & english_words)
        de_count = len(words & german_words)

        if de_count > en_count:
            return "de"
        return "en"

    def _extractive_summary(self, content: str, max_length: int) -> str:
        """Generate extractive summary (first sentences)"""
        sentences = self._split_sentences(content)
        if not sentences:
            return ""

        summary = []
        current_length = 0

        for sentence in sentences:
            if current_length + len(sentence) > max_length:
                break
            summary.append(sentence)
            current_length += len(sentence)

        return '. '.join(summary) + '.' if summary else ""

    # --- AI-enhanced methods ---

    def _enhance_with_ai(self, content: str, analysis: DocumentAnalysis):
        """Enhance analysis with AI capabilities"""
        try:
            # Get AI summary
            ai_summary = self._ai_summarize(content, 300)
            if ai_summary:
                analysis.summary = ai_summary

            # Get AI suggestions
            ai_suggestions = self._ai_suggestions(content)
            if ai_suggestions:
                analysis.suggestions = ai_suggestions

        except Exception as e:
            logger.warning(f"AI enhancement failed: {e}")

    def _ai_extract_keywords(self, content: str, max_keywords: int) -> List[str]:
        """Extract keywords using AI"""
        if not self.ai_bridge:
            return []

        try:
            prompt = f"""Extract the {max_keywords} most important keywords/key phrases from this text.
Return only the keywords as a comma-separated list, no explanation.

Text:
{content[:3000]}

Keywords:"""

            response = self.ai_bridge.chat(prompt)
            if response.success and response.content:
                # Parse comma-separated keywords
                keywords = [k.strip() for k in response.content.split(',')]
                return keywords[:max_keywords]
        except Exception as e:
            logger.warning(f"AI keyword extraction failed: {e}")

        return []

    def _ai_summarize(self, content: str, max_length: int) -> str:
        """Generate summary using AI"""
        if not self.ai_bridge:
            return ""

        try:
            prompt = f"""Summarize the following text in about {max_length} characters.
Be concise but capture the main points.

Text:
{content[:4000]}

Summary:"""

            response = self.ai_bridge.chat(prompt)
            if response.success:
                return response.content.strip()
        except Exception as e:
            logger.warning(f"AI summarization failed: {e}")

        return ""

    def _ai_suggestions(self, content: str) -> List[str]:
        """Get improvement suggestions from AI"""
        if not self.ai_bridge:
            return []

        try:
            prompt = f"""Analyze this document and provide 3-5 specific suggestions for improvement.
Focus on clarity, structure, and effectiveness.
Return suggestions as a numbered list.

Document:
{content[:3000]}

Suggestions:"""

            response = self.ai_bridge.chat(prompt)
            if response.success and response.content:
                # Parse numbered suggestions
                suggestions = []
                for line in response.content.split('\n'):
                    line = line.strip()
                    if line and (line[0].isdigit() or line.startswith('-')):
                        # Remove numbering/bullets
                        clean = re.sub(r'^[\d\.\-\*\)]+\s*', '', line)
                        if clean:
                            suggestions.append(clean)
                return suggestions
        except Exception as e:
            logger.warning(f"AI suggestions failed: {e}")

        return []


def analyze_document(content: str, ai_bridge=None) -> DocumentAnalysis:
    """Convenience function for document analysis"""
    analyzer = DocumentAnalyzer(ai_bridge=ai_bridge)
    return analyzer.analyze(content)
