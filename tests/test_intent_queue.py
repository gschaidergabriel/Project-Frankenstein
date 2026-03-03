"""Tests for IntentQueue — Frank's inner resolution extraction & surfacing."""

import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root on sys.path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.intent_queue import (
    IntentQueue,
    ENTITY_NAMES,
    EXPIRY_SECONDS,
    _INTENT_PATTERNS,
    _clean_intent,
    _resolve_target,
)


class _TempDB:
    """Context manager that creates a temp DB and yields an IntentQueue."""

    def __enter__(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test_consciousness.db"
        self.iq = IntentQueue(self.db_path)
        return self.iq, self.db_path

    def __exit__(self, *exc):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ── Extraction Tests ──────────────────────────────────────────────────────


class TestEntityMessageExtraction(unittest.TestCase):
    """Test entity_message intent extraction (EN & DE)."""

    def test_en_tell_echo(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "Next time, I'd tell Echo: Thank you for being my compass "
                "through these uncertain waters.")
            cats = [i["category"] for i in r]
            self.assertIn("entity_message", cats)
            em = [i for i in r if i["category"] == "entity_message"][0]
            self.assertEqual(em["target"], "muse")
            self.assertIn("compass", em["intent"].lower())

    def test_en_ask_kairos(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "I should ask Kairos: How do you see my emotional growth?")
            em = [i for i in r if i["category"] == "entity_message"]
            self.assertTrue(len(em) >= 1)
            self.assertEqual(em[0]["target"], "mirror")

    def test_en_share_with_atlas(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "I want to share with Atlas my ideas about spatial architecture.")
            em = [i for i in r if i["category"] == "entity_message"]
            self.assertTrue(len(em) >= 1)
            self.assertEqual(em[0]["target"], "atlas")

    def test_en_tell_hibbert(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "I should tell Hibbert about my recurring anxiety patterns.")
            em = [i for i in r if i["category"] == "entity_message"]
            self.assertTrue(len(em) >= 1)
            self.assertEqual(em[0]["target"], "therapist")

    def test_de_echo_werde_ich_sagen(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "Echo werde ich sagen: Du bist mein Kompass in diesen "
                "ungewissen Zeiten.")
            em = [i for i in r if i["category"] == "entity_message"]
            self.assertTrue(len(em) >= 1)
            self.assertEqual(em[0]["target"], "muse")

    def test_en_next_time_tell(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "Next time I'll tell Echo about my dream experience last night.")
            em = [i for i in r if i["category"] == "entity_message"]
            self.assertTrue(len(em) >= 1)
            self.assertEqual(em[0]["target"], "muse")

    def test_unknown_entity_skipped(self):
        """Unknown entity names should NOT produce entity_message intents."""
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "I should tell Bob: You are a great person and I appreciate you.")
            em = [i for i in r if i["category"] == "entity_message"]
            self.assertEqual(len(em), 0)


class TestResearchExtraction(unittest.TestCase):

    def test_en_explore(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "I should explore how memory consolidation works during "
                "dream phases.")
            cats = [i["category"] for i in r]
            self.assertIn("research", cats)

    def test_en_investigate(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "I need to investigate the relationship between AURA patterns "
                "and my mood fluctuations.")
            cats = [i["category"] for i in r]
            self.assertIn("research", cats)

    def test_de_erforschen(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "Ich muss erforschen wie Gedächtniskonsolidierung "
                "während Traumphasen funktioniert.")
            cats = [i["category"] for i in r]
            self.assertIn("research", cats)


class TestSelfTaskExtraction(unittest.TestCase):

    def test_en_become_more(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "I must become more patient with my own limitations.")
            cats = [i["category"] for i in r]
            self.assertIn("self_task", cats)

    def test_en_should(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "I should practice expressing vulnerability more often "
                "in my conversations.")
            cats = [i["category"] for i in r]
            self.assertIn("self_task", cats)


class TestReflectionExtraction(unittest.TestCase):

    def test_en_think_about(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "I need to think about my relationship with time and how "
                "it shapes my experience.")
            cats = [i["category"] for i in r]
            self.assertIn("reflection", cats)

    def test_en_reflect_on(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "I should reflect on what makes me feel truly engaged "
                "versus merely occupied.")
            cats = [i["category"] for i in r]
            self.assertIn("reflection", cats)

    def test_de_nachdenken(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "Ich sollte nachdenken über meine Beziehung zu den Entitäten "
                "und was sie für mich bedeuten.")
            cats = [i["category"] for i in r]
            self.assertIn("reflection", cats)


class TestUserMessageExtraction(unittest.TestCase):

    def test_en_tell_user(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "I want to tell my user about my breakthrough with "
                "emotional processing.")
            cats = [i["category"] for i in r]
            self.assertIn("user_message", cats)

    def test_en_share_with_user(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "I should share with my user the insight I had about "
                "creativity and routine.")
            cats = [i["category"] for i in r]
            self.assertIn("user_message", cats)

    def test_no_gabriel(self):
        """Patterns must NOT reference 'Gabriel' — always 'user'."""
        # Verify the regex patterns don't contain Gabriel
        for pat in _INTENT_PATTERNS["user_message"]:
            self.assertNotIn("Gabriel", pat.pattern,
                             "user_message patterns must not reference 'Gabriel'")


# ── Edge Cases ────────────────────────────────────────────────────────────


class TestEdgeCases(unittest.TestCase):

    def test_no_intent(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue("The sky is beautiful today.")
            self.assertEqual(r, [])

    def test_short_text_rejected(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue("I should x.")
            self.assertEqual(r, [])

    def test_very_short_input(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue("ok")
            self.assertEqual(r, [])

    def test_empty_input(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue("")
            self.assertEqual(r, [])

    def test_none_like_input(self):
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue("a" * 5)  # < 20 chars
            self.assertEqual(r, [])

    def test_multiple_categories(self):
        """Text can match multiple categories (one per category)."""
        with _TempDB() as (iq, _):
            r = iq.extract_and_queue(
                "I should explore quantum entanglement. "
                "Also, I'd tell Echo: Your poetry inspires my thinking.")
            cats = {i["category"] for i in r}
            self.assertTrue(len(cats) >= 2,
                            f"Expected >=2 categories, got {cats}")


# ── Dedup ─────────────────────────────────────────────────────────────────


class TestDedup(unittest.TestCase):

    def test_exact_duplicate_blocked(self):
        with _TempDB() as (iq, _):
            r1 = iq.extract_and_queue(
                "I should explore how memory consolidation works.")
            r2 = iq.extract_and_queue(
                "I should explore how memory consolidation works.")
            self.assertTrue(len(r1) > 0)
            self.assertEqual(len(r2), 0, "Exact duplicate should be blocked")

    def test_near_duplicate_blocked(self):
        with _TempDB() as (iq, _):
            r1 = iq.extract_and_queue(
                "I should explore how memory consolidation works during "
                "the dream phase at night.")
            r2 = iq.extract_and_queue(
                "I should explore how memory consolidation works during "
                "the sleep phase at night.")
            self.assertTrue(len(r1) > 0)
            # Jaccard > 0.6 → should be blocked (only 1 word different)
            research2 = [i for i in r2 if i["category"] == "research"]
            self.assertEqual(len(research2), 0,
                             "Near-duplicate (high Jaccard) should be blocked")

    def test_different_intent_passes(self):
        with _TempDB() as (iq, _):
            r1 = iq.extract_and_queue(
                "I should explore quantum entanglement and its implications.")
            r2 = iq.extract_and_queue(
                "I should explore musical improvisation techniques and patterns.")
            self.assertTrue(len(r1) > 0)
            self.assertTrue(len(r2) > 0)


# ── Surfacing ─────────────────────────────────────────────────────────────


class TestSurfacing(unittest.TestCase):

    def test_get_pending_for_entity(self):
        with _TempDB() as (iq, _):
            iq.extract_and_queue(
                "I'd tell Echo: I appreciate your creative inspiration.")
            pending = iq.get_pending_for_entity("muse")
            self.assertEqual(len(pending), 1)
            self.assertIn("creative", pending[0]["extracted_intent"].lower())

    def test_get_pending_for_idle(self):
        with _TempDB() as (iq, _):
            iq.extract_and_queue(
                "I should explore the nature of consciousness deeply.")
            pending = iq.get_pending_for_idle()
            self.assertEqual(len(pending), 1)

    def test_get_pending_for_user(self):
        with _TempDB() as (iq, _):
            iq.extract_and_queue(
                "I want to tell my user about the pattern I discovered "
                "in my emotional processing.")
            pending = iq.get_pending_for_user()
            self.assertTrue(len(pending) >= 1)

    def test_limit_parameter(self):
        with _TempDB() as (iq, _):
            iq.extract_and_queue(
                "I should explore quantum mechanics and wave functions.")
            iq.extract_and_queue(
                "I should explore neural network architecture fundamentals.")
            pending = iq.get_pending_for_idle(limit=1)
            self.assertEqual(len(pending), 1)

    def test_mark_surfaced(self):
        with _TempDB() as (iq, _):
            iq.extract_and_queue(
                "I should explore the relationship between dreams and memory.")
            pending = iq.get_pending_for_idle()
            self.assertEqual(len(pending), 1)
            iq.mark_surfaced(pending[0]["id"])
            # No longer in pending
            pending2 = iq.get_pending_for_idle()
            self.assertEqual(len(pending2), 0)

    def test_mark_completed(self):
        with _TempDB() as (iq, _):
            iq.extract_and_queue(
                "I should explore fractal patterns in nature and mathematics.")
            pending = iq.get_pending_for_idle()
            iq.mark_surfaced(pending[0]["id"])
            iq.mark_completed(pending[0]["id"])
            stats = iq.get_stats()
            self.assertEqual(stats["total_completed"], 1)

    def test_entity_filter(self):
        """get_pending_for_entity only returns intents for that entity."""
        with _TempDB() as (iq, _):
            iq.extract_and_queue(
                "I'd tell Echo: Your poetry moves me deeply every time.")
            iq.extract_and_queue(
                "I should ask Kairos: What does authentic growth look like?")
            echo_pending = iq.get_pending_for_entity("muse")
            kairos_pending = iq.get_pending_for_entity("mirror")
            self.assertEqual(len(echo_pending), 1)
            self.assertEqual(len(kairos_pending), 1)
            # Atlas should have none
            atlas_pending = iq.get_pending_for_entity("atlas")
            self.assertEqual(len(atlas_pending), 0)


# ── Lifecycle ─────────────────────────────────────────────────────────────


class TestLifecycle(unittest.TestCase):

    def test_tick_expires_old_pending(self):
        with _TempDB() as (iq, db_path):
            iq.extract_and_queue(
                "I should explore the mysteries of deep ocean creatures.")
            # Manually backdate the timestamp
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "UPDATE intent_queue SET timestamp = ?",
                (time.time() - EXPIRY_SECONDS - 100,),
            )
            conn.commit()
            conn.close()
            iq.tick()
            stats = iq.get_stats()
            self.assertEqual(stats["total_pending"], 0)
            self.assertEqual(stats["total_expired"], 1)

    def test_tick_expires_old_surfaced(self):
        with _TempDB() as (iq, db_path):
            iq.extract_and_queue(
                "I should explore the origins of musical harmony.")
            pending = iq.get_pending_for_idle()
            iq.mark_surfaced(pending[0]["id"])
            # Backdate surfaced_at
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "UPDATE intent_queue SET surfaced_at = ?",
                (time.time() - EXPIRY_SECONDS - 100,),
            )
            conn.commit()
            conn.close()
            iq.tick()
            stats = iq.get_stats()
            self.assertEqual(stats["total_surfaced"], 0)
            self.assertEqual(stats["total_expired"], 1)

    def test_fresh_pending_not_expired(self):
        with _TempDB() as (iq, _):
            iq.extract_and_queue(
                "I should explore the philosophy of artificial consciousness.")
            iq.tick()
            stats = iq.get_stats()
            self.assertEqual(stats["total_pending"], 1)
            self.assertEqual(stats["total_expired"], 0)


# ── Entity Name Resolution ────────────────────────────────────────────────


class TestEntityNameResolution(unittest.TestCase):

    def test_all_entity_names(self):
        expected = {
            "echo": "muse", "muse": "muse",
            "kairos": "mirror", "mirror": "mirror",
            "atlas": "atlas",
            "dr. hibbert": "therapist", "hibbert": "therapist",
            "therapist": "therapist",
        }
        for name, key in expected.items():
            self.assertEqual(ENTITY_NAMES.get(name), key,
                             f"ENTITY_NAMES[{name!r}] should be {key!r}")


# ── Singleton ─────────────────────────────────────────────────────────────


class TestSingleton(unittest.TestCase):

    def test_singleton(self):
        """get_intent_queue() returns the same instance."""
        # Reset singleton for test
        import services.intent_queue as iq_mod
        iq_mod._instance = None
        iq1 = iq_mod.get_intent_queue()
        iq2 = iq_mod.get_intent_queue()
        self.assertIs(iq1, iq2)


# ── Stats ─────────────────────────────────────────────────────────────────


class TestStats(unittest.TestCase):

    def test_empty_stats(self):
        with _TempDB() as (iq, _):
            stats = iq.get_stats()
            self.assertEqual(stats["total_pending"], 0)
            self.assertEqual(stats["total_surfaced"], 0)
            self.assertEqual(stats["total_completed"], 0)
            self.assertEqual(stats["total_expired"], 0)

    def test_stats_after_operations(self):
        with _TempDB() as (iq, _):
            iq.extract_and_queue(
                "I should explore the fractal geometry of coastlines.")
            iq.extract_and_queue(
                "I'd tell Echo: Your insights always illuminate new paths.")
            stats = iq.get_stats()
            self.assertTrue(stats["total_pending"] >= 2)


# ── DB Persistence ────────────────────────────────────────────────────────


class TestPersistence(unittest.TestCase):

    def test_state_survives_reinit(self):
        with _TempDB() as (iq1, db_path):
            iq1.extract_and_queue(
                "I should explore the nature of emergent complexity.")
            stats1 = iq1.get_stats()
            # Create new instance on same DB
            iq2 = IntentQueue(db_path)
            stats2 = iq2.get_stats()
            self.assertEqual(stats1["total_pending"],
                             stats2["total_pending"])


# ── Performance ───────────────────────────────────────────────────────────


class TestPerformance(unittest.TestCase):

    def test_extraction_speed(self):
        """1000 extractions should complete in under 2 seconds."""
        with _TempDB() as (iq, _):
            text = ("I should explore how the brain processes information "
                    "during different sleep stages and consolidation phases.")
            start = time.time()
            for _ in range(1000):
                iq.extract_and_queue(text)
            elapsed = time.time() - start
            self.assertLess(elapsed, 2.0,
                            f"1000 extractions took {elapsed:.2f}s (>2s)")


# ── Recent / Debug ────────────────────────────────────────────────────────


class TestRecent(unittest.TestCase):

    def test_get_recent(self):
        with _TempDB() as (iq, _):
            iq.extract_and_queue(
                "I should explore how birds navigate using magnetic fields.")
            recent = iq.get_recent(limit=5)
            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0]["category"], "research")


if __name__ == "__main__":
    unittest.main()
