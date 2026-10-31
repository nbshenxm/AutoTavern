"""Which teacher is stronger than the network? Search data only helps training when the search
plays better than the network it searches with (expert iteration); the 18:21 best's search
data alone has held the runs at its level. From every logged round start from round 8 on (your
seat, the bridge's game) with top-1% library seats (5, 6, 7), whole games are played with your
seat taken by each teacher and the other seats by the network (greedy), on the same seeds:

- net: the network's most likely action;
- search: the plan search (search.best_plan, k plans), its first step at every decision;
- spend: the same search, its plans never ending a turn with 3+ Gold a buy or Refresh could use;
- odds: the same search, plans scored with the simulated combat against the next opponent.

Mean placement per teacher and the paired difference with `net`.

`--turn R` (the default, R = 16): what training takes from a teacher is its turn, and whole
games with a search at every decision cost ~650 s each and vary by +-2 places. So the teacher
plays the start's turn only, then the network plays every seat to the end, R times under
different random draws (the same R for every teacher): the mean over R is the turn's worth.

    python -X utf8 -m advisor.teacher_test data/models/best.pt --workers 12 --from-round 10
"""

import argparse
import json
import math
from multiprocessing import Pool

import numpy as np
import taverngym
import torch

from advisor import search
from advisor.policy import load
from advisor.state import GAME_CONFIG

TEACHERS = {"net": {}, "search": {"k": 8}, "spend": {"k": 8, "spend": 3}, "odds": {"k": 8, "odds": 0.5}}
_W = {}


def _init(path, lib):
    torch.set_num_threads(1)
    _W["net"], _ = load(path, "cpu")
    from advisor import library
    _W["config"] = {**GAME_CONFIG, "library": library.library(lib, comps=True)} if lib else GAME_CONFIG


def play(job):
    """Seat 0's placement in one game from a logged start, played by teacher `name`."""
    from advisor.train import pause_if_playing
    st, name, seed = job
    net, opts = _W["net"], TEACHERS[name]
    g = taverngym.Game(seed, json.dumps(_W["config"]))
    fresh = json.loads(g.state_json())
    st = json.loads(json.dumps(st))
    st["rng"] = fresh["rng"]
    st["cfg"] = {**fresh["cfg"], "lobby_types": st["cfg"].get("lobby_types")}
    g = taverngym.Game.from_json(json.dumps(st))
    n = 0
    for _ in range(200_000):
        if g.is_over() or not json.loads(g.view(0))["me"]["alive"]:
            break
        stepped = False
        for seat in range(g.num_players):
            if not g.needs_action(seat):
                continue
            if seat == 0 and opts:
                pause_if_playing()
                n += 1
                acts, _, _ = search.best_plan(g, net, 0, None, opts["k"], 1.0, seed=seed * 7919 + n,
                                              spend=opts.get("spend", 0), odds=opts.get("odds", 0.0))
                a = int(acts[0]) if acts else int(search._policy(net, g, 0)[0].argmax())
            else:
                a = int(search._policy(net, g, seat)[0].argmax())
            g.step(seat, a)
            stepped = True
        if not stepped:
            break
    return int(g.placements()[0]) or 4.5


def _start(st, seed):
    g = taverngym.Game(seed, json.dumps(_W["config"]))
    fresh = json.loads(g.state_json())
    st = json.loads(json.dumps(st))
    st["rng"] = fresh["rng"]
    st["cfg"] = {**fresh["cfg"], "lobby_types": st["cfg"].get("lobby_types")}
    return taverngym.Game.from_json(json.dumps(st))


def _act(g, seat, name, seed, n):
    opts = TEACHERS[name] if seat == 0 else {}
    if opts:
        acts, _, _ = search.best_plan(g, _W["net"], 0, None, opts["k"], 1.0, seed=seed * 7919 + n,
                                      spend=opts.get("spend", 0), odds=opts.get("odds", 0.0))
        if acts:
            return int(acts[0])
    return int(search._policy(_W["net"], g, seat)[0].argmax())


def turn_value(job):
    """Seat 0's mean placement over `rollouts` continuations after teacher `name` played the
    start's turn (the other seats the network's)."""
    from advisor.train import pause_if_playing
    st, name, seed, rollouts = job
    g = _start(st, seed)
    turn, n = json.loads(g.view(0))["turn"], 0
    for _ in range(5_000):  # the teacher's turn: until seat 0 has ended it
        v = json.loads(g.view(0))
        if g.is_over() or v["turn"] != turn or v["me"]["ended_turn"]:
            break
        stepped = False
        for seat in range(g.num_players):
            if g.needs_action(seat):
                pause_if_playing()
                n += seat == 0
                g.step(seat, _act(g, seat, name, seed, n))
                stepped = True
        if not stepped:
            break
    places = []
    for r in range(rollouts):
        c = search.fair_copy(g, 0, seed=seed * 31 + r)  # the same draws for every teacher
        for _ in range(200_000):
            if c.is_over() or not json.loads(c.view(0))["me"]["alive"]:
                break
            stepped = False
            for seat in range(c.num_players):
                if c.needs_action(seat):
                    c.step(seat, int(search._policy(_W["net"], c, seat)[0].argmax()))
                    stepped = True
            if not stepped:
                break
        places.append(int(c.placements()[0]) or 4.5)
    return float(np.mean(places))


def paired(a, b):
    d = [x - y for x, y in zip(a, b)]
    m = sum(d) / len(d)
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / max(1, len(d) - 1))
    return {"mean": round(sum(a) / len(a), 3), "vs_net": round(m, 3), "se": round(sd / math.sqrt(len(d)), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("net")
    ap.add_argument("--teachers", nargs="+", default=list(TEACHERS))
    ap.add_argument("--from-round", type=int, default=8)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--library", type=int, nargs="*", default=[5, 6, 7])
    ap.add_argument("--seed", type=int, default=49_000_000)
    ap.add_argument("--turn", type=int, default=16, metavar="R",
                    help="the teacher plays one turn, then R continuations (0: whole games)")
    a = ap.parse_args()
    from advisor.train import RealStarts
    states = [st for st in RealStarts(1.0, 0, log=lambda r: None).real if st["turn"] >= a.from_round]
    jobs = [(st, t, a.seed + r * 1000 + i) for r in range(a.reps) for i, st in enumerate(states) for t in a.teachers]
    with Pool(a.workers, initializer=_init, initargs=(a.net, a.library)) as pool:
        if a.turn:
            places = pool.map(turn_value, [j + (a.turn,) for j in jobs], chunksize=1)
        else:
            places = pool.map(play, jobs, chunksize=1)
    res = {t: [p for (_, tt, _), p in zip(jobs, places) if tt == t] for t in a.teachers}
    out = {"starts": len(states), "reps": a.reps, "library": a.library,
           **{t: paired(res[t], res["net"]) if "net" in res else {"mean": round(float(np.mean(res[t])), 3)}
              for t in a.teachers}}
    print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
