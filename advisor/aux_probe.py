"""Can the network learn to see scaling? (Nov 7, the long-term return plan, step 1.) The value head
can't tell a mid-game engine from a stat pile (value_probe: it prefers your round 5-8 End Turn
59-62%, chance), so PPO's noisy final-place signal never reaches the buys that build one. The plan:
extra heads that predict the warband's stats 2 and 4 rounds on (low noise, scaling itself). Before a
run, offline:

1. collect: main1 plays games on every seat; at each End Turn, its trunk output z (what every head
   reads), the value, the warband's stats, Health, Tier, round; then what followed (stats 2 and 4
   rounds on, the place). Rounds 4-9 also keep the observation (for 2c).
2. fit (held-out games): growth log(stats_{r+k} / stats_r) for k = 2, 4, rounds 5-8, from
   a. current stats + round + Tier + Health (the baseline: what a stat pile says),
   b. z, frozen (ridge): is scaling already in what main1 sees,
   c. a copy of main1 trained on it (the aux head with its trunk): can it be learned;
   and how the value head itself tracks growth.
3. your games: does each predictor (b, c) rate your round 5-8 End Turn above the network's own from
   the same start (the value head: 59-62%), and track your real growth (your logs, 2 and 4 rounds on)?

    python -X utf8 -m advisor.aux_probe collect data/models/archive/main1_it1400.pt --out data/audit/aux --games 480
    python -X utf8 -m advisor.aux_probe fit data/models/archive/main1_it1400.pt --out data/audit/aux
"""

import argparse
import copy
import json
import math
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from advisor import bridge
from advisor.policy import L, load, observe
from advisor.train import CONFIG, BatchEnv

ROOT = Path(__file__).resolve().parents[1]
KS = (2, 4)


def stats(board):
    return float(sum((m.get("atk") or 0) + (m.get("hp") or 0) for m in board))


def hook(net):
    """net.trunk's output after every forward, in out["z"]."""
    out = {}
    net.trunk.register_forward_hook(lambda m, i, o: out.__setitem__("z", o.detach()))
    return out


# ------------------------------------------------------------------ 1. collect

@torch.no_grad()
def _collect(job):
    path, m, seed = job
    torch.set_num_threads(1)
    net = load(path, "cpu")[0].eval()
    zs = hook(net)
    env = BatchEnv(m, seed=seed, controlled=list(range(8)), config=CONFIG, threads=1)
    obs = env.observe()
    recs = {}  # slot -> {round: record}
    place = {}
    for _ in range(400_000):
        if len(place) == env.n_slots:
            break
        ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
        ready = np.array([i for i in ready if i not in place], dtype=np.int64)
        actions = np.zeros(env.n_slots, dtype=np.int64)
        if len(ready):
            f = torch.from_numpy(obs["features"][ready])
            c = torch.from_numpy(obs["cards"][ready])
            mk = torch.from_numpy(obs["action_mask"][ready])
            logits, value = net(f, c, mk)
            a = logits.argmax(1).numpy()
            actions[ready] = a
            for j in np.flatnonzero(a == L["A_END"]):
                i = int(ready[j])
                g, seat = env.game(i // 8), i % 8
                v = json.loads(g.view(seat))
                me = v["me"]
                if v["phase"].lower() != "recruit" or me.get("pending"):
                    continue
                r = int(me.get("turn") or g.turn)
                rec = {"z": zs["z"][j].numpy().astype(np.float16), "v": float(value[j]), "stats": stats(me["board"]),
                       "hp": float(me["health"]), "tier": int(me["tier"]), "round": r}
                if 4 <= r <= 9:
                    rec["obs"] = (obs["features"][i].copy(), obs["cards"][i].copy(), obs["action_mask"][i].copy())
                recs.setdefault(i, {})[r] = rec
        _, done, info = env.step(actions)
        for i in np.flatnonzero(done):
            if int(i) not in place:
                place[int(i)] = int(info["placement"][i]) or 4.5
        obs = env.observe()
    rows = []
    for i, by in recs.items():
        for r, rec in by.items():
            fut = {k: by[r + k]["stats"] if r + k in by else None for k in KS}
            rows.append({**rec, "game": seed * 1000 + i // 8, "place": place.get(i, 4.5), "future": fut})
    return rows


def collect(a):
    import multiprocessing as mp
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    per = 8
    jobs = [(a.checkpoint, per, 77_000 + k) for k in range(a.games // per)]
    rows = []
    with mp.get_context("spawn").Pool(min(a.workers, len(jobs))) as p:
        for j, rs in enumerate(p.imap_unordered(_collect, jobs)):
            rows += rs
            print(f"{j + 1}/{len(jobs)} batches, {len(rows)} End Turns", flush=True)
    torch.save(rows, out / "collect.pt")


# ------------------------------------------------------------------ 2. fit

def growth(r, k):
    f = r["future"][k]
    return None if f is None else math.log((f + 1) / (r["stats"] + 1))


def ridge(X, y, lam=1.0):
    X1 = np.hstack([X, np.ones((len(X), 1))])
    w = np.linalg.solve(X1.T @ X1 + lam * np.eye(X1.shape[1]), X1.T @ y)
    return lambda Z: np.hstack([Z, np.ones((len(Z), 1))]) @ w


def r2(pred, y):
    return round(float(1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()), 3)


def base_x(r):
    return [math.log(r["stats"] + 1), r["round"], r["tier"], r["hp"] / 40]


class Aux(nn.Module):
    """A copy of the network with heads for growth at KS (its trunk trained with them)."""

    def __init__(self, net):
        super().__init__()
        self.net = copy.deepcopy(net)
        self.z = hook(self.net)
        self.head = nn.Linear(self.net.trunk[0].out_features, len(KS))

    def forward(self, f, c, m):
        self.net(f, c, m)
        return self.head(self.z["z"])


def fit_aux(net, train, test, epochs, out):
    torch.set_num_threads(16)
    model = Aux(net).train()
    opt = torch.optim.Adam(model.parameters(), lr=1e-4)

    def tensors(rs):
        f = torch.from_numpy(np.stack([r["obs"][0] for r in rs]))
        c = torch.from_numpy(np.stack([r["obs"][1] for r in rs]))
        m = torch.from_numpy(np.stack([r["obs"][2] for r in rs]))
        y = torch.tensor([[growth(r, k) if growth(r, k) is not None else float("nan") for k in KS] for r in rs])
        return f, c, m, y

    tr, te = tensors(train), tensors(test)
    rng = np.random.default_rng(0)
    for ep in range(epochs):
        idx = rng.permutation(len(train))
        for s in range(0, len(idx), 256):
            b = idx[s:s + 256]
            p = model(tr[0][b], tr[1][b], tr[2][b])
            y = tr[3][b]
            ok = ~torch.isnan(y)
            loss = ((p - torch.nan_to_num(y)) ** 2)[ok].mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            p = torch.cat([model(te[0][s:s + 512], te[1][s:s + 512], te[2][s:s + 512]) for s in range(0, len(test), 512)])
        model.train()
        res = {}
        for j, k in enumerate(KS):
            ok = ~torch.isnan(te[3][:, j])
            res[f"+{k}"] = r2(p[ok, j].numpy(), te[3][ok, j].numpy())
        print(f"aux epoch {ep + 1}: held-out R2 {res}", flush=True)
    torch.save(model.state_dict(), Path(out) / "aux.pt")
    return model.eval(), res


@torch.no_grad()
def your_games(net, ridges, model, decisions, combats):
    """3: on your round 5-8 turns, each predictor's rating of your End Turn vs the network's (from
    the same start), and how it tracks your real growth."""
    from advisor.value_check import positions
    from advisor.value_probe import net_turn
    zs = hook(net)
    logs = {}
    for d in decisions:
        if d["kind"] == "options" and d["turn"] % 2 == 1:
            logs.setdefault(d["log"], {}).setdefault(d["turn"], []).append(d)
    rows = []
    for d, last in positions(decisions, combats, range(5, 9)):
        cb = bridge.game_combats(combats, last)
        gy, gaps = bridge.build(last, cb)
        gn = net_turn(net, d, bridge.game_combats(combats, d))
        if gaps or gn is None:
            continue
        row = {"round": (d["turn"] + 1) // 2}
        for who, g in (("you", gy), ("net", gn)):
            f, c, m = observe(g, 0)
            f, c, m = (torch.from_numpy(x)[None] for x in (f, c, m))
            _, v = net(f, c, m)
            me = json.loads(g.view(0))["me"]
            z = zs["z"][0].numpy()
            x = np.array([base_x({"stats": stats(me["board"]), "round": row["round"], "tier": me["tier"], "hp": me["health"]})])
            row[who] = {"v": float(v[0]), "stats": stats(me["board"]),
                        **{f"z+{k}": float(ridges[k](z[None])[0]) for k in KS},
                        **{f"base+{k}": float(ridges[f"base{k}"](x)[0]) for k in KS},
                        **{f"aux+{k}": float(model(f, c, m)[0, j]) for j, k in enumerate(KS)}}
        # your real growth: your warband at the end of the turn k rounds on (the log's last decision)
        for k in KS:
            later = logs.get(d["log"], {}).get(d["turn"] + 2 * k)
            real = stats(later[-1]["state"]["friendly"]["board"]) if later else None
            row[f"real+{k}"] = None if real is None else math.log((real + 1) / (row["you"]["stats"] + 1))
        rows.append(row)
    out = {"positions": len(rows)}
    for key in ["v"] + [f"{p}+{k}" for p in ("base", "z", "aux") for k in KS]:
        out[f"prefers_yours[{key}]"] = round(float(np.mean([r["you"][key] > r["net"][key] for r in rows])), 3)
    for k in KS:
        rs = [r for r in rows if r[f"real+{k}"] is not None]
        if len(rs) > 2:
            y = np.array([r[f"real+{k}"] for r in rs])
            for p in ("base", "z", "aux"):
                out[f"tracks_your_real_growth[{p}+{k}] (corr, n={len(rs)})"] = round(float(np.corrcoef([r["you"][f"{p}+{k}"] for r in rs], y)[0, 1]), 3)
    return out


def fit(a):
    out = Path(a.out)
    rows = torch.load(out / "collect.pt", weights_only=False)
    games = sorted({r["game"] for r in rows})
    test_games = set(games[::5])
    mid = [r for r in rows if 5 <= r["round"] <= 8]
    res = {"end_turns": len(rows), "mid_end_turns": len(mid), "games": len(games)}
    ridges = {}
    for k in KS:
        tr = [r for r in mid if r["game"] not in test_games and growth(r, k) is not None]
        te = [r for r in mid if r["game"] in test_games and growth(r, k) is not None]
        ytr, yte = np.array([growth(r, k) for r in tr]), np.array([growth(r, k) for r in te])
        Xb = lambda rs: np.array([base_x(r) for r in rs])
        Xz = lambda rs: np.stack([r["z"].astype(np.float32) for r in rs])
        ridges[f"base{k}"] = ridge(Xb(tr), ytr)
        ridges[k] = ridge(Xz(tr), ytr, lam=10.0)
        res[f"+{k}"] = {"n_test": len(te), "growth_sd": round(float(yte.std()), 3),
                        "R2_baseline(stats,round,tier,hp)": r2(ridges[f"base{k}"](Xb(te)), yte),
                        "R2_frozen_z": r2(ridges[k](Xz(te)), yte),
                        "value_corr_with_growth": round(float(np.corrcoef([r["v"] for r in te], yte)[0, 1]), 3)}
        print(json.dumps({f"+{k}": res[f"+{k}"]}), flush=True)
    net = load(a.checkpoint, "cpu")[0].eval()
    tr = [r for r in mid if r["game"] not in test_games and "obs" in r]
    te = [r for r in mid if r["game"] in test_games and "obs" in r]
    model, res["R2_aux_trained"] = fit_aux(net, tr, te, a.epochs, out)
    dec = [json.loads(l) for l in open(ROOT / "data" / "replay" / "decisions.jsonl", encoding="utf-8")]
    com = [json.loads(l) for l in open(ROOT / "data" / "replay" / "combats.jsonl", encoding="utf-8")]
    res["your_games"] = your_games(net, ridges, model, dec, com)
    (out / "fit.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["collect", "fit"])
    ap.add_argument("checkpoint")
    ap.add_argument("--out", required=True)
    ap.add_argument("--games", type=int, default=480)
    ap.add_argument("--workers", type=int, default=60)
    ap.add_argument("--epochs", type=int, default=4)
    a = ap.parse_args()
    (collect if a.step == "collect" else fit)(a)


if __name__ == "__main__":
    main()
