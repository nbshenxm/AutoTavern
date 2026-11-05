"""Is the value head blind, or right about its own network? value_probe found main1's value head
prefers your mid-game End Turn over its own only by chance (49%, your round 5-8 turns). But a value
is the outcome *under the network's own play*: if it can't use your build, your End Turn isn't
worth more to it, and the value is right. From each of value_probe's positions, both End Turns
(your turn rebuilt from its last decision; the network's own greedy turn, the same seed) are
played out to seat 0's end with every seat the network (greedy), `--seeds` times: the places that
actually follow, beside what the value head said.

- your End Turn really ends better, the value says not: the value head is blind (teach it).
- neither ends better: the value is right; the network can't follow your build through (the
  policy's follow-through is the gap, and a search over this value can't teach it).

    python -X utf8 -m advisor.value_check data/models/archive/main1_it949.pt --out data/audit/value/check_main1.json
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import torch

from advisor import bridge, engine_exam, search
from advisor.policy import load
from advisor.value_probe import at_end, net_turn

ROOT = Path(__file__).resolve().parents[1]


def positions(decisions, combats, rounds):
    turns, by_turn = {}, {}
    for d in decisions:
        if d["turn"] % 2 == 1:
            turns.setdefault((d["log"], d["segment"], d["turn"]), []).append(d)
    for (log, seg, t), ds in turns.items():
        ds = [x for x in ds if x["kind"] == "options" or x is not ds[0]]
        if len(ds) > len(by_turn.get((log, t), [])):
            by_turn[(log, t)] = ds
    out = []
    for d0, _ in engine_exam.positions(decisions, combats, rounds):
        turn = by_turn.get((d0["log"], d0["turn"]), [])
        while turn and turn[0]["kind"] != "options":
            turn = turn[1:]
        if len(turn) >= 2:
            out.append((turn[0], turn[-1]))
    return out


def play_out(net, g):
    """Seat 0's place, every seat the network (greedy), from game `g` (seat 0 at its End Turn)."""
    for _ in range(200_000):
        v0 = json.loads(g.view(0))["me"]
        if not v0["alive"] or g.is_over():
            return v0.get("placement") or 4.5
        stepped = False
        for seat in range(g.num_players):
            if g.needs_action(seat):
                probs, _ = search._policy(net, g, seat)
                g.step(seat, int(probs.argmax()))
                stepped = True
        if not stepped:
            break
    return json.loads(g.view(0))["me"].get("placement") or 4.5


_W = {}


def _init(path, items):
    torch.set_num_threads(1)
    _W["net"] = load(path, "cpu")[0].eval()
    _W["pos"] = items  # [(first decision, last decision, their games' combats)]


def _end(g):
    """Press End Turn (both turns are rebuilt or played up to it)."""
    v = json.loads(g.view(0))
    if v["phase"].lower() == "recruit" and g.needs_action(0) and not v["me"]["pending"]:
        g.step(0, v["actions"]["END"])


@torch.no_grad()
def _work(job):
    k, seed = job
    net = _W["net"]
    d, last, combats = _W["pos"][k]
    gy, gaps = bridge.build(last, combats, seed=seed)
    gn = net_turn(net, d, combats, seed=seed)
    if gaps or gn is None:
        return {"pos": k, "seed": seed, "failed": True}
    (vy, sy), (vn, sn) = at_end(net, gy), at_end(net, gn)
    _end(gy)
    _end(gn)
    return {"pos": k, "seed": seed, "round": (d["turn"] + 1) // 2, "value_you": float(vy), "value_net": float(vn),
            "stats_you": sy, "stats_net": sn, "place_you": play_out(net, gy), "place_net": play_out(net, gn)}


def summary(rows):
    out = {}
    for name, lo, hi in (("rounds 5-8", 5, 9), ("rounds 9-13", 9, 14)):
        rs = [r for r in rows if lo <= r["round"] < hi]
        if len(rs) < 2:
            continue
        dp = np.array([r["place_you"] - r["place_net"] for r in rs], float)  # < 0: yours ends better
        dv = np.array([r["value_you"] - r["value_net"] for r in rs], float)
        # The value as a predictor of the place that followed (1st = +1 ... 8th = -1)
        v = np.array([x for r in rs for x in (r["value_you"], r["value_net"])])
        p = np.array([x for r in rs for x in (r["place_you"], r["place_net"])])
        out[name] = {"pairs": len(rs), "positions": len({r["pos"] for r in rs}),
                     "place_you_minus_net": [round(float(dp.mean()), 3), round(float(dp.std(ddof=1) / math.sqrt(len(dp))), 3)],
                     "value_you_minus_net": [round(float(dv.mean()), 4), round(float(dv.std(ddof=1) / math.sqrt(len(dv))), 4)],
                     "value_vs_place_corr": round(float(np.corrcoef(v, -p)[0, 1]), 3),
                     "yours_ends_better_share": round(float((dp < 0).mean()), 3),
                     "value_prefers_yours_share": round(float((dv > 0).mean()), 3)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("--decisions", default=str(ROOT / "data" / "replay" / "decisions.jsonl"))
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--workers", type=int, default=60)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    dec = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    com = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    items = [(d, last, bridge.game_combats(com, last)) for d, last in positions(dec, com, range(5, 14))]
    del dec, com
    items = items[:a.limit] if a.limit else items
    n = len(items)
    # Each pair is kept as it ends (OUT.rows.jsonl), so a run resumes
    part = Path(str(a.out) + ".rows.jsonl")
    seen = {(r["pos"], r["seed"]) for r in map(json.loads, open(part, encoding="utf-8"))} if part.is_file() else set()
    jobs = [(k, 1000 + s) for k in range(n) for s in range(a.seeds) if (k, 1000 + s) not in seen]
    print(f"{n} positions x {a.seeds} seeds: {len(seen)} done, {len(jobs)} to play", flush=True)
    if jobs:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(min(a.workers, len(jobs)), _init, (a.checkpoint, items)) as pool, \
                open(part, "a", encoding="utf-8") as f:
            for j, r in enumerate(pool.imap_unordered(_work, jobs, chunksize=1)):
                f.write(json.dumps(r) + "\n")
                f.flush()
                if j % 50 == 0:
                    print(f"{j + 1}/{len(jobs)}", flush=True)
    rows = [r for r in map(json.loads, open(part, encoding="utf-8")) if not r.get("failed")]
    res = {"checkpoint": a.checkpoint, "summary": summary(rows), "rows": rows}
    Path(a.out).write_text(json.dumps(res), encoding="utf-8")
    print(json.dumps(res["summary"], indent=1), flush=True)


if __name__ == "__main__":
    main()
