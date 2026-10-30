"""A larger network that starts where the current one is: it learns to copy a trained network's
move probabilities and value (policy distillation) in games that network plays in every seat,
then PPO continues from it (advisor.train --resume). AutoTavern's size test found its largest
network (18M parameters) best; ours has 0.86M.

    python -X utf8 -m advisor.distill --teacher data/models/best.pt --run big1 --d 256 --layers 4
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from advisor.policy import load, make, save
from advisor.train import CHUNK, CONFIG, cap_gpu_memory, evaluate, evaluate_league, wait_while_playing
from taverngym import BatchEnv


@torch.no_grad()
def collect(env, obs, teacher, n, device):
    """`n` decisions of the teacher playing every seat (sampled): (features, cards, masks, the
    teacher's probabilities, its values) and the next obs."""
    rows = [[], [], [], [], []]
    stored = 0
    while stored < n:
        ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
        acts = np.zeros(env.n_slots, dtype=np.int64)
        if len(ready):
            f, c, m = (torch.from_numpy(obs[k][ready]).to(device) for k in ("features", "cards", "action_mask"))
            logits, v = teacher(f, c, m)
            p = torch.softmax(logits.float(), 1)
            acts[ready] = torch.multinomial(p, 1).squeeze(1).cpu().numpy()
            for r, x in zip(rows, (obs["features"][ready], obs["cards"][ready], obs["action_mask"][ready],
                                   p.half().cpu().numpy(), v.float().cpu().numpy())):
                r.append(x)
            stored += len(ready)
        env.step(acts)
        obs = env.observe()
    return [np.concatenate(r) for r in rows], obs


def train_step(net, opt, batch, device, minibatch, amp, vf=0.5):
    f, c, m, p, v = batch
    order = np.random.permutation(len(v))
    stats = {"kl": 0.0, "v": 0.0, "agree": 0.0}
    n = 0
    for s in range(0, len(v), minibatch):
        j = order[s:s + minibatch]
        opt.zero_grad()
        for k in range(0, len(j), CHUNK):  # gradients added up: one step per minibatch
            jj = j[k:k + CHUNK]
            ft, ct, mt = (torch.from_numpy(x[jj]).to(device) for x in (f, c, m))
            pt = torch.from_numpy(p[jj].astype(np.float32)).to(device)
            vt = torch.from_numpy(v[jj]).to(device)
            with torch.autocast(device_type=device.split(":")[0], dtype=torch.bfloat16, enabled=amp):
                logits, value = net(ft, ct, mt)
            logp = torch.log_softmax(logits.float(), 1)
            kl = (pt * (torch.log(pt.clamp(min=1e-8)) - logp)).sum(1).mean()
            vl = (value.float() - vt).pow(2).mean()
            ((kl + vf * vl) * len(jj) / len(j)).backward()
            stats["kl"] += kl.item() * len(jj)
            stats["v"] += vl.item() * len(jj)
            stats["agree"] += (logp.argmax(1) == pt.argmax(1)).float().sum().item()
            n += len(jj)
        torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
        opt.step()
    return {k: round(x / n, 4) for k, x in stats.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teacher", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", default="data/train")
    ap.add_argument("--d", type=int, default=256)
    ap.add_argument("--layers", type=int, default=4)
    ap.add_argument("--heads", type=int, default=8)
    ap.add_argument("--card-dim", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--games", type=int, default=128)
    ap.add_argument("--transitions", type=int, default=65536)
    ap.add_argument("--minibatch", type=int, default=4096)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--hours", type=float, default=2)
    ap.add_argument("--eval-every", type=int, default=20)
    ap.add_argument("--eval-episodes", type=int, default=200)
    ap.add_argument("--amp", action="store_true")
    ap.add_argument("--resume")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--gpu-memory", type=float, default=0.3)
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

    teacher, tck = load(a.teacher, a.device)
    it, best = 0, 9.0
    if a.resume:
        net, ck = load(a.resume, a.device)
        it, best = ck.get("iteration", 0), ck.get("best", 9.0)
    else:
        net = make({"arch": "entity", "card_dim": a.card_dim, "d": a.d, "layers": a.layers,
                    "heads": a.heads}).to(a.device)
    net.train()
    opt = torch.optim.Adam(net.parameters(), lr=a.lr)
    env = BatchEnv(a.games, seed=77_000_003 + it, controlled=list(range(8)), config=CONFIG,
                   threads=a.threads)
    obs = env.observe()
    log({"start": a.run, "distill": a.teacher, "teacher": tck.get("source"),
         "params": sum(p.numel() for p in net.parameters())})
    while time.time() - t0 < a.hours * 3600:
        wait_while_playing(log)
        it += 1
        ts = time.time()
        batch, obs = collect(env, obs, teacher, a.transitions, a.device)
        tc = time.time() - ts
        stats = train_step(net, opt, batch, a.device, a.minibatch, a.amp)
        row = {"iteration": it, "batch": len(batch[4]), "collect_s": round(tc, 1),
               "update_s": round(time.time() - ts - tc, 1), **stats}
        if it % a.eval_every == 0:
            net.eval()
            row["eval"] = evaluate(net, a.device, a.eval_episodes, threads=a.threads)
            vs = evaluate_league(net, [teacher], a.device, a.eval_episodes, threads=a.threads)
            vs.pop("pool", None)
            row["vs_teacher"] = vs
            net.train()
            if vs["mean_place"] < best:
                best = vs["mean_place"]
                save(net, out / "best.pt", {"iteration": it, "best": best, "distilled": a.teacher})
        save(net, out / "last.pt", {"iteration": it, "best": best, "distilled": a.teacher,
                                    "opt": opt.state_dict()})
        log(row)


if __name__ == "__main__":
    main()
