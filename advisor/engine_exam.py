"""The engine exam: the late game from your own positions (docs/CASE_LATE_GAME.md). From the start
of each of your logged turns in rounds 9-13, a network plays the turn (greedy, its seat only; the
others End at once) and its warband at End Turn is set against yours at that round's combat (its
start, before Start of Combat). Per position:

- growth: log(network's warband Attack+Health / yours), over the turn (0 = as much as you)
- funnel: the share of the turn's stat gain that went to the two minions with the most stats at
  the start (your engine as it stood), for you and for the network
- on-type: the share of the End-of-turn warband of the start warband's main type
- kept: whether those two minions are still in the warband

Two networks (`--against`) are compared pair by pair on the same positions and seeds.

    python -X utf8 -m advisor.engine_exam data/models/best.pt
    python -X utf8 -m advisor.engine_exam data/train/p37/last.pt --against data/models/best.pt
    python -X utf8 -m advisor.engine_exam data/models/best.pt --search 8 --against data/models/best.pt
"""

import argparse
import collections
import json
import math
from pathlib import Path

import numpy as np
import torch

from advisor import bridge, search
from advisor.policy import load
from advisor.state import CAT, normal_form

ROOT = Path(__file__).resolve().parents[1]
ROUNDS = range(9, 14)


def stats(m):
    return m["atk"] + m["hp"]


def main_type(board, races_of):
    c = collections.Counter(t for m in board for t in races_of(m) if t != "ALL")
    return c.most_common(1)[0][0] if c else None


def logged_races(m):
    return CAT.get(normal_form(m.get("card") or "")[0], {}).get("races") or []


def measure(start, end, races_of):
    """(funnel, on_type, kept) of a turn from board `start` to board `end` (matched by eid)."""
    top = sorted(start, key=lambda m: -stats(m))[:2]
    top_eids = {m["eid"] for m in top}
    before = {m["eid"]: stats(m) for m in start}
    gain = {m["eid"]: stats(m) - before.get(m["eid"], 0) for m in end}
    total = sum(max(0, x) for x in gain.values())
    funnel = sum(max(0, gain.get(e, 0)) for e in top_eids) / total if total > 0 else None
    t = main_type(start, races_of)
    on = sum(t in races_of(m) or "ALL" in races_of(m) for m in end) / len(end) if end and t else None
    kept = all(any(m["eid"] == e for m in end) for e in top_eids)
    return funnel, on, kept


def positions(decisions, combats):
    """[(first decision of the turn, your board at that round's combat)] for rounds 9-13."""
    at_combat = {(c["log"], c["turn"]): c["start"]["friendly"]["board"] for c in combats}
    seen, out = set(), []
    for d in decisions:
        r = (d["turn"] + 1) // 2
        key = (d["log"], d["turn"])
        if d["kind"] != "options" or d["turn"] % 2 == 0 or r not in ROUNDS or key in seen:
            continue
        seen.add(key)
        end = at_combat.get((d["log"], d["turn"] + 1))
        if end:
            out.append((d, end))
    return out


def turn_value(net, c, rng, max_steps=80):
    """The value head at the End Turn of the rest of the turn on game copy `c`, the policy
    sampled (temperature 1) through Refreshes and offers."""
    for _ in range(max_steps):
        v = json.loads(c.view(0))
        if not c.needs_action(0) or v["phase"].lower() != "recruit":
            break
        probs, value = search._policy(net, c, 0)
        a = int(rng.choice(len(probs), p=probs / probs.sum()))
        if a == v["actions"]["END"] and not v["me"]["pending"]:
            return value
        c.step(0, a)
    return search._policy(net, c, 0)[1]


def lookahead_action(g, net, seed, top=4, reps=2):
    """A full-turn lookahead: the policy's `top` actions and every legal Activate, each played
    `reps` times to the turn's end on a fair copy (hidden cards re-dealt), the best by the mean
    value there (End Turn: the value now)."""
    v = json.loads(g.view(0))
    probs, now = search._policy(net, g, 0)
    legal = np.flatnonzero(probs > 0)
    cands = list(legal[np.argsort(-probs[legal])][:top])
    cands += [int(a) for a in legal if 23 <= a < 30 and a not in cands]  # Activates
    if len(cands) == 1:
        return int(cands[0])
    rng = np.random.default_rng(seed)
    best, best_v = None, -np.inf
    for a in cands:
        a = int(a)
        if a == v["actions"]["END"] and not v["me"]["pending"]:
            val = now
        else:
            vals = []
            for r in range(reps):
                c = search.fair_copy(g, 0, seed=seed * 7919 + a * 31 + r)
                c.step(0, a)
                vals.append(turn_value(net, c, rng))
            val = float(np.mean(vals))
        if val > best_v:
            best, best_v = a, val
    return best


# `--force CARD...`: a probe, not a player: whenever one of these minions can Activate, it does
FORCE = set()


def forced(v):
    """The first legal Activate of a FORCE minion, or None."""
    if v["me"]["pending"]:
        return None
    for i, m in enumerate(v["me"]["board"]):
        if (m.get("id") or "").split("_G")[0] in FORCE and v["mask"][23 + i]:
            return 23 + i
    return None


# `--funnel`: a probe: a friendly target or a Magnetization the network picks goes to the biggest
# minion of the warband's main type instead (its engine, as you funnel buffs into it)
FUNNEL = [False]


def funnel(v, a):
    me = v["me"]
    board = me["board"]
    t = main_type(board, lambda m: m.get("races") or [])
    engine = [m for m in board if t in (m.get("races") or []) or "ALL" in (m.get("races") or [])]
    if not engine:
        return a
    big = max(engine, key=stats)
    p = me["pending"]
    if isinstance(p, dict) and p.get("kind") == "target" and 30 <= a < 46:
        opts = p.get("targets") or []
        friendly = {m["eid"] for m in board}
        if opts[a - 30] in friendly and big["eid"] in opts:
            return 30 + opts.index(big["eid"])
    if 126 <= a < 196:
        h, b = divmod(a - 126, 7)
        i = next(i for i, m in enumerate(board) if m["eid"] == big["eid"])
        alt = 126 + h * 7 + i
        if "MECHANICAL" in (big.get("races") or []) and v["mask"][alt]:
            return alt
    return a


@torch.no_grad()
def play_turn(net, d, combats, seed, search_k=0, look=None):
    """(start board, End-of-turn board) of the network's turn from decision `d` (view minions).
    `search_k` > 0: each step is the first of the plan search's best plan (advisor.search, the
    greedy plan and k sampled ones, re-planned at every decision as the live advisor does)."""
    g, gaps = bridge.build(d, bridge.game_combats(combats, d), seed=seed)
    if gaps:
        return None
    start = json.loads(g.view(0))["me"]["board"]
    for step in range(300):
        v = json.loads(g.view(0))
        if not g.needs_action(0) or v["phase"].lower() != "recruit":
            return None
        a = forced(v) if FORCE else None
        if a is not None:
            pass
        elif look:
            a = lookahead_action(g, net, seed * 100_003 + step, *look)
        elif search_k:
            plan, _, _ = search.best_plan(g, net, 0, None, search_k, seed=seed * 100_003 + step)
            a = plan[0] if plan else None
        if a is None:
            probs, _ = search._policy(net, g, 0)
            a = int(np.argmax(probs))
            if FUNNEL[0]:
                a = funnel(v, a)
        if a == v["actions"]["END"] and not v["me"]["pending"]:
            return start, v["me"]["board"]
        g.step(0, a)
    return None


def exam(net, pos, combats, seeds, search_k=0, look=None, types=None):
    rows = []
    for d, real_end in pos:
        real_start = d["state"]["friendly"]["board"]
        if types and main_type(real_start, logged_races) not in types:
            continue
        yours = measure(real_start, real_end, logged_races)
        real = sum(stats(m) for m in real_end)
        for s in seeds:
            r = play_turn(net, d, combats, s, search_k, look)
            if r is None or real <= 0:
                continue
            start, end = r
            sim = sum(stats(m) for m in end)
            top = max(real_start, key=stats) if real_start else {}
            rows.append({"log": d["log"], "turn": d["turn"], "seed": s,
                         "engine": CAT.get(normal_form(top.get("card") or "")[0], {}).get("name"),
                         "growth": math.log(max(sim, 1) / real), "you": yours,
                         "net": measure(start, end, lambda m: m.get("races") or [])})
    return rows


def summary(rows):
    def mean(xs):
        xs = [x for x in xs if x is not None]
        return (round(float(np.mean(xs)), 3), round(float(np.std(xs, ddof=1) / math.sqrt(len(xs))), 3)) if len(xs) > 1 else None
    out = {"n": len(rows), "growth": mean([r["growth"] for r in rows]),
           "ratio": round(math.exp(np.mean([r["growth"] for r in rows])), 3) if rows else None}
    for i, k in enumerate(("funnel", "on_type", "kept")):
        out[k] = {"you": mean([float(r["you"][i]) if r["you"][i] is not None else None for r in rows]),
                  "net": mean([float(r["net"][i]) if r["net"][i] is not None else None for r in rows])}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("--against", help="a second network, compared pair by pair")
    ap.add_argument("--decisions", default=str(ROOT / "data" / "replay" / "decisions.jsonl"))
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--out", help="the rows as JSON")
    ap.add_argument("--search", type=int, default=0, metavar="K",
                    help="the candidate (not --against) plays with the plan search over K plans")
    ap.add_argument("--lookahead", type=int, nargs=2, metavar=("TOP", "REPS"),
                    help="the candidate plays with the full-turn lookahead (lookahead_action)")
    ap.add_argument("--types", nargs="+", help="only positions whose main type is one of these (BEAST MECHANICAL...)")
    ap.add_argument("--force", nargs="+", default=[], help="a probe: the candidate Activates these minions whenever it can")
    ap.add_argument("--funnel", action="store_true", help="a probe: the candidate's friendly targets and Magnetizations go to its engine")
    a = ap.parse_args()
    torch.set_num_threads(4)
    decisions = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    pos = positions(decisions, combats)
    seeds = [11 + k for k in range(a.seeds)]
    res = {}
    for name, path in [("cand", a.checkpoint)] + ([("champ", a.against)] if a.against else []):
        net, _ = load(path, "cpu")
        cand = name == "cand"
        FORCE.clear()
        FORCE.update(a.force if cand else [])
        FUNNEL[0] = a.funnel and cand
        rows = exam(net.eval(), pos, combats, seeds, a.search if cand else 0,
                    a.lookahead if cand else None, a.types)
        res[name] = rows
        s = summary(rows)
        print(json.dumps({"net": path, **s}), flush=True)
        by = collections.defaultdict(list)
        for r in rows:
            by[r["engine"]].append(r["growth"])
        for e, g in sorted(by.items(), key=lambda x: -len(x[1]))[:12]:
            print(f"  {e:<28} n {len(g):3d}  x{math.exp(np.mean(g)):.2f} of yours")
    if a.against:
        pair = {(r["log"], r["turn"], r["seed"]): r["growth"] for r in res["champ"]}
        diffs = [r["growth"] - pair[k] for r in res["cand"] if (k := (r["log"], r["turn"], r["seed"])) in pair]
        if len(diffs) > 1:
            m, se = float(np.mean(diffs)), float(np.std(diffs, ddof=1) / math.sqrt(len(diffs)))
            print(json.dumps({"paired_growth_diff": round(m, 3), "se": round(se, 3), "n": len(diffs),
                              "ratio": round(math.exp(m), 3)}))
    if a.out:
        Path(a.out).write_text(json.dumps(res), encoding="utf-8")


if __name__ == "__main__":
    main()
