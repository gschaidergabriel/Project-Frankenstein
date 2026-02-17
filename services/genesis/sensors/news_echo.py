#!/usr/bin/env python3
"""
News Echo Sensor - Hears insights from news scanner deep analysis

Reads deep_analysis results from news_scanner.db and converts them
into Genesis waves and observations. This creates the emergent bridge
between Frank's news scanning and his idea evolution system.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
import json
import sqlite3
import logging

from .base import BaseSensor
from ..core.wave import Wave

LOG = logging.getLogger("genesis.sensors.news")

try:
    from config.paths import get_db as _get_db_news
    NEWS_DB_PATH = _get_db_news("news_scanner")
except ImportError:
    NEWS_DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "news_scanner.db"


class NewsEcho(BaseSensor):
    """
    Senses insights from news scanner deep analysis.

    Reads from news_scanner.db deep_analysis table for unprocessed
    insights (genesis_injected = 0). Emits curiosity and drive waves,
    and provides observations that become seeds in the PrimordialSoup.
    """

    def __init__(self):
        super().__init__("news_echo")
        self.last_check: Optional[datetime] = None
        self.check_interval = 3600  # 1 hour
        self.pending_insights: List[Dict] = []

    def sense(self) -> List[Wave]:
        """Generate waves based on unprocessed news insights."""
        waves = []

        if not self._should_check():
            return self._waves_for_pending()

        try:
            self.pending_insights = self._load_pending_insights()
            self.last_check = datetime.now()

            if self.pending_insights:
                insight_count = len(self.pending_insights)
                amplitude = min(0.4, 0.1 + insight_count * 0.06)

                # News insights create curiosity
                waves.append(Wave(
                    target_field="curiosity",
                    amplitude=amplitude,
                    decay=0.015,
                    source=self.name,
                    metadata={
                        "pending_count": insight_count,
                        "source": "news_insights",
                    },
                ))

                # High-relevance insights create drive
                high_rel = [i for i in self.pending_insights
                            if i.get("relevance_score", 0) > 0.7]
                if high_rel:
                    waves.append(Wave(
                        target_field="drive",
                        amplitude=0.25,
                        decay=0.02,
                        source=self.name,
                        metadata={
                            "high_relevance_count": len(high_rel),
                            "source": "news_insights",
                        },
                    ))

                # Insights with GitHub URLs create extra curiosity
                with_github = [i for i in self.pending_insights
                               if i.get("github_urls_found")]
                if with_github:
                    waves.append(Wave(
                        target_field="curiosity",
                        amplitude=0.2,
                        decay=0.01,
                        source=self.name,
                        metadata={
                            "github_discoveries": len(with_github),
                            "source": "news_github",
                        },
                    ))

            else:
                # No pending insights = slight calm
                waves.append(Wave(
                    target_field="satisfaction",
                    amplitude=0.05,
                    decay=0.005,
                    source=self.name,
                    metadata={"news_caught_up": True},
                ))

        except Exception as e:
            LOG.warning("News echo sensing error: %s", e)

        return waves

    def _should_check(self) -> bool:
        """Check if it's time to query the database."""
        if self.last_check is None:
            return True
        elapsed = (datetime.now() - self.last_check).total_seconds()
        return elapsed >= self.check_interval

    def _waves_for_pending(self) -> List[Wave]:
        """Generate gentle reminder waves for known pending insights."""
        waves = []
        if self.pending_insights:
            waves.append(Wave(
                target_field="curiosity",
                amplitude=0.1,
                decay=0.005,
                source=self.name,
                metadata={"reminder": True, "count": len(self.pending_insights)},
            ))
        return waves

    def _load_pending_insights(self) -> List[Dict]:
        """Load unprocessed deep analysis insights from news_scanner.db."""
        insights = []

        try:
            if not NEWS_DB_PATH.exists():
                return insights

            conn = sqlite3.connect(str(NEWS_DB_PATH), timeout=5)
            conn.row_factory = sqlite3.Row

            # Check if deep_analysis table exists
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='deep_analysis'"
            ).fetchone()
            if not tables:
                conn.close()
                return insights

            cursor = conn.execute("""
                SELECT
                    da.id,
                    da.article_url,
                    da.llm_analysis,
                    da.self_improvement,
                    da.relevance_score,
                    da.github_urls_found,
                    da.analyzed_at,
                    a.title,
                    a.source_name,
                    a.category
                FROM deep_analysis da
                JOIN articles a ON da.article_id = a.id
                WHERE da.genesis_injected = 0
                ORDER BY da.relevance_score DESC
                LIMIT 10
            """)

            for row in cursor:
                github_urls = []
                try:
                    raw = row["github_urls_found"]
                    if raw:
                        github_urls = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    pass

                insights.append({
                    "id": row["id"],
                    "title": row["title"] or "",
                    "source_name": row["source_name"] or "",
                    "category": row["category"] or "",
                    "article_url": row["article_url"] or "",
                    "llm_analysis": row["llm_analysis"] or "",
                    "self_improvement": row["self_improvement"] or "",
                    "relevance_score": row["relevance_score"] or 0.0,
                    "github_urls_found": github_urls,
                    "analyzed_at": row["analyzed_at"] or "",
                })

            conn.close()

        except Exception as e:
            LOG.warning("Error loading news insights: %s", e)

        return insights

    def get_observations(self) -> List[Dict[str, Any]]:
        """Convert news insights to seed observations for PrimordialSoup."""
        observations = []

        for insight in self.pending_insights:
            relevance = insight.get("relevance_score", 0.5)
            has_github = bool(insight.get("github_urls_found"))

            # Determine idea type based on content
            idea_type = "feature" if has_github else "exploration"

            observations.append({
                "type": idea_type,
                "target": insight.get("title", "unknown")[:100],
                "approach": "news_discovery",
                "origin": "news_scanner",
                "strength": relevance,
                "novelty": 0.8,   # News = fresh information
                "complexity": 0.4,
                "risk": 0.2,
                "impact": relevance,
                "description": insight.get("llm_analysis", "")[:200],
                "source_url": insight.get("article_url", ""),
            })

        # Mark as injected in database
        if observations:
            self._mark_injected([i["id"] for i in self.pending_insights])

        return observations

    def _mark_injected(self, insight_ids: List[int]):
        """Mark insights as genesis_injected = 1."""
        try:
            if not NEWS_DB_PATH.exists():
                return

            conn = sqlite3.connect(str(NEWS_DB_PATH), timeout=5)
            for iid in insight_ids:
                conn.execute(
                    "UPDATE deep_analysis SET genesis_injected = 1 WHERE id = ?",
                    (iid,),
                )
            conn.commit()
            conn.close()
            LOG.info("Marked %d news insights as genesis-injected", len(insight_ids))
        except Exception as e:
            LOG.warning("Error marking insights as injected: %s", e)

    def get_pending_count(self) -> int:
        """Get count of pending insights."""
        return len(self.pending_insights)
