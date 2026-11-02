"""Your logged combats through Bob's Buddy, beside TavernGym's replay of them (advisor.replay):
which of the two predicts the logged results better. Bob's Buddy gets what the log shows plainly
(cards, stats, golden, keywords, script data, the player's "this game" counters, trinkets) but
not effects held in enchantments; TavernGym gets the full rebuild. Both calibrated by bucket:
the predicted chance you won against how often you did. Bob's Buddy calibrated and TavernGym
not: TavernGym's rules; both off the same way: what neither gets from the log.

    python -X utf8 -m advisor.bb_real --replay data/progress/combat_replay.json
"""

import argparse
import json
import math
import subprocess
from pathlib import Path

from advisor.state import player_stats

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "tools" / "bbdiff" / "bin" / "real" / "BbDiff.exe"
KEYWORDS = {"TAUNT": "taunt", "DIVINE_SHIELD": "div", "REBORN": "reborn", "WINDFURY": "windfury",
            "POISONOUS": "poisonous", "VENOMOUS": "venomous", "STEALTH": "stealth"}
# TavernGym's PlayerStats fields (state.player_stats) -> Bob's Buddy's Player properties
COUNTERS = {"undead_atk": "UndeadAttackBonus", "beetle_atk": "BeetlesAtkBuff", "beetle_hp": "BeetlesHealthBuff",
            "gem_atk": "BloodGemAtkBuff", "gem_hp": "BloodGemHealthBuff", "volumizer_atk": "VolumizerAtkBuff",
            "volumizer_hp": "VolumizerHealthBuff", "eternal_knight_deaths": "EternalKnightCounter",
            "lobster_bonus": "TastyLobsterCounter", "spell_atk": "TavernSpellAtkBuff", "spell_hp": "TavernSpellHealthBuff"}


def side(s):
    minions = []
    for m in s["board"][:7]:
        x = {"card": m["card"], "atk": m["atk"], "hp": max(1, m["hp"]), "golden": bool(m.get("golden"))}
        for k, v in KEYWORDS.items():
            x[v] = k in (m.get("keywords") or [])
        if m.get("data"):
            x["sd1"], x["sd2"] = (m["data"] + [0, 0])[:2]
        minions.append(x)
    counters = {COUNTERS[k]: v for k, v in player_stats(s).items() if k in COUNTERS}
    return {"tier": max(1, s.get("tier") or 1), "health": max(1, s.get("health") or 30), "minions": minions,
            "counters": counters, "trinkets": [t["card"] for t in s.get("trinkets", [])]}


def calibration(pairs):
    """[(predicted win, won)] -> rows by bucket, the total and its SD."""
    out = []
    for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
        xs = [(p, w) for p, w in pairs if lo <= p < lo + 0.2 or (lo == 0.8 and p == 1.0)]
        if xs:
            out.append((lo, len(xs), sum(p for p, _ in xs) / len(xs), sum(w for _, w in xs) / len(xs)))
    pred, won = sum(p for p, _ in pairs), sum(w for _, w in pairs)
    sd = math.sqrt(sum(p * (1 - p) for p, _ in pairs)) or 1
    return out, pred, won, (won - pred) / sd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--replay", default=str(ROOT / "data" / "progress" / "combat_replay.json"))
    ap.add_argument("--n", type=int, default=500)
    a = ap.parse_args()
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    tg = {(r["log"], r["segment"], r["turn"]): r for r in json.load(open(a.replay, encoding="utf-8"))["rows"] if r["mode"] == "start"}
    bb = subprocess.Popen([str(EXE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    rows = []
    for k, c in enumerate(combats):
        t = tg.get((c["log"], c["segment"], c["turn"]))
        if t is None:
            continue
        f = {"id": k, "turn": max(1, c["turn"] // 2), "n": a.n,
             "player": side(c["start"]["friendly"]), "opponent": side(c["start"]["opponent"])}
        bb.stdin.write(json.dumps(f) + "\n")
        bb.stdin.flush()
        r = json.loads(bb.stdout.readline())
        if r.get("error"):
            continue
        rows.append({"log": c["log"], "segment": c["segment"], "turn": c["turn"], "won": c["winner"] == "friendly",
                     "bb": r["win"], "tg": t["sim"]["win"]})
    bb.stdin.close()
    (ROOT / "data" / "progress" / "bb_real.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"{len(rows)} combats")
    for name in ("tg", "bb"):
        buckets, pred, won, z = calibration([(r[name], r["won"]) for r in rows])
        print(f"{'TavernGym' if name == 'tg' else 'Bob' + chr(39) + 's Buddy'}: predicted {pred:.1f} wins, actual {won} ({z:+.1f} SD)")
        for lo, n, p, w in buckets:
            print(f"    {lo:.1f}-{lo + 0.2:.1f}: n={n:3d} predicted {p:.2f} won {w:.2f}")
    both = [r for r in rows if r["won"] and r["tg"] < 0.45]
    print("fights you won that TavernGym gave < 0.45: Bob's Buddy gave",
          [round(r["bb"], 2) for r in both], "TavernGym", [round(r["tg"], 2) for r in both])


if __name__ == "__main__":
    main()
