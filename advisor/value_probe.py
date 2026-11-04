"""Does the network's value head know your late turn is better? From the start of each of your
logged turns in rounds 9-13 (advisor.engine_exam's positions): your turn replayed in TavernGym
(the Tavern follows the log, choices take your pick: advisor.turn_replay) up to your End Turn,
and the network's own greedy turn; the value head (its expected placement reward, 1st = 1, 8th = -1) and the
warband's stats at both End Turns. If it prefers your turn where yours is bigger, a search over
turns scored by it would find your play; if not, the value head has to learn it first.

    python -X utf8 -m advisor.value_probe data/models/best.pt
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import taverngym
import torch

from advisor import bridge, engine_exam, recruit_diff, search, turn_replay
from advisor.policy import load

ROOT = Path(__file__).resolve().parents[1]
L = dict(taverngym.layout())


def your_turn(turn, combats):
    """The game at your End Turn (TavernGym after your logged actions), or None."""
    while turn and turn[0]["kind"] != "options":
        turn = turn[1:]
    if not turn:
        return None
    g, gaps = bridge.build(turn[0], bridge.game_combats(combats, turn[0]))
    if gaps:
        return None
    for k, d in enumerate(turn):
        v = json.loads(g.view(0))
        if d["kind"] != "options":
            if v["me"]["pending"] and not turn_replay.pick(g, d, L):
                return None
            continue
        if v["me"]["pending"]:
            return None
        if k:
            g = turn_replay.set_shop(g, d["state"])
        act = turn_replay.action_of(d, L, g)
        if act is None:
            return None
        actions, target, _ = act
        if actions == [L["A_END"]]:
            return g
        try:
            for a in actions:
                g.step(0, a)
            if target is not None:
                i = recruit_diff._target_choice(g, d, target)
                if i is not None:
                    g.step(0, L["A_CHOOSE"] + i)
        except ValueError:
            return None
    return None


def net_turn(net, d, combats, seed=11):
    g, gaps = bridge.build(d, bridge.game_combats(combats, d), seed=seed)
    if gaps:
        return None
    for _ in range(300):
        v = json.loads(g.view(0))
        if v["phase"].lower() != "recruit":
            return None
        probs, _ = search._policy(net, g, 0)
        a = int(np.argmax(probs))
        if a == v["actions"]["END"] and not v["me"]["pending"]:
            return g
        g.step(0, a)
    return None


def at_end(net, g):
    v = json.loads(g.view(0))
    _, value = search._policy(net, g, 0)
    return value, sum(m["atk"] + m["hp"] for m in v["me"]["board"])


@torch.no_grad()
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint", nargs="?", default=str(ROOT / "data" / "models" / "best.pt"))
    ap.add_argument("--decisions", default=str(ROOT / "data" / "replay" / "decisions.jsonl"))
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--out")
    a = ap.parse_args()
    torch.set_num_threads(4)
    net, _ = load(a.checkpoint, "cpu")
    net.eval()
    decisions = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    turns = {}
    for d in decisions:
        if d["turn"] % 2 == 1:
            turns.setdefault((d["log"], d["turn"]), []).append(d)
    rows = []
    for d, _ in engine_exam.positions(decisions, combats):
        gy = your_turn(turns[(d["log"], d["turn"])], combats)
        gn = net_turn(net, d, combats)
        if gy is None or gn is None:
            continue
        (vy, sy), (vn, sn) = at_end(net, gy), at_end(net, gn)
        top = max(d["state"]["friendly"]["board"], key=engine_exam.stats, default={})
        rows.append({"log": d["log"], "turn": d["turn"], "engine": top.get("card"),
                     "value_you": vy, "value_net": vn, "stats_you": sy, "stats_net": sn})
        print(f"{d['log'][-8:]} r{(d['turn'] + 1) // 2}: you {sy:>7} value {vy:+.3f} | net {sn:>7} value {vn:+.3f}", flush=True)
    bigger = [r for r in rows if r["stats_you"] > 1.2 * r["stats_net"]]
    smaller = [r for r in rows if r["stats_net"] > 1.2 * r["stats_you"]]
    diff = [r["value_you"] - r["value_net"] for r in rows]
    print(json.dumps({
        "n": len(rows),
        "value_you_minus_net": (round(float(np.mean(diff)), 4), round(float(np.std(diff, ddof=1) / math.sqrt(len(diff))), 4)) if len(diff) > 1 else None,
        "prefers_yours": round(float(np.mean([x > 0 for x in diff])), 3) if diff else None,
        "where_yours_is_bigger": {"n": len(bigger), "prefers_yours": round(float(np.mean([r["value_you"] > r["value_net"] for r in bigger])), 3) if bigger else None},
        "where_its_own_is_bigger": {"n": len(smaller), "prefers_yours": round(float(np.mean([r["value_you"] > r["value_net"] for r in smaller])), 3) if smaller else None},
    }))
    if a.out:
        Path(a.out).write_text(json.dumps(rows), encoding="utf-8")


if __name__ == "__main__":
    main()
