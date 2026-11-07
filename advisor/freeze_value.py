"""Does the network's Freeze at End Turn pay? It ends 40% of turns frozen from your positions (R6;
you 12%), and you flagged a "Freeze, End turn" (Oct 31). From each of your logged turn starts, the
network's greedy turn up to its End Turn; where the Tavern is frozen then, both are played out
(paired seeds, the network on every seat, as value_check): End Turn frozen, or the Freeze undone
first. Split by round and by what the frozen Tavern held (a copy of a warband or hand minion: a
triple piece; a minion of the warband's main tribe; its best tier against the Tavern's).

    python -X utf8 -m advisor.freeze_value data/models/best.pt --out data/audit/freeze/r6.json
"""

import argparse
import collections
import json
import math
from pathlib import Path

import numpy as np
import taverngym
import torch

from advisor import bridge, search
from advisor.buy_audit import on, top_tribe
from advisor.mistake_audit import turns
from advisor.policy import act, load
from advisor.value_check import play_out

ROOT = Path(__file__).resolve().parents[1]
L = dict(taverngym.layout())


def to_end(g, net, max_steps=120):
    """The network's greedy turn on `g` up to (not through) its End Turn: True if it got there."""
    sold = {}
    for _ in range(max_steps):
        if not g.needs_action(0):
            return False
        v = json.loads(g.view(0))
        a, _, _ = act(net, g, 0, search.detour_mask(v, sold))
        a = int(a)
        if a == L["A_END"] and not v["me"].get("pending"):
            return True
        search.note_sold(v, a, sold)
        g.step(0, a)
    return False


def frozen(me):
    return bool(me.get("frozen") or any(m.get("frozen") for m in me["shop"]))


def what(me):
    """What the frozen Tavern holds."""
    mine = {(m.get("id") or "").replace("_G", "") for m in me["board"] + me["hand"]}
    tribe = top_tribe(me["board"])
    minions = [m for m in me["shop"] if m.get("type", "minion") == "minion"]
    return {"triple_piece": any((m.get("id") or "").replace("_G", "") in mine for m in minions),
            "on_tribe": any(on(m, tribe) for m in minions),
            "top_tier": max([m.get("tier") or 0 for m in minions] or [0]) >= me["tier"],
            "spells": sum(m.get("type") == "spell" for m in me["shop"])}


_W = {}


def _init(path, items):
    torch.set_num_threads(1)
    _W["net"] = load(path, "cpu")[0].eval()
    _W["items"] = items


@torch.no_grad()
def _work(job):
    k, seed = job
    net = _W["net"]
    d, combats = _W["items"][k]
    g, gaps = bridge.build(d, combats, seed=seed)
    if gaps or not to_end(g, net):
        return {"k": k, "seed": seed, "failed": True}
    me = json.loads(g.view(0))["me"]
    if not frozen(me):
        return {"k": k, "seed": seed, "frozen": False}
    keep, undo = g.copy(), g.copy()
    undo.step(0, L["A_FREEZE"])
    if frozen(json.loads(undo.view(0))["me"]):
        return {"k": k, "seed": seed, "failed": True}
    keep.step(0, L["A_END"])
    undo.step(0, L["A_END"])
    return {"k": k, "seed": seed, "frozen": True, "round": (d["turn"] + 1) // 2, **what(me),
            "place_frozen": play_out(net, keep), "place_unfrozen": play_out(net, undo)}


def stat(xs):
    xs = np.array(xs, float)
    return [round(float(xs.mean()), 3), round(float(xs.std(ddof=1) / math.sqrt(len(xs))), 3) if len(xs) > 1 else None, len(xs)]


def summary(rows):
    fr = [r for r in rows if r.get("frozen")]
    out = {"turns_played": len(rows), "ended_frozen": round(len(fr) / max(len(rows), 1), 3)}
    diff = lambda rs: [r["place_frozen"] - r["place_unfrozen"] for r in rs]  # < 0: the Freeze paid
    out["frozen_minus_unfrozen"] = stat(diff(fr)) if len(fr) > 1 else None
    for band, lo, hi in (("rounds 1-4", 1, 4), ("rounds 5-8", 5, 8), ("rounds 9+", 9, 99)):
        rs = [r for r in fr if lo <= r["round"] <= hi]
        if len(rs) > 1:
            out[band] = stat(diff(rs))
    for key in ("triple_piece", "on_tribe", "top_tier"):
        for val in (True, False):
            rs = [r for r in fr if r[key] == val]
            if len(rs) > 1:
                out[f"{key}={val}"] = stat(diff(rs))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("--decisions", default=str(ROOT / "data" / "replay" / "decisions.jsonl"))
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--workers", type=int, default=60)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    dec = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    com = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    items = []
    for (log, t), ds in sorted(turns(dec).items()):
        d0 = next((d for d in ds if d["kind"] == "options"), None)
        if d0 is not None and t >= 3:
            items.append((d0, bridge.game_combats(com, d0)))
    del dec, com
    items = items[:a.limit] if a.limit else items
    part = Path(str(a.out) + ".rows.jsonl")
    part.parent.mkdir(parents=True, exist_ok=True)
    done = {(r["k"], r["seed"]) for r in map(json.loads, open(part, encoding="utf-8"))} if part.is_file() else set()
    jobs = [(k, 3000 + s) for k in range(len(items)) for s in range(a.seeds) if (k, 3000 + s) not in done]
    print(f"{len(items)} turn starts x {a.seeds} seeds: {len(done)} done, {len(jobs)} to play", flush=True)
    if jobs:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(min(a.workers, len(jobs)), _init, (a.checkpoint, items)) as p, \
                open(part, "a", encoding="utf-8") as f:
            for j, r in enumerate(p.imap_unordered(_work, jobs, chunksize=1)):
                f.write(json.dumps(r) + "\n")
                f.flush()
                if j % 200 == 0:
                    print(f"{j + 1}/{len(jobs)}", flush=True)
    rows = [r for r in map(json.loads, open(part, encoding="utf-8")) if not r.get("failed")]
    res = {"checkpoint": a.checkpoint, "summary": summary(rows), "rows": rows}
    Path(a.out).write_text(json.dumps(res), encoding="utf-8")
    print(json.dumps(res["summary"], indent=1), flush=True)


if __name__ == "__main__":
    main()
