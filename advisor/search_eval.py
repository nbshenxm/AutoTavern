"""Does plan search make the network play better? Complete games where seat 0 follows either the
network's own choice or the plan search (advisor.search), against seven scripted bots, on the
same seeds; mean placement of each.

The search only sees what seat 0 knows (advisor.search.fair_copy), as the live advice does.

    python -X utf8 -m advisor.search_eval data/models/best.pt --games 200 --workers 8 --k 8
"""

import argparse
import json
import time
from multiprocessing import Pool

import numpy as np
import torch

import taverngym
from advisor import search
from advisor.policy import load
from advisor.state import GAME_CONFIG

_NET = None


def _init(path):
    global _NET
    torch.set_num_threads(1)
    _NET, _ = load(path, "cpu")


def play(args):
    """One game: seat 0 by `mode` ("policy" or "search"), the rest scripted bots."""
    seed, mode, k, temperature = args
    g = taverngym.Game(seed, json.dumps(GAME_CONFIG))
    t0, decisions = time.time(), 0
    for _ in range(100_000):
        if g.is_over():
            break
        for seat in range(g.num_players):
            if not g.needs_action(seat):
                continue
            if seat:
                g.step(seat, g.bot_action(seat))
                continue
            decisions += 1
            if mode == "policy":
                probs, _ = search._policy(_NET, g, 0)
                a = int(probs.argmax())
            else:
                actions, _, _ = search.best_plan(g, _NET, 0, None, k, temperature,
                                                 seed=seed * 100_003 + decisions)
                a = actions[0]
            g.step(0, a)
    return {"seed": seed, "mode": mode, "place": int(g.placements()[0]),
            "decisions": decisions, "seconds": round(time.time() - t0, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--k", type=int, default=8, help="sampled plans besides the greedy one")
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=50_000_000)
    ap.add_argument("--out")
    a = ap.parse_args()
    jobs = [(a.seed + i, mode, a.k, a.temperature) for i in range(a.games)
            for mode in ("policy", "search")]
    rows = []
    with Pool(a.workers, initializer=_init, initargs=(a.checkpoint,)) as pool:
        for r in pool.imap_unordered(play, jobs):
            rows.append(r)
            if a.out:
                with open(a.out, "a", encoding="utf-8") as f:
                    f.write(json.dumps(r) + "\n")
    for mode in ("policy", "search"):
        p = np.array([r["place"] for r in rows if r["mode"] == mode])
        s = [r["seconds"] / max(1, r["decisions"]) for r in rows if r["mode"] == mode]
        print(f"{mode:7s}: mean place {p.mean():.3f} ± {p.std() / np.sqrt(len(p)):.3f}, "
              f"top 4 {np.mean(p <= 4):.1%}, n {len(p)}, {np.mean(s) * 1000:.0f} ms per decision")
    paired = [(r["place"], q["place"]) for r in rows if r["mode"] == "policy"
              for q in rows if q["mode"] == "search" and q["seed"] == r["seed"]]
    d = np.array([s - p for p, s in paired])
    print(f"search - policy, same seeds: {d.mean():+.3f} ± {d.std() / np.sqrt(len(d)):.3f} places")


if __name__ == "__main__":
    main()
