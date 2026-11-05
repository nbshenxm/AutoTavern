"""Does one Upgrade pay, for this network, where you could afford one? The networks give Upgrade a
probability of 1e-6 to 1e-13 at your round 4-11 starts (Nov 5: R3 and main1), so training never
samples one and can't learn what it is worth. From each such start (`--lobby`: the gate's library lobby,
seats 5-7 library and the others the network; or those seats at your lobbies' logged strength; or
the network alone) the network plays on as it would, and in the paired
arm Upgrades once at the start of that turn and then plays on; same seeds, `--reps` of each.
Split by round, Tier, Gold to spare and health: if it pays somewhere, the policy is stuck
(exploration; the fix learns from forced Upgrades where they paid); if it pays nowhere, the
network can't use the Tier (the value head, the follow-through).

    python -X utf8 -m advisor.upgrade_value data/models/archive/main1_it949.pt --name main1_it949 --workers 60
    python -X utf8 -m advisor.upgrade_value --report data/audit/upgrade_main1_it949
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from advisor.gate import CONFIG, library_config
from advisor.policy import load
from advisor.train import BatchEnv, RealStarts, load_start, play_frozen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "audit"
SEED = 67_000_000
A_UPGRADE = 3


def eligible(states):
    """Indices of the starts in rounds 4-11 (the probe's)."""
    return [i for i, st in enumerate(states) if 4 <= st["turn"] <= 11]


@torch.no_grad()
def play(net, states, seed, force):
    """Seat 0's place in games from `states` (all seats `net`, library seats 5-7), seat 0 made to
    Upgrade at its first decision when `force` and legal. Returns [(place, start row)]."""
    m = len(states)
    env = BatchEnv(m, seed=seed, controlled=list(range(8)), config=_W["lib"], threads=1)
    rows = [None] * m
    for i in range(m):
        load_start(env, i, states[i])
        v = json.loads(env.game(i).view(0))
        me = v["me"]
        rows[i] = {"round": v["turn"], "tier": me["tier"], "gold": me["gold"], "price": me["upgrade_price"],
                   "hp": me["health"] + me.get("armor", 0), "minions": len(me["board"]),
                   "stats": sum(x["atk"] + x["hp"] for x in me["board"])}
    first = set(range(m))  # games whose seat 0 hasn't decided yet
    forced = [False] * m
    net_of = {i: net for i in range(env.n_slots)}
    obs = env.observe()
    place = {}
    for step in range(200_000):
        if len(place) == m:
            break
        ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
        ready = np.array([i for i in ready if i // 8 not in place], dtype=np.int64)
        actions = np.zeros(env.n_slots, dtype=np.int64)
        play_frozen(obs, ready, net_of, actions, "cpu")
        for i in ready[ready % 8 == 0]:
            g = int(i // 8)
            if g in first:
                first.discard(g)
                if force and obs["action_mask"][i][A_UPGRADE]:
                    actions[i], forced[g] = A_UPGRADE, True
        _, done, info = env.step(actions)
        for i in np.flatnonzero(done):
            if i % 8 == 0 and i // 8 not in place:
                place[int(i // 8)] = int(info["placement"][i]) or 4.5
        obs = env.observe()
    return [(place.get(g, 4.5), rows[g], forced[g]) for g in range(m)]


_W = {}


def lobby_config(lobby):
    """library: the gate's (seats 5-7 your lobbies' boards scaled to the top 1%, comps too); logged:
    the same seats at your lobbies' logged strength; self: no library, all seats the network."""
    if lobby == "self":
        return CONFIG
    if lobby == "logged":
        from advisor import library
        return {**CONFIG, "library": library.library([5, 6, 7], strength=0.0, comps=False)}
    return library_config()


def _init(path, lobby="library"):
    torch.set_num_threads(1)
    _W["net"] = load(path, "cpu")[0].eval()
    _W["lib"] = lobby_config(lobby)
    _W["starts"] = RealStarts(1.0, 0, log=lambda r: None).real


def _work(job):
    idx, rep, seed = job
    states = [_W["starts"][i] for i in idx]
    base = play(_W["net"], states, seed, False)
    up = play(_W["net"], states, seed, True)
    return {"rep": rep, "seed": seed, "games": [
        {"start": i, "row": b[1], "base": b[0], "up": u[0], "forced": u[2]} for i, b, u in zip(idx, base, up)]}


def run(path, name, reps=8, seed=SEED, workers=60, chunk=8, limit=None, lobby="library"):
    d = OUT / f"upgrade_{name}"
    d.mkdir(parents=True, exist_ok=True)
    out = d / "games.jsonl"
    done = {(r["rep"], r["seed"]) for r in map(json.loads, open(out, encoding="utf-8"))} if out.is_file() else set()
    idx = eligible(RealStarts(1.0, 0, log=lambda r: None).real)[:limit]
    jobs = [(idx[lo:lo + chunk], rep, seed + rep * 100_003 + lo) for rep in range(reps) for lo in range(0, len(idx), chunk)]
    todo = [j for j in jobs if (j[1], j[2]) not in done]
    print(f"{len(idx)} starts x {reps} reps: {len(done)} chunks done, {len(todo)} to play", flush=True)
    import multiprocessing as mp
    with mp.get_context("spawn").Pool(workers, _init, (path, lobby)) as pool, open(out, "a", encoding="utf-8") as f:
        for k, r in enumerate(pool.imap_unordered(_work, todo, chunksize=1)):
            f.write(json.dumps(r) + "\n")
            f.flush()
            if k % 20 == 0:
                print(f"{k + 1}/{len(todo)}", flush=True)
    return report(d)


def _split(gs, key, edges):
    out = {}
    for lo, hi in zip(edges, edges[1:]):
        x = [g["up"] - g["base"] for g in gs if lo <= key(g) < hi]
        if len(x) > 1:
            out[f"{lo}-{hi - 1}"] = {"n": len(x), "mean": round(float(np.mean(x)), 3),
                                     "se": round(float(np.std(x, ddof=1) / np.sqrt(len(x))), 3)}
    return out


def report(d):
    d = Path(d)
    gs = [g for r in map(json.loads, open(d / "games.jsonl", encoding="utf-8")) for g in r["games"] if g["forced"]]
    x = np.array([g["up"] - g["base"] for g in gs], float)
    # The same start over reps: its mean, so a start that pays shows apart from noise
    per = {}
    for g in gs:
        per.setdefault(g["start"], []).append(g["up"] - g["base"])
    means = np.array([np.mean(v) for v in per.values()])
    res = {"pairs": len(gs), "starts": len(per),
           "all": {"mean": round(float(x.mean()), 3), "se": round(float(x.std(ddof=1) / np.sqrt(len(x))), 3)},
           "starts_better": round(float((means < -0.25).mean()), 3),
           "starts_worse": round(float((means > 0.25).mean()), 3),
           "by_round": _split(gs, lambda g: g["row"]["round"], [4, 6, 8, 10, 12]),
           "by_tier": _split(gs, lambda g: g["row"]["tier"], [1, 3, 4, 5, 6]),
           "by_spare_gold": _split(gs, lambda g: g["row"]["gold"] - g["row"]["price"], [0, 1, 3, 6, 99]),
           "by_health": _split(gs, lambda g: g["row"]["hp"], [-99, 15, 25, 35, 99])}
    (d / "report.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("net", nargs="?")
    ap.add_argument("--name")
    ap.add_argument("--reps", type=int, default=8)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--workers", type=int, default=60)
    ap.add_argument("--chunk", type=int, default=8)
    ap.add_argument("--lobby", choices=("library", "logged", "self"), default="library",
                    help="the other seats (lobby_config)")
    ap.add_argument("--limit", type=int, help="the first N starts only (a smoke test)")
    ap.add_argument("--report")
    a = ap.parse_args()
    if a.report:
        report(a.report)
        return
    if not (a.net and a.name):
        raise SystemExit("NET --name NAME (or --report DIR)")
    run(a.net, a.name, a.reps, a.seed, a.workers, a.chunk, a.limit, a.lobby)


if __name__ == "__main__":
    main()
