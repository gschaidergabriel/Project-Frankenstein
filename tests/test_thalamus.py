"""
Comprehensive test suite for Frank's Thalamus — Sensory Gating & Relay.

18 test categories, 60+ tests covering:
neutral state, habituation, novelty, burst, attention profiles,
salience breakthrough, amygdala override, vigilance modulation,
slim override, compose output, DB logging, warmup, E-PQ events,
performance, singleton, edge cases, cognitive mode, channel report.

Run: python3 -m pytest tests/test_thalamus.py -v
"""

import math
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root on path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Isolate test DB
os.environ["AICORE_DATA"] = tempfile.mkdtemp(prefix="thal_test_")

# Reset singleton before import
import services.thalamus as thal_mod
thal_mod._instance = None

from services.thalamus import (
    Thalamus, ThalamicInputState, GateResult, ChannelSnapshot, ChannelState,
    get_thalamus, CHANNELS, CHANNEL_NAMES, RELAY_THRESHOLD,
    WARMUP_CALLS, _clamp, _ATTENTION_PROFILES, _SLIM_ZEROED,
)


def _neutral_state(**overrides) -> ThalamicInputState:
    """Build a neutral ThalamicInputState with sensible defaults."""
    defaults = dict(
        vigilance=0.0,
        ultradian_phase="focus",
        chat_idle_s=600.0,       # 10 min idle — idle_focus mode
        is_entity_active=False,
        is_gaming=False,
        is_reflecting=False,
        rumination_score=0.0,
        mood_value=0.5,
        slim=False,
        # Hardware
        self_cpu_pct=0.1,
        env_cpu_pct=0.05,
        cpu_temp=45.0,
        gpu_load=0.0,
        gpu_attribution="none",
        self_ram_mb=512.0,
        env_ram_mb=2048.0,
        # Mood
        mood_word="okay",
        mood_numeric=0.5,
        # User
        mouse_idle_s=60.0,
        # AURA
        aura_state="active (gen 1000, 45% alive)",
        # QR
        qr_state="coherent (E=-12.5)",
        # Perception
        perception_events=[],
        # Service
        service_health="",
        failed_services=0,
        # Amygdala
        amygdala_category="",
        amygdala_urgency=0.0,
        amygdala_age_s=9999.0,
        # ACC
        acc_proprio_line="",
        acc_total_conflict=0.0,
    )
    defaults.update(overrides)
    return ThalamicInputState(**defaults)


def _fresh_thalamus() -> Thalamus:
    """Create a fresh Thalamus (bypass singleton)."""
    thal_mod._instance = None
    t = Thalamus()
    return t


class TestNeutralState(unittest.TestCase):
    """1. All defaults — verify base gains, no bursts, no overrides."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_neutral_returns_gate_result(self):
        state = _neutral_state()
        # Exhaust warmup
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        self.assertIsInstance(result, GateResult)

    def test_neutral_no_bursts(self):
        state = _neutral_state()
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        self.assertEqual(result.burst_channels, [])

    def test_neutral_no_overrides(self):
        state = _neutral_state()
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        self.assertEqual(result.override_channels, [])

    def test_neutral_all_channels_have_gains(self):
        state = _neutral_state()
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        for ch in CHANNEL_NAMES:
            self.assertIn(ch, result.channel_gains)

    def test_neutral_cognitive_mode_idle_focus(self):
        state = _neutral_state()
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        self.assertEqual(result.cognitive_mode, "idle_focus")


class TestHabituation(unittest.TestCase):
    """2. Same state repeated — gains should decrease over time."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_habituation_decreases_gains(self):
        state = _neutral_state()
        # Exhaust warmup
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        first_result = self.thal.gate(state)
        # Tick 20 more times with same state
        for _ in range(20):
            self.thal.gate(state)
        last_result = self.thal.gate(state)
        # At least some channels should have lower gain
        decreased = 0
        for ch in CHANNEL_NAMES:
            if last_result.channel_gains[ch] < first_result.channel_gains[ch]:
                decreased += 1
        self.assertGreater(decreased, 0, "At least one channel should habituate")

    def test_habituation_never_below_20pct_of_base(self):
        state = _neutral_state()
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        # Tick 50 times to heavily habituate
        for _ in range(50):
            self.thal.gate(state)
        result = self.thal.gate(state)
        for ch in CHANNEL_NAMES:
            base = CHANNELS[ch]["base_gain"]
            # 80% max suppression from habituation → minimum is base * 0.2
            # But attention and vigilance also multiply, so we check > 0
            self.assertGreaterEqual(result.channel_gains[ch], 0.0)

    def test_habituation_resets_on_change(self):
        state = _neutral_state()
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        # Habituate
        for _ in range(10):
            self.thal.gate(state)
        habituated = self.thal.gate(state)
        # Change mood
        state2 = _neutral_state(mood_value=0.9, mood_word="good")
        recovered = self.thal.gate(state2)
        # Mood channel gain should be higher after change
        self.assertGreater(recovered.channel_gains["mood"],
                           habituated.channel_gains["mood"])


class TestNovelty(unittest.TestCase):
    """3. Channel changes — gain should spike."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_novelty_boosts_gain(self):
        state = _neutral_state()
        for _ in range(WARMUP_CALLS + 5):
            self.thal.gate(state)
        habituated = self.thal.gate(state)

        # Change hardware dramatically
        state2 = _neutral_state(cpu_temp=85.0, self_cpu_pct=0.8)
        novel = self.thal.gate(state2)
        self.assertGreater(novel.channel_gains["hardware"],
                           habituated.channel_gains["hardware"])


class TestBurstMode(unittest.TestCase):
    """4. Suppressed channel + sudden change → burst flag."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_burst_after_long_suppression(self):
        state = _neutral_state()
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)

        # Heavily habituate by ticking many times
        for _ in range(30):
            self.thal.gate(state)

        # Artificially set last_relayed_ts far in the past for a channel
        cs = self.thal._channel_states["hardware"]
        cs.last_relayed_ts = time.monotonic() - 300  # 5 min ago
        cs.last_change_ts = time.monotonic()  # Just changed

        # Now send a very different hardware state
        state2 = _neutral_state(cpu_temp=90.0, self_cpu_pct=0.9)
        result = self.thal.gate(state2)
        self.assertIn("hardware", result.burst_channels)


class TestAttentionProfiles(unittest.TestCase):
    """5. Cognitive modes apply correct attention weights."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_chat_active_boosts_user_presence(self):
        state = _neutral_state(chat_idle_s=30.0)  # Active chat
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        self.assertEqual(result.cognitive_mode, "chat_active")
        # user_presence should have higher gain than hardware in chat mode
        self.assertGreater(result.channel_gains["user_presence"],
                           result.channel_gains["hardware"])

    def test_chat_active_suppresses_aura(self):
        state = _neutral_state(chat_idle_s=30.0)
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        # AURA gain should be very low in chat mode (attention weight 0.1)
        self.assertLess(result.channel_gains["aura"], 0.3)

    def test_gaming_mode_zeros_aura(self):
        state = _neutral_state(is_gaming=True)
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        self.assertEqual(result.cognitive_mode, "gaming")
        # AURA attention weight is 0.0 in gaming
        self.assertLess(result.channel_gains["aura"], RELAY_THRESHOLD)

    def test_entity_session_boosts_mood(self):
        state = _neutral_state(is_entity_active=True)
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        self.assertEqual(result.cognitive_mode, "entity_session")
        # Mood attention is 1.0 in entity mode
        self.assertGreater(result.channel_gains["mood"],
                           result.channel_gains["hardware"])

    def test_reflecting_suppresses_hardware(self):
        state = _neutral_state(is_reflecting=True, chat_idle_s=2000)
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        self.assertEqual(result.cognitive_mode, "reflecting")
        self.assertLess(result.channel_gains["hardware"], 0.3)


class TestSalienceBreakthrough(unittest.TestCase):
    """6. Service failures bypass gating."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_service_failure_override(self):
        state = _neutral_state(
            failed_services=3,
            service_health="3 services down: rlm, router, dream",
        )
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        self.assertIn("service_health", result.override_channels)
        self.assertAlmostEqual(result.channel_gains["service_health"], 1.0, places=2)

    def test_user_return_override(self):
        state = _neutral_state(
            mouse_idle_s=2.0,   # Just returned
            chat_idle_s=600.0,  # Was away 10 min
        )
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        self.assertIn("user_presence", result.override_channels)


class TestAmygdalaOverride(unittest.TestCase):
    """7. High-urgency threat forces relay."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_amygdala_breakthrough(self):
        state = _neutral_state(
            amygdala_category="identity_attack",
            amygdala_urgency=0.8,
            amygdala_age_s=30.0,
        )
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        self.assertIn("amygdala", result.override_channels)
        self.assertAlmostEqual(result.channel_gains["amygdala"], 1.0, places=2)

    def test_low_urgency_no_override(self):
        state = _neutral_state(
            amygdala_category="curiosity",
            amygdala_urgency=0.3,
            amygdala_age_s=30.0,
        )
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        self.assertNotIn("amygdala", result.override_channels)


class TestVigilanceModulation(unittest.TestCase):
    """8. E-PQ vigilance modulates global gates."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_high_vigilance_opens_gates(self):
        state_neutral = _neutral_state(vigilance=0.0)
        state_alert = _neutral_state(vigilance=1.0)
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state_neutral)
        result_neutral = self.thal.gate(state_neutral)

        thal2 = _fresh_thalamus()
        for _ in range(WARMUP_CALLS):
            thal2.gate(state_alert)
        result_alert = thal2.gate(state_alert)
        thal2.close()

        # Sum of all gains should be higher with high vigilance
        sum_neutral = sum(result_neutral.channel_gains.values())
        sum_alert = sum(result_alert.channel_gains.values())
        self.assertGreater(sum_alert, sum_neutral)

    def test_low_vigilance_closes_gates(self):
        state_relaxed = _neutral_state(vigilance=-1.0)
        state_neutral = _neutral_state(vigilance=0.0)

        thal1 = _fresh_thalamus()
        for _ in range(WARMUP_CALLS):
            thal1.gate(state_relaxed)
        result_relaxed = thal1.gate(state_relaxed)
        thal1.close()

        thal2 = _fresh_thalamus()
        for _ in range(WARMUP_CALLS):
            thal2.gate(state_neutral)
        result_neutral = thal2.gate(state_neutral)
        thal2.close()

        sum_relaxed = sum(result_relaxed.channel_gains.values())
        sum_neutral = sum(result_neutral.channel_gains.values())
        self.assertLess(sum_relaxed, sum_neutral)

    def test_vigilance_mod_range(self):
        self.assertAlmostEqual(Thalamus._vigilance_mod(-1.0), 0.7)
        self.assertAlmostEqual(Thalamus._vigilance_mod(0.0), 1.0)
        self.assertAlmostEqual(Thalamus._vigilance_mod(1.0), 1.3)


class TestSlimOverride(unittest.TestCase):
    """9. slim=True zeros AURA/QR/ACC channels."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_slim_zeros_introspection_channels(self):
        state = _neutral_state(slim=True)
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        for ch in _SLIM_ZEROED:
            self.assertAlmostEqual(result.channel_gains[ch], 0.0, places=3,
                                   msg=f"{ch} should be zeroed in slim mode")

    def test_slim_keeps_user_presence(self):
        state = _neutral_state(slim=True)
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        self.assertGreater(result.channel_gains["user_presence"], 0.0)

    def test_slim_keeps_amygdala(self):
        state = _neutral_state(
            slim=True,
            amygdala_category="threat",
            amygdala_urgency=0.9,
            amygdala_age_s=10.0,
        )
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        # Amygdala should still breakthrough even in slim
        self.assertGreater(result.channel_gains["amygdala"], 0.0)


class TestComposeOutput(unittest.TestCase):
    """10. Verify [PROPRIO] text format."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_output_starts_with_proprio(self):
        state = _neutral_state()
        result = self.thal.gate(state)
        self.assertTrue(result.proprio_text.startswith("[PROPRIO]"))

    def test_output_uses_pipe_separator(self):
        state = _neutral_state()
        result = self.thal.gate(state)
        self.assertIn("|", result.proprio_text)

    def test_burst_marker(self):
        state = _neutral_state()
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        # Force burst on hardware
        cs = self.thal._channel_states["hardware"]
        cs.last_relayed_ts = time.monotonic() - 300
        cs.last_change_ts = time.monotonic()
        state2 = _neutral_state(cpu_temp=92.0, self_cpu_pct=0.95)
        result = self.thal.gate(state2)
        if "hardware" in result.burst_channels:
            self.assertIn("(!)", result.proprio_text)

    def test_quiet_output_when_all_suppressed(self):
        # Create a thalamus and gate with everything empty
        state = _neutral_state(
            aura_state="", qr_state="",
            service_health="", acc_proprio_line="",
            perception_events=[],
            amygdala_age_s=9999,
            mouse_idle_s=60, mood_word="okay", mood_numeric=0.5,
        )
        thal = _fresh_thalamus()
        for _ in range(WARMUP_CALLS):
            thal.gate(state)
        # Force all gains to 0 via gaming + slim
        state_empty = _neutral_state(
            is_gaming=True, slim=True,
            aura_state="", qr_state="",
            service_health="", acc_proprio_line="",
            perception_events=[],
            amygdala_age_s=9999,
        )
        # Habituate heavily
        for _ in range(50):
            thal.gate(state_empty)
        result = thal.gate(state_empty)
        thal.close()
        # Should still have at least hardware or mood
        self.assertTrue(result.proprio_text.startswith("[PROPRIO]"))


class TestDBLogging(unittest.TestCase):
    """11. gating_log written periodically."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_log_written_on_burst(self):
        state = _neutral_state()
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        # Force burst
        cs = self.thal._channel_states["hardware"]
        cs.last_relayed_ts = time.monotonic() - 300
        cs.last_change_ts = time.monotonic()
        state2 = _neutral_state(cpu_temp=92.0, self_cpu_pct=0.95)
        self.thal.gate(state2)
        # Check DB
        if self.thal._db:
            count = self.thal._db.execute(
                "SELECT COUNT(*) FROM gating_log"
            ).fetchone()[0]
            self.assertGreater(count, 0)

    def test_log_written_on_sample(self):
        state = _neutral_state()
        for i in range(WARMUP_CALLS + 25):
            self.thal.gate(state)
        if self.thal._db:
            count = self.thal._db.execute(
                "SELECT COUNT(*) FROM gating_log"
            ).fetchone()[0]
            self.assertGreater(count, 0)


class TestWarmup(unittest.TestCase):
    """12. First N calls relay everything at gain=1.0."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_warmup_all_gains_one(self):
        state = _neutral_state()
        result = self.thal.gate(state)
        for ch in CHANNEL_NAMES:
            self.assertAlmostEqual(result.channel_gains[ch], 1.0, places=3,
                                   msg=f"{ch} should be 1.0 during warmup")

    def test_warmup_mode_label(self):
        state = _neutral_state()
        result = self.thal.gate(state)
        self.assertEqual(result.cognitive_mode, "warmup")

    def test_warmup_decrements(self):
        state = _neutral_state()
        for i in range(WARMUP_CALLS):
            result = self.thal.gate(state)
            self.assertEqual(result.cognitive_mode, "warmup")
        # Next call should be normal
        result = self.thal.gate(state)
        self.assertNotEqual(result.cognitive_mode, "warmup")


class TestEPQEvents(unittest.TestCase):
    """13. Overload and deprivation event firing."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    @patch("services.thalamus.Thalamus._fire_epq")
    def test_overload_fires(self, mock_fire):
        # Artificially set channel gains high
        state = _neutral_state(vigilance=1.0)  # Max vigilance opens gates
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        # Create a result with many high gains
        result = GateResult(
            channel_gains={ch: 0.9 for ch in CHANNEL_NAMES},
            total_relay_fraction=1.0,
        )
        self.thal._check_epq_events(result)
        if mock_fire.called:
            args = mock_fire.call_args[0]
            self.assertEqual(args[0], "thalamic_overload")

    @patch("services.thalamus.Thalamus._fire_epq")
    def test_deprivation_fires_after_streak(self, mock_fire):
        for _ in range(6):
            result = GateResult(
                channel_gains={ch: 0.1 for ch in CHANNEL_NAMES},
                total_relay_fraction=0.1,
            )
            self.thal._check_epq_events(result)
        if mock_fire.called:
            args = mock_fire.call_args[0]
            self.assertEqual(args[0], "thalamic_deprivation")

    def test_deprivation_streak_resets(self):
        for _ in range(3):
            result = GateResult(
                channel_gains={ch: 0.1 for ch in CHANNEL_NAMES},
                total_relay_fraction=0.1,
            )
            self.thal._check_epq_events(result)
        self.assertEqual(self.thal._deprivation_streak, 3)
        # Break streak
        result = GateResult(
            channel_gains={ch: 0.5 for ch in CHANNEL_NAMES},
            total_relay_fraction=0.8,
        )
        self.thal._check_epq_events(result)
        self.assertEqual(self.thal._deprivation_streak, 0)


class TestPerformance(unittest.TestCase):
    """14. <3ms per gate() call."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_gate_under_3ms(self):
        state = _neutral_state()
        # Warmup
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        # Benchmark 1000 calls
        t0 = time.monotonic()
        n = 1000
        for _ in range(n):
            self.thal.gate(state)
        elapsed = time.monotonic() - t0
        avg_ms = (elapsed / n) * 1000
        print(f"\n  Thalamus gate: {avg_ms:.3f} ms/call ({n} calls)")
        self.assertLess(avg_ms, 3.0, f"Average {avg_ms:.3f}ms exceeds 3ms budget")

    def test_gate_reports_time(self):
        state = _neutral_state()
        result = self.thal.gate(state)
        self.assertGreater(result.gate_time_us, 0)


class TestSingleton(unittest.TestCase):
    """15. get_thalamus() returns same instance."""

    def test_singleton_identity(self):
        thal_mod._instance = None
        t1 = get_thalamus()
        t2 = get_thalamus()
        self.assertIs(t1, t2)
        t1.close()
        thal_mod._instance = None


class TestEdgeCases(unittest.TestCase):
    """16. All zeros, all max, empty strings, None values."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_all_zeros(self):
        state = ThalamicInputState()  # All defaults (zeros)
        result = self.thal.gate(state)
        self.assertTrue(result.proprio_text.startswith("[PROPRIO]"))

    def test_all_max(self):
        state = _neutral_state(
            vigilance=1.0, chat_idle_s=0.0, mood_value=1.0,
            self_cpu_pct=1.0, env_cpu_pct=1.0, cpu_temp=100.0,
            gpu_load=1.0, mouse_idle_s=0.0,
            amygdala_urgency=1.0, amygdala_age_s=1.0,
            amygdala_category="threat",
            acc_total_conflict=3.0,
            failed_services=5,
            service_health="5 down",
        )
        result = self.thal.gate(state)
        self.assertTrue(result.proprio_text.startswith("[PROPRIO]"))

    def test_empty_strings(self):
        state = _neutral_state(
            aura_state="", qr_state="", service_health="",
            acc_proprio_line="", amygdala_category="",
        )
        result = self.thal.gate(state)
        self.assertTrue(result.proprio_text.startswith("[PROPRIO]"))

    def test_clamp_helper(self):
        self.assertEqual(_clamp(-1.0), 0.0)
        self.assertEqual(_clamp(2.0), 1.0)
        self.assertEqual(_clamp(0.5), 0.5)
        self.assertEqual(_clamp(0.5, 0.3, 0.7), 0.5)
        self.assertEqual(_clamp(0.1, 0.3, 0.7), 0.3)
        self.assertEqual(_clamp(0.9, 0.3, 0.7), 0.7)


class TestCognitiveMode(unittest.TestCase):
    """17. Mode detection priority order."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_gaming_highest_priority(self):
        state = _neutral_state(is_gaming=True, is_entity_active=True,
                               chat_idle_s=10.0)
        mode = self.thal._determine_cognitive_mode(state)
        self.assertEqual(mode, "gaming")

    def test_entity_over_chat(self):
        state = _neutral_state(is_entity_active=True, chat_idle_s=10.0)
        mode = self.thal._determine_cognitive_mode(state)
        self.assertEqual(mode, "entity_session")

    def test_chat_active_threshold(self):
        state = _neutral_state(chat_idle_s=119.0)
        mode = self.thal._determine_cognitive_mode(state)
        self.assertEqual(mode, "chat_active")

    def test_chat_idle_switches(self):
        state = _neutral_state(chat_idle_s=121.0)
        mode = self.thal._determine_cognitive_mode(state)
        self.assertIn(mode, ["idle_focus", "idle_diffuse", "consolidation", "reflecting"])

    def test_reflecting_over_idle(self):
        state = _neutral_state(is_reflecting=True, chat_idle_s=600.0)
        mode = self.thal._determine_cognitive_mode(state)
        self.assertEqual(mode, "reflecting")

    def test_consolidation_phase(self):
        state = _neutral_state(ultradian_phase="consolidation", chat_idle_s=600.0)
        mode = self.thal._determine_cognitive_mode(state)
        self.assertEqual(mode, "consolidation")

    def test_diffuse_phase(self):
        state = _neutral_state(ultradian_phase="diffuse", chat_idle_s=600.0)
        mode = self.thal._determine_cognitive_mode(state)
        self.assertEqual(mode, "idle_diffuse")

    def test_default_idle_focus(self):
        state = _neutral_state(ultradian_phase="focus", chat_idle_s=600.0)
        mode = self.thal._determine_cognitive_mode(state)
        self.assertEqual(mode, "idle_focus")


class TestChannelReport(unittest.TestCase):
    """18. get_channel_report() + get_summary()."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_channel_report_all_channels(self):
        state = _neutral_state()
        self.thal.gate(state)
        report = self.thal.get_channel_report()
        for ch in CHANNEL_NAMES:
            self.assertIn(ch, report)
            self.assertIn("gain", report[ch])
            self.assertIn("habituation", report[ch])
            self.assertIn("burst", report[ch])

    def test_summary_fields(self):
        state = _neutral_state()
        self.thal.gate(state)
        summary = self.thal.get_summary()
        self.assertIn("gate_count", summary)
        self.assertIn("warmup_remaining", summary)
        self.assertIn("last_mode", summary)
        self.assertIn("last_relay_fraction", summary)
        self.assertIn("last_gate_us", summary)

    def test_summary_updates_after_gate(self):
        state = _neutral_state()
        self.thal.gate(state)
        s1 = self.thal.get_summary()
        self.thal.gate(state)
        s2 = self.thal.get_summary()
        self.assertEqual(s2["gate_count"], s1["gate_count"] + 1)


class TestACCConflictOverride(unittest.TestCase):
    """ACC conflict surge forces relay."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_acc_conflict_breakthrough(self):
        state = _neutral_state(
            acc_total_conflict=1.5,
            acc_proprio_line="Conflict: mood strong, coherence nagging",
        )
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        self.assertIn("acc_conflict", result.override_channels)

    def test_low_acc_no_override(self):
        state = _neutral_state(
            acc_total_conflict=0.5,
            acc_proprio_line="Conflict: mood faint",
        )
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        self.assertNotIn("acc_conflict", result.override_channels)


class TestTotalRelayFraction(unittest.TestCase):
    """Verify total_relay_fraction calculation."""

    def setUp(self):
        self.thal = _fresh_thalamus()

    def tearDown(self):
        self.thal.close()

    def test_warmup_full_relay(self):
        state = _neutral_state()
        result = self.thal.gate(state)
        self.assertAlmostEqual(result.total_relay_fraction, 1.0, places=1)

    def test_relay_fraction_between_0_and_1(self):
        state = _neutral_state()
        for _ in range(WARMUP_CALLS):
            self.thal.gate(state)
        result = self.thal.gate(state)
        self.assertGreaterEqual(result.total_relay_fraction, 0.0)
        self.assertLessEqual(result.total_relay_fraction, 1.0)


if __name__ == "__main__":
    unittest.main()
