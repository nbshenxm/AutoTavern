"""Skill exams: how far a network is from master play, one skill at a time (the goal: 14k+ MMR,
AutoTavern's level). Each exam is a fixed set of positions from your games with a reference
that doesn't depend on the network: what a search over the simulator finds best, or what you
did. Results are appended to data/progress/exams.jsonl (one row per network and exam).

- positioning: your warband just before each logged combat. Three orders against the warband
  you really met (combat_preview, win - loss): yours, the network's (from your turn's last
  decision it may only move minions or end the turn) and the best a swap/insert search finds.
  Score: the network's gap to the best (0 = master), and how often it is within 0.05.
- habits: your turns against the network's from each turn's start (advisor.compare_play), by
  phase: Freezes, Upgrades, buys on your warband's type, cards played (holding), Gold kept,
  Refreshes, sells. Score: the mean relative gap to you over those (0 = plays like you). Your
  habits are a milestone on the way to 14k, not the ceiling (a 7k player's turns).

    python -X utf8 -m advisor.exams data/models/best.pt --exam positioning
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import taverngym
import torch

from advisor import bridge, replay
from advisor.policy import load
from advisor.search import _policy

ROOT = Path(__file__).resolve().parents[1]
L = dict(taverngym.layout())
OUT = ROOT / "data" / "progress" / "exams.jsonl"


def score(c, order, n=200, seed=7):
    """Win - loss of seat 0 in combat `c` (start snapshot) with its warband in `order` (indices
    into the logged warband)."""
    snap = json.loads(json.dumps(c["start"]))
    board = snap["friendly"]["board"]
    snap["friendly"]["board"] = [board[i] for i in order]
    g, _ = replay.setup(c, snap, seed)
    r = json.loads(g.debug(json.dumps({"cmd": "combat_preview", "a": 0, "b": 1, "n": n})))
    return r["win_a"] - r["win_b"]


def best_order(c, start, n=100):
    """Hill-climbing over swaps and single moves from `start`: (order, score)."""
    best, best_s = list(start), score(c, start, n)
    k = len(best)
    for _ in range(3):
        improved = False
        cands = []
        for i in range(k):
            for j in range(k):
                if i == j:
                    continue
                o = list(best)
                o.insert(j, o.pop(i))  # move i to j
                cands.append(o)
                if i < j:
                    o2 = list(best)
                    o2[i], o2[j] = o2[j], o2[i]
                    cands.append(o2)
        for o in cands:
            s = score(c, o, n)
            if s > best_s + 0.02:
                best, best_s, improved = o, s, True
        if not improved:
            break
    return best, best_s


def network_order(d, combats, net, c):
    """The order the network leaves your warband in from decision `d` (only moves or End Turn),
    as indices into combat `c`'s logged warband; None when the warbands don't match."""
    g, gaps = bridge.build(d, bridge.game_combats(combats, d))
    if gaps:
        return None
    start = [m["eid"] for m in json.loads(g.view(0))["me"]["board"]]
    allowed = np.zeros(L["N_ACTIONS"], bool)
    allowed[L["A_END"]] = True
    allowed[L["A_MOVE"]:L["A_MOVE"] + L["N_BOARD"] * L["N_BOARD"]] = True
    for _ in range(20):
        if not g.needs_action(0):
            break
        mask = np.array(json.loads(g.view(0))["mask"], bool) & allowed
        if not mask.any():
            break
        p, _ = _policy(net, g, 0, mask)
        a = int(p.argmax())
        if a == L["A_END"]:
            break
        g.step(0, a)
    final = [m["eid"] for m in json.loads(g.view(0))["me"]["board"]]
    if sorted(final) != sorted(start):
        return None
    # the decision's warband -> the combat's: the same minions (card, stats) in its order
    logged = d["state"]["friendly"]["board"]
    combat = c["start"]["friendly"]["board"]
    used, to_combat = set(), {}
    for i, m in enumerate(logged):
        j = next((j for j, x in enumerate(combat) if j not in used and x["card"] == m["card"]
                  and x["atk"] == m["atk"] and x["hp"] == m["hp"]), None)
        if j is None:
            return None
        used.add(j)
        to_combat[start[i]] = j
    return [to_combat[e] for e in final]


def positioning(net, decisions, combats, limit=None):
    last = {}
    for d in decisions:
        if d["kind"] == "options" and d["turn"] % 2 == 1:
            last[(d["log"], d["player_id"], d["turn"] + 1)] = d
    rows = []
    for c in combats:
        d = last.get((c["log"], c["player_id"], c["turn"]))
        board = c["start"]["friendly"]["board"]
        if d is None or len(board) < 3 or not c["start"]["opponent"]["board"]:
            continue
        net_o = network_order(d, combats, net, c)
        if net_o is None:
            continue
        yours = list(range(len(board)))
        best, _ = best_order(c, yours)
        s = {k: score(c, o, 400) for k, o in (("yours", yours), ("network", net_o), ("best", best))}
        rows.append(s)
        if limit and len(rows) >= limit:
            break
    gap = [r["best"] - r["network"] for r in rows]
    return {"n": len(rows), "network": round(float(np.mean([r["network"] for r in rows])), 3),
            "yours": round(float(np.mean([r["yours"] for r in rows])), 3),
            "best": round(float(np.mean([r["best"] for r in rows])), 3),
            "gap": round(float(np.mean(gap)), 3),
            "within_0.05": round(float(np.mean([g <= 0.05 for g in gap])), 3),
            "your_gap": round(float(np.mean([r["best"] - r["yours"] for r in rows])), 3)}


HABITS = ("freeze", "upgrade", "bought on-tribe", "play", "gold left", "refresh", "sell")


def habits(net, decisions, combats):
    from advisor import compare_play
    table = compare_play.compare(net, decisions, combats, compare_play.EARLY_BANDS + compare_play.BANDS)
    gaps, out = [], {}
    for band, t in table.items():
        row = {}
        for k in HABITS:
            you, it = t[k]
            row[k] = [you, it]
            gaps.append(abs(it - you) / max(abs(you), 0.25))  # relative (floored: rare habits)
        out[band] = row
    return {"n": sum(t["turns"] for t in table.values()), "gap": round(float(np.mean(gaps)), 3), "bands": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("net")
    ap.add_argument("--exam", default="all", choices=("positioning", "habits", "all"))
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    torch.set_num_threads(4)
    net, ck = load(a.net, "cpu")
    decisions = [json.loads(l) for l in open(ROOT / "data" / "replay" / "decisions.jsonl", encoding="utf-8")]
    combats = [json.loads(l) for l in open(ROOT / "data" / "replay" / "combats.jsonl", encoding="utf-8")]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for exam in (("positioning", "habits") if a.exam == "all" else (a.exam,)):
        if exam == "positioning":
            res = positioning(net, decisions, combats, a.limit)
        else:
            res = habits(net, decisions, combats)
        row = {"time": datetime.now().isoformat(timespec="minutes"), "net": a.net,
               "source": ck.get("source"), "iteration": ck.get("iteration"), "exam": exam, **res}
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        print(json.dumps(row)[:700])


if __name__ == "__main__":
    main()
