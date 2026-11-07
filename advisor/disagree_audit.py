"""Where the network decides differently from you, who was right? (Nov 7: the mistake audit finds
little plain waste left; the network's errors are in its choices.) At each of your logged recruit
decisions (sampled) where the network's greedy action differs from yours, both are played out from
the same rebuilt position and seed: your action (its target too), or the network's, then the
network plays every seat to the game's end (greedy, as value_check). Paired over `--seeds`.

A decision where your action ends clearly better is a mistake the network makes even by its own
follow-through (its play-on favours its own style: advisor.value_check, Nov 5), so these are the
safe ones to fix. Grouped by what you did against what it did (buy / sell / play / refresh /
upgrade / end...) and by round.

    python -X utf8 -m advisor.disagree_audit data/models/best.pt --sample 800 --out data/audit/disagree/r6.json
"""

import argparse
import collections
import json
import math
import random
from pathlib import Path

import numpy as np
import taverngym
import torch

from advisor import bridge, recruit_diff, search
from advisor.compare_play import kind_of
from advisor.policy import load
from advisor.value_check import play_out

ROOT = Path(__file__).resolve().parents[1]
L = dict(taverngym.layout())


def your_actions(d):
    """([actions], target eid or None) for your choice at `d`, or None."""
    ch = d.get("chosen") or {}
    opt = next((o for o in d["options"] if isinstance(ch, dict) and o["id"] == ch.get("option")), None)
    if opt is None:
        return None
    if opt.get("type") == "END_TURN":
        return [L["A_END"]], None
    acts = recruit_diff.chosen_actions(d)
    if acts is not None:
        return acts[0], acts[1]
    card = ((opt.get("entity") or {}).get("card")) or ""
    for part, a in (("Reroll", "A_REFRESH"), ("LockAll", "A_FREEZE"), ("TechUp", "A_UPGRADE")):
        if part in card:
            return [L[a]], None
    if card == "BG36_Button_DarkGift":
        return [L["A_DARK_GIFT"]], None
    return None


def apply_yours(g, d, acts, target):
    """Your action on `g` (and its target); False when the simulator can't take it."""
    for a in acts:
        mask = json.loads(g.view(0))["mask"]
        if not mask[a]:
            return False
        g.step(0, a)
    if target is not None:
        v = json.loads(g.view(0))
        pending = v["me"].get("pending") or {}
        if pending.get("kind") == "target":
            ts = pending.get("targets") or []
            i = recruit_diff._target_choice(g, d, target)
            if i is None or i >= len(ts):
                return False
            g.step(0, L["A_CHOOSE"] + i)
    return True


_W = {}


def _init(path, items):
    torch.set_num_threads(1)
    _W["net"] = load(path, "cpu")[0].eval()
    _W["items"] = items


@torch.no_grad()
def _work(job):
    k, seed = job
    net = _W["net"]
    d, combats, acts, target, a_net = _W["items"][k]
    g, gaps = bridge.build(d, combats, seed=seed)
    if gaps:
        return {"k": k, "seed": seed, "failed": "gaps"}
    gy, gn = g.copy(), g.copy()
    if not apply_yours(gy, d, acts, target):
        return {"k": k, "seed": seed, "failed": "yours"}
    gn.step(0, a_net)
    return {"k": k, "seed": seed, "place_you": play_out(net, gy), "place_net": play_out(net, gn)}


def summary(items, rows):
    by_k = collections.defaultdict(list)
    for r in rows:
        by_k[r["k"]].append(r["place_you"] - r["place_net"])  # < 0: yours ends better
    groups = collections.defaultdict(list)
    cases = []
    for k, diffs in by_k.items():
        d, _, acts, _, a_net = items[k]
        rnd = (d["turn"] + 1) // 2
        key = f"you {kind_of(acts[0])} / net {kind_of(a_net)}"
        m = float(np.mean(diffs))
        se = float(np.std(diffs, ddof=1) / math.sqrt(len(diffs))) if len(diffs) > 1 else 0.0
        groups[key].append(m)
        groups["all"].append(m)
        band = "rounds 1-4" if rnd <= 4 else "rounds 5-8" if rnd <= 8 else "rounds 9+"
        groups[band].append(m)
        cases.append({"k": k, "log": d["log"], "turn": d["turn"], "round": rnd, "you": kind_of(acts[0]),
                      "net": kind_of(a_net), "a_you": acts[0], "a_net": a_net, "mean": round(m, 3), "se": round(se, 3), "n": len(diffs)})
    out = {}
    for key, ms in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        ms = np.array(ms)
        out[key] = {"decisions": len(ms), "you_minus_net": [round(float(ms.mean()), 3),
                                                            round(float(ms.std(ddof=1) / math.sqrt(len(ms))), 3) if len(ms) > 1 else None],
                    "yours_clearly_better": round(float((ms <= -0.5).mean()), 3),
                    "its_clearly_better": round(float((ms >= 0.5).mean()), 3)}
    cases.sort(key=lambda c: c["mean"])
    return out, cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("--decisions", default=str(ROOT / "data" / "replay" / "decisions.jsonl"))
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--sample", type=int, default=800, help="disagreements to play out")
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--workers", type=int, default=60)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    torch.set_num_threads(4)
    net = load(a.checkpoint, "cpu")[0].eval()
    dec = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    com = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    random.seed(11)
    pool = [d for d in dec if d["kind"] == "options" and d["turn"] % 2 == 1 and d["turn"] >= 3]
    random.shuffle(pool)
    items, seen = [], 0
    with torch.no_grad():
        for d in pool:
            if len(items) >= a.sample:
                break
            ya = your_actions(d)
            if ya is None:
                continue
            combats = bridge.game_combats(com, d)
            g, gaps = bridge.build(d, combats)
            if gaps:
                continue
            seen += 1
            probs, _ = search._policy(net, g, 0)
            a_net = int(probs.argmax())
            if a_net == ya[0][0]:
                continue
            items.append((d, combats, ya[0], ya[1], a_net))
    del dec, com
    print(f"{seen} decisions looked at, {len(items)} disagreements ({len(items) / max(seen, 1):.0%})", flush=True)
    part = Path(str(a.out) + ".rows.jsonl")
    part.parent.mkdir(parents=True, exist_ok=True)
    done = {(r["k"], r["seed"]) for r in map(json.loads, open(part, encoding="utf-8"))} if part.is_file() else set()
    jobs = [(k, 2000 + s) for k in range(len(items)) for s in range(a.seeds) if (k, 2000 + s) not in done]
    print(f"{len(items)} x {a.seeds} seeds: {len(done)} done, {len(jobs)} to play", flush=True)
    if jobs:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(min(a.workers, len(jobs)), _init, (a.checkpoint, items)) as p, \
                open(part, "a", encoding="utf-8") as f:
            for j, r in enumerate(p.imap_unordered(_work, jobs, chunksize=1)):
                f.write(json.dumps(r) + "\n")
                f.flush()
                if j % 200 == 0:
                    print(f"{j + 1}/{len(jobs)}", flush=True)
    rows = [r for r in map(json.loads, open(part, encoding="utf-8")) if "failed" not in r]
    groups, cases = summary(items, rows)
    Path(a.out).write_text(json.dumps({"checkpoint": a.checkpoint, "groups": groups, "cases": cases}), encoding="utf-8")
    print(json.dumps(groups, indent=1), flush=True)


if __name__ == "__main__":
    main()
