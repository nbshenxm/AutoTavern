"""Does a network level? From your logged round starts (data/library/starts.jsonl, rounds 4-11)
where it can afford an Upgrade: its probability of Upgrade first, and how often its greedy turn
includes one, by pair of rounds (every network gave ~0% in rounds 4-9 on Nov 1; you level 0.3
times a turn in rounds 7-9). `--curve`: also its strength curve in the top-1% library lobby
(advisor.study.curve, lobby "library": tier and warband by round). One process per job; each
result is written to `--out` as it comes.

    python -X utf8 -m advisor.upgrade_probe data/train/big3ad/best.pt data/models/best.pt --curve
"""

import argparse
import collections
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np


def probe(path):
    import taverngym
    import torch
    from advisor.policy import load
    from advisor.search import _policy, rollout
    from advisor.train import CONFIG, BatchEnv, RealStarts, load_start
    torch.set_num_threads(4)
    L = dict(taverngym.layout())
    net, ck = load(path, "cpu")
    env = BatchEnv(1, seed=1, controlled=list(range(8)), config=CONFIG, threads=1)
    rows = collections.defaultdict(list)
    for st in RealStarts(1.0, 0, log=lambda r: None).real:
        if not 4 <= st["turn"] <= 11:
            continue
        load_start(env, 0, st)
        g = env.game(0)
        me = json.loads(g.view(0))["me"]
        if not g.needs_action(0) or me["tier"] >= 6 or me["gold"] < me["upgrade_price"]:
            continue
        p, _ = _policy(net, g, 0)
        acts, _ = rollout(g, net, 0)
        rows[st["turn"] // 2 * 2].append((float(p[L["A_UPGRADE"]]), L["A_UPGRADE"] in acts))
    return {"net": path, "source": ck.get("source"), "kind": "upgrade",
            "rounds": {f"{k}-{k + 1}": {"n": len(v), "p_first": round(float(np.mean([x[0] for x in v])), 3),
                                        "in_turn": round(float(np.mean([x[1] for x in v])), 3)}
                       for k, v in sorted(rows.items())}}


def lib_curve(path, games):
    import torch
    from advisor.policy import load
    from advisor.study import curve
    torch.set_num_threads(4)
    net, ck = load(path, "cpu")
    return {"net": path, "source": ck.get("source"), "kind": "curve", "lobby": "library",
            "rounds": curve(net, games, lobby="library")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("nets", nargs="+")
    ap.add_argument("--curve", action="store_true")
    ap.add_argument("--games", type=int, default=16)
    ap.add_argument("--out", default="data/progress/upgrade_probe.jsonl")
    a = ap.parse_args()
    nets = [n for n in a.nets if Path(n).exists()]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=2 * len(nets)) as ex:
        jobs = [ex.submit(probe, n) for n in nets]
        if a.curve:
            jobs += [ex.submit(lib_curve, n, a.games) for n in nets]
        for f in as_completed(jobs):
            r = f.result()
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(r) + "\n")
            print(r["kind"], r["net"], json.dumps(r["rounds"])[:300], flush=True)


if __name__ == "__main__":
    main()
