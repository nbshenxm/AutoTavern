"""PPO self-play in TavernGym (docs/ROADMAP.md, M5).

Every seat of every game is played by the current network (BatchEnv with all eight seats
controlled); a seat's episode ends with the placement reward (1st = 1, 8th = -1). Seats act
asynchronously, so each one keeps its own trajectory; the last unfinished transition of a seat
waits for the next rollout, where its value bootstraps the one before it.

The gate: the greedy network on one seat against seven scripted bots, mean placement over fresh
seeds (bots against bots average 4.5). Pause-aware: waits while Hearthstone runs (home rule).

    python -X utf8 -m advisor.train --run smoke --minutes 10
    python -X utf8 -m advisor.train --run office1 --hours 4 --resume data/train/office1/last.pt
"""

import argparse
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import torch

from advisor.policy import PolicyNet, load, save
from taverngym import BatchEnv

CONFIG = {
    "hero_choices": 4,  # the player's season-pass offer (docs/REPLAY.md, recruit rules)
    # Moves and Freeze never advance the game: a turn ends after this many actions, a little
    # above the most the player took in a logged turn (6, 5, 10, 10, 18, 38, 28, 49, 58...)
    "turn_action_caps": [8, 8, 12, 12, 20, 40, 40, 60],
}


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


def collect(env, net, obs, seats, n_transitions, device):
    """Step the batch until `n_transitions` new transitions are stored. Returns the next obs and
    stats (finished episodes' placements)."""
    stored, placements = 0, []
    while stored < n_transitions:
        ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
        actions = np.zeros(env.n_slots, dtype=np.int64)
        if len(ready):
            f = torch.from_numpy(obs["features"][ready]).to(device)
            c = torch.from_numpy(obs["cards"][ready]).to(device)
            m = torch.from_numpy(obs["action_mask"][ready]).to(device)
            with torch.no_grad():
                logits, v = net(f, c, m)
                dist = torch.distributions.Categorical(logits=logits)
                a = dist.sample()
                lp = dist.log_prob(a)
            a, lp, v = a.cpu().numpy(), lp.cpu().numpy(), v.cpu().numpy()
            actions[ready] = a
            for j, i in enumerate(ready):
                seats[i].items.append([obs["features"][i], obs["cards"][i],
                                       obs["action_mask"][i], int(a[j]), float(lp[j]),
                                       float(v[j]), 0.0, False])
            stored += len(ready)
        rew, done, info = env.step(actions)
        for i in np.flatnonzero((rew != 0) | done):
            if seats[i].items:
                seats[i].items[-1][6] += float(rew[i])
                if done[i]:
                    seats[i].items[-1][7] = True
            if done[i] and info["placement"][i]:
                placements.append(int(info["placement"][i]))
        obs = env.observe()
    return obs, placements


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


def update(net, opt, batch, device, epochs=3, minibatch=4096, clip=0.2, vf=0.5, ent=0.01):
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
            logits, v = net(f[idx].to(device), c[idx].to(device), m[idx].to(device))
            dist = torch.distributions.Categorical(logits=logits)
            lp = dist.log_prob(a[idx].to(device))
            ratio = (lp - old_lp[idx].to(device)).exp()
            ad = adv[idx].to(device)
            pi_loss = -torch.min(ratio * ad, ratio.clamp(1 - clip, 1 + clip) * ad).mean()
            v_loss = (v - ret[idx].to(device)).pow(2).mean()
            entropy = dist.entropy().mean()
            loss = pi_loss + vf * v_loss - ent * entropy
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
def evaluate(net, device, episodes=200, games=32, seed=10_000_000, threads=8):
    """Mean placement of the greedy network on seat 0 against seven scripted bots."""
    env = BatchEnv(games, seed=seed, controlled=[0], config=CONFIG, threads=threads)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", default="data/train")
    ap.add_argument("--minutes", type=float, default=0)
    ap.add_argument("--hours", type=float, default=0)
    ap.add_argument("--games", type=int, default=128)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--transitions", type=int, default=32768, help="per update")
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--gamma", type=float, default=0.995)
    ap.add_argument("--lam", type=float, default=0.95)
    ap.add_argument("--eval-every", type=int, default=10)
    ap.add_argument("--eval-episodes", type=int, default=200)
    ap.add_argument("--resume")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    a = ap.parse_args()
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
        net, it0, best = PolicyNet().to(a.device), 0, 9.0
    opt = torch.optim.Adam(net.parameters(), lr=a.lr)
    if a.resume and "opt" in ck:
        opt.load_state_dict(ck["opt"])
    env = BatchEnv(a.games, seed=a.seed * 1_000_003 + it0, controlled=list(range(8)),
                   config=CONFIG, threads=a.threads)
    seats = [Seat() for _ in range(env.n_slots)]
    obs = env.observe()
    log({"start": a.run, "params": sum(p.numel() for p in net.parameters()), "device": a.device,
         "iteration": it0, "slots": env.n_slots})
    if it0 == 0:
        log({"iteration": 0, "eval": evaluate(net, a.device, a.eval_episodes, threads=a.threads)})
    it = it0
    while budget == 0 or time.time() - t0 < budget:
        wait_while_playing(log)
        it += 1
        ts = time.time()
        obs, placements = collect(env, net, obs, seats, a.transitions, a.device)
        batch = advantages(seats, a.gamma, a.lam)
        tc = time.time()
        net.train()
        stats = update(net, opt, batch, a.device)
        net.eval()
        row = {"iteration": it, "batch": len(batch), "episodes": len(placements),
               "collect_s": round(tc - ts, 1), "update_s": round(time.time() - tc, 1),
               "decisions_per_s": round(len(batch) / max(1e-6, tc - ts)), **stats}
        if it % a.eval_every == 0:
            ev = evaluate(net, a.device, a.eval_episodes, threads=a.threads)
            row["eval"] = ev
            if ev["mean_place"] < best:
                best = ev["mean_place"]
                save(net, out / "best.pt", {"iteration": it, "eval": ev, "best": best})
        log(row)
        save(net, out / "last.pt", {"iteration": it, "best": best, "opt": opt.state_dict()})
        if budget == 0 and it - it0 >= 1:
            break


if __name__ == "__main__":
    main()
