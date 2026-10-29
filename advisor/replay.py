"""Replay logged combats in TavernGym and compare with what happened in the game.

Each combat from advisor.logs is rebuilt with the debug commands (heroes, Hero Powers,
trinkets, tiers, health, warbands with logged stats and keywords, attached Dark Gifts and
magnetized minions) and simulated N times. A combat agrees when the logged result is a likely
outcome of the simulation; a logged winner the simulator gives under 2% points at a rules or
content gap (or at state the log shows but the setup can't carry, listed per combat).

Two modes: "start" simulates from the boards before Start of Combat; "attack" from the boards
just before the first attack, with the logged first attacker (isolates the attack phase).

Run:    python -X utf8 -m advisor.replay data/replay/combats.jsonl [-n 500] [--out FILE]
"""

import argparse
import collections
import json
import sys
from pathlib import Path

from advisor.state import damage_cap, debug, recruit_game, set_side

SURPRISE = 0.02
SIDES = ("friendly", "opponent")


def setup(c, snap, seed):
    """A TavernGym game holding the logged combat on seats 0 (friendly) and 1 (opponent).
    Returns (game, gaps): gaps are the logged parts the setup could not carry."""
    g = recruit_game(seed)
    gaps = []
    debug(g, cmd="set_turn", turn=max(1, c["turn"] // 2))
    for p, side in enumerate(SIDES):
        set_side(g, p, snap[side], gaps, side)
    return g, gaps


def replay(c, n, mode, seed):
    snap = c["start"] if mode == "start" else c["first_attack"]
    if snap is None:
        return None
    g, gaps = setup(c, snap, seed)
    cmd = {"cmd": "combat_preview", "a": 0, "b": 1, "n": n, "details": True,
           "ghost_b": snap["opponent"].get("health", 1) <= 0}
    if mode == "attack":
        cmd.update(after_start=True, first_attacker=0 if c["first_attacker"] == "friendly" else 1)
    r = json.loads(g.debug(json.dumps(cmd)))
    want = {"friendly": 0, "opponent": 1, "tie": 2}[c["winner"]]
    # The logged damage is after the cap, which depends on how many players are left; the
    # setup lobby always has eight, so the cap is applied here from the logged count.
    cap = damage_cap(max(1, c["turn"] // 2), c.get("alive") or 8)
    outcomes = collections.Counter()
    for t in r["trials"]:
        dmg = 0 if t["winner"] == 2 else t["damage"] if cap is None else min(t["damage"], cap)
        outcomes[(t["winner"], dmg)] += 1
    p_win = sum(v for (w, _), v in outcomes.items() if w == want) / n
    p_exact = outcomes[(want, c["damage"] if want < 2 else 0)] / n
    return {"log": c["log"], "segment": c["segment"], "build": c["build"], "turn": c["turn"],
            "mode": mode, "winner": c["winner"], "damage": c["damage"],
            "p_win": round(p_win, 4), "p_exact": round(p_exact, 4),
            "sim": {"win": r["win_a"], "loss": r["win_b"], "tie": r["tie"]},
            # Simulated damage when the logged winner wins: {damage: share of those wins}
            "sim_damage": {d: round(v / max(1, p_win * n), 3) for (w, d), v in
                           sorted(outcomes.items()) if w == want and want < 2},
            "gaps": sorted(set(gaps)), "surprise": p_win < SURPRISE}


def summarize(rows):
    out = {}
    for key in sorted({(r["build"], r["mode"]) for r in rows}):
        rs = [r for r in rows if (r["build"], r["mode"]) == key]
        clean = [r for r in rs if not r["gaps"]]
        def stats(x):
            if not x:
                return {"n": 0}
            return {"n": len(x),
                    "mean_p_win": round(sum(r["p_win"] for r in x) / len(x), 3),
                    "mean_p_exact": round(sum(r["p_exact"] for r in x) / len(x), 3),
                    "surprises": sum(r["surprise"] for r in x)}
        out[f"{key[0]}/{key[1]}"] = {"all": stats(rs), "no_gaps": stats(clean)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("combats")
    ap.add_argument("-n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--modes", default="start,attack")
    ap.add_argument("--out", help="JSON report (default: next to the combats file)")
    a = ap.parse_args()
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    rows = []
    for c in combats:
        for mode in a.modes.split(","):
            r = replay(c, a.n, mode, a.seed)
            if r is not None:
                rows.append(r)
    summary = summarize(rows)
    out = Path(a.out or Path(a.combats).with_name("replay_report.json"))
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    for k, v in summary.items():
        print(k, json.dumps(v))
    gaps = collections.Counter(x for r in rows if r["mode"] == "start" for x in r["gaps"])
    if gaps:
        print("setup gaps:", gaps.most_common(15))
    print(f"wrote {out}")


if __name__ == "__main__":
    sys.exit(main())
