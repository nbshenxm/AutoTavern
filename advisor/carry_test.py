"""What carries from one turn to the next: the player's warband at the end of each logged
recruit turn (the state of its last decision, rebuilt by the bridge), End Turn in TavernGym,
the combat against the warband the player really met that round (every other seat is given it,
so whoever is paired brings it), and the next turn's start; then the warband against the one
the log shows at the start of the next turn. advisor.turn_replay restarts every turn from the
log and advisor.replay checks a combat's result, so neither sees what a warband keeps from
combat (permanent gains, Avenge, Deathrattles that buff the warband or the player's counters)
or from end and start of turn effects: where real late warbands grow most.

    python -X utf8 -m advisor.carry_test
"""

import argparse
import collections
import json
from pathlib import Path

from advisor import bridge
from advisor.state import CAT, add_minion, debug, normal_form


def _stats(board):
    return sum(m["atk"] + m["hp"] for m in board)


def _name(c):
    return CAT.get(normal_form(c or "")[0], {}).get("name", c)


def pairs(decisions):
    """(last decision of a turn, first decision of the next turn) of the same game segment."""
    opts = [d for d in decisions if d["kind"] == "options" and d["turn"] % 2 == 1]
    last, first = {}, {}
    for d in opts:
        k = (d["log"], d["segment"], d["turn"])
        last[k] = d
        first.setdefault(k, d)
    for (log, seg, t), d in last.items():
        nxt = first.get((log, seg, t + 2))
        if nxt is not None:
            yield d, nxt


def matched(before, real, sim):
    """[(card, stats before, real stats, TavernGym stats)]: each card's copies paired in board
    order (a position can shift when a minion dies or one is made)."""
    def by_card(board):
        out = collections.defaultdict(list)
        for m in board:
            out[normal_form(m.get("card") or m.get("id") or "")[0]].append(m["atk"] + m["hp"])
        return out
    b, r, t = by_card(before), by_card(real), by_card(sim)
    rows = []
    for card, xs in r.items():
        for i, x in enumerate(xs):
            rows.append((card, b[card][i] if i < len(b[card]) else None, x,
                         t[card][i] if i < len(t[card]) else None))
    return rows


def carry(d, nxt, combats, seed=7):
    """{round, real, sim, per-minion [(card, real stats, sim stats)]} or None (not rebuilt)."""
    met = [c for c in combats if c["log"] == d["log"] and c["player_id"] == d["player_id"]
           and c["turn"] == d["turn"] + 1]
    if not met:
        return None
    g, gaps = bridge.build(d, bridge.game_combats(combats, d), seed=seed)
    if gaps:
        return None
    opp = met[0]["start"]["opponent"]["board"]
    for s in range(1, 8):
        debug(g, cmd="clear_zone", p=s, zone="board")
        for m in opp[:7]:
            add_minion(g, s, "board", m, [], "seen")
    turn0 = json.loads(g.view(0))["turn"]
    for _ in range(400):
        v = json.loads(g.view(0))
        if v["turn"] > turn0 and g.needs_action(0):
            break
        if not v["me"]["alive"]:
            return None
        acted = False
        for s in range(8):
            if g.needs_action(s):
                try:
                    g.step(s, 0)  # End Turn (a choice pending: its first option)
                except ValueError:
                    m = json.loads(g.view(s))["mask"]
                    g.step(s, m.index(True))
                acted = True
                break
        if not acted:
            return None
    else:
        return None
    sim = json.loads(g.view(0))["me"]["board"]
    real = nxt["state"]["friendly"]["board"]
    before = d["state"]["friendly"]["board"]
    rows = [(c, x, y) for c, _, x, y in matched(before, real, sim)]
    return {"round": (d["turn"] + 1) // 2, "real": _stats(real), "sim": _stats(sim),
            "cards": [m["card"] for m in real], "rows": rows, "before": _stats(before),
            "per_card": matched(before, real, sim)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisions", default="data/replay/decisions.jsonl")
    ap.add_argument("--combats", default="data/replay/combats.jsonl")
    ap.add_argument("--examples", type=int, default=12)
    ap.add_argument("--seeds", type=int, default=1, help="combats per turn pair (their outcome is random)")
    ap.add_argument("--json", help="the per-card table, as JSON")
    a = ap.parse_args()
    decisions = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    out = [r for d, n in pairs(decisions) for k in range(a.seeds) if (r := carry(d, n, combats, seed=7 + k))]
    by = collections.defaultdict(list)
    for r in out:
        by["rounds 1-6" if r["round"] <= 6 else "rounds 7-9" if r["round"] <= 9 else "rounds 10+"].append(r)
    print(f"{len(out)} turn pairs rebuilt")
    for k in ("rounds 1-6", "rounds 7-9", "rounds 10+"):
        rs = by.get(k, [])
        if not rs:
            continue
        gain_real = sum(r["real"] - r["before"] for r in rs)
        gain_sim = sum(r["sim"] - r["before"] for r in rs)
        exact = sum(r["real"] == r["sim"] for r in rs)
        print(f"{k}: n={len(rs)} exact {exact}  warband gained over combat and the turn change: "
              f"real {gain_real}, TavernGym {gain_sim} ({gain_sim / gain_real if gain_real else 0:.2f}x)")
    # Per card: what its copies gained over combat and the turn change, real and in TavernGym
    # (averaged over the seeds), where both boards have the copy
    cards = collections.defaultdict(lambda: {"n": 0, "real": 0.0, "sim": 0.0, "exact": 0})
    for r in out:
        for card, b, x, y in r["per_card"]:
            if b is None or y is None:
                continue
            c = cards[card]
            c["n"] += 1 / a.seeds
            c["real"] += (x - b) / a.seeds
            c["sim"] += (y - b) / a.seeds
            c["exact"] += (x == y) / a.seeds
    ranked = sorted(cards.items(), key=lambda kv: -abs(kv[1]["real"] - kv[1]["sim"]))
    print("cards whose gain differs most (n, real gain, TavernGym gain, exact share):")
    for card, c in ranked[:25]:
        if abs(c["real"] - c["sim"]) < 1:
            break
        print(f"  {_name(card):28s} {card:14s} n={c['n']:5.1f} real {c['real']:9.0f}  TavernGym {c['sim']:9.0f}"
              f"  exact {c['exact'] / max(c['n'], 1e-9):.0%}")
    if a.json:
        Path(a.json).write_text(json.dumps({k: {**v, "name": _name(k)} for k, v in ranked}, indent=1), encoding="utf-8")
    for r in sorted(out, key=lambda r: r["sim"] - r["real"])[:a.examples]:
        print(f"  round {r['round']}: before {r['before']}, real {r['real']}, TavernGym {r['sim']}:",
              [(_name(c), x, y) for c, x, y in r["rows"] if x != y][:5])


if __name__ == "__main__":
    main()
