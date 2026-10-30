"""PPO self-play in TavernGym (docs/ROADMAP.md, M5).

Every seat of every game is played by the current network (BatchEnv with all eight seats
controlled); a seat's episode ends with the placement reward (1st = 1, 8th = -1). Seats act
asynchronously, so each one keeps its own trajectory; the last unfinished transition of a seat
waits for the next rollout, where its value bootstraps the one before it.

The gate: the greedy network on one seat against seven scripted bots, mean placement over fresh
seeds (bots against bots average 4.5). Pause-aware: waits while Hearthstone runs (home rule).

    python -X utf8 -m advisor.train --run smoke --minutes 10
    python -X utf8 -m advisor.train --run office1 --hours 4 --resume data/train/office1/last.pt
    python -X utf8 -m advisor.train --evaluate data/train/office1/best.pt --eval-episodes 1000
"""

import argparse
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import torch

from advisor.policy import load, make, save
from advisor.state import GAME_CONFIG
from taverngym import BatchEnv

CONFIG = GAME_CONFIG  # advisor.state: shared with the live advisor
# Ending a turn with gold left while Refresh is legal and the Tavern isn't frozen costs this much
# reward per gold: gold doesn't carry over, so a Refresh is free then. Self-play alone left the
# network ending late turns with 4-9 gold (advisor.train docstring)
WASTED_GOLD = 0.003
F_GOLD, F_FROZEN = 7, 15  # global observation features (obs.rs): gold / 10, Tavern frozen
A_END, A_REFRESH = 0, 1  # taverngym.layout()


def hearthstone_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Hearthstone.exe", "/NH"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False  # no tasklist (Linux): no game to wait for
    return "Hearthstone.exe" in out


def wait_while_playing(log):
    if hearthstone_running():
        log({"paused": "Hearthstone is running"})
        while hearthstone_running():
            time.sleep(30)
        log({"resumed": True})


class Seat:
    """One slot's transitions: obs, cards, mask, action, logp, value, reward, done."""
    __slots__ = ("items",)

    def __init__(self):
        self.items = []


def wasted_gold(obs, i, a):
    """The shaping cost of slot `i` taking action `a` (WASTED_GOLD)."""
    f, m = obs["features"][i], obs["action_mask"][i]
    if a != A_END or not m[A_REFRESH] or f[F_FROZEN] > 0.5:
        return 0.0
    return WASTED_GOLD * round(float(f[F_GOLD]) * 10)


def collect(env, net, obs, seats, n_transitions, device, opponent_of=None):
    """Step the batch until `n_transitions` new transitions are stored. Returns the next obs and
    stats (finished episodes' placements of the current network's seats). `opponent_of` maps a
    slot to the frozen network playing it (a pool snapshot); those seats aren't learned from."""
    opponent_of = opponent_of or {}
    stored, placements = 0, []
    while stored < n_transitions:
        ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
        actions = np.zeros(env.n_slots, dtype=np.int64)
        own = np.array([i for i in ready if i not in opponent_of], dtype=np.int64)
        if len(own):
            f = torch.from_numpy(obs["features"][own]).to(device)
            c = torch.from_numpy(obs["cards"][own]).to(device)
            m = torch.from_numpy(obs["action_mask"][own]).to(device)
            with torch.no_grad():
                logits, v = net(f, c, m)
                dist = torch.distributions.Categorical(logits=logits)
                a = dist.sample()
                lp = dist.log_prob(a)
            a, lp, v = a.cpu().numpy(), lp.cpu().numpy(), v.cpu().numpy()
            actions[own] = a
            for j, i in enumerate(own):
                seats[i].items.append([obs["features"][i], obs["cards"][i],
                                       obs["action_mask"][i], int(a[j]), float(lp[j]),
                                       float(v[j]), -wasted_gold(obs, i, int(a[j])), False])
            stored += len(own)
        play_frozen(obs, ready, opponent_of, actions, device, sample=True)
        rew, done, info = env.step(actions)
        for i in np.flatnonzero((rew != 0) | done):
            if i in opponent_of:
                continue
            if seats[i].items:
                seats[i].items[-1][6] += float(rew[i])
                if done[i]:
                    seats[i].items[-1][7] = True
            if done[i] and info["placement"][i]:
                placements.append(int(info["placement"][i]))
        obs = env.observe()
    return obs, placements


@torch.no_grad()
def play_frozen(obs, ready, net_of, actions, device, sample=False):
    """Actions of the ready slots that frozen networks play (`net_of`: slot -> network)."""
    groups = {}
    for i in ready:
        if i in net_of:
            groups.setdefault(id(net_of[i]), (net_of[i], []))[1].append(i)
    for n, idx in groups.values():
        idx = np.array(idx)
        logits, _ = n(torch.from_numpy(obs["features"][idx]).to(device),
                      torch.from_numpy(obs["cards"][idx]).to(device),
                      torch.from_numpy(obs["action_mask"][idx]).to(device))
        a = torch.distributions.Categorical(logits=logits).sample() if sample else logits.argmax(1)
        actions[idx] = a.cpu().numpy()


def advantages(seats, gamma, lam):
    """GAE over every seat's finished part; the unfinished last transition stays behind."""
    batch = []
    for s in seats:
        items = s.items
        if not items:
            continue
        keep = [] if items[-1][7] else [items[-1]]
        use = items if items[-1][7] else items[:-1]
        next_v = 0.0 if items[-1][7] else items[-1][5]
        gae = 0.0
        out = []
        for it in reversed(use):
            v, r, d = it[5], it[6], it[7]
            if d:
                next_v, gae = 0.0, 0.0
            delta = r + gamma * next_v - v
            gae = delta + gamma * lam * gae
            out.append((it, gae + v, gae))
            next_v = v
        batch.extend(reversed(out))
        s.items = keep
    return batch


def update(net, opt, batch, device, epochs=3, minibatch=4096, clip=0.2, vf=0.5, ent=0.01,
           amp=False, value_only=False, anchor=None, anchor_coef=0.0):
    """PPO epochs over the batch. `amp`: the network's forward pass in bfloat16 on a GPU (the
    probabilities and losses stay float32). `value_only`: only the value loss (a hot-started
    policy waits until the value fits). `anchor`: a frozen network the policy is kept close to,
    `anchor_coef` times KL(anchor || policy)."""
    f = torch.from_numpy(np.stack([b[0][0] for b in batch]))
    c = torch.from_numpy(np.stack([b[0][1] for b in batch]))
    m = torch.from_numpy(np.stack([b[0][2] for b in batch]))
    a = torch.tensor([b[0][3] for b in batch])
    old_lp = torch.tensor([b[0][4] for b in batch])
    ret = torch.tensor([b[1] for b in batch], dtype=torch.float32)
    adv = torch.tensor([b[2] for b in batch], dtype=torch.float32)
    adv = (adv - adv.mean()) / (adv.std() + 1e-8)
    n = len(batch)
    stats = {"pi": 0.0, "v": 0.0, "ent": 0.0, "kl": 0.0}
    steps = 0
    for _ in range(epochs):
        for idx in torch.randperm(n).split(minibatch):
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=amp and device == "cuda"):
                logits, v = net(f[idx].to(device), c[idx].to(device), m[idx].to(device))
            logits, v = logits.float(), v.float()
            dist = torch.distributions.Categorical(logits=logits)
            lp = dist.log_prob(a[idx].to(device))
            ratio = (lp - old_lp[idx].to(device)).exp()
            ad = adv[idx].to(device)
            pi_loss = -torch.min(ratio * ad, ratio.clamp(1 - clip, 1 + clip) * ad).mean()
            v_loss = (v - ret[idx].to(device)).pow(2).mean()
            entropy = dist.entropy().mean()
            loss = vf * v_loss if value_only else pi_loss + vf * v_loss - ent * entropy
            if anchor is not None and anchor_coef > 0:  # in the warmup too: it holds the policy
                with torch.no_grad():
                    al, _ = anchor(f[idx].to(device), c[idx].to(device), m[idx].to(device))
                    ap = torch.softmax(al.float(), 1)
                anchor_kl = (ap * (torch.log_softmax(al.float(), 1)
                                   - torch.log_softmax(logits, 1))).sum(1).mean()
                loss = loss + anchor_coef * anchor_kl
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
            with torch.no_grad():
                kl = (old_lp[idx].to(device) - lp).mean().item()
            for k, x in (("pi", pi_loss.item()), ("v", v_loss.item()), ("ent", entropy.item()), ("kl", kl)):
                stats[k] += x
            steps += 1
    return {k: round(v / max(1, steps), 4) for k, v in stats.items()}


@torch.no_grad()
def evaluate(net, device, episodes=200, games=32, seed=10_000_000, threads=8, config=None):
    """Mean placement of the greedy network on seat 0 against seven scripted bots (`config`'s
    teacher bots when it has one)."""
    env = BatchEnv(games, seed=seed, controlled=[0], config=config or CONFIG, threads=threads)
    obs = env.observe()
    places = []
    while len(places) < episodes:
        ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
        actions = np.zeros(env.n_slots, dtype=np.int64)
        if len(ready):
            logits, _ = net(torch.from_numpy(obs["features"][ready]).to(device),
                            torch.from_numpy(obs["cards"][ready]).to(device),
                            torch.from_numpy(obs["action_mask"][ready]).to(device))
            actions[ready] = logits.argmax(1).cpu().numpy()
        _, done, info = env.step(actions)
        places += [int(p) for p in info["placement"][done] if p]
        obs = env.observe()
    places = places[:episodes]
    return {"mean_place": round(float(np.mean(places)), 3),
            "se": round(float(np.std(places) / np.sqrt(len(places))), 3),
            "top4": round(float(np.mean([p <= 4 for p in places])), 3), "n": len(places)}


@torch.no_grad()
def evaluate_league(net, pool, device, episodes=200, games=32, seed=30_000_000, threads=8):
    """Mean placement of the greedy network on seat 0 against seven pool snapshots (greedy too):
    under 4.5 beats its own past versions."""
    env = BatchEnv(games, seed=seed, controlled=list(range(8)), config=CONFIG, threads=threads)
    net_of = {i: pool[(i // 8 + i % 8) % len(pool)] for i in range(env.n_slots) if i % 8}
    net_of.update({i: net for i in range(env.n_slots) if i % 8 == 0})
    obs = env.observe()
    places = []
    while len(places) < episodes:
        ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
        actions = np.zeros(env.n_slots, dtype=np.int64)
        play_frozen(obs, ready, net_of, actions, device)
        _, done, info = env.step(actions)
        places += [int(info["placement"][i]) for i in np.flatnonzero(done)
                   if i % 8 == 0 and info["placement"][i]]
        obs = env.observe()
    places = places[:episodes]
    return {"mean_place": round(float(np.mean(places)), 3),
            "se": round(float(np.std(places) / np.sqrt(len(places))), 3),
            "top4": round(float(np.mean([p <= 4 for p in places])), 3), "n": len(places),
            "pool": len(pool)}


POOL_SIZE = 6
OPPONENT_SEATS = (6, 7)  # of each game's eight, played by pool snapshots in training


def load_pool(out, device):
    pool = []
    for f in sorted((out / "pool").glob("it_*.pt"), key=lambda f: int(f.stem[3:]))[-POOL_SIZE:]:
        n, _ = load(f, device)
        pool.append(n)
    return pool


def assign_opponents(env, pool, it):
    """Slot -> pool snapshot for the opponent seats of every game, rotating by iteration."""
    if not pool:
        return {}
    return {g * 8 + seat: pool[(g + it) % len(pool)]
            for g in range(env.n_games) for seat in OPPONENT_SEATS}


MODELS = Path(__file__).resolve().parents[1] / "data" / "models"  # advisor.promote's
GEN_BEST_SEATS, GEN_PAST_SEATS = (4, 5, 6), (7,)


class Generation:
    """--generations: each game's seats 4-6 play the frozen current best (data/models/best.pt,
    reloaded when a promotion replaces it), seat 7 an older promoted network (archive/), and
    the learner the other four. A generation trains against the network it has to beat."""

    def __init__(self, device, models=MODELS):
        self.device, self.best_path, self.archive = device, models / "best.pt", models / "archive"
        self.version, self.best, self.past = None, None, []

    def refresh(self, log):
        """Reload when a promotion replaced the best; True then."""
        if not self.best_path.is_file():
            return False
        version = self.best_path.stat().st_mtime_ns
        if version == self.version:
            return False
        self.best, ck = load(self.best_path, self.device)
        self.past = [load(f, self.device)[0]
                     for f in sorted(self.archive.glob("best_*.pt"))[-POOL_SIZE:]]
        self.version = version
        log({"opponents": "generation", "best": ck.get("source"), "past": len(self.past)})
        return True

    def assign(self, env, it, pool):
        past = self.past or pool
        out = {}
        for g in range(env.n_games):
            if self.best is not None:
                out.update({g * 8 + s: self.best for s in GEN_BEST_SEATS})
            if past:
                out.update({g * 8 + s: past[(g + it) % len(past)] for s in GEN_PAST_SEATS})
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", help="run name (data/train/RUN)")
    ap.add_argument("--evaluate", metavar="CKPT",
                    help="only the gate: CKPT against seven bots on --eval-episodes fresh games")
    ap.add_argument("--out", default="data/train")
    ap.add_argument("--minutes", type=float, default=0)
    ap.add_argument("--hours", type=float, default=0)
    ap.add_argument("--games", type=int, default=128)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--transitions", type=int, default=32768, help="per update")
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--gamma", type=float, default=0.995)
    ap.add_argument("--lam", type=float, default=0.95)
    ap.add_argument("--ent", type=float, default=0.01, help="entropy bonus")
    ap.add_argument("--amp", action="store_true", help="bfloat16 forward pass in the updates")
    ap.add_argument("--eval-every", type=int, default=10)
    ap.add_argument("--eval-episodes", type=int, default=200)
    ap.add_argument("--resume")
    ap.add_argument("--arch", default="mlp", choices=["mlp", "entity"], help="a new run's network")
    ap.add_argument("--snapshot-every", type=int, default=50,
                    help="iterations between pool snapshots (opponents and the league gate)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--generations", action="store_true",
                    help="train against the frozen current best (Generation); best.pt by place vs it")
    ap.add_argument("--critic-warmup", type=int, default=0, metavar="N",
                    help="the first N iterations train only the value (after a hot start)")
    ap.add_argument("--anchor", help="keep the policy close to this checkpoint (a hot start)")
    ap.add_argument("--anchor-coef", type=float, default=0.1)
    ap.add_argument("--anchor-iters", type=int, default=200,
                    help="iterations over which the anchor fades out")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    a = ap.parse_args()
    if a.evaluate:
        net, ck = load(a.evaluate, a.device)
        # Seeds apart from the training gate's, so a promotion is judged on unseen games
        ev = evaluate(net, a.device, a.eval_episodes, seed=20_000_000, threads=a.threads)
        print(json.dumps({"checkpoint": a.evaluate, "iteration": ck.get("iteration"), **ev}))
        return
    if not a.run:
        ap.error("--run is required for training")
    budget = a.minutes * 60 + a.hours * 3600
    out = Path(a.out) / a.run
    out.mkdir(parents=True, exist_ok=True)
    logf = open(out / "log.jsonl", "a", encoding="utf-8")

    def log(row):
        row = {"t": round(time.time() - t0, 1), **row}
        logf.write(json.dumps(row) + "\n")
        logf.flush()
        print(json.dumps(row), flush=True)

    t0 = time.time()
    torch.manual_seed(a.seed)
    if a.resume:
        net, ck = load(a.resume, a.device)
        net.train()
        it0, best = ck.get("iteration", 0), ck.get("best", 9.0)
    else:
        net, it0, best = make({"arch": a.arch}).to(a.device), 0, 9.0
    opt = torch.optim.Adam(net.parameters(), lr=a.lr)
    if a.resume and "opt" in ck:
        opt.load_state_dict(ck["opt"])
    anchor = load(a.anchor, a.device)[0] if a.anchor else None
    env = BatchEnv(a.games, seed=a.seed * 1_000_003 + it0, controlled=list(range(8)),
                   config=CONFIG, threads=a.threads)
    seats = [Seat() for _ in range(env.n_slots)]
    obs = env.observe()
    pool = load_pool(out, a.device)
    gen = Generation(a.device) if a.generations else None
    best_h2h = ck.get("best_h2h", 4.5) if a.resume else 4.5  # place vs the best (generations)
    log({"start": a.run, "params": sum(p.numel() for p in net.parameters()), "device": a.device,
         "iteration": it0, "slots": env.n_slots})
    if it0 == 0:
        log({"iteration": 0, "eval": evaluate(net, a.device, a.eval_episodes, threads=a.threads)})
    it = it0
    while budget == 0 or time.time() - t0 < budget:
        wait_while_playing(log)
        it += 1
        ts = time.time()
        if gen and gen.refresh(log):
            best_h2h = 4.5  # a new generation: the record against the old best is void
        opponents = gen.assign(env, it, pool) if gen else assign_opponents(env, pool, it)
        obs, placements = collect(env, net, obs, seats, a.transitions, a.device, opponents)
        for i in opponents:  # a seat that changes hands starts its trajectory anew
            seats[i].items = []
        batch = advantages(seats, a.gamma, a.lam)
        tc = time.time()
        net.train()
        warm = it - it0 <= a.critic_warmup
        fade = max(0, it - it0 - a.critic_warmup) / a.anchor_iters  # from the warmup's end
        coef = a.anchor_coef * max(0.0, 1 - fade) if anchor else 0.0
        stats = update(net, opt, batch, a.device, ent=a.ent, amp=a.amp, value_only=warm,
                       anchor=anchor, anchor_coef=coef)
        if warm:
            stats["critic_warmup"] = True
        net.eval()
        row = {"iteration": it, "batch": len(batch), "episodes": len(placements),
               "place": round(float(np.mean(placements)), 3) if placements else None,
               "collect_s": round(tc - ts, 1), "update_s": round(time.time() - tc, 1),
               "decisions_per_s": round(len(batch) / max(1e-6, tc - ts)), **stats}
        if it % a.snapshot_every == 0:
            save(net, out / "pool" / f"it_{it}.pt", {"iteration": it})
            frozen = make(net.config).to(a.device)
            frozen.load_state_dict(net.state_dict())
            frozen.eval()
            pool = (pool + [frozen])[-POOL_SIZE:]
        if it % a.eval_every == 0:
            ev = evaluate(net, a.device, a.eval_episodes, threads=a.threads)
            row["eval"] = ev
            if pool:
                row["league"] = evaluate_league(net, pool, a.device, a.eval_episodes,
                                                threads=a.threads)
            if gen and gen.best is not None:
                vs = evaluate_league(net, [gen.best], a.device, a.eval_episodes, threads=a.threads)
                vs.pop("pool", None)
                row["vs_best"] = vs
                if vs["mean_place"] < best_h2h:  # the candidate advisor.promote judges
                    best_h2h = vs["mean_place"]
                    save(net, out / "best.pt", {"iteration": it, "eval": ev, "best": best,
                                                "vs_best": vs, "best_h2h": best_h2h})
            elif ev["mean_place"] < best:
                best = ev["mean_place"]
                save(net, out / "best.pt", {"iteration": it, "eval": ev, "best": best})
            best = min(best, ev["mean_place"])
        log(row)
        save(net, out / "last.pt", {"iteration": it, "best": best, "best_h2h": best_h2h,
                                    "opt": opt.state_dict()})
        if budget == 0 and it - it0 >= 1:
            break


if __name__ == "__main__":
    main()
