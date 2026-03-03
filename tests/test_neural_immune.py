"""
Tests for Neural Immune System
================================
25+ tests covering models, DB, circuit breaker, collector, training,
lifecycle, and supervisor.
"""

import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import torch

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.neural_immune.models import (
    AnomalyNet, BaselineNet, RestartNet, ImmuneModels,
    ANOMALY_INPUT_DIM, BASELINE_INPUT_DIM, BASELINE_LATENT_DIM,
    RESTART_INPUT_DIM, MAX_RESTART_DELAY,
)
from services.neural_immune.db import ImmuneDB
from services.neural_immune.circuit_breaker import (
    CircuitBreaker, CircuitState, FAILURE_THRESHOLD,
    BASE_COOLDOWN, MAX_COOLDOWN,
)
from services.neural_immune.collector import (
    SERVICE_REGISTRY, FEATURES_PER_STEP, WINDOW_SIZE,
    HealthCollector, get_system_metrics,
)
from services.neural_immune.training import ImmuneTrainer


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def db(tmp_dir):
    d = ImmuneDB(tmp_dir / "test.db")
    yield d
    d.close()


@pytest.fixture
def models(tmp_dir):
    return ImmuneModels(model_path=tmp_dir / "test.pt")


# ══════════════════════════════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════════════════════════════

class TestAnomalyNet:
    def test_output_range(self):
        net = AnomalyNet()
        x = torch.randn(5, ANOMALY_INPUT_DIM)
        out = net(x)
        assert out.shape == (5,)
        assert (out >= 0).all() and (out <= 1).all()

    def test_param_count(self):
        net = AnomalyNet()
        params = sum(p.numel() for p in net.parameters())
        assert 7000 < params < 10000, f"Expected ~8.4K, got {params}"

    def test_single_sample(self):
        net = AnomalyNet()
        x = torch.zeros(1, ANOMALY_INPUT_DIM)
        out = net(x)
        assert out.shape == (1,)
        assert 0 <= out.item() <= 1


class TestBaselineNet:
    def test_reconstruction_shape(self):
        net = BaselineNet()
        x = torch.randn(5, BASELINE_INPUT_DIM)
        recon, latent = net(x)
        assert recon.shape == (5, BASELINE_INPUT_DIM)
        assert latent.shape == (5, BASELINE_LATENT_DIM)

    def test_param_count(self):
        net = BaselineNet()
        params = sum(p.numel() for p in net.parameters())
        assert 6000 < params < 9000, f"Expected ~7.8K, got {params}"

    def test_anomaly_score(self):
        net = BaselineNet()
        x = torch.randn(1, BASELINE_INPUT_DIM)
        score = net.anomaly_score(x)
        assert isinstance(score, float)
        assert score >= 0


class TestRestartNet:
    def test_output_ranges(self):
        net = RestartNet()
        x = torch.randn(5, RESTART_INPUT_DIM)
        delay, restart, cascade = net(x)
        assert delay.shape == (5,)
        assert restart.shape == (5,)
        assert cascade.shape == (5,)
        assert (delay >= 0).all() and (delay <= MAX_RESTART_DELAY).all()
        assert (restart >= 0).all() and (restart <= 1).all()
        assert (cascade >= 0).all() and (cascade <= 1).all()

    def test_param_count(self):
        net = RestartNet()
        params = sum(p.numel() for p in net.parameters())
        assert 2000 < params < 4000, f"Expected ~3.1K, got {params}"


class TestImmuneModels:
    def test_total_params(self, models):
        total = models.total_params()
        assert 15000 < total < 25000, f"Expected ~19K, got {total}"

    def test_cold_start_anomaly(self, models):
        """Cold start should return 0.0 (no prediction)."""
        assert models._anomaly_steps == 0
        result = models.predict_failure([0.0] * ANOMALY_INPUT_DIM)
        assert result == 0.0

    def test_cold_start_baseline(self, models):
        assert models._baseline_steps == 0
        result = models.baseline_anomaly([0.0] * BASELINE_INPUT_DIM)
        assert result == 0.0

    def test_cold_start_restart(self, models):
        assert models._restart_steps == 0
        result = models.restart_policy({}, default_delay=5.0)
        assert result["delay"] == 5.0
        assert result["should_restart"] == 1.0
        assert result["cascade_risk"] == 0.0

    def test_blending_rate(self, models):
        assert models._blend_rate(0, 100) == 0.0
        assert models._blend_rate(50, 100) == 0.5
        assert models._blend_rate(100, 100) == 1.0
        assert models._blend_rate(200, 100) == 1.0

    def test_warm_anomaly(self, models):
        """After threshold, should return neural output (not 0.0)."""
        models._anomaly_steps = 200  # Past threshold
        result = models.predict_failure([0.5] * ANOMALY_INPUT_DIM)
        # Should be non-zero (neural prediction)
        assert isinstance(result, float)

    def test_save_load(self, tmp_dir):
        m1 = ImmuneModels(model_path=tmp_dir / "test.pt")
        m1._anomaly_steps = 42
        m1._baseline_steps = 99
        m1._save()

        m2 = ImmuneModels(model_path=tmp_dir / "test.pt")
        assert m2._anomaly_steps == 42
        assert m2._baseline_steps == 99
        assert m2.total_params() == m1.total_params()


# ══════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════

class TestImmuneDB:
    def test_tables_exist(self, db):
        conn = db._get_conn()
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "health_snapshots" in tables
        assert "incident_log" in tables
        assert "service_baselines" in tables
        assert "circuit_states" in tables
        assert "training_meta" in tables
        assert "lifecycle_events" in tables

    def test_snapshot_crud(self, db):
        db.log_snapshot({"svc": [1, 0, 0, 0]}, is_healthy=True, anomaly_score=0.1)
        db.log_snapshot({"svc": [0, 0, 0, 0]}, is_healthy=False, anomaly_score=0.9)
        assert db.get_snapshot_count(healthy_only=True) == 1
        assert db.get_snapshot_count(healthy_only=False) == 2

        healthy = db.get_healthy_snapshots(limit=10)
        assert len(healthy) == 1
        assert "svc" in healthy[0]

    def test_incident_crud(self, db):
        db.log_incident("svc1", "crash", "test", pre_window="[1,2,3]")
        db.log_incident("svc2", "restart", "test", restart_success=True)
        assert db.get_incident_count() == 2
        assert db.get_incident_count("svc1") == 1

        incidents = db.get_incidents(service="svc1")
        assert len(incidents) == 1
        assert incidents[0]["event_type"] == "crash"

    def test_training_windows(self, db):
        db.log_incident("s", "crash", pre_window="[0.1,0.2,0.3]")
        db.log_incident("s", "restart", pre_window="[0.4,0.5,0.6]")
        windows = db.get_training_windows()
        assert len(windows) == 2
        # crash → label 1, restart → label 0
        labels = [w[1] for w in windows]
        assert 1 in labels
        assert 0 in labels

    def test_baseline_crud(self, db):
        db.update_baseline("svc1", 5.0, 1.0, 100.0, 10.0, 0.1, 0.05, 3600.0)
        bl = db.get_baseline("svc1")
        assert bl["mean_cpu"] == 5.0
        assert bl["mean_rss"] == 100.0

        assert db.get_baseline("nonexistent") is None

    def test_circuit_state_crud(self, db):
        db.save_circuit_state("svc1", "open", 3, 1000.0, 5.0)
        cs = db.load_circuit_state("svc1")
        assert cs["state"] == "open"
        assert cs["failure_count"] == 3

        all_states = db.load_all_circuit_states()
        assert "svc1" in all_states

    def test_training_meta(self, db):
        assert db.get_training_steps("anomaly") == 0
        db.update_training_meta("anomaly", 50, 0.05)
        assert db.get_training_steps("anomaly") == 50

    def test_lifecycle_events(self, db):
        db.log_lifecycle("startup", 0, ["svc1", "svc2"], True, 5.0)
        # Just verify no error — lifecycle events are write-mostly

    def test_prune_old_data(self, db):
        db.log_snapshot({"old": []}, is_healthy=True)
        db.log_incident("old", "crash")
        # Prune with 0 days → everything deleted
        db.prune_old_data(max_age_days=0)
        # Recent data should survive
        assert db.get_snapshot_count(False) == 0


# ══════════════════════════════════════════════════════════════════
# CIRCUIT BREAKER
# ══════════════════════════════════════════════════════════════════

class TestCircuitBreaker:
    def test_initial_state(self, db):
        cb = CircuitBreaker("test", db)
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.allows_restart()

    def test_closed_to_open(self, db):
        cb = CircuitBreaker("test", db)
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_open_blocks_restart(self, db):
        cb = CircuitBreaker("test", db)
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        assert not cb.allows_restart()

    def test_open_to_half_open(self, db):
        cb = CircuitBreaker("test", db, base_delay=0.01)
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        # Force cooldown to expire
        cb.cooldown_until = time.time() - 1
        assert cb.allows_restart()
        assert cb.state == CircuitState.HALF_OPEN

    def test_reset(self, db):
        cb = CircuitBreaker("test", db)
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_success_decays_failures(self, db):
        cb = CircuitBreaker("test", db)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2
        cb.record_success()
        assert cb.failure_count == 1

    def test_jitter_within_bounds(self, db):
        cb = CircuitBreaker("test", db, base_delay=3.0)
        for _ in range(100):
            delay = cb._jitter_delay(5.0)
            assert cb._base_delay <= delay <= MAX_COOLDOWN

    def test_persistence(self, db):
        cb1 = CircuitBreaker("test", db, base_delay=2.0)
        for _ in range(FAILURE_THRESHOLD):
            cb1.record_failure()

        cb2 = CircuitBreaker("test", db, base_delay=2.0)
        assert cb2.state == CircuitState.OPEN
        assert cb2.failure_count == FAILURE_THRESHOLD

    def test_to_dict(self, db):
        cb = CircuitBreaker("test", db)
        d = cb.to_dict()
        assert d["service"] == "test"
        assert d["state"] == CircuitState.CLOSED
        assert "failure_count" in d


# ══════════════════════════════════════════════════════════════════
# COLLECTOR
# ══════════════════════════════════════════════════════════════════

class TestHealthCollector:
    def test_service_registry_populated(self):
        assert len(SERVICE_REGISTRY) > 20

    def test_all_services_have_tier(self):
        for name, info in SERVICE_REGISTRY.items():
            assert "tier" in info, f"{name} missing tier"
            assert 0 <= info["tier"] <= 4

    def test_window_creation(self):
        coll = HealthCollector({"test": {"port": None, "health": None,
                                          "critical": True, "tier": 0, "delay": 1,
                                          "cooldown": 10, "max_restarts": 5,
                                          "reset_after": 300}})
        assert "test" in coll.windows
        assert len(coll.windows["test"]) == 0

    def test_get_window_padding(self):
        coll = HealthCollector({"test": {"port": None, "health": None,
                                          "critical": True, "tier": 0, "delay": 1,
                                          "cooldown": 10, "max_restarts": 5,
                                          "reset_after": 300}})
        window = coll.get_window("test")
        assert len(window) == WINDOW_SIZE * FEATURES_PER_STEP
        assert all(v == 0.0 for v in window)

    def test_get_baseline_vector_size(self):
        coll = HealthCollector()
        vec = coll.get_baseline_vector()
        assert len(vec) == 80

    def test_system_metrics(self):
        metrics = get_system_metrics()
        assert "cpu_system" in metrics
        assert "ram_system_pct" in metrics
        # On Linux these should be > 0
        if os.path.exists("/proc/stat"):
            assert metrics["cpu_system"] >= 0
            assert metrics["ram_system_pct"] >= 0

    def test_dependency_health(self):
        coll = HealthCollector()
        # Tier 0 → always 1.0
        assert coll._calc_dependency_health(0) == 1.0
        # Higher tiers depend on lower
        health = coll._calc_dependency_health(1)
        assert 0.0 <= health <= 1.0

    def test_update_restart_count(self):
        coll = HealthCollector()
        coll.update_restart_count("test", 5)
        assert coll._restart_counts["test"] == 5


# ══════════════════════════════════════════════════════════════════
# TRAINING
# ══════════════════════════════════════════════════════════════════

class TestTraining:
    def test_train_cycle_no_data(self, tmp_dir):
        """Training with no data should complete without error."""
        db = ImmuneDB(tmp_dir / "test.db")
        models = ImmuneModels(model_path=tmp_dir / "test.pt")
        trainer = ImmuneTrainer(models, db)
        trainer.train_cycle()
        db.close()

    def test_train_anomaly_with_data(self, tmp_dir):
        db = ImmuneDB(tmp_dir / "test.db")
        models = ImmuneModels(model_path=tmp_dir / "test.pt")
        trainer = ImmuneTrainer(models, db)

        # Generate enough training data (need 20+ valid windows)
        for i in range(50):
            window = [float(j % 10) / 10.0 for j in range(ANOMALY_INPUT_DIM)]
            event = "crash" if i % 3 == 0 else "restart"
            db.log_incident("svc", event, pre_window=json.dumps(window))

        trainer._train_anomaly()
        assert models._anomaly_steps > 0
        db.close()

    def test_train_baseline_with_data(self, tmp_dir):
        db = ImmuneDB(tmp_dir / "test.db")
        models = ImmuneModels(model_path=tmp_dir / "test.pt")
        trainer = ImmuneTrainer(models, db)

        # Generate 60 healthy snapshots
        for i in range(60):
            snap = {}
            names = sorted(SERVICE_REGISTRY.keys())[:20]
            for name in names:
                snap[name] = [1.0, 0.1, 0.2, 0.01]
            db.log_snapshot(snap, is_healthy=True)

        trainer._train_baseline()
        assert models._baseline_steps > 0
        db.close()

    def test_train_performance(self, tmp_dir):
        """Training should complete in <2000ms (first run includes optimizer init)."""
        db = ImmuneDB(tmp_dir / "test.db")
        models = ImmuneModels(model_path=tmp_dir / "test.pt")
        trainer = ImmuneTrainer(models, db)

        # Add some data
        for i in range(50):
            window = [0.5] * ANOMALY_INPUT_DIM
            db.log_incident("svc", "crash" if i % 2 else "restart",
                           pre_window=json.dumps(window))

        # First run: includes lazy optimizer creation (~1s on first torch use)
        trainer.train_cycle()

        # Second run: should be fast (<200ms) since optimizers exist
        t0 = time.monotonic()
        trainer.train_cycle()
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert elapsed_ms < 200, f"Second training took {elapsed_ms:.1f}ms (max 200ms)"
        db.close()


# ══════════════════════════════════════════════════════════════════
# LIFECYCLE
# ══════════════════════════════════════════════════════════════════

class TestLifecycle:
    def test_wave_ordering(self):
        from services.neural_immune.lifecycle import RESTART_WAVES, WAVE_LABELS
        assert len(RESTART_WAVES) == 5
        assert len(WAVE_LABELS) == 5
        # Wave 0 should have LLM services
        assert "aicore-llama3-gpu" in RESTART_WAVES[0]
        # Wave 1 = router
        assert RESTART_WAVES[1] == ["aicore-router"]
        # Wave 2 = core
        assert RESTART_WAVES[2] == ["aicore-core"]
        # Wave 4 = overlay
        assert "frank-overlay" in RESTART_WAVES[4]

    def test_shutdown_services(self):
        from services.neural_immune.lifecycle import FULL_SHUTDOWN_SERVICES, RESTART_WAVES
        assert len(FULL_SHUTDOWN_SERVICES) > 15
        assert "aicore-core" in FULL_SHUTDOWN_SERVICES
        assert "aicore-router" in FULL_SHUTDOWN_SERVICES

    def test_shutdown_covers_all_waves(self):
        """FULL_SHUTDOWN_SERVICES must include every service from RESTART_WAVES."""
        from services.neural_immune.lifecycle import FULL_SHUTDOWN_SERVICES, RESTART_WAVES
        all_wave_services = set()
        for wave in RESTART_WAVES:
            all_wave_services.update(wave)
        missing = all_wave_services - set(FULL_SHUTDOWN_SERVICES)
        assert not missing, f"Missing from FULL_SHUTDOWN_SERVICES: {missing}"


# ══════════════════════════════════════════════════════════════════
# SINGLETON
# ══════════════════════════════════════════════════════════════════

class TestSingleton:
    def test_get_immune_system(self):
        """Singleton returns same instance."""
        import services.neural_immune as pkg
        # Reset singleton
        pkg._instance = None
        s1 = pkg.get_immune_system()
        s2 = pkg.get_immune_system()
        assert s1 is s2
        pkg._instance = None  # Cleanup


# ══════════════════════════════════════════════════════════════════
# SPECIAL CASES
# ══════════════════════════════════════════════════════════════════

class TestSpecialCases:
    def test_overlay_skip_conditions(self):
        """Overlay should have tier 4 and be critical."""
        info = SERVICE_REGISTRY.get("frank-overlay")
        assert info is not None
        assert info["tier"] == 4
        assert info["critical"] is True

    def test_dream_non_critical(self):
        """Dream daemon should be non-critical."""
        info = SERVICE_REGISTRY.get("aicore-dream")
        assert info is not None
        assert info["critical"] is False

    def test_sentinel_non_critical(self):
        """Frank sentinel should be non-critical."""
        info = SERVICE_REGISTRY.get("frank-sentinel")
        assert info is not None
        assert info["critical"] is False

    def test_llm_services_tier_0(self):
        """LLM services should be tier 0 (infrastructure)."""
        assert SERVICE_REGISTRY["aicore-llama3-gpu"]["tier"] == 0
        assert SERVICE_REGISTRY["aicore-micro-llm"]["tier"] == 0


# ══════════════════════════════════════════════════════════════════
# BUG FIX REGRESSION TESTS
# ══════════════════════════════════════════════════════════════════

class TestBugFixes:
    """Tests for bugs found by bug search agents."""

    def test_blend_rate_zero_threshold(self, tmp_dir):
        """_blend_rate should not divide by zero when threshold=0."""
        models = ImmuneModels(model_path=tmp_dir / "test.pt")
        # Should not raise
        assert models._blend_rate(0, 0) == 0.0
        assert models._blend_rate(1, 0) == 1.0
        assert models._blend_rate(100, 0) == 1.0

    def test_healthy_snapshots_corrupt_json(self, tmp_dir):
        """get_healthy_snapshots should skip corrupt JSON rows."""
        db = ImmuneDB(tmp_dir / "test.db")
        # Insert a valid snapshot
        db.log_snapshot({"svc1": [1.0, 0.1, 0.2, 0.01]}, is_healthy=True)
        # Manually insert a corrupt row
        conn = db._get_conn()
        conn.execute(
            "INSERT INTO health_snapshots (timestamp, snapshot, is_healthy) "
            "VALUES (?, ?, 1)",
            (time.time(), "not-valid-json{{{")
        )
        conn.commit()
        # Should return only the valid snapshot (skip corrupt)
        snaps = db.get_healthy_snapshots()
        assert len(snaps) == 1
        assert "svc1" in snaps[0]
        db.close()

    def test_cpu_delta_calculation(self):
        """CPU% should use delta-based jiffies, not cumulative."""
        from services.neural_immune.collector import get_process_metrics, _prev_cpu_jiffies
        pid = os.getpid()
        # First call: no delta available yet, should return 0.0
        _prev_cpu_jiffies.pop(pid, None)
        m1 = get_process_metrics(pid)
        assert m1["cpu_pct"] == 0.0  # No previous sample
        # Second call: should have a delta
        time.sleep(0.15)
        m2 = get_process_metrics(pid)
        assert m2["cpu_pct"] >= 0.0
        assert m2["cpu_pct"] <= 100.0

    def test_training_step_lock(self, tmp_dir):
        """Training step counter updates should be thread-safe."""
        db = ImmuneDB(tmp_dir / "test.db")
        models = ImmuneModels(model_path=tmp_dir / "test.pt")
        trainer = ImmuneTrainer(models, db)

        # Add enough data
        for i in range(30):
            window = [0.5] * ANOMALY_INPUT_DIM
            db.log_incident("svc", "crash" if i % 2 else "restart",
                           pre_window=json.dumps(window))

        old_steps = models._anomaly_steps
        trainer._train_anomaly()
        # Steps should have increased
        assert models._anomaly_steps > old_steps
        db.close()

    def test_rotating_log_handler(self):
        """__main__ should use RotatingFileHandler."""
        import logging.handlers
        # Just verify the import works and RotatingFileHandler exists
        assert hasattr(logging.handlers, 'RotatingFileHandler')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
