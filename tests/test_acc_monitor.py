"""
Tests for ACC Monitor (Anterior Cingulate Cortex)
=============================================
Tests: neutral state, conflict detection, Gratton adaptive thresholds,
       E-PQ event firing, PROPRIO line building, DB logging, edge cases.
"""
import sys, os, time, sqlite3, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Isolate DB to temp directory
_tmp = tempfile.mkdtemp()
os.environ["AICORE_DATA"] = _tmp

# Must reset singleton before import
import services.acc_monitor as acc_mod
acc_mod._instance = None

from services.acc_monitor import (
    ACCMonitor, ACCInputState, ACCTickResult, ChannelReading,
    CHANNELS, get_acc, _clamp,
    GRATTON_RAISE, GRATTON_DECAY_RATE, GRATTON_MAX_RAISE, GRATTON_MIN,
    EPQ_FIRE_THRESHOLD, EPQ_COOLDOWN_S,
)

PASS = 0
FAIL = 0

def check(name, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


def fresh_acc():
    """Create a fresh ACCMonitor instance (not singleton)."""
    return ACCMonitor()


# ═══════════════════════════════════════════════
# 1. Neutral State — No False Positives
# ═══════════════════════════════════════════════

print("\n=== 1. Neutral State (pure defaults) ===")
acc = fresh_acc()
state = ACCInputState()  # All defaults
result = acc.tick(state)

# Debug output
for ch_name, reading in result.channels.items():
    tag = "FIRE" if reading.conflict else "    "
    print(f"  {tag} {ch_name:12s}: belief={reading.belief:.3f} reality={reading.reality:.3f} "
          f"disc={reading.discrepancy:.3f} thresh={reading.threshold:.3f}")

check("neutral total_conflict == 0",
      result.total_conflict == 0.0)
check("neutral no dominant channel",
      result.dominant_channel == "")
check("mood: no conflict at rest",
      not result.channels["mood"].conflict)
check("vigilance: no conflict at rest",
      not result.channels["vigilance"].conflict)
check("coherence: no conflict at rest",
      not result.channels["coherence"].conflict)
check("body: no conflict at rest",
      not result.channels["body"].conflict)
check("prediction: no conflict at rest",
      not result.channels["prediction"].conflict)
check("identity: no conflict at rest",
      not result.channels["identity"].conflict)
check("activity: no conflict at rest",
      not result.channels["activity"].conflict)
check("neutral proprio_line is empty",
      result.proprio_line == "")
check("neutral no epq events fired",
      len(result.epq_events_fired) == 0)


# ═══════════════════════════════════════════════
# 2. Each Channel Fires Correctly
# ═══════════════════════════════════════════════

print("\n=== 2. Individual Channel Conflicts ===")

# 2a. Mood: positive self-model but quiet AURA (real density > 0)
acc2 = fresh_acc()
state_mood = ACCInputState(
    epq_mood_buffer=0.6,   # belief = (0.6+1)/2 = 0.8 (positive mood)
    aura_mood_density=0.15,  # AURA says mood zone is quiet (> 0 → not "no data")
)
r = acc2.tick(state_mood)
check("mood conflict fires (positive mood but quiet AURA)",
      r.channels["mood"].conflict)
check("mood discrepancy > 0.25",
      r.channels["mood"].discrepancy > 0.25)

# 2b. Vigilance: relaxed but amygdala firing
acc2b = fresh_acc()
state_vig = ACCInputState(
    epq_vigilance=-0.5,  # belief = (-0.5+1)/2 = 0.25 (relaxed)
    amygdala_alert_count_5min=7,  # reality = 0.5 + 7/10 = 1.2 → clamped 1.0
)
r = acc2b.tick(state_vig)
check("vigilance conflict fires (relaxed + many alerts)",
      r.channels["vigilance"].conflict)
check("vigilance label mentions threats",
      "threats" in r.channels["vigilance"].label.lower() or
      "amygdala" in r.channels["vigilance"].label.lower())

# 2c. Coherence: precision feels high but QR has violations
acc2c = fresh_acc()
state_coh = ACCInputState(
    epq_precision=0.6,  # belief = (0.6+1)/2 = 0.8
    qr_violations=5,    # reality = 0.5 - 5*0.10 = 0.0
)
r = acc2c.tick(state_coh)
check("coherence conflict fires (high precision + QR violations)",
      r.channels["coherence"].conflict)
check("coherence high discrepancy",
      r.channels["coherence"].discrepancy > 0.3)

# 2d. Body: services offline
acc2d = fresh_acc()
state_body = ACCInputState(
    services_total=15,
    services_down=6,
)
r = acc2d.tick(state_body)
check("body conflict fires (6/15 services down)",
      r.channels["body"].conflict)
check("body label mentions organs/offline",
      "offline" in r.channels["body"].label.lower() or
      "organ" in r.channels["body"].label.lower())

# 2e. Prediction: surprise high (bad predictions)
acc2e = fresh_acc()
state_pred = ACCInputState(
    prediction_surprise_avg=0.8,  # reality = 1-0.8 = 0.2
)
r = acc2e.tick(state_pred)
check("prediction conflict fires (high surprise)",
      r.channels["prediction"].conflict)
check("prediction belief=0.5 reality=0.2",
      abs(r.channels["prediction"].reality - 0.2) < 0.01)

# 2f. Identity: attacks while confident
acc2f = fresh_acc()
state_id = ACCInputState(
    epq_confidence=0.8,
    amygdala_identity_attacks_5min=4,  # reality = 0.5 - 4/6 ≈ 0.17 → clamped
)
r = acc2f.tick(state_id)
check("identity conflict fires (confident + attacks)",
      r.channels["identity"].conflict)
check("identity discrepancy > 0.5",
      r.channels["identity"].discrepancy > 0.5)

# 2g. Activity: goals but ruminating
acc2g = fresh_acc()
state_act = ACCInputState(
    has_active_goals=True,
    rumination_score=0.8,  # reality = 0.7 - 0.8*0.7 = 0.14
)
r = acc2g.tick(state_act)
check("activity conflict fires (goals + rumination)",
      r.channels["activity"].conflict)
check("activity label mentions circling/growth",
      "circling" in r.channels["activity"].label.lower() or
      "growth" in r.channels["activity"].label.lower())


# ═══════════════════════════════════════════════
# 3. Activity: No goals + rumination
# ═══════════════════════════════════════════════

print("\n=== 3. Activity Edge Cases ===")
acc3 = fresh_acc()
state_nogoal_rum = ACCInputState(
    has_active_goals=False,
    rumination_score=0.8,  # reality = 0.5 - 0.8*0.5 = 0.1
)
r = acc3.tick(state_nogoal_rum)
check("no goals + high rumination fires",
      r.channels["activity"].conflict)
check("no goals + rumination label mentions 'racing' or 'no'",
      "racing" in r.channels["activity"].label.lower() or
      "no" in r.channels["activity"].label.lower())

# Goals, no rumination → no conflict
acc3b = fresh_acc()
state_goals_calm = ACCInputState(
    has_active_goals=True,
    rumination_score=0.0,  # reality = 0.7 - 0 = 0.7 = belief
)
r = acc3b.tick(state_goals_calm)
check("goals + no rumination: NO conflict",
      not r.channels["activity"].conflict)


# ═══════════════════════════════════════════════
# 4. Gratton Adaptive Thresholds
# ═══════════════════════════════════════════════

print("\n=== 4. Gratton Adaptive Thresholds ===")

acc4 = fresh_acc()
base_vig = CHANNELS["vigilance"]["base_threshold"]  # 0.30

# Fire vigilance conflict 3 times
conflict_state = ACCInputState(
    epq_vigilance=-0.8,       # belief = 0.1
    amygdala_alert_count_5min=8,  # reality = 0.5 + 0.8 = 1.3 → 1.0
)
for i in range(3):
    r = acc4.tick(conflict_state)

thresh_after_3 = acc4._thresholds["vigilance"]
check("Gratton: threshold raised after 3 conflicts",
      thresh_after_3 > base_vig + 0.1)
check("Gratton: threshold not above max",
      thresh_after_3 <= base_vig + GRATTON_MAX_RAISE)

# Now tick with neutral state many times → threshold decays
neutral = ACCInputState()
for _ in range(50):
    acc4.tick(neutral)

thresh_decayed = acc4._thresholds["vigilance"]
check("Gratton: threshold decays toward base after neutral ticks",
      thresh_decayed < thresh_after_3)
check("Gratton: threshold >= base",
      thresh_decayed >= base_vig - 0.01)


# ═══════════════════════════════════════════════
# 5. Salience Calculation
# ═══════════════════════════════════════════════

print("\n=== 5. Salience ===")
acc5 = fresh_acc()
# Create a state where mood has known discrepancy (density > 0 → real data)
state5 = ACCInputState(
    epq_mood_buffer=0.8,   # belief = (0.8+1)/2 = 0.9
    aura_mood_density=0.1,  # reality = 0.1 (> 0.001 → not "no data")
)
r = acc5.tick(state5)
mood_r = r.channels["mood"]
check("salience > 0 when conflict",
      mood_r.salience > 0)
check("salience capped at 1.0",
      mood_r.salience <= 1.0)
expected_sal = min(1.0, (mood_r.discrepancy - mood_r.threshold) / 0.40)
check("salience formula correct",
      abs(mood_r.salience - expected_sal) < 0.01)


# ═══════════════════════════════════════════════
# 6. Total Conflict Aggregation
# ═══════════════════════════════════════════════

print("\n=== 6. Aggregation ===")
acc6 = fresh_acc()
multi_state = ACCInputState(
    epq_mood_buffer=0.8,
    aura_mood_density=0.15,  # > 0 so mood treats as real data
    epq_vigilance=-0.8,
    amygdala_alert_count_5min=8,
    has_active_goals=True,
    rumination_score=0.9,
)
r = acc6.tick(multi_state)
active_count = sum(1 for ch in r.channels.values() if ch.conflict)
check("multiple channels fire simultaneously",
      active_count >= 3)
check("total_conflict = sum of saliences",
      abs(r.total_conflict - sum(ch.salience for ch in r.channels.values() if ch.conflict)) < 0.01)
check("dominant channel has highest salience",
      r.dominant_channel != "" and
      r.channels[r.dominant_channel].salience >= max(
          (ch.salience for ch in r.channels.values() if ch.conflict), default=0))


# ═══════════════════════════════════════════════
# 7. Subdivision Summary
# ═══════════════════════════════════════════════

print("\n=== 7. Subdivision Summary ===")
check("subdivision has dACC key",
      "dACC" in r.subdivision_summary)
check("subdivision has vACC key",
      "vACC" in r.subdivision_summary)


# ═══════════════════════════════════════════════
# 8. PROPRIO Line
# ═══════════════════════════════════════════════

print("\n=== 8. PROPRIO Line ===")
check("proprio_line non-empty for multi-conflict",
      r.proprio_line != "")
check("proprio_line starts with 'Conflict:'",
      r.proprio_line.startswith("Conflict:"))
check("proprio_line contains intensity word",
      any(w in r.proprio_line for w in ("strong", "nagging", "faint")))


# ═══════════════════════════════════════════════
# 9. DB Logging
# ═══════════════════════════════════════════════

print("\n=== 9. DB Logging ===")
acc9 = fresh_acc()
db = acc9._get_db()
if db:
    # Clear any prior logs
    db.execute("DELETE FROM conflict_log")
    db.commit()

    # Fire a conflict (density > 0 so it's treated as real data)
    state9 = ACCInputState(
        epq_mood_buffer=0.8,   # belief = 0.9
        aura_mood_density=0.1,  # reality = 0.1
    )
    acc9.tick(state9)

    rows = db.execute("SELECT channel, belief, reality, salience FROM conflict_log").fetchall()
    check("conflict logged to DB",
          len(rows) >= 1)
    check("logged channel is 'mood'",
          any(r[0] == "mood" for r in rows))
    check("logged belief matches reading",
          any(abs(r[1] - 0.9) < 0.01 for r in rows))
else:
    check("DB available", False)
    check("(skipped)", False)
    check("(skipped)", False)


# ═══════════════════════════════════════════════
# 10. Singleton
# ═══════════════════════════════════════════════

print("\n=== 10. Singleton ===")
acc_mod._instance = None  # Reset
a1 = get_acc()
a2 = get_acc()
check("get_acc() returns same instance",
      a1 is a2)


# ═══════════════════════════════════════════════
# 11. get_summary()
# ═══════════════════════════════════════════════

print("\n=== 11. get_summary() ===")
summary = a1.get_summary()
check("summary has status key (no_data initially)",
      "status" in summary or "tick_count" in summary)

# Run a tick first
a1.tick(ACCInputState())
summary = a1.get_summary()
check("summary has tick_count",
      "tick_count" in summary)
check("summary has total_conflict",
      "total_conflict" in summary)


# ═══════════════════════════════════════════════
# 12. Edge Cases
# ═══════════════════════════════════════════════

print("\n=== 12. Edge Cases ===")
acc12 = fresh_acc()

# Extreme E-PQ values
state_extreme = ACCInputState(
    epq_mood_buffer=1.0,   # max
    epq_vigilance=1.0,
    epq_precision=1.0,
    epq_confidence=1.0,
    epq_autonomy=1.0,
    aura_mood_density=0.0,
    amygdala_alert_count_5min=20,
    amygdala_identity_attacks_5min=10,
    qr_violations=10,
    services_down=15,
    prediction_surprise_avg=1.0,
    rumination_score=1.0,
    has_active_goals=True,
)
r_ext = acc12.tick(state_extreme)
check("extreme state: all channels have valid readings",
      all(0.0 <= ch.belief <= 1.0 and 0.0 <= ch.reality <= 1.0
          for ch in r_ext.channels.values()))
check("extreme state: saliences capped at 1.0",
      all(ch.salience <= 1.0 for ch in r_ext.channels.values()))
check("extreme state: high total conflict",
      r_ext.total_conflict > 2.0)

# All negative E-PQ (Frank feeling bad)
state_neg = ACCInputState(
    epq_mood_buffer=-1.0,   # belief = 0.0
    aura_mood_density=1.0,  # AURA says mood is very active
    epq_vigilance=-1.0,     # belief = 0.0 (totally relaxed)
    epq_precision=-1.0,     # belief = 0.0
)
r_neg = acc12.tick(state_neg)
check("negative E-PQ: all values in [0,1]",
      all(0.0 <= ch.belief <= 1.0 and 0.0 <= ch.reality <= 1.0
          for ch in r_neg.channels.values()))


# ═══════════════════════════════════════════════
# 13. Prediction threshold behavior
# ═══════════════════════════════════════════════

print("\n=== 13. Prediction Threshold ===")
acc13 = fresh_acc()
# surprise_avg just below threshold → neutral
state_low = ACCInputState(prediction_surprise_avg=0.03)
r_low = acc13.tick(state_low)
check("surprise < 0.05 → reality=0.5 (neutral)",
      abs(r_low.channels["prediction"].reality - 0.5) < 0.01)

# surprise_avg above threshold → normal mapping
state_hi = ACCInputState(prediction_surprise_avg=0.6)
r_hi = acc13.tick(state_hi)
check("surprise=0.6 → reality=0.4",
      abs(r_hi.channels["prediction"].reality - 0.4) < 0.01)


# ═══════════════════════════════════════════════
# 14. Identity centering
# ═══════════════════════════════════════════════

print("\n=== 14. Identity Centering ===")
acc14 = fresh_acc()
# 0 attacks → 0.5 neutral
state_id0 = ACCInputState(epq_confidence=0.5, amygdala_identity_attacks_5min=0)
r_id0 = acc14.tick(state_id0)
check("0 attacks + conf=0.5 → no identity conflict",
      not r_id0.channels["identity"].conflict)
check("0 attacks → reality=0.5",
      abs(r_id0.channels["identity"].reality - 0.5) < 0.01)

# 3 attacks → reality=0.0
state_id3 = ACCInputState(epq_confidence=0.5, amygdala_identity_attacks_5min=3)
r_id3 = acc14.tick(state_id3)
check("3 attacks → identity conflict fires",
      r_id3.channels["identity"].conflict)
check("3 attacks → reality=0.0",
      abs(r_id3.channels["identity"].reality - 0.0) < 0.01)


# ═══════════════════════════════════════════════
# 15. Performance Benchmark
# ═══════════════════════════════════════════════

print("\n=== 15. Performance ===")
acc15 = fresh_acc()
# Use neutral state for pure computation benchmark (no DB writes from conflicts)
state15_neutral = ACCInputState()
# Warmup
for _ in range(10):
    acc15.tick(state15_neutral)

N = 1000
t0 = time.perf_counter()
for _ in range(N):
    acc15.tick(state15_neutral)
elapsed = time.perf_counter() - t0
per_tick_us = (elapsed / N) * 1e6
print(f"  {N} neutral ticks in {elapsed*1000:.1f}ms ({per_tick_us:.0f}µs/tick)")
check(f"performance: <5ms/tick ({per_tick_us:.0f}µs)",
      per_tick_us < 5000)

# Also benchmark with conflicts (includes DB writes)
acc15b = fresh_acc()
state15_conflict = ACCInputState(
    epq_mood_buffer=0.8,
    aura_mood_density=0.15,
    amygdala_alert_count_5min=8,
)
for _ in range(10):
    acc15b.tick(state15_conflict)
t1 = time.perf_counter()
for _ in range(200):
    acc15b.tick(state15_conflict)
elapsed2 = time.perf_counter() - t1
per_tick_us2 = (elapsed2 / 200) * 1e6
print(f"  200 conflict ticks in {elapsed2*1000:.1f}ms ({per_tick_us2:.0f}µs/tick)")
check(f"conflict performance: <5ms/tick ({per_tick_us2:.0f}µs)",
      per_tick_us2 < 5000)


# ═══════════════════════════════════════════════
# 16. Conflict Trend
# ═══════════════════════════════════════════════

print("\n=== 16. Conflict Trend ===")
acc16 = fresh_acc()
trend = acc16.get_conflict_trend("mood")
check("trend with no history → 'stable'",
      trend == "stable")

# Generate enough history
for _ in range(10):
    acc16.tick(ACCInputState(epq_mood_buffer=0.8, aura_mood_density=0.1))
trend2 = acc16.get_conflict_trend("mood")
check("trend with repeated conflict → valid string",
      trend2 in ("stable", "escalating", "resolving"))


# ═══════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════

print(f"\n{'='*50}")
print(f"ACC Monitor Tests: {PASS} passed, {FAIL} failed out of {PASS+FAIL}")
if FAIL == 0:
    print("ALL TESTS PASSED")
else:
    print(f"FAILURES: {FAIL}")
    sys.exit(1)
