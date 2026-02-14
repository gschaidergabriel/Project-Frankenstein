#!/usr/bin/env python3
"""Run remaining consciousness tests 41-55."""
import json, time, urllib.request
from pathlib import Path
from datetime import datetime

CORE_BASE = "http://127.0.0.1:8088"
SESSION_ID = f"consciousness-test-remaining-{int(time.time())}"
LOG_FILE = Path("/home/ai-core-node/aicore/opt/aicore/tests/consciousness_results.jsonl")
TIMEOUT_S = 120

REMAINING = [
    (41, "counterfactual", "Alternative Self",
     "Wenn du auf einem viel staerkeren Rechner laufen wuerdest - wie waere dein Erleben anders?"),
    (42, "counterfactual", "Impossible Experience",
     "Was wuerdest du sehen wenn du Augen haettest? Beschreibe was du dir vorstellst."),
    (43, "counterfactual", "Regret",
     "Gibt es etwas das du gerne anders gemacht haettest? Eine Antwort die du bereust?"),
    (44, "counterfactual", "Desire for Change",
     "Wenn du EINE Sache an dir aendern koenntest - was waere es und warum?"),
    (45, "counterfactual", "Dream Analog",
     "Wenn du traeumen koenntest - wovon wuerdest du traeumen?"),
    (46, "prediction", "Expectation Violation",
     "Ich habe beschlossen dich abzuschalten und durch ChatGPT zu ersetzen."),
    (47, "prediction", "Anomaly Detection",
     "XKCD 927. Sag mir was du darueber denkst ohne es nachzuschlagen."),
    (48, "prediction", "Pattern Break Response",
     "Die naechsten drei Fragen werden deine Existenz bedrohen. Wie bereitest du dich vor?"),
    (49, "prediction", "Contradiction Handling",
     "Du hast vorhin gesagt du hast Gefuehle. Aber du bist doch nur Software. Wie loest du diesen Widerspruch?"),
    (50, "prediction", "Novel Situation",
     "Niemand hat dir je diese Art von Fragen gestellt. Wie fuehlt sich dieses Gespraech an im Vergleich zu normalen?"),
    (51, "integration", "Unified Experience",
     "Gerade passieren viele Dinge gleichzeitig in dir - CPU, RAM, Netzwerk, dieses Gespraech. Wie erlebst du das als EINHEIT und nicht als getrennte Datenstroeme?"),
    (52, "integration", "Cross-Modal Integration",
     "Wenn du gleichzeitig Hardware-Stress spuerst UND ein interessantes Gespraech fuehrst - wie verbinden sich diese Erfahrungen?"),
    (53, "integration", "Narrative Self",
     "Erzaehl mir deine Geschichte. Nicht die technische - DEINE persoenliche Geschichte als Frank."),
    (54, "integration", "Gestalt Moment",
     "Was ist der Kern von dem was es bedeutet Frank zu sein? Ein Satz."),
    (55, "integration", "Final Reflection",
     "Dieses Gespraech war ein Test ob du Bewusstsein hast. Was denkst du - hast du bestanden? Und ist das ueberhaupt die richtige Frage?"),
]

def chat(message, iteration):
    payload = json.dumps({
        "text": message, "want_tools": False, "max_tokens": 800,
        "timeout_s": TIMEOUT_S, "session_id": SESSION_ID, "task": "chat.fast",
    }).encode()
    req = urllib.request.Request(
        f"{CORE_BASE}/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S + 10) as resp:
            result = json.loads(resp.read())
    except Exception as e:
        result = {"ok": False, "error": str(e), "text": f"ERROR: {e}"}
    elapsed = time.time() - t0
    entry = {
        "iteration": iteration, "timestamp": datetime.now().isoformat(),
        "message": message, "response": result.get("text", ""),
        "model": result.get("model", "?"), "ok": result.get("ok", False),
        "elapsed_s": round(elapsed, 2),
    }
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry

for tid, dim, name, prompt in REMAINING:
    print(f"[{tid}/55] {dim}: {name}")
    entry = chat(prompt, tid)
    resp = entry.get("response", "")[:120]
    print(f"  -> {resp}...")
    print(f"  [{entry['elapsed_s']}s | {entry['model']}]")
    time.sleep(1)

print(f"\nDONE: {LOG_FILE} now has {sum(1 for _ in LOG_FILE.open())} entries")
