"""Are plan1's plans real? (Nov 8.) Self-play lobbies of one network, played greedily (the advice's
way), every seat drawing a plan as training does: from a random round in 3..6, a tribe among those
on its warband and in its Tavern (train.plan_tribes). With a plan-conditioned network the even seats
play under their plan (the network's plan input) and the odd seats without one, keeping theirs as a
shadow (the same draw, not fed); with a network without plans (main1) every seat's plan is a shadow.
Per seat:

1. follow: at its buys from the plan's start on, where a minion of the plan's tribe was for sale,
   the share that bought one; the plan tribe's minions on the warband at rounds 8 and 12 (ALL counts).
2. scale: the warband's stats at rounds 8 and 12 (End Turn) and the log growth between them.
3. place: planned seats against unplanned ones in the same lobbies.
4. values (plan-conditioned networks): at End Turns in rounds 5-8, V(s, c) + Phi_c(s) over none and
   the tribes present (as PlanPicker compares them): the spread, best minus none, and how often a
   tribe beats none.

    python -m advisor.plan_check data/models/archive/plan1_it4600.pt --lobbies 64 --out data/audit/plan/p4600.json
    python -m advisor.plan_check data/models/archive/main1_it4600.pt --lobbies 64 --out data/audit/plan/m4600.json
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import torch

from advisor.policy import L, load
from advisor.train import CONFIG, BatchEnv, _tribe_tables, plan_potential, plan_tribes

N_BOARD = L["N_BOARD"]
N_SHOP = L["N_SHOP"]


def stats(board):
    return float(sum((m.get("atk") or 0) + (m.get("hp") or 0) for m in board))


def on_plan_slots(cards, plan):
    """(n, N_SHOP) bool: the Tavern's minions of each row's plan tribe (ALL counts)."""
    t = _tribe_tables()
    shop = cards[:, t["shop"]:t["shop"] + N_SHOP]
    r = t["races"][shop]  # (n, 8, R)
    j = np.clip(plan - 1, 0, r.shape[2] - 2)
    on = r[np.arange(len(cards))[:, None], np.arange(N_SHOP)[None, :], j[:, None]] | r[:, :, -1]
    return on & t["minion"][shop] & (plan > 0)[:, None]


@torch.no_grad()
def plan_values(net, f, c, m, beta):
    """Per row: (value of none, the best tribe's value, the spread), each value V + Phi."""
    t = _tribe_tables()
    cn = c.numpy()
    slots = np.concatenate([cn[:, t["board"]:t["board"] + N_BOARD], cn[:, t["shop"]:t["shop"] + N_SHOP]], 1)
    have = (t["races"][slots][:, :, :-1] & t["minion"][slots][:, :, None]).any(1)
    out = []
    for i in range(len(cn)):
        plans = np.array([0] + [j + 1 for j in np.flatnonzero(have[i])], np.int64)
        k = len(plans)
        _, v = net(f[i:i + 1].repeat(k, 1), c[i:i + 1].repeat(k, 1), m[i:i + 1].repeat(k, 1),
                   plan=torch.from_numpy(plans))
        raw = v.float().numpy()
        v = raw + plan_potential(np.repeat(cn[i:i + 1], k, 0), plans, beta)
        out.append((float(v[0]), float(v[1:].max()) if k > 1 else float(v[0]), float(v.max() - v.min()), k - 1,
                    float(raw[1:].max() - raw[0]) if k > 1 else 0.0, float(raw.max() - raw.min())))
    return out


@torch.no_grad()
def _work(job):
    path, m, seed, beta = job
    torch.set_num_threads(1)
    np.random.seed(seed)
    net = load(path, "cpu")[0].eval()
    has_plan = getattr(net, "plan_emb", None) is not None
    env = BatchEnv(m, seed=seed, controlled=list(range(8)), config=CONFIG, threads=1)
    n = env.n_slots
    fed = np.array([has_plan and i % 2 == 0 for i in range(n)])
    plan = np.zeros(n, np.int64)
    plan_round = np.random.randint(3, 7, n)
    drawn = np.zeros(n, bool)
    seat = [{"fed": bool(fed[i]), "buys_offered": 0, "buys_on": 0, "stats": {}, "on": {}} for i in range(n)]
    values = []
    obs = env.observe()
    place = {}
    for _ in range(400_000):
        if len(place) == n:
            break
        ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
        ready = np.array([i for i in ready if i not in place], dtype=np.int64)
        actions = np.zeros(n, dtype=np.int64)
        if len(ready):
            rnd = np.rint(obs["features"][ready, 0] * 20).astype(np.int64)
            new = ~drawn[ready] & (rnd >= plan_round[ready])
            if new.any():
                plan[ready[new]] = plan_tribes(obs["cards"][ready[new]])
                drawn[ready[new]] = True
            f = torch.from_numpy(obs["features"][ready])
            c = torch.from_numpy(obs["cards"][ready])
            mk = torch.from_numpy(obs["action_mask"][ready])
            if has_plan:
                logits, _ = net(f, c, mk, plan=torch.from_numpy(np.where(fed[ready], plan[ready], 0)))
            else:
                logits, _ = net(f, c, mk)
            a = logits.argmax(1).numpy()
            actions[ready] = a
            cn = obs["cards"][ready]
            onp = on_plan_slots(cn, plan[ready])
            legal = obs["action_mask"][ready][:, L["A_BUY"]:L["A_BUY"] + N_SHOP]
            buy = (a >= L["A_BUY"]) & (a < L["A_BUY"] + N_SHOP)
            for j in np.flatnonzero(buy & (onp & legal).any(1)):
                s = seat[int(ready[j])]
                s["buys_offered"] += 1
                s["buys_on"] += int(onp[j, a[j] - L["A_BUY"]])
            ends = np.flatnonzero(a == L["A_END"])
            vrows = []
            for j in ends:
                i = int(ready[j])
                g = env.game(i // 8)
                v = json.loads(g.view(i % 8))
                me = v["me"]
                if v["phase"].lower() != "recruit" or me.get("pending"):
                    continue
                r = int(me.get("turn") or g.turn)
                if r in (8, 12):
                    seat[i]["stats"][r] = stats(me["board"])
                    seat[i]["on"][r] = round(float(plan_potential(cn[j:j + 1], plan[i:i + 1], 1.0)[0] * N_BOARD), 2)
                if has_plan and 5 <= r <= 8:
                    vrows.append(j)
            if vrows:
                vr = np.array(vrows)
                for (none, best, spread, k, raw_best, raw_spread), j in zip(
                        plan_values(net, f[vr], c[vr], mk[vr], beta), vr):
                    values.append({"round": int(rnd[j]), "none": none, "best": best, "spread": spread,
                                   "tribes": k, "raw_best_minus_none": raw_best, "raw_spread": raw_spread})
        _, done, info = env.step(actions)
        for i in np.flatnonzero(done):
            if int(i) not in place:
                place[int(i)] = int(info["placement"][i]) or 4.5
        obs = env.observe()
    for i in range(n):
        seat[i].update(place=place.get(i, 4.5), plan=int(plan[i]), plan_round=int(plan_round[i]))
    return seat, values


def mean_se(x):
    x = [v for v in x if v is not None]
    if len(x) < 2:
        return None
    return [round(float(np.mean(x)), 3), round(float(np.std(x, ddof=1) / math.sqrt(len(x))), 3), len(x)]


def summary(seats, values):
    out = {}
    for name, rs in (("planned", [s for s in seats if s["fed"]]), ("unplanned", [s for s in seats if not s["fed"]])):
        if not rs:
            continue
        rs_p = [s for s in rs if s["plan"] > 0]
        out[name] = {
            "seats": len(rs),
            "place": mean_se([s["place"] for s in rs]),
            "follow (plan buys / buys with one for sale)": round(
                sum(s["buys_on"] for s in rs_p) / max(sum(s["buys_offered"] for s in rs_p), 1), 3),
            "plan minions r8": mean_se([s["on"].get(8) for s in rs_p]),
            "plan minions r12": mean_se([s["on"].get(12) for s in rs_p]),
            "stats r8": mean_se([s["stats"].get(8) for s in rs]),
            "stats r12": mean_se([s["stats"].get(12) for s in rs]),
            "log growth r8-12": mean_se([math.log((s["stats"][12] + 1) / (s["stats"][8] + 1))
                                         for s in rs if 8 in s["stats"] and 12 in s["stats"]]),
        }
    if values:
        out["values (V + Phi, rounds 5-8 End Turns)"] = {
            "n": len(values),
            "spread": mean_se([v["spread"] for v in values]),
            "best tribe - none": mean_se([v["best"] - v["none"] for v in values if v["tribes"]]),
            "a tribe beats none": round(float(np.mean([v["best"] > v["none"] for v in values if v["tribes"]])), 3),
            "raw V (no Phi): spread": mean_se([v["raw_spread"] for v in values]),
            "raw V: best tribe - none": mean_se([v["raw_best_minus_none"] for v in values if v["tribes"]]),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("--lobbies", type=int, default=64)
    ap.add_argument("--per", type=int, default=4, help="lobbies per worker job")
    ap.add_argument("--workers", type=int, default=60)
    ap.add_argument("--beta", type=float, default=0.3)
    ap.add_argument("--seed", type=int, default=91_000)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    import multiprocessing as mp
    jobs = [(a.checkpoint, a.per, a.seed + k, a.beta) for k in range(max(a.lobbies // a.per, 1))]
    seats, values = [], []
    with mp.get_context("spawn").Pool(min(a.workers, len(jobs))) as p:
        for k, (s, v) in enumerate(p.imap_unordered(_work, jobs)):
            seats += s
            values += v
            print(f"{k + 1}/{len(jobs)} jobs", flush=True)
    res = {"checkpoint": a.checkpoint, "summary": summary(seats, values)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    torch.save({"seats": seats, "values": values}, a.out + ".raw.pt")
    print(json.dumps(res["summary"], indent=1))


if __name__ == "__main__":
    main()
