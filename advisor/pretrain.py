"""Hot start: the network learns to play like the teacher bot (advisor.teacher, TavernGym's
teacher.rs) before PPO, instead of starting from random play.

Every seat of every game is played by the teacher; each iteration the network is trained on the
new decisions (cross-entropy against the teacher's action over the legal ones) and the games go
on. Nothing is stored beyond one batch. The gate is the network's own play: on seat 0 against
seven plain bots (advisor.train.evaluate) and against seven teachers. PPO then continues from
the checkpoint (advisor.train --resume ... --critic-warmup N).

    python -X utf8 -m advisor.pretrain --run teach1 --hours 2
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from advisor import teacher
from advisor.policy import load, make, save
from advisor.train import CHUNK, CONFIG, cap_gpu_memory, evaluate, wait_while_playing
from taverngym import BatchEnv

TEACHER_CONFIG = {**CONFIG, "teacher": teacher.config()}


def collect(env, obs, n):
    """`n` of the teacher's decisions: (features, cards, masks, actions) and the next obs."""
    rows = [[], [], [], []]
    stored = 0
    while stored < n:
        acts = env.bot_actions()
        ready = np.flatnonzero(obs["ready"] & (acts >= 0))
        rows[0].append(obs["features"][ready])
        rows[1].append(obs["cards"][ready])
        rows[2].append(obs["action_mask"][ready])
        rows[3].append(acts[ready])
        stored += len(ready)
        env.step(np.maximum(acts, 0))
        obs = env.observe()
    return [np.concatenate(r) for r in rows], obs


def train_step(net, opt, batch, device, minibatch, amp):
    f, c, m, a = batch
    order = np.random.permutation(len(a))
    stats = {"loss": 0.0, "acc": 0.0}
    n = 0
    for s in range(0, len(a), minibatch):
        j = order[s:s + minibatch]
        opt.zero_grad()
        for k in range(0, len(j), CHUNK):  # gradients added up: one step per minibatch
            jj = j[k:k + CHUNK]
            ft, ct = torch.from_numpy(f[jj]).to(device), torch.from_numpy(c[jj]).to(device)
            mt, at = torch.from_numpy(m[jj]).to(device), torch.from_numpy(a[jj]).to(device)
            with torch.autocast(device_type=device.split(":")[0], dtype=torch.bfloat16, enabled=amp):
                logits, _ = net(ft, ct, mt)
            logits = logits.float()
            loss = torch.nn.functional.cross_entropy(logits, at)
            (loss * len(jj) / len(j)).backward()
            stats["loss"] += float(loss) * len(jj)
            stats["acc"] += float((logits.argmax(1) == at).float().sum())
            n += len(jj)
        torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
        opt.step()
    return {k: round(v / n, 4) for k, v in stats.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", default="data/train")
    ap.add_argument("--arch", default="entity")
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--games", type=int, default=256)
    ap.add_argument("--transitions", type=int, default=65536)
    ap.add_argument("--minibatch", type=int, default=4096)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--hours", type=float, default=0)
    ap.add_argument("--minutes", type=float, default=0)
    ap.add_argument("--eval-every", type=int, default=20)
    ap.add_argument("--eval-episodes", type=int, default=200)
    ap.add_argument("--amp", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--resume", help="continue from this checkpoint (its last.pt)")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--gpu-memory", type=float, default=0.4, help="the most of the GPU it takes")
    a = ap.parse_args()
    cap_gpu_memory(a.device, a.gpu_memory)
    out = Path(a.out) / a.run
    out.mkdir(parents=True, exist_ok=True)
    logf = open(out / "log.jsonl", "a", encoding="utf-8")
    t0 = time.time()

    def log(row):
        row = {"t": round(time.time() - t0, 1), **row}
        logf.write(json.dumps(row) + "\n")
        logf.flush()
        print(json.dumps(row), flush=True)

    torch.manual_seed(a.seed)
    best, it = 9.0, 0
    if a.resume:
        net, ck = load(a.resume, a.device)
        best, it = ck.get("best", 9.0), ck.get("iteration", 0)
    else:
        net = make({"arch": a.arch}).to(a.device)
    net.train()
    opt = torch.optim.Adam(net.parameters(), lr=a.lr)
    if a.resume and "opt" in ck and "adapted" not in ck:
        opt.load_state_dict(ck["opt"])
    env = BatchEnv(a.games, seed=a.seed * 1_000_003 + it, controlled=list(range(8)),
                   config=TEACHER_CONFIG, threads=a.threads)
    obs = env.observe()
    budget = a.minutes * 60 + a.hours * 3600
    log({"start": a.run, "pretrain": True, "teacher": TEACHER_CONFIG["teacher"]["level_turns"],
         "params": sum(p.numel() for p in net.parameters())})
    while budget == 0 or time.time() - t0 < budget:
        wait_while_playing(log)
        it += 1
        ts = time.time()
        batch, obs = collect(env, obs, a.transitions)
        tc = time.time() - ts
        stats = train_step(net, opt, batch, a.device, a.minibatch, a.amp)
        row = {"iteration": it, "batch": len(batch[3]), "collect_s": round(tc, 1),
               "update_s": round(time.time() - ts - tc, 1), **stats}
        if it % a.eval_every == 0:
            net.eval()
            row["eval"] = evaluate(net, a.device, a.eval_episodes, threads=a.threads)
            row["eval_teachers"] = evaluate(net, a.device, a.eval_episodes, threads=a.threads,
                                            config=TEACHER_CONFIG)
            net.train()
            if row["eval"]["mean_place"] < best:
                best = row["eval"]["mean_place"]
                save(net, out / "best.pt", {"iteration": it, "best": best, "pretrain": True})
        save(net, out / "last.pt", {"iteration": it, "best": best, "pretrain": True,
                                    "opt": opt.state_dict()})
        log(row)


if __name__ == "__main__":
    main()
