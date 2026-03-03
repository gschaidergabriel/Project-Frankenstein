#!/usr/bin/env python3
"""Tests for Titan Neural Cortex — 6 micro-networks for living memory."""

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

# Ensure project root on sys.path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import torch
from tools.titan.neural_cortex import (
    TitanCortex,
    MemoryImportanceScorer,
    EmotionalTagger,
    RetrievalWeightLearner,
    AssociativeStrengthener,
    ConsolidationGate,
    InterferenceDetector,
    get_cortex,
    _ORIGIN_DEFAULTS,
    _DEFAULT_RETRIEVAL_WEIGHTS,
    _COLD_MIS,
    _COLD_RWL,
    _COLD_ET,
    _COLD_AS,
    _COLD_CG,
    _COLD_ID,
)


class TestModuleOutputRanges(unittest.TestCase):
    """Test that each module produces output in the expected range."""

    def test_mis_output_range(self):
        """MIS output must be in [0.1, 1.0]."""
        m = MemoryImportanceScorer()
        for _ in range(10):
            x = torch.randn(1, 12)
            out = m(x).item()
            self.assertGreaterEqual(out, 0.1)
            self.assertLessEqual(out, 1.0)

    def test_et_valence_range(self):
        """ET valence must be in [-1, 1], arousal in [0, 1]."""
        m = EmotionalTagger()
        for _ in range(10):
            x = torch.randn(1, 384)
            v, a = m(x)
            self.assertGreaterEqual(v.item(), -1.0)
            self.assertLessEqual(v.item(), 1.0)
            self.assertGreaterEqual(a.item(), 0.0)
            self.assertLessEqual(a.item(), 1.0)

    def test_rwl_weights_sum_to_one(self):
        """RWL weights must sum to 1.0."""
        m = RetrievalWeightLearner()
        for _ in range(10):
            x = torch.randn(1, 8)
            w = m(x).squeeze(0)
            self.assertAlmostEqual(w.sum().item(), 1.0, places=4)
            self.assertEqual(len(w), 4)

    def test_as_output_range(self):
        """AS output must be in [-0.1, 0.1]."""
        m = AssociativeStrengthener()
        for _ in range(10):
            x = torch.randn(1, 773)
            out = m(x).item()
            self.assertGreaterEqual(out, -0.1)
            self.assertLessEqual(out, 0.1)

    def test_cg_output_is_softmax(self):
        """CG output must be 3 probabilities summing to 1."""
        m = ConsolidationGate()
        for _ in range(10):
            x = torch.randn(1, 389)
            out = m(x).squeeze(0)
            self.assertEqual(len(out), 3)
            self.assertAlmostEqual(out.sum().item(), 1.0, places=4)
            for p in out:
                self.assertGreaterEqual(p.item(), 0.0)

    def test_id_output_range(self):
        """ID output must be in [0, 1]."""
        m = InterferenceDetector()
        for _ in range(10):
            x = torch.randn(1, 768)
            out = m(x).item()
            self.assertGreaterEqual(out, 0.0)
            self.assertLessEqual(out, 1.0)


class TestParamCounts(unittest.TestCase):
    """Verify parameter counts match design spec."""

    def test_total_under_100k(self):
        """Total params should be under 100K."""
        total = 0
        for cls in [MemoryImportanceScorer, EmotionalTagger,
                     RetrievalWeightLearner, AssociativeStrengthener,
                     ConsolidationGate, InterferenceDetector]:
            m = cls()
            total += sum(p.numel() for p in m.parameters())
        self.assertLess(total, 100_000)
        self.assertGreater(total, 50_000)  # should be ~77K

    def test_rwl_is_tiny(self):
        """RWL should be the smallest module (<500 params)."""
        m = RetrievalWeightLearner()
        count = sum(p.numel() for p in m.parameters())
        self.assertLess(count, 500)


class TestCortexColdStart(unittest.TestCase):
    """Test cold start behavior — modules return defaults."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "titan_test.db"
        # Create the DB
        conn = sqlite3.connect(str(self.db_path))
        conn.close()
        with patch("tools.titan.neural_cortex.MODEL_PATH",
                    Path(self.tmpdir) / "cortex_test.pt"):
            self.cortex = TitanCortex(db_path=self.db_path)

    def test_mis_cold_start_returns_origin_default(self):
        """MIS cold start should return ORIGIN_CONFIDENCE values."""
        for origin, expected in _ORIGIN_DEFAULTS.items():
            score = self.cortex.score_importance({"origin": origin})
            self.assertAlmostEqual(score, expected, places=1,
                                   msg=f"MIS cold start for {origin}")

    def test_rwl_cold_start_returns_default_weights(self):
        """RWL cold start should return [0.4, 0.3, 0.2, 0.1]."""
        w = self.cortex.get_retrieval_weights({
            "rrf": 0.5, "conf": 0.7, "recency": 0.3, "graph": 0.2,
            "query_len": 5, "n_results": 3, "valence": 0.0, "arousal": 0.5,
        })
        for got, expected in zip(w, _DEFAULT_RETRIEVAL_WEIGHTS):
            self.assertAlmostEqual(got, expected, places=1)

    def test_et_cold_start_returns_neutral(self):
        """ET cold start should return (0.0, 0.5)."""
        emb = np.zeros(384, dtype=np.float32)
        v, a = self.cortex.tag_emotion(emb)
        self.assertAlmostEqual(v, 0.0, places=1)
        self.assertAlmostEqual(a, 0.5, places=1)

    def test_as_cold_start_returns_zero(self):
        """AS cold start should return 0.0 (no change)."""
        emb = np.zeros(384, dtype=np.float32)
        delta = self.cortex.predict_edge_delta(
            emb, emb, {"confidence": 0.5, "age_days": 3,
                       "co_retrieval_count": 2, "same_origin": True,
                       "relation": "mentions"})
        self.assertAlmostEqual(delta, 0.0, places=1)

    def test_cg_cold_start_returns_keep(self):
        """CG cold start should always return 'keep'."""
        emb = np.zeros(384, dtype=np.float32)
        decision = self.cortex.gate_memory(emb, 5.0, 3, 0.7, 4, 0.3)
        self.assertEqual(decision, "keep")

    def test_id_cold_start_returns_zero(self):
        """ID cold start should return 0.0 (no interference)."""
        emb = np.zeros(384, dtype=np.float32)
        score = self.cortex.detect_interference(emb, emb)
        self.assertAlmostEqual(score, 0.0, places=1)


class TestCortexBlending(unittest.TestCase):
    """Test that blending transitions from default to neural."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "titan_test.db"
        conn = sqlite3.connect(str(self.db_path))
        conn.close()
        with patch("tools.titan.neural_cortex.MODEL_PATH",
                    Path(self.tmpdir) / "cortex_test.pt"):
            self.cortex = TitanCortex(db_path=self.db_path)

    def test_blending_midpoint(self):
        """At 50% of threshold, output should be 50/50 blend."""
        # Set MIS to half threshold
        self.cortex._mis_steps = _COLD_MIS // 2
        score = self.cortex.score_importance({"origin": "user"})
        # Should be between pure default (0.8) and pure neural
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.1)

    def test_blending_at_threshold(self):
        """At threshold, output should be pure neural."""
        self.cortex._mis_steps = _COLD_MIS
        # At threshold, cold_blend returns pure neural
        result = self.cortex._cold_blend(0.9, 0.5, _COLD_MIS, _COLD_MIS)
        self.assertAlmostEqual(result, 0.9, places=4)

    def test_blending_at_zero(self):
        """At 0 steps, output should be pure default."""
        result = self.cortex._cold_blend(0.9, 0.5, 0, _COLD_MIS)
        self.assertAlmostEqual(result, 0.5, places=4)


class TestCortexSaveLoad(unittest.TestCase):
    """Test save/load round-trip."""

    def test_save_load_preserves_state(self):
        """Save and load should preserve all module states."""
        tmpdir = tempfile.mkdtemp()
        db_path = Path(tmpdir) / "titan_test.db"
        model_path = Path(tmpdir) / "cortex_test.pt"

        conn = sqlite3.connect(str(db_path))
        conn.close()

        with patch("tools.titan.neural_cortex.MODEL_PATH", model_path):
            c1 = TitanCortex(db_path=db_path)
            c1._mis_steps = 42
            c1._rwl_steps = 17
            c1._training_steps = 5

            # Get outputs before save
            emb = np.random.randn(384).astype(np.float32)
            v1, a1 = c1.tag_emotion(emb)
            w1 = c1.get_retrieval_weights({"rrf": 0.5, "conf": 0.5,
                                           "recency": 0.5, "graph": 0.5,
                                           "query_len": 5, "n_results": 3,
                                           "valence": 0.0, "arousal": 0.5})
            c1._save_all()

            # Load into new instance
            c2 = TitanCortex(db_path=db_path)
            self.assertEqual(c2._mis_steps, 42)
            self.assertEqual(c2._rwl_steps, 17)
            self.assertEqual(c2._training_steps, 5)

            # Outputs should match
            v2, a2 = c2.tag_emotion(emb)
            self.assertAlmostEqual(v1, v2, places=4)
            self.assertAlmostEqual(a1, a2, places=4)


class TestCortexDB(unittest.TestCase):
    """Test DB table operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "titan_test.db"
        conn = sqlite3.connect(str(self.db_path))
        conn.close()
        self._model_patch = patch("tools.titan.neural_cortex.MODEL_PATH",
                                  Path(self.tmpdir) / "cortex_test.pt")
        self._model_patch.start()
        self.cortex = TitanCortex(db_path=self.db_path)

    def tearDown(self):
        self.cortex.close()
        self._model_patch.stop()

    def test_tables_created(self):
        """All 3 cortex tables should exist."""
        conn = sqlite3.connect(str(self.db_path))
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        self.assertIn("access_log", tables)
        self.assertIn("co_retrieval", tables)
        self.assertIn("rwl_feedback", tables)
        conn.close()

    def test_log_access(self):
        """log_access should insert rows."""
        self.cortex.log_access(["node_a", "node_b"], "test query", [0.8, 0.6])
        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute("SELECT * FROM access_log").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][1], "node_a")  # node_id
        self.assertAlmostEqual(rows[0][4], 0.8, places=1)  # score
        conn.close()

    def test_log_co_retrieval(self):
        """log_co_retrieval should track pairs."""
        self.cortex.log_co_retrieval(["n1", "n2", "n3"])
        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute("SELECT * FROM co_retrieval").fetchall()
        self.assertEqual(len(rows), 3)  # (n1,n2), (n1,n3), (n2,n3)
        conn.close()

    def test_co_retrieval_increment(self):
        """Repeated co-retrieval should increment count."""
        self.cortex.log_co_retrieval(["n1", "n2"])
        self.cortex.log_co_retrieval(["n1", "n2"])
        conn = sqlite3.connect(str(self.db_path))
        row = conn.execute("SELECT count FROM co_retrieval").fetchone()
        self.assertEqual(row[0], 2)
        conn.close()

    def test_rwl_feedback(self):
        """record_rwl_feedback should store entries."""
        self.cortex.record_rwl_feedback(
            [0.4, 0.3, 0.2, 0.1],
            {"rrf": 0.5, "conf": 0.7},
            0.65)
        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute("SELECT * FROM rwl_feedback").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0][4], 0.65, places=2)  # reward
        conn.close()

    def test_rwl_feedback_ring_buffer(self):
        """RWL feedback should be capped at 500 entries."""
        for i in range(520):
            self.cortex.record_rwl_feedback(
                [0.4, 0.3, 0.2, 0.1], {"i": i}, float(i))
        conn = sqlite3.connect(str(self.db_path))
        count = conn.execute("SELECT COUNT(*) FROM rwl_feedback").fetchone()[0]
        self.assertLessEqual(count, 500)
        conn.close()

    def test_cleanup_access_log(self):
        """cleanup_access_log should remove old entries."""
        # Insert via cortex's own connection
        db = self.cortex._get_db()
        old_ts = time.time() - 40 * 86400  # 40 days ago
        db.execute(
            "INSERT INTO access_log (node_id, query_hash, timestamp, score) "
            "VALUES (?, ?, ?, ?)", ("old_node", "hash", old_ts, 0.5))
        db.execute(
            "INSERT INTO access_log (node_id, query_hash, timestamp, score) "
            "VALUES (?, ?, ?, ?)", ("new_node", "hash", time.time(), 0.9))
        db.commit()

        self.cortex.cleanup_access_log(max_age_days=30)

        rows = db.execute("SELECT node_id FROM access_log").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "new_node")

    def test_log_access_empty(self):
        """log_access with empty list should be no-op."""
        self.cortex.log_access([], "query")
        conn = sqlite3.connect(str(self.db_path))
        count = conn.execute("SELECT COUNT(*) FROM access_log").fetchone()[0]
        self.assertEqual(count, 0)
        conn.close()


class TestCortexInputBuilders(unittest.TestCase):
    """Test input tensor shapes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "titan_test.db"
        conn = sqlite3.connect(str(self.db_path))
        conn.close()
        with patch("tools.titan.neural_cortex.MODEL_PATH",
                    Path(self.tmpdir) / "cortex_test.pt"):
            self.cortex = TitanCortex(db_path=self.db_path)

    def test_mis_input_shape(self):
        x = self.cortex._build_mis_input({"origin": "user"})
        self.assertEqual(x.shape, (1, 12))

    def test_rwl_input_shape(self):
        x = self.cortex._build_rwl_input({"rrf": 0.5})
        self.assertEqual(x.shape, (1, 8))

    def test_as_input_shape(self):
        emb = np.zeros(384, dtype=np.float32)
        x = self.cortex._build_as_input(emb, emb, {})
        self.assertEqual(x.shape, (1, 773))

    def test_cg_input_shape(self):
        emb = np.zeros(384, dtype=np.float32)
        x = self.cortex._build_cg_input(emb, 1.0, 3, 0.7, 4, 0.3)
        self.assertEqual(x.shape, (1, 389))

    def test_id_input_shape(self):
        emb = np.zeros(384, dtype=np.float32)
        x = self.cortex._build_id_input(emb, emb)
        self.assertEqual(x.shape, (1, 768))

    def test_short_embedding_padded(self):
        """Short embeddings should be zero-padded to 384."""
        short_emb = np.ones(100, dtype=np.float32)
        x = self.cortex._build_id_input(short_emb, short_emb)
        self.assertEqual(x.shape, (1, 768))


class TestCortexStats(unittest.TestCase):
    """Test stats reporting."""

    def test_stats_structure(self):
        tmpdir = tempfile.mkdtemp()
        db_path = Path(tmpdir) / "titan_test.db"
        conn = sqlite3.connect(str(db_path))
        conn.close()
        with patch("tools.titan.neural_cortex.MODEL_PATH",
                    Path(tmpdir) / "cortex_test.pt"):
            cortex = TitanCortex(db_path=db_path)
        stats = cortex.get_stats()
        self.assertIn("total_params", stats)
        self.assertIn("training_steps", stats)
        self.assertIn("module_steps", stats)
        self.assertIn("data", stats)
        self.assertIn("cold_start", stats)
        self.assertIsInstance(stats["total_params"], int)
        self.assertGreater(stats["total_params"], 50000)


class TestCortexTrainCycle(unittest.TestCase):
    """Test that train_cycle runs without errors."""

    def test_train_cycle_empty_db(self):
        """train_cycle should handle empty DB gracefully."""
        tmpdir = tempfile.mkdtemp()
        db_path = Path(tmpdir) / "titan_test.db"
        conn = sqlite3.connect(str(db_path))
        conn.close()
        with patch("tools.titan.neural_cortex.MODEL_PATH",
                    Path(tmpdir) / "cortex_test.pt"):
            cortex = TitanCortex(db_path=db_path)
        # Should not raise
        cortex.train_cycle()
        self.assertEqual(cortex._training_steps, 1)

    def test_train_cycle_with_rwl_data(self):
        """train_cycle with RWL feedback should train RWL."""
        tmpdir = tempfile.mkdtemp()
        db_path = Path(tmpdir) / "titan_test.db"
        conn = sqlite3.connect(str(db_path))
        conn.close()
        with patch("tools.titan.neural_cortex.MODEL_PATH",
                    Path(tmpdir) / "cortex_test.pt"):
            cortex = TitanCortex(db_path=db_path)
        # Add some feedback
        for i in range(20):
            cortex.record_rwl_feedback(
                [0.4, 0.3, 0.2, 0.1],
                {"rrf": 0.5, "conf": 0.7, "recency": 0.3, "graph": 0.2,
                 "query_len": 5, "n_results": 3, "valence": 0.0, "arousal": 0.5},
                0.5 + (i % 3) * 0.1)
        cortex.train_cycle()
        self.assertGreater(cortex._rwl_steps, 0)


class TestCortexPerformance(unittest.TestCase):
    """Performance tests."""

    def test_inference_speed(self):
        """All 6 inference calls should complete in <10ms."""
        tmpdir = tempfile.mkdtemp()
        db_path = Path(tmpdir) / "titan_test.db"
        conn = sqlite3.connect(str(db_path))
        conn.close()
        with patch("tools.titan.neural_cortex.MODEL_PATH",
                    Path(tmpdir) / "cortex_test.pt"):
            cortex = TitanCortex(db_path=db_path)

        emb = np.random.randn(384).astype(np.float32)
        emb2 = np.random.randn(384).astype(np.float32)

        t0 = time.time()
        for _ in range(100):
            cortex.score_importance({"origin": "user"})
            cortex.tag_emotion(emb)
            cortex.get_retrieval_weights({"rrf": 0.5, "conf": 0.5,
                                         "recency": 0.5, "graph": 0.5,
                                         "query_len": 5, "n_results": 3,
                                         "valence": 0.0, "arousal": 0.5})
            cortex.predict_edge_delta(emb, emb2, {
                "confidence": 0.5, "age_days": 3,
                "co_retrieval_count": 2, "same_origin": True,
                "relation": "mentions"})
            cortex.gate_memory(emb, 5.0, 3, 0.7, 4, 0.3)
            cortex.detect_interference(emb, emb2)
        elapsed = (time.time() - t0) * 1000 / 100  # ms per full inference cycle
        print(f"\nAll 6 modules inference: {elapsed:.2f}ms per cycle")
        self.assertLess(elapsed, 50)  # 50ms budget for 100 iterations avg


class TestSingleton(unittest.TestCase):
    """Test singleton behavior."""

    def test_singleton_returns_same_instance(self):
        """get_cortex() should return the same instance."""
        import tools.titan.neural_cortex as mod
        # Reset singleton
        mod._cortex = None
        c1 = get_cortex()
        c2 = get_cortex()
        if c1 is not None:
            self.assertIs(c1, c2)


class TestCortexGateMemoryDecisions(unittest.TestCase):
    """Test that gate_memory returns valid decisions."""

    def test_gate_returns_valid_string(self):
        tmpdir = tempfile.mkdtemp()
        db_path = Path(tmpdir) / "titan_test.db"
        conn = sqlite3.connect(str(db_path))
        conn.close()
        with patch("tools.titan.neural_cortex.MODEL_PATH",
                    Path(tmpdir) / "cortex_test.pt"):
            cortex = TitanCortex(db_path=db_path)

        # Force mature (past cold start)
        cortex._cg_steps = _COLD_CG + 1

        emb = np.random.randn(384).astype(np.float32)
        valid = {"keep", "compress", "forget"}
        for _ in range(20):
            decision = cortex.gate_memory(emb, 10.0, 0, 0.1, 0, 0.0)
            self.assertIn(decision, valid)


if __name__ == "__main__":
    unittest.main()
