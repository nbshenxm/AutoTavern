"""Would levelling on a normal curve have helped? In the top-1% library lobby the network reaches
round 10 at tier 2.8 (your lobbies: 5.3) and falls from more stats than the lobby at round 8 to a
third of them at round 10 (study --lobby library). From every logged round start (as
advisor.spend_test: the network in the player's seat and the others, paired seeds), the same
games are played as the network plays them, and with seat 0 made to Upgrade whenever it can
while below a curve: "curve" (tier 2 in round 2, 3 in 4, 4 in 6, 5 in 8, 6 in 10: about your
lobbies' median) and "late" (one round later). Better placements with the curve say the
network under-levels (a training problem: it doesn't see what levelling pays); none says the
simulator doesn't pay for it (a realism problem). Results are appended to `--out` as they come.

    python -X utf8 -m advisor.level_test data/models/best.pt --reps 2 --from-round 4 --library 5 6 7
"""

import argparse
import json
from pathlib import Path

import numpy as np
import taverngym
import torch

from advisor.policy import load
from advisor.spend_test import paired, places
from advisor.train import CONFIG, RealStarts

L = dict(taverngym.layout())
CURVES = {"curve": {2: 2, 4: 3, 6: 4, 8: 5, 10: 6}, "late": {3: 2, 5: 3, 7: 4, 9: 5, 11: 6}}


def target(curve, turn):
    return max([t for r, t in CURVES[curve].items() if turn >= r], default=1)


def level_mask(env, obs, ready, mode, start_turn):
    """Seat 0 of the ready games may only Upgrade while it can and its tier is below the curve."""
    m = obs["action_mask"]
    for i in ready:
        if i % 8 or not m[i, L["A_UPGRADE"]]:
            continue
        v = json.loads(env.game(i // 8).view(0))
        if v["me"]["tier"] < target(mode, v["turn"]):
            m[i] = False
            m[i, L["A_UPGRADE"]] = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("net")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--from-round", type=int, default=4)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--seed", type=int, default=49_000_000)
    ap.add_argument("--library", type=int, nargs="*", default=[])
    ap.add_argument("--out", default="data/progress/level_test.jsonl")
    a = ap.parse_args()
    config = CONFIG
    if a.library:
        from advisor import library
        config = {**CONFIG, "library": library.library(a.library, comps=True)}
    torch.set_num_threads(a.threads)
    net, _ = load(a.net, "cpu")
    states = [st for st in RealStarts(1.0, 0, log=lambda r: None).real
              if st["turn"] >= a.from_round]
    out = Path(a.out)
    done = {}
    if out.exists():  # resume: the (mode, rep) rows already played
        for line in out.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("net") == a.net and r.get("starts") == len(states):
                done[(r["mode"], r["rep"])] = r["places"]
    res = {m: [] for m in ("none", *CURVES)}
    for r in range(a.reps):
        for m in res:
            if (m, r) not in done:
                got = places(net, states, m, a.seed + r * 1000, a.threads, config=config,
                             masker=level_mask)
                done[(m, r)] = got
                with out.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"net": a.net, "starts": len(states), "mode": m, "rep": r,
                                        "places": got}) + "\n")
            res[m] += done[(m, r)]
            print(m, r, round(float(np.mean(res[m])), 3), flush=True)
    print(json.dumps({"starts": len(states), "reps": a.reps, "library": a.library,
                      "none": round(float(np.mean(res["none"])), 3),
                      **{m: paired(res[m], res["none"]) for m in CURVES}}))


if __name__ == "__main__":
    main()
