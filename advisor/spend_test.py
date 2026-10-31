"""Would spending the Gold have helped? The advice and the network often end a mid or late turn
with 3+ Gold while a Refresh or a buy is legal (advisor.audit_play: end_with_gold; your own late
turns refresh about 4 times). From every logged round start (train.evaluate_real: the network in
the player's seat, the best in the others, paired seeds), the same games are played three ways:
as the network plays them; with End Turn masked in the player's seat while 3+ Gold and a spend
are left, on the start turn only ("first"); and on every turn ("all"). A better placement with
the mask says the simulator rewards spending and the network hasn't learned it (a training
problem); none says the simulator doesn't reward what real lobbies do (a realism problem).
`--library 5 6 7`: those seats fight with the top-1% library boards (as in training), a lobby
the player's real position doesn't simply outgrow.

    python -X utf8 -m advisor.spend_test data/models/best.pt --reps 2 --from-round 8 --library 5 6 7
"""

import argparse
import json
import math

import numpy as np
import taverngym
import torch

from advisor.policy import load
from advisor.train import CONFIG, BatchEnv, RealStarts, load_start, play_frozen, wait_while_playing

L = dict(taverngym.layout())
SPEND = 3  # the review's threshold


def spend_mask(env, obs, ready, mode, start_turn):
    """End Turn masked in seat 0 of the ready games while SPEND+ Gold and a Refresh or a buy are
    legal (on the start turn only, or every turn)."""
    m = obs["action_mask"]
    for i in ready:
        if i % 8 or not m[i, L["A_END"]]:
            continue
        if not (m[i, L["A_REFRESH"]] or m[i, L["A_BUY"]:L["A_BUY"] + L["N_SHOP"]].any()):
            continue
        v = json.loads(env.game(i // 8).view(0))
        if v["me"]["gold"] < SPEND or (mode == "first" and v["turn"] != start_turn[i // 8]):
            continue
        m[i, L["A_END"]] = False


def places(net, states, mode, seed, threads=8, games=64, config=CONFIG):
    out = []
    for k in range(0, len(states), games):
        wait_while_playing(print)  # home rule
        chunk = states[k:k + games]
        env = BatchEnv(len(chunk), seed=seed + k, controlled=list(range(8)), config=config,
                       threads=threads)
        for i, st in enumerate(chunk):
            load_start(env, i, st)
        start_turn = [st["turn"] for st in chunk]
        net_of = {i: net for i in range(env.n_slots)}
        obs = env.observe()
        got = {}
        for _ in range(100_000):
            if len(got) == len(chunk):
                break
            ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
            ready = np.array([i for i in ready if i // 8 not in got], dtype=np.int64)
            if mode != "none":
                spend_mask(env, obs, ready, mode, start_turn)
            actions = np.zeros(env.n_slots, dtype=np.int64)
            play_frozen(obs, ready, net_of, actions, "cpu")
            _, done, info = env.step(actions)
            for i in np.flatnonzero(done):
                if i % 8 == 0 and i // 8 not in got:
                    got[i // 8] = int(info["placement"][i]) or 4.5
            obs = env.observe()
        out += [got.get(i, 4.5) for i in range(len(chunk))]
    return out


def paired(a, b):
    d = [x - y for x, y in zip(a, b)]
    mean = sum(d) / len(d)
    sd = math.sqrt(sum((x - mean) ** 2 for x in d) / max(1, len(d) - 1))
    return {"mean": round(sum(a) / len(a), 3), "diff": round(mean, 3), "se": round(sd / math.sqrt(len(d)), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("net")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--from-round", type=int, default=8)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--seed", type=int, default=48_000_000)
    ap.add_argument("--library", type=int, nargs="*", default=[])
    a = ap.parse_args()
    config = CONFIG
    if a.library:
        from advisor import library
        config = {**CONFIG, "library": library.library(a.library, comps=True)}
    torch.set_num_threads(a.threads)
    net, _ = load(a.net, "cpu")
    states = [st for st in RealStarts(1.0, 0, log=lambda r: None).real
              if st["turn"] >= a.from_round]  # (a state's turn is the round)
    res = {m: [] for m in ("none", "first", "all")}
    for r in range(a.reps):
        for m in res:
            res[m] += places(net, states, m, a.seed + r * 1000, a.threads, config=config)
            print(m, r, round(float(np.mean(res[m])), 3), flush=True)
    print(json.dumps({"starts": len(states), "reps": a.reps, "library": a.library, "none": round(float(np.mean(res["none"])), 3),
                      "first": paired(res["first"], res["none"]), "all": paired(res["all"], res["none"])}))


if __name__ == "__main__":
    main()
