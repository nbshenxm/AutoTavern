"""Does the simulator pay for levelling? No network: seat 0 plays the teacher bot (advisor.teacher)
with different levelling curves, the others the plain bot, library seats as `--library` says;
the same seeds for every curve (paired). advisor.level_test made the network level on a curve
and it placed worse (0.14 +- 0.07): either the network can't use a higher Tavern, or the
simulator doesn't reward it. A teacher that places better on the faster curves says the first.

    python -X utf8 -m advisor.level_bots --games 400 --library 5 6 7
"""

import argparse
import json

import numpy as np

from advisor import teacher
from advisor.spend_test import paired
from advisor.train import CONFIG, BatchEnv

CURVES = {  # the turn by which to reach Tavern Tier 2, 3, 4, 5, 6
    "fast": [2, 4, 6, 8, 10],
    "standard": teacher.LEVEL_TURNS,
    "slow": [3, 6, 8, 10, 12],
    "slower": [3, 7, 10, 13, 16],
    "tier3": [2, 5, 99, 99, 99],
}


def places(config, games, seed, threads):
    env = BatchEnv(games, seed=seed, controlled=[0], config=config, threads=threads)
    obs = env.observe()
    got = {}
    while len(got) < games:
        _, done, info = env.step(env.bot_actions())
        for i in np.flatnonzero(done):
            if i not in got:
                got[i] = int(info["placement"][i]) or 4.5
    return [got[i] for i in range(games)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=400)
    ap.add_argument("--seed", type=int, default=51_000_000)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--library", type=int, nargs="*", default=[])
    ap.add_argument("--strength", type=float, default=1.0,
                    help="the library's strength (advisor.library: 1 = toward the top 1%%, 0 = your lobbies as logged)")
    a = ap.parse_args()
    base = dict(CONFIG)
    if a.library:
        from advisor import library
        base["library"] = library.library(a.library, strength=a.strength, comps=a.strength >= 1)
    t = teacher.config(seats=[0])
    res = {}
    for name, turns in CURVES.items():
        res[name] = places({**base, "teacher": {**t, "level_turns": turns}}, a.games, a.seed, a.threads)
        print(name, round(float(np.mean(res[name])), 3), flush=True)
    print(json.dumps({"games": a.games, "library": a.library,
                      **{k: paired(v, res["standard"]) for k, v in res.items()}}))


if __name__ == "__main__":
    main()
