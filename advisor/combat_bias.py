"""Does the simulator undervalue boards like yours? Your logged fights win more often than TavernGym
predicts (+2.7 SD from Start of Combat on the Nov 4 build, spread over rounds 1-10). If the excess
sits in committed (one-tribe) boards in the mid-game, the simulator teaches every training method
that synergy doesn't pay (Nov 5: forced tribe-keeping costs main1 +0.30..+0.45 places, its warband
10% smaller three rounds on). Each logged combat is replayed from Start of Combat (advisor.replay,
`-n` fights), and the predicted chance that you win is set beside what happened, split by round and
by how committed each warband was (the share of its most common tribe; ALL counts for every tribe).

    python -X utf8 -m advisor.combat_bias data/replay/combats.jsonl --out data/audit/combat_bias.json
"""

import argparse
import collections
import json
import math
from pathlib import Path

from advisor.replay import owed_minions, replay, used_powers
from advisor.state import CAT, normal_form

BANDS = [("rounds 1-6", 1, 7), ("rounds 7-10", 7, 11), ("rounds 11+", 11, 99)]
COMMIT = [("mixed (<= 3/7 one tribe)", 0.0, 0.45), ("partial (4/7)", 0.45, 0.65), ("committed (5/7+)", 0.65, 1.01)]


def races(card):
    return set(CAT.get(normal_form(card)[0], {}).get("races") or CAT.get(card, {}).get("races") or [])


def commitment(board):
    """(the most common tribe, its share of the warband), ALL counting for every tribe."""
    if not board:
        return None, 0.0
    rs = [races(m["card"]) for m in board]
    c = collections.Counter(r for x in rs for r in x if r != "ALL")
    if not c:
        return None, 0.0
    top = c.most_common(1)[0][0]
    return top, sum(top in x or "ALL" in x for x in rs) / len(board)


def bias(rows):
    """Wins you got minus the simulator's expected wins, with its z (ties count half both ways)."""
    if not rows:
        return {"n": 0}
    got = sum(1.0 if r["winner"] == "friendly" else 0.5 if r["winner"] == "tie" else 0.0 for r in rows)
    exp = sum(r["p_you"] + 0.5 * r["p_tie"] for r in rows)
    var = sum(r["p_you"] * (1 - r["p_you"]) + 0.25 * r["p_tie"] for r in rows)
    return {"n": len(rows), "won": round(got, 1), "expected": round(exp, 1),
            "excess": round(got - exp, 1), "z": round((got - exp) / math.sqrt(max(var, 1e-9)), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("combats")
    ap.add_argument("-n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--build", type=int, help="only this client build (default: the newest in the file)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    build = a.build or max(c["build"] for c in combats)
    combats = [c for c in combats if c["build"] == build]
    dpath = Path(a.combats).with_name("decisions.jsonl")
    decisions = [json.loads(l) for l in open(dpath, encoding="utf-8")] if dpath.exists() else []
    used, owed = used_powers(decisions), owed_minions(decisions)
    rows = []
    for k, c in enumerate(combats):
        key = (c["log"], c["player_id"], c["turn"])
        r = replay(c, a.n, "start", a.seed, used.get(key, ()), owed.get(key, ()))
        if r is None:
            continue
        you, ys = commitment(c["start"]["friendly"]["board"])
        opp, os_ = commitment(c["start"]["opponent"]["board"])
        rows.append({"log": c["log"], "turn": c["turn"], "round": max(1, c["turn"] // 2), "winner": c["winner"],
                     "p_you": r["sim"]["win"], "p_tie": r["sim"]["tie"], "gaps": r["gaps"],
                     "you_tribe": you, "you_share": round(ys, 3), "opp_tribe": opp, "opp_share": round(os_, 3),
                     "you_minions": len(c["start"]["friendly"]["board"])})
        if k % 25 == 0:
            print(f"{k}/{len(combats)}", flush=True)
    out = {"build": build, "combats": len(rows), "all": bias(rows), "by_round": {}, "by_commitment": {},
           "by_round_and_commitment": {}, "by_tribe": {}}
    for name, lo, hi in BANDS:
        out["by_round"][name] = bias([r for r in rows if lo <= r["round"] < hi])
    for name, lo, hi in COMMIT:
        out["by_commitment"][name] = bias([r for r in rows if lo <= r["you_share"] < hi])
    for bname, blo, bhi in BANDS:
        for cname, clo, chi in COMMIT:
            out["by_round_and_commitment"][f"{bname} / {cname}"] = bias(
                [r for r in rows if blo <= r["round"] < bhi and clo <= r["you_share"] < chi])
    for t in sorted({r["you_tribe"] for r in rows if r["you_tribe"]}):
        out["by_tribe"][t] = bias([r for r in rows if r["you_tribe"] == t and r["you_share"] >= 0.65])
    out["clean_only"] = bias([r for r in rows if not r["gaps"]])
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({**out, "rows": rows}, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
