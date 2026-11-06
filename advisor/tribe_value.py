"""Does keeping the tribe pay, for this network? The buy audit (Nov 5): offered an affordable minion
of your warband's tribe in rounds 7-9, main1 takes it 35% of the time (you 72%) and sells on-tribe
minions more; it doesn't value the synergy. Before teaching it, measure whether the synergy pays
for it at all: from your round 5-9 starts, the network plays on as it would, and in the paired arm
it keeps the tribe for three rounds (a buy of an off-tribe minion while an affordable on-tribe one
is offered buys the on-tribe one, highest Tier first; a sell of an on-tribe minion while an
off-tribe one is on the warband sells that one, the weakest), then plays on as it would. Same
seeds, `--reps` of each; place, first places, the warband three rounds on.

- it pays: the policy is stuck (it never keeps a tribe long enough to see it pay): exploration
  toward on-tribe buys, learned where it paid (collect's forced steps + self-imitation).
- it doesn't: what makes a tribe scale is missing in its play (the payoff cards) or the simulator
  pays tribes less than the game (a fidelity question).

    python -X utf8 -m advisor.tribe_value data/models/archive/main1_it1400.pt --name main1_it1400 --workers 60
    python -X utf8 -m advisor.tribe_value --report data/audit/tribe_main1_it1400
"""

import argparse
import json
from pathlib import Path

import numpy as np
import taverngym
import torch

from advisor.buy_audit import on, top_tribe
from advisor.policy import load
from advisor.train import BatchEnv, RealStarts, load_start, play_frozen
from advisor.upgrade_value import lobby_config

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "audit"
SEED = 71_000_000
L = dict(taverngym.layout())
A_BUY, A_SELL, N_SHOP, N_BOARD = L["A_BUY"], L["A_SELL"], L["N_SHOP"], L["N_BOARD"]
WINDOW = 3  # rounds the rule holds, from the start's round


def eligible(states):
    return [i for i, st in enumerate(states) if 5 <= st["turn"] <= 9]  # rounds 5-9


def keep_tribe(v, mask, a, tribe):
    """The rule's action instead of `a`, or None to leave it."""
    me = v["me"]
    if A_BUY <= a < A_BUY + N_SHOP:
        slot = a - A_BUY
        if slot >= len(me["shop"]) or me["shop"][slot].get("type", "minion") != "minion" or on(me["shop"][slot], tribe):
            return None
        best = [(x.get("tier") or 0, x["atk"] + x["hp"], j) for j, x in enumerate(me["shop"][:N_SHOP])
                if x.get("type", "minion") == "minion" and on(x, tribe) and mask[A_BUY + j]]
        return A_BUY + max(best)[2] if best else None
    if A_SELL <= a < A_SELL + N_BOARD:
        slot = a - A_SELL
        if slot >= len(me["board"]) or not on(me["board"][slot], tribe):
            return None
        other = [(x["atk"] + x["hp"], j) for j, x in enumerate(me["board"][:N_BOARD])
                 if not on(x, tribe) and mask[A_SELL + j]]
        return A_SELL + min(other)[1] if other else None
    return None


@torch.no_grad()
def play(net, states, seed, rule):
    m = len(states)
    env = BatchEnv(m, seed=seed, controlled=list(range(8)), config=_W["lib"], threads=1)
    rows, tribes, r0 = [None] * m, [None] * m, [0] * m
    for i in range(m):
        load_start(env, i, states[i])
        v = json.loads(env.game(i).view(0))
        tribes[i] = top_tribe(v["me"]["board"])
        r0[i] = v["turn"]
        rows[i] = {"round": v["turn"], "tribe": tribes[i], "tier": v["me"]["tier"],
                   "hp": v["me"]["health"] + v["me"].get("armor", 0),
                   "on_tribe": sum(on(x, tribes[i]) for x in v["me"]["board"]),
                   "stats": sum(x["atk"] + x["hp"] for x in v["me"]["board"])}
    net_of = {i: net for i in range(env.n_slots)}
    obs = env.observe()
    place, changed, later = {}, [0] * m, [None] * m
    for step in range(200_000):
        if len(place) == m:
            break
        ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
        ready = np.array([i for i in ready if i // 8 not in place], dtype=np.int64)
        actions = np.zeros(env.n_slots, dtype=np.int64)
        play_frozen(obs, ready, net_of, actions, "cpu")
        for i in ready[ready % 8 == 0]:
            g = int(i // 8)
            t = env.game(g).turn
            if later[g] is None and t >= r0[g] + WINDOW:  # the warband three rounds on
                v = json.loads(env.game(g).view(0))
                later[g] = {"stats": sum(x["atk"] + x["hp"] for x in v["me"]["board"]),
                            "on_tribe": sum(on(x, tribes[g]) for x in v["me"]["board"]), "tier": v["me"]["tier"]}
            if not rule or not tribes[g] or t >= r0[g] + WINDOW:
                continue
            a = int(actions[i])
            if not (A_BUY <= a < A_BUY + N_SHOP or A_SELL <= a < A_SELL + N_BOARD):
                continue
            v = json.loads(env.game(g).view(0))
            if v["phase"].lower() != "recruit" or v["me"]["pending"]:
                continue
            b = keep_tribe(v, obs["action_mask"][i], a, tribes[g])
            if b is not None:
                actions[i] = b
                changed[g] += 1
        _, done, info = env.step(actions)
        for i in np.flatnonzero(done):
            if i % 8 == 0 and i // 8 not in place:
                place[int(i // 8)] = int(info["placement"][i]) or 4.5
        obs = env.observe()
    return [(place.get(g, 4.5), rows[g], changed[g], later[g]) for g in range(m)]


_W = {}


def _init(path, lobby="library"):
    torch.set_num_threads(1)
    _W["net"] = load(path, "cpu")[0].eval()
    _W["lib"] = lobby_config(lobby)
    _W["starts"] = RealStarts(1.0, 0, log=lambda r: None).real


def _work(job):
    idx, rep, seed = job
    states = [_W["starts"][i] for i in idx]
    base = play(_W["net"], states, seed, False)
    kept = play(_W["net"], states, seed, True)
    return {"rep": rep, "seed": seed, "games": [
        {"start": i, "row": b[1], "base": b[0], "kept": k[0], "changed": k[2], "later_base": b[3], "later_kept": k[3]}
        for i, b, k in zip(idx, base, kept)]}


def run(path, name, reps=8, seed=SEED, workers=60, chunk=8, limit=None, lobby="library"):
    d = OUT / f"tribe_{name}"
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


def _ms(x):
    x = np.asarray(x, float)
    return {"n": len(x), "mean": round(float(x.mean()), 3),
            "se": round(float(x.std(ddof=1) / np.sqrt(len(x))), 3) if len(x) > 1 else None}


def report(d):
    d = Path(d)
    gs = [g for r in map(json.loads, open(d / "games.jsonl", encoding="utf-8")) for g in r["games"] if g["changed"] > 0]
    res = {"pairs": len(gs), "starts": len({g["start"] for g in gs}),
           "changes_per_game": round(float(np.mean([g["changed"] for g in gs])), 2) if gs else None,
           "place": _ms([g["kept"] - g["base"] for g in gs]),
           "first": _ms([(g["kept"] == 1) - (g["base"] == 1) for g in gs]),
           "top4": _ms([(g["kept"] <= 4) - (g["base"] <= 4) for g in gs])}
    both = [g for g in gs if g["later_base"] and g["later_kept"]]
    if both:
        res["three_rounds_on"] = {
            "warband_log_ratio": _ms([np.log(max(1, g["later_kept"]["stats"]) / max(1, g["later_base"]["stats"])) for g in both]),
            "on_tribe_kept_minus_base": _ms([g["later_kept"]["on_tribe"] - g["later_base"]["on_tribe"] for g in both]),
            "tier_kept_minus_base": _ms([g["later_kept"]["tier"] - g["later_base"]["tier"] for g in both])}
    res["by_round"] = {}
    for lo, hi in ((5, 7), (7, 10)):
        x = [g["kept"] - g["base"] for g in gs if lo <= g["row"]["round"] < hi]
        if len(x) > 1:
            res["by_round"][f"{lo}-{hi - 1}"] = _ms(x)
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
    ap.add_argument("--lobby", choices=("library", "logged", "self"), default="library")
    ap.add_argument("--limit", type=int)
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
