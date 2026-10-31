"""Does scoring the plan search's candidates by simulated combat buy better? From every logged
turn from round 10 on (its first decision rebuilt), the plan search plays the turn out (each
step the first of its best plan, as the advice does), scored by the network's value alone or by
value + W x (win - loss) of the warband against the next opponent's last seen warband
(search.best_plan odds=W). Per setting: the share of minion buys of the warband's main type
(you: 66%, the network 31%), Gold left at End, and the turn's last warband's odds.

    python -X utf8 -m advisor.odds_test data/models/best.pt --weights 0 0.5 --workers 8
"""

import argparse
import json
from multiprocessing import Pool

import numpy as np
import torch

from advisor import bridge, compare_play, search
from advisor.policy import load

L = compare_play.L
_NET = {}


def _init(path):
    torch.set_num_threads(1)
    _NET["net"], _ = load(path, "cpu")


def turn(job):
    """One turn played by the search from a logged position: (on-type flags of minion buys,
    Gold left at End or None, win - loss at the end or None)."""
    d, combats, w, k, seed = job
    from advisor.train import pause_if_playing
    g, gaps = bridge.build(d, combats)
    if gaps:
        return None
    net = _NET["net"]
    buys, gold = [], None
    for step in range(60):
        pause_if_playing()
        if not g.needs_action(0):
            break
        acts, _, _ = search.best_plan(g, net, 0, None, k, 1.0, seed=seed * 101 + step, odds=w)
        a = int(acts[0]) if acts else int(search._policy(net, g, 0)[0].argmax())
        v = json.loads(g.view(0))
        if L["A_BUY"] <= a < L["A_BUY"] + L["N_SHOP"]:
            q = compare_play._buy_quality(v, a - L["A_BUY"])
            if q:
                buys.append(q[1])
        if a == L["A_END"]:
            gold = v["me"]["gold"]
            break
        g.step(0, a)
    return buys, gold, search.plan_odds(g, 0, [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("net")
    ap.add_argument("--weights", type=float, nargs="+", default=[0.0, 0.5])
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--from-round", type=int, default=10)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open("data/replay/decisions.jsonl", encoding="utf-8")]
    combats = [json.loads(l) for l in open("data/replay/combats.jsonl", encoding="utf-8")]
    first = {}
    for d in rows:
        if d["kind"] == "options" and d["turn"] % 2 == 1 and (d["turn"] + 1) // 2 >= a.from_round:
            first.setdefault((d["log"], d["segment"], d["turn"]), d)
    starts = [(d, bridge.game_combats(combats, d)) for d in first.values()]
    with Pool(a.workers, initializer=_init, initargs=(a.net,)) as pool:
        for w in a.weights:
            res = [r for r in pool.map(turn, [(d, c, w, a.k, i) for i, (d, c) in enumerate(starts)]) if r]
            buys = [b for r in res for b in r[0]]
            gold = [r[1] for r in res if r[1] is not None]
            odds = [r[2] for r in res if r[2] is not None]
            print(json.dumps({"odds_weight": w, "turns": len(res), "minion_buys": len(buys),
                              "on_type": round(float(np.mean(buys)), 3) if buys else None,
                              "gold_left": round(float(np.mean(gold)), 2) if gold else None,
                              "win_minus_loss": round(float(np.mean(odds)), 3) if odds else None}), flush=True)


if __name__ == "__main__":
    main()
