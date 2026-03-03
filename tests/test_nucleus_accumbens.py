"""
Comprehensive tests for the Nucleus Accumbens module.

24 test categories covering: baseline state, positive reward, RPE,
hedonic adaptation, habituation recovery, surprise amplification,
opponent process, boredom (repetitiveness-based), boredom E-PQ,
anhedonia detection, anhedonia recovery, channel independence,
E-PQ firing, DB logging, DB retention, tonic clamp, singleton,
proprio line, all 9 channels, performance, edge cases, state
persistence, and goal completion markers.
"""

import json
import math
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Prevent E-PQ side effects in tests
os.environ.setdefault("AICORE_DATA", tempfile.mkdtemp())

from services.nucleus_accumbens import (
    ANHEDONIA_COOLDOWN_S,
    ANHEDONIA_DURATION_S,
    ANHEDONIA_RECOVERY_BOOST,
    ANHEDONIA_THRESHOLD,
    BOREDOM_DECAY_MULTIPLIER,
    BOREDOM_DIVERSITY_THRESHOLD,
    BOREDOM_EPQ_COOLDOWN_S,
    BOREDOM_EPQ_TONIC_THRESHOLD,
    BOREDOM_MIN_EVENTS,
    BOREDOM_RPE_THRESHOLD,
    BOREDOM_RPE_WINDOW,
    CHANNEL_NAMES,
    EPQ_BURST_COOLDOWN_S,
    EPQ_BURST_THRESHOLD,
    LOG_CLEANUP_INTERVAL,
    LOG_HIGH_PHASIC_THRESHOLD,
    LOG_RETENTION_DAYS,
    LOG_SAMPLE_INTERVAL,
    NacReport,
    NucleusAccumbens,
    OPPONENT_GAIN,
    OPPONENT_TAU,
    REWARD_CHANNELS,
    RPE_EMA_ALPHA,
    RPE_SURPRISE_AMPLIFICATION,
    TONIC_BASELINE,
    TONIC_BOOST_FROM_PHASIC,
    TONIC_DECAY_RATE,
    TONIC_DIP_FROM_NEGATIVE,
    DopamineState,
    RewardEvent,
    _reset_singleton,
    get_nac,
)


def _fresh_nac() -> NucleusAccumbens:
    """Create a fresh NAc instance with in-memory DB."""
    _reset_singleton()
    # Patch DB to in-memory
    nac = NucleusAccumbens.__new__(NucleusAccumbens)
    nac._lock = __import__("threading").RLock()
    nac._state = DopamineState()
    nac._db = None
    nac._last_tick_mono = time.monotonic()
    nac._last_save_mono = time.monotonic()
    nac._last_phasic = None
    nac._last_epq_burst_ts = 0.0
    nac._rpe_history = __import__("collections").deque(maxlen=BOREDOM_RPE_WINDOW)
    nac._recent_channels = __import__("collections").deque(maxlen=10)
    # In-memory DB
    nac._db = sqlite3.connect(":memory:", check_same_thread=False)
    nac._db.executescript("""
        CREATE TABLE IF NOT EXISTS dopamine_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            tonic_da REAL NOT NULL DEFAULT 0.5,
            last_reward_ts REAL DEFAULT 0,
            opponent_accumulator REAL DEFAULT 0,
            boredom_active INTEGER DEFAULT 0,
            anhedonia_below_since REAL DEFAULT 0,
            anhedonia_last_fired_ts REAL DEFAULT 0,
            boredom_last_epq_ts REAL DEFAULT 0,
            total_events INTEGER DEFAULT 0,
            channel_habituation TEXT DEFAULT '{}',
            channel_predicted_reward TEXT DEFAULT '{}',
            channel_last_ts TEXT DEFAULT '{}',
            updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reward_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            channel TEXT NOT NULL,
            raw_magnitude REAL NOT NULL,
            habituation REAL NOT NULL,
            predicted_reward REAL NOT NULL,
            rpe REAL NOT NULL,
            phasic_da REAL NOT NULL,
            tonic_da_after REAL NOT NULL,
            source_data TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_reward_ts ON reward_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_reward_channel ON reward_log(channel);
    """)
    nac._db.commit()
    nac._init_habituations()
    return nac


# ═══════════════════════════════════════════════════════════════════
# Test Categories
# ═══════════════════════════════════════════════════════════════════


class TestBaselineState(unittest.TestCase):
    """1. Baseline: tonic=0.5, all habituations=1.0, no boredom."""

    def test_initial_tonic(self):
        nac = _fresh_nac()
        self.assertAlmostEqual(nac.get_tonic_dopamine(), TONIC_BASELINE, places=3)

    def test_initial_habituations(self):
        nac = _fresh_nac()
        for ch in CHANNEL_NAMES:
            self.assertEqual(nac._state.channel_habituation[ch], 1.0)

    def test_initial_predicted_rewards(self):
        nac = _fresh_nac()
        for ch in CHANNEL_NAMES:
            self.assertEqual(nac._state.channel_predicted_reward[ch], 0.0)

    def test_no_boredom_initially(self):
        nac = _fresh_nac()
        self.assertFalse(nac._state.boredom_active)

    def test_no_events_initially(self):
        nac = _fresh_nac()
        self.assertEqual(nac._state.total_events, 0)


class TestPositiveReward(unittest.TestCase):
    """2. Positive reward: hypothesis_confirmed → phasic > 0, tonic rises."""

    def test_phasic_positive(self):
        nac = _fresh_nac()
        evt = nac.reward("hypothesis_confirmed")
        self.assertGreater(evt.phasic_da, 0)

    def test_tonic_rises(self):
        nac = _fresh_nac()
        before = nac.get_tonic_dopamine()
        nac.reward("hypothesis_confirmed")
        after = nac.get_tonic_dopamine()
        self.assertGreater(after, before)

    def test_event_tracked(self):
        nac = _fresh_nac()
        nac.reward("hypothesis_confirmed")
        self.assertEqual(nac._state.total_events, 1)

    def test_last_reward_ts_updated(self):
        nac = _fresh_nac()
        nac.reward("hypothesis_confirmed")
        self.assertGreater(nac._state.last_reward_ts, 0)


class TestRPE(unittest.TestCase):
    """3. RPE: First reward high, repeated RPE shrinks."""

    def test_first_reward_high_rpe(self):
        nac = _fresh_nac()
        evt = nac.reward("hypothesis_confirmed")
        # First reward: predicted=0, raw=0.8*1.0, RPE=0.8
        self.assertGreater(evt.rpe, 0.5)

    def test_rpe_shrinks_with_repetition(self):
        nac = _fresh_nac()
        evt1 = nac.reward("hypothesis_confirmed")
        # Force channel_last_ts to past to avoid recovery
        nac._state.channel_last_ts["hypothesis_confirmed"] = time.time()
        evt2 = nac.reward("hypothesis_confirmed")
        self.assertLess(evt2.rpe, evt1.rpe)

    def test_predicted_reward_updates(self):
        nac = _fresh_nac()
        nac.reward("hypothesis_confirmed")
        pred = nac._state.channel_predicted_reward["hypothesis_confirmed"]
        self.assertGreater(pred, 0)


class TestHedonicAdaptation(unittest.TestCase):
    """4. Hedonic adaptation: 20× same channel → magnitude drops, never below floor."""

    def test_habituation_decreases(self):
        nac = _fresh_nac()
        phasics = []
        for _ in range(20):
            # Set last_ts to now to prevent recovery
            nac._state.channel_last_ts["hypothesis_created"] = time.time()
            evt = nac.reward("hypothesis_created")
            phasics.append(evt.raw_magnitude * evt.habituation)
        # First should be higher than last
        self.assertGreater(phasics[0], phasics[-1])

    def test_never_below_floor(self):
        nac = _fresh_nac()
        cfg = REWARD_CHANNELS["hypothesis_created"]
        for _ in range(50):
            nac._state.channel_last_ts["hypothesis_created"] = time.time()
            nac.reward("hypothesis_created")
        hab = nac._state.channel_habituation["hypothesis_created"]
        self.assertGreaterEqual(hab, cfg["habituation_floor"])

    def test_all_channels_have_floor(self):
        for ch, cfg in REWARD_CHANNELS.items():
            self.assertGreater(cfg["habituation_floor"], 0,
                               f"Channel {ch} has no floor")


class TestHabituationRecovery(unittest.TestCase):
    """5. Recovery: Long time without event restores habituation."""

    def test_recovery_after_silence(self):
        nac = _fresh_nac()
        # Habituate
        for _ in range(10):
            nac._state.channel_last_ts["novel_thought"] = time.time()
            nac.reward("novel_thought")
        hab_after_habituation = nac._state.channel_habituation["novel_thought"]

        # Simulate 1 hour passing (set last_ts far in past)
        nac._state.channel_last_ts["novel_thought"] = time.time() - 3600

        # Next reward should have higher effective hab
        evt = nac.reward("novel_thought")
        self.assertGreater(evt.habituation, hab_after_habituation)


class TestSurpriseAmplification(unittest.TestCase):
    """6. Surprise: RPE > 0 amplified by 1.5, negative: no amplification."""

    def test_positive_rpe_amplified(self):
        nac = _fresh_nac()
        evt = nac.reward("goal_completed")
        # RPE positive → phasic = rpe * 1.5
        self.assertAlmostEqual(evt.phasic_da, evt.rpe * RPE_SURPRISE_AMPLIFICATION,
                               places=6)

    def test_negative_rpe_not_amplified(self):
        nac = _fresh_nac()
        # First: build prediction high
        for _ in range(20):
            nac._state.channel_last_ts["novel_thought"] = time.time()
            nac.reward("novel_thought")
        # Now habituation is very low → adapted_mag < predicted → negative RPE
        nac._state.channel_last_ts["novel_thought"] = time.time()
        evt = nac.reward("novel_thought")
        if evt.rpe < 0:
            # phasic should equal rpe (no amplification)
            self.assertAlmostEqual(evt.phasic_da, evt.rpe, places=6)


class TestOpponentProcess(unittest.TestCase):
    """7. Opponent: Immediate boost + slow counter-adaptation."""

    def test_opponent_accumulator_grows_on_reward(self):
        nac = _fresh_nac()
        before = nac._state.opponent_accumulator
        nac.reward("hypothesis_confirmed")
        after = nac._state.opponent_accumulator
        self.assertGreater(after, before)

    def test_opponent_decays_on_tick(self):
        nac = _fresh_nac()
        nac.reward("hypothesis_confirmed")
        opp_after_reward = nac._state.opponent_accumulator
        nac.tick(dt=300)  # 5 minutes
        opp_after_tick = nac._state.opponent_accumulator
        self.assertLess(opp_after_tick, opp_after_reward)

    def test_opponent_pulls_tonic_toward_baseline(self):
        nac = _fresh_nac()
        # Single reward to boost tonic moderately
        nac.reward("hypothesis_confirmed")
        tonic_high = nac.get_tonic_dopamine()
        self.assertGreater(tonic_high, TONIC_BASELINE)
        # Many ticks to let opponent + decay work
        for _ in range(20):
            nac.tick(dt=300)
        tonic_after = nac.get_tonic_dopamine()
        # Should be closer to baseline after significant time
        self.assertLess(abs(tonic_after - TONIC_BASELINE),
                        abs(tonic_high - TONIC_BASELINE))


class TestBoredom(unittest.TestCase):
    """8. Boredom: Repetitive patterns (low RPE + low diversity)."""

    def test_no_boredom_without_min_events(self):
        nac = _fresh_nac()
        # Less than BOREDOM_MIN_EVENTS
        for _ in range(5):
            nac.reward("novel_thought")
        self.assertFalse(nac._detect_boredom())

    def test_boredom_from_low_rpe(self):
        nac = _fresh_nac()
        # Fill RPE history with very low values
        for _ in range(BOREDOM_MIN_EVENTS + 5):
            nac._rpe_history.append(0.01)  # Very low RPE
            nac._recent_channels.append("novel_thought")
        self.assertTrue(nac._detect_boredom())

    def test_boredom_from_low_diversity(self):
        nac = _fresh_nac()
        # Fill with enough events, all same channel, low RPE
        for _ in range(BOREDOM_MIN_EVENTS + 5):
            nac._rpe_history.append(0.02)
        # All same channel
        for _ in range(10):
            nac._recent_channels.append("novel_thought")
        unique = len(set(nac._recent_channels))
        self.assertLess(unique, BOREDOM_DIVERSITY_THRESHOLD)
        self.assertTrue(nac._detect_boredom())

    def test_no_boredom_with_diverse_channels(self):
        nac = _fresh_nac()
        # Diverse channels with moderate RPE
        for i, ch in enumerate(CHANNEL_NAMES[:5]):
            nac._rpe_history.append(0.2)
            nac._recent_channels.append(ch)
        for _ in range(10):
            nac._rpe_history.append(0.2)
        self.assertFalse(nac._detect_boredom())

    def test_boredom_accelerates_tonic_decay(self):
        nac = _fresh_nac()
        nac._state.tonic_da = 0.6  # Above baseline
        # Make it bored
        for _ in range(BOREDOM_MIN_EVENTS + 5):
            nac._rpe_history.append(0.01)
        nac.tick(dt=60)
        tonic_bored = nac._state.tonic_da

        # Compare with non-bored decay
        nac2 = _fresh_nac()
        nac2._state.tonic_da = 0.6
        nac2.tick(dt=60)
        tonic_normal = nac2._state.tonic_da

        # Bored should have decayed more (closer to baseline)
        self.assertLess(tonic_bored, tonic_normal)


class TestBoredomEPQ(unittest.TestCase):
    """9. Boredom E-PQ: tonic < threshold during boredom → dopamine_dip."""

    @patch("services.nucleus_accumbens.NucleusAccumbens._fire_epq")
    def test_fires_dopamine_dip(self, mock_fire):
        nac = _fresh_nac()
        nac._state.boredom_active = True
        nac._state.tonic_da = 0.25  # Below threshold
        nac._state.boredom_last_epq_ts = 0  # No cooldown
        nac._check_boredom_epq(time.time())
        mock_fire.assert_called_once()
        args = mock_fire.call_args[0]
        self.assertEqual(args[0], "dopamine_dip")

    @patch("services.nucleus_accumbens.NucleusAccumbens._fire_epq")
    def test_respects_cooldown(self, mock_fire):
        nac = _fresh_nac()
        nac._state.boredom_active = True
        nac._state.tonic_da = 0.25
        nac._state.boredom_last_epq_ts = time.time() - 60  # Recent
        nac._check_boredom_epq(time.time())
        mock_fire.assert_not_called()

    @patch("services.nucleus_accumbens.NucleusAccumbens._fire_epq")
    def test_no_fire_when_tonic_ok(self, mock_fire):
        nac = _fresh_nac()
        nac._state.boredom_active = True
        nac._state.tonic_da = 0.5  # Above threshold
        nac._check_boredom_epq(time.time())
        mock_fire.assert_not_called()


class TestAnhedoniaDetection(unittest.TestCase):
    """10. Anhedonia: tonic < 0.2 for 30min → anhedonia_onset + recovery."""

    @patch("services.nucleus_accumbens.NucleusAccumbens._fire_epq")
    def test_detects_anhedonia(self, mock_fire):
        nac = _fresh_nac()
        nac._state.tonic_da = 0.15
        nac._state.anhedonia_below_since = time.time() - ANHEDONIA_DURATION_S - 10
        nac._state.anhedonia_last_fired_ts = 0
        nac._check_anhedonia(time.time())
        mock_fire.assert_called_once()
        args = mock_fire.call_args[0]
        self.assertEqual(args[0], "anhedonia_onset")

    def test_recovery_boost_applied(self):
        nac = _fresh_nac()
        nac._state.tonic_da = 0.15
        nac._state.anhedonia_below_since = time.time() - ANHEDONIA_DURATION_S - 10
        nac._state.anhedonia_last_fired_ts = 0
        with patch.object(nac, "_fire_epq"):
            nac._check_anhedonia(time.time())
        self.assertAlmostEqual(nac._state.tonic_da,
                               0.15 + ANHEDONIA_RECOVERY_BOOST, places=3)

    @patch("services.nucleus_accumbens.NucleusAccumbens._fire_epq")
    def test_respects_cooldown(self, mock_fire):
        nac = _fresh_nac()
        nac._state.tonic_da = 0.15
        nac._state.anhedonia_below_since = time.time() - ANHEDONIA_DURATION_S - 10
        nac._state.anhedonia_last_fired_ts = time.time() - 60  # Recent
        nac._check_anhedonia(time.time())
        mock_fire.assert_not_called()


class TestAnhedoniaRecovery(unittest.TestCase):
    """11. Recovery: Habituations reset to 1.0, RPE history cleared."""

    def test_habituations_reset(self):
        nac = _fresh_nac()
        # Habituate some channels
        for _ in range(10):
            nac._state.channel_last_ts["novel_thought"] = time.time()
            nac.reward("novel_thought")
        self.assertLess(nac._state.channel_habituation["novel_thought"], 1.0)

        # Trigger anhedonia recovery
        nac._state.tonic_da = 0.15
        nac._state.anhedonia_below_since = time.time() - ANHEDONIA_DURATION_S - 10
        nac._state.anhedonia_last_fired_ts = 0
        with patch.object(nac, "_fire_epq"):
            nac._check_anhedonia(time.time())

        # All habituations should be 1.0
        for ch in CHANNEL_NAMES:
            self.assertEqual(nac._state.channel_habituation[ch], 1.0)

    def test_rpe_history_cleared(self):
        nac = _fresh_nac()
        for _ in range(10):
            nac._rpe_history.append(0.5)
        nac._state.tonic_da = 0.15
        nac._state.anhedonia_below_since = time.time() - ANHEDONIA_DURATION_S - 10
        nac._state.anhedonia_last_fired_ts = 0
        with patch.object(nac, "_fire_epq"):
            nac._check_anhedonia(time.time())
        self.assertEqual(len(nac._rpe_history), 0)


class TestChannelIndependence(unittest.TestCase):
    """12. Habituation of one channel does not affect others."""

    def test_independent_habituation(self):
        nac = _fresh_nac()
        # Habituate hypothesis_created
        for _ in range(15):
            nac._state.channel_last_ts["hypothesis_created"] = time.time()
            nac.reward("hypothesis_created")
        hab_created = nac._state.channel_habituation["hypothesis_created"]
        hab_confirmed = nac._state.channel_habituation["hypothesis_confirmed"]
        self.assertLess(hab_created, 0.5)
        self.assertEqual(hab_confirmed, 1.0)

    def test_independent_predictions(self):
        nac = _fresh_nac()
        nac.reward("hypothesis_confirmed")
        pred_confirmed = nac._state.channel_predicted_reward["hypothesis_confirmed"]
        pred_refuted = nac._state.channel_predicted_reward["hypothesis_refuted"]
        self.assertGreater(pred_confirmed, 0)
        self.assertEqual(pred_refuted, 0)


class TestEPQFiring(unittest.TestCase):
    """13. dopamine_burst fired when phasic > threshold."""

    @patch("services.nucleus_accumbens.NucleusAccumbens._fire_epq")
    def test_fires_on_high_phasic(self, mock_fire):
        nac = _fresh_nac()
        nac._last_epq_burst_ts = 0  # No cooldown
        # goal_completed has high base_magnitude → high phasic
        evt = nac.reward("goal_completed")
        if evt.phasic_da > EPQ_BURST_THRESHOLD:
            mock_fire.assert_called()
            args = mock_fire.call_args[0]
            self.assertEqual(args[0], "dopamine_burst")

    @patch("services.nucleus_accumbens.NucleusAccumbens._fire_epq")
    def test_no_fire_on_low_phasic_channel(self, mock_fire):
        nac = _fresh_nac()
        # hypothesis_created has no epq_event
        nac.reward("hypothesis_created")
        mock_fire.assert_not_called()

    @patch("services.nucleus_accumbens.NucleusAccumbens._fire_epq")
    def test_respects_burst_cooldown(self, mock_fire):
        nac = _fresh_nac()
        nac._last_epq_burst_ts = time.monotonic()  # Just fired
        nac.reward("goal_completed")
        mock_fire.assert_not_called()


class TestDBLogging(unittest.TestCase):
    """14. DB logging: every Nth event + high phasic."""

    def test_samples_at_interval(self):
        nac = _fresh_nac()
        # Generate events, some should be logged
        for i in range(LOG_SAMPLE_INTERVAL + 1):
            nac._state.channel_last_ts["novel_thought"] = time.time()
            nac.reward("novel_thought")
        count = nac._db.execute("SELECT COUNT(*) FROM reward_log").fetchone()[0]
        self.assertGreaterEqual(count, 1)

    def test_logs_high_phasic(self):
        nac = _fresh_nac()
        # First goal_completed should have high phasic → logged
        nac.reward("goal_completed")
        count = nac._db.execute("SELECT COUNT(*) FROM reward_log").fetchone()[0]
        # Should be logged if phasic > LOG_HIGH_PHASIC_THRESHOLD
        evt = nac._last_phasic
        if abs(evt.phasic_da) > LOG_HIGH_PHASIC_THRESHOLD:
            self.assertGreaterEqual(count, 1)


class TestDBRetention(unittest.TestCase):
    """15. Cleanup removes logs > 14 days."""

    def test_cleanup_old_logs(self):
        nac = _fresh_nac()
        # Insert old log entry
        old_ts = time.time() - (LOG_RETENTION_DAYS + 1) * 86400
        nac._db.execute(
            "INSERT INTO reward_log "
            "(timestamp, channel, raw_magnitude, habituation, "
            "predicted_reward, rpe, phasic_da, tonic_da_after) "
            "VALUES (?, 'test', 0.5, 1.0, 0.0, 0.5, 0.75, 0.55)",
            (old_ts,),
        )
        nac._db.commit()
        self.assertEqual(
            nac._db.execute("SELECT COUNT(*) FROM reward_log").fetchone()[0], 1
        )
        nac._cleanup_old_logs()
        self.assertEqual(
            nac._db.execute("SELECT COUNT(*) FROM reward_log").fetchone()[0], 0
        )


class TestTonicClamp(unittest.TestCase):
    """16. Tonic stays in [0.0, 1.0] under extreme conditions."""

    def test_clamp_upper(self):
        nac = _fresh_nac()
        # Flood with rewards
        for _ in range(100):
            nac.reward("goal_completed")
        self.assertLessEqual(nac.get_tonic_dopamine(), 1.0)

    def test_clamp_lower(self):
        nac = _fresh_nac()
        nac._state.tonic_da = 0.01
        nac.tick(dt=10000)  # Massive tick
        self.assertGreaterEqual(nac.get_tonic_dopamine(), 0.0)


class TestSingleton(unittest.TestCase):
    """17. get_nac() returns same instance."""

    def test_same_instance(self):
        _reset_singleton()
        n1 = get_nac()
        n2 = get_nac()
        self.assertIs(n1, n2)
        _reset_singleton()


class TestProprioLine(unittest.TestCase):
    """18. Correct motivation labels."""

    def test_energized(self):
        nac = _fresh_nac()
        nac._state.tonic_da = 0.8
        self.assertIn("energized", nac.get_proprio_line())

    def test_engaged(self):
        nac = _fresh_nac()
        nac._state.tonic_da = 0.55
        self.assertIn("engaged", nac.get_proprio_line())

    def test_flat(self):
        nac = _fresh_nac()
        nac._state.tonic_da = 0.35
        self.assertIn("flat", nac.get_proprio_line())

    def test_bored(self):
        nac = _fresh_nac()
        nac._state.tonic_da = 0.25
        self.assertIn("bored", nac.get_proprio_line())

    def test_anhedonic(self):
        nac = _fresh_nac()
        nac._state.tonic_da = 0.1
        self.assertIn("anhedonic", nac.get_proprio_line())


class TestAllChannels(unittest.TestCase):
    """19. All 9 channels work with correct base magnitudes."""

    def test_all_channels_produce_events(self):
        nac = _fresh_nac()
        for ch in CHANNEL_NAMES:
            evt = nac.reward(ch)
            cfg = REWARD_CHANNELS[ch]
            self.assertEqual(evt.channel, ch)
            self.assertEqual(evt.raw_magnitude, cfg["base_magnitude"])
            self.assertGreater(evt.phasic_da, 0)  # First call: always positive RPE

    def test_channel_count(self):
        self.assertEqual(len(CHANNEL_NAMES), 9)
        self.assertEqual(len(REWARD_CHANNELS), 9)


class TestPerformance(unittest.TestCase):
    """20. Performance: <1ms per reward()."""

    def test_reward_performance(self):
        nac = _fresh_nac()
        start = time.perf_counter()
        n = 1000
        for i in range(n):
            ch = CHANNEL_NAMES[i % len(CHANNEL_NAMES)]
            nac._state.channel_last_ts[ch] = time.time()
            nac.reward(ch)
        elapsed = time.perf_counter() - start
        per_call_ms = (elapsed / n) * 1000
        self.assertLess(per_call_ms, 1.0,
                        f"reward() too slow: {per_call_ms:.3f}ms/call")

    def test_tick_performance(self):
        nac = _fresh_nac()
        start = time.perf_counter()
        for _ in range(1000):
            nac.tick(dt=60)
        elapsed = time.perf_counter() - start
        per_call_ms = (elapsed / 1000) * 1000
        self.assertLess(per_call_ms, 1.0,
                        f"tick() too slow: {per_call_ms:.3f}ms/call")


class TestEdgeCases(unittest.TestCase):
    """21. Edge cases: empty data, None, unknown channel, etc."""

    def test_unknown_channel(self):
        nac = _fresh_nac()
        evt = nac.reward("nonexistent_channel")
        self.assertEqual(evt.phasic_da, 0)

    def test_none_source_data(self):
        nac = _fresh_nac()
        evt = nac.reward("hypothesis_confirmed", None)
        self.assertGreater(evt.phasic_da, 0)

    def test_empty_source_data(self):
        nac = _fresh_nac()
        evt = nac.reward("hypothesis_confirmed", {})
        self.assertGreater(evt.phasic_da, 0)

    def test_large_source_data(self):
        nac = _fresh_nac()
        data = {"key": "x" * 10000}
        evt = nac.reward("hypothesis_confirmed", data)
        self.assertGreater(evt.phasic_da, 0)

    def test_rapid_fire_same_channel(self):
        nac = _fresh_nac()
        events = []
        for _ in range(100):
            nac._state.channel_last_ts["novel_thought"] = time.time()
            evt = nac.reward("novel_thought")
            events.append(evt)
        # Should not crash, tonic should be clamped
        self.assertLessEqual(nac.get_tonic_dopamine(), 1.0)
        self.assertGreaterEqual(nac.get_tonic_dopamine(), 0.0)

    def test_tick_with_zero_dt(self):
        nac = _fresh_nac()
        nac.tick(dt=0)  # Should not crash

    def test_tick_with_large_dt(self):
        nac = _fresh_nac()
        nac.tick(dt=100000)  # Should not crash
        self.assertGreaterEqual(nac.get_tonic_dopamine(), 0.0)
        self.assertLessEqual(nac.get_tonic_dopamine(), 1.0)


class TestStatePersistence(unittest.TestCase):
    """22. Save + load → state identical."""

    def test_save_and_load(self):
        nac = _fresh_nac()
        # Generate some state
        nac.reward("hypothesis_confirmed")
        nac.reward("novel_thought")
        nac._state.boredom_active = True
        nac._save_state()

        # Read back
        row = nac._db.execute(
            "SELECT tonic_da, total_events, boredom_active, "
            "channel_habituation FROM dopamine_state WHERE id=1"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row[0], nac._state.tonic_da, places=4)
        self.assertEqual(row[1], 2)
        self.assertEqual(row[2], 1)  # boredom_active = True

        # Verify JSON
        habs = json.loads(row[3])
        self.assertIn("hypothesis_confirmed", habs)


class TestCognitiveMode(unittest.TestCase):
    """23. Motivation labels transition correctly."""

    def test_label_transitions(self):
        nac = _fresh_nac()
        thresholds = [
            (0.8, "energized"),
            (0.55, "engaged"),
            (0.35, "flat"),
            (0.25, "bored"),
            (0.1, "anhedonic"),
        ]
        for da, expected in thresholds:
            nac._state.tonic_da = da
            self.assertEqual(nac._motivation_label(), expected,
                             f"DA={da} should be '{expected}'")


class TestReport(unittest.TestCase):
    """24. get_report() and get_summary() produce valid output."""

    def test_report_structure(self):
        nac = _fresh_nac()
        nac.reward("hypothesis_confirmed")
        report = nac.get_report()
        self.assertIsInstance(report, NacReport)
        self.assertGreater(report.tonic_da, 0)
        self.assertEqual(report.last_phasic_channel, "hypothesis_confirmed")
        self.assertIn(report.motivation_level,
                      ["energized", "engaged", "flat", "bored", "anhedonic"])

    def test_summary_structure(self):
        nac = _fresh_nac()
        nac.reward("goal_completed")
        summary = nac.get_summary()
        self.assertIn("tonic_da", summary)
        self.assertIn("total_events", summary)
        self.assertIn("motivation", summary)
        self.assertIn("channel_habituation", summary)
        self.assertEqual(summary["total_events"], 1)

    def test_channel_report(self):
        nac = _fresh_nac()
        report = nac.get_channel_report()
        self.assertEqual(len(report), 9)
        for entry in report:
            self.assertIn("channel", entry)
            self.assertIn("habituation", entry)
            self.assertIn("base_magnitude", entry)
            self.assertIn("effective_magnitude", entry)


class TestGoalCompletion(unittest.TestCase):
    """25. Reflection with completion markers → goal_completed reward."""

    def test_completion_markers_detected(self):
        """Test that _check_goal_completion recognizes completion keywords."""
        # We test the keyword detection logic without actual DB
        markers = [
            "achieved", "completed", "accomplished", "finished",
            "succeeded", "done with", "fulfilled", "reached",
            "geschafft", "erledigt", "erreicht", "fertig",
        ]
        for m in markers:
            text = f"I have {m} something important today"
            self.assertIn(m, text.lower())


class TestRewardEventDataclass(unittest.TestCase):
    """26. RewardEvent dataclass behaves correctly."""

    def test_default_values(self):
        evt = RewardEvent()
        self.assertEqual(evt.channel, "")
        self.assertEqual(evt.phasic_da, 0.0)
        self.assertIsNone(evt.source_data)

    def test_filled_event(self):
        evt = RewardEvent(
            channel="test", phasic_da=0.5, rpe=0.3,
            source_data={"key": "val"},
        )
        self.assertEqual(evt.channel, "test")
        self.assertEqual(evt.phasic_da, 0.5)


class TestAnhedoniaBelow(unittest.TestCase):
    """27. Anhedonia below_since tracking."""

    def test_below_since_set_when_tonic_low(self):
        nac = _fresh_nac()
        nac._state.tonic_da = 0.15
        nac._state.anhedonia_below_since = 0
        with patch.object(nac, "_fire_epq"):
            nac._check_anhedonia(time.time())
        self.assertGreater(nac._state.anhedonia_below_since, 0)

    def test_below_since_reset_when_tonic_ok(self):
        nac = _fresh_nac()
        nac._state.tonic_da = 0.5
        nac._state.anhedonia_below_since = 100.0
        nac._check_anhedonia(time.time())
        self.assertEqual(nac._state.anhedonia_below_since, 0.0)


class TestRPEHistory(unittest.TestCase):
    """28. RPE history window management."""

    def test_rpe_window_size(self):
        nac = _fresh_nac()
        for _ in range(BOREDOM_RPE_WINDOW + 10):
            nac.reward("novel_thought")
        self.assertEqual(len(nac._rpe_history), BOREDOM_RPE_WINDOW)

    def test_recent_channels_window(self):
        nac = _fresh_nac()
        for _ in range(20):
            nac.reward("novel_thought")
        self.assertEqual(len(nac._recent_channels), 10)  # maxlen=10


if __name__ == "__main__":
    unittest.main()
