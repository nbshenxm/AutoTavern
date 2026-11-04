"""The mid-game exam: from your logged position at the start of rounds 6-9, a network plays every
seat on for `--ahead` rounds (greedy), and at each of its End Turns its warband is set against
yours at that round's combat (docs/CASE_LATE_GAME.md: you hold the engine's type from rounds 6-8
and the engine itself from round 9 or so). Per position and round ahead:

- growth: log(its warband Attack+Health / yours)
- type: how many minions of your main type at that round it has, against yours
- engine: whether it holds the card that carried your game at its end (your biggest minion)
- Tier: its Tavern Tier against yours

    python -X utf8 -m advisor.mid_exam data/models/best.pt --against data/models/best.pt
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


def races(card):
    return [r for r in (CAT.get(normal_form(card or "")[0], {}).get("races") or []) if r != "ALL"]


def main_type(cards):
    c = collections.Counter(t for x in cards for t in races(x))
    return c.most_common(1)[0][0] if c else None


def positions(decisions, combats, rounds):
    """[(start decision, {round: (your combat board, your Tier)}, your engine card)]."""
    at_combat = {(c["log"], c["turn"]): c["start"]["friendly"]["board"] for c in combats}
    first, last, tier = {}, {}, {}
    for d in decisions:
        if d["kind"] != "options" or d["turn"] % 2 == 0:
            continue
        r = (d["turn"] + 1) // 2
        first.setdefault((d["log"], r), d)
        last[d["log"]] = max(last.get(d["log"], (0, None)), (r, d), key=lambda x: x[0])
        tier[(d["log"], r)] = d["state"]["friendly"].get("tier")
    out = []
    for (log, r), d in sorted(first.items(), key=lambda x: (x[0][0], x[0][1])):
        if r not in rounds or last[log][0] < 11:
            continue
        end = last[log][1]["state"]["friendly"]["board"]
        engine = normal_form(max(end, key=lambda m: m["atk"] + m["hp"])["card"])[0] if end else None
        yours = {k: (at_combat[(log, 2 * k)], tier.get((log, k)))
                 for k in range(r, r + 4) if (log, 2 * k) in at_combat}
        if r in yours:
            out.append((d, yours, engine))
    return out


def probe_mask(v, mask, lock):
    """`--type-lock` (a probe): no selling a minion of type `lock`, no buying a minion without it."""
    m = np.array(mask, bool)
    for i, x in enumerate(v["me"]["board"]):
        if lock in (x.get("races") or []):
            m[23 - 7 + i] = False  # A_SELL + i (16..22)
    for j, x in enumerate(v["me"]["shop"]):
        if x.get("type") == "minion" and lock not in (x.get("races") or []) and "ALL" not in (x.get("races") or []):
            m[8 + j] = False  # A_BUY + j
    return m if m.any() else None


@torch.no_grad()
def rollout(net, d, combats, seed, ahead, tiers=None, lock=None):
    """{round: (seat 0's board at its End Turn, its Tier)} for rounds r .. r+ahead. Probes for seat
    0: `tiers` {round: Tier}: it Upgrades whenever below it; `lock`: probe_mask's type."""
    g, gaps = bridge.build(d, bridge.game_combats(combats, d), seed=seed)
    if gaps:
        return None
    r0 = (d["turn"] + 1) // 2
    out = {}
    for _ in range(100_000):
        if g.is_over():
            break
        stepped = False
        for seat in range(g.num_players):
            if not g.needs_action(seat):
                continue
            v = json.loads(g.view(seat))
            if v["turn"] > r0 + ahead:
                return out
            mask = None
            if seat == 0 and lock and v["phase"].lower() == "recruit" and not v["me"]["pending"]:
                mask = probe_mask(v, v["mask"], lock)
            probs, _ = search._policy(net, g, seat, mask)
            a = int(probs.argmax())
            if seat == 0 and tiers and v["phase"].lower() == "recruit" and not v["me"]["pending"]:
                want = max((t for r, t in tiers.items() if r <= v["turn"] and t), default=None)
                if want and v["me"]["tier"] < want and v["mask"][3]:
                    a = 3  # A_UPGRADE
            if seat == 0 and v["phase"].lower() == "recruit" and not v["me"]["pending"] and a == v["actions"]["END"]:
                out[v["turn"]] = (v["me"]["board"], v["me"]["tier"])
            g.step(seat, a)
            stepped = True
        if not stepped:
            break
    return out


def exam(net, pos, combats, seeds, ahead, follow_tier=False, type_lock=False):
    rows = []
    for d, yours, engine in pos:
        r0 = (d["turn"] + 1) // 2
        tiers = {r: t for r, (_, t) in yours.items()} if follow_tier else None
        lock = main_type([m["card"] for m in d["state"]["friendly"]["board"]]) if type_lock else None
        for s in seeds:
            sim = rollout(net, d, combats, s, ahead, tiers, lock)
            if not sim:
                continue
            for k in range(ahead + 1):
                r = r0 + k
                if r not in yours or r not in sim:
                    continue
                yb, yt = yours[r]
                nb, nt = sim[r]
                real = sum(m["atk"] + m["hp"] for m in yb)
                if real <= 0:
                    continue
                t = main_type([m["card"] for m in yb])
                rows.append({"log": d["log"], "start": r0, "ahead": k, "seed": s,
                             "growth": math.log(max(1, sum(m["atk"] + m["hp"] for m in nb)) / real),
                             "type_you": sum(t in races(m["card"]) for m in yb) if t else 0,
                             "type_net": sum(t in (m.get("races") or []) for m in nb) if t else 0,
                             "engine_you": any(normal_form(m["card"])[0] == engine for m in yb),
                             "engine_net": any(normal_form(m.get("id") or "")[0] == engine for m in nb),
                             "tier_you": yt, "tier_net": nt})
    return rows


def summary(rows):
    out = {}
    for k in sorted({r["ahead"] for r in rows}):
        rs = [r for r in rows if r["ahead"] == k]
        g = [r["growth"] for r in rs]
        out[f"+{k}"] = {"n": len(rs), "ratio": round(math.exp(np.mean(g)), 3),
                        "se": round(float(np.std(g, ddof=1) / math.sqrt(len(g))), 3) if len(g) > 1 else None,
                        "type": [round(float(np.mean([r["type_you"] for r in rs])), 2), round(float(np.mean([r["type_net"] for r in rs])), 2)],
                        "engine": [round(float(np.mean([r["engine_you"] for r in rs])), 2), round(float(np.mean([r["engine_net"] for r in rs])), 2)],
                        "tier": [round(float(np.mean([r["tier_you"] or 0 for r in rs])), 2), round(float(np.mean([r["tier_net"] or 0 for r in rs])), 2)]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("--against")
    ap.add_argument("--decisions", default=str(ROOT / "data" / "replay" / "decisions.jsonl"))
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--rounds", type=int, nargs="+", default=[6, 7, 8, 9])
    ap.add_argument("--ahead", type=int, default=3)
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--out")
    ap.add_argument("--follow-tier", action="store_true", help="a probe: the candidate Upgrades to your Tier of each round")
    ap.add_argument("--type-lock", action="store_true",
                    help="a probe: the candidate keeps your main type (no selling it, no buying other types)")
    a = ap.parse_args()
    torch.set_num_threads(4)
    decisions = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    pos = positions(decisions, combats, set(a.rounds))
    seeds = [11 + k for k in range(a.seeds)]
    res = {}
    for name, path in [("cand", a.checkpoint)] + ([("champ", a.against)] if a.against else []):
        net, _ = load(path, "cpu")
        cand = name == "cand"
        rows = exam(net.eval(), pos, combats, seeds, a.ahead, a.follow_tier and cand, a.type_lock and cand)
        res[name] = rows
        print(json.dumps({"net": path, "positions": len(pos), **summary(rows)}), flush=True)
    if a.against:
        pair = {(r["log"], r["start"], r["ahead"], r["seed"]): r["growth"] for r in res["champ"]}
        for k in range(a.ahead + 1):
            diffs = [r["growth"] - pair[key] for r in res["cand"] if r["ahead"] == k
                     and (key := (r["log"], r["start"], r["ahead"], r["seed"])) in pair]
            if len(diffs) > 1:
                print(json.dumps({"ahead": k, "paired_growth_diff": round(float(np.mean(diffs)), 3),
                                  "se": round(float(np.std(diffs, ddof=1) / math.sqrt(len(diffs))), 3), "n": len(diffs)}))
    if a.out:
        Path(a.out).write_text(json.dumps(res), encoding="utf-8")


if __name__ == "__main__":
    main()
