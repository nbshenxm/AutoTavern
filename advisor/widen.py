"""Grow a checkpoint's feed-forward layers (ffn x d per layer, 2 until Nov 5) without changing what it
plays: the new units get the usual random input weights and zero output weights, so the wider
network computes exactly the old one's outputs and training grows into the room (Net2Net style).
AutoTavern's 18M network has the same trunk as ours (d 384, 8 layers, 8 heads) with the usual 4 x d;
ours has 2 x d (11M). Checked here on real observations before it is saved; marked "adapted" so a
resumed run starts a fresh optimizer (the old Adam state has the old shapes).

    python -X utf8 -m advisor.widen data/train/main1/last.pt data/models/archive/wide_start.pt --ffn 4
"""

import argparse

import numpy as np
import torch

from advisor.policy import load, make, save


@torch.no_grad()
def widen(net, ffn):
    cfg = dict(net.config)
    old = cfg.get("ffn", 2)
    if ffn <= old:
        raise SystemExit(f"already ffn {old}")
    wide = make({**cfg, "ffn": ffn})
    state = net.state_dict()
    new = wide.state_dict()
    for k, v in new.items():
        src = state[k]
        if src.shape == v.shape:
            new[k] = src.clone()
        elif k.endswith("linear1.weight"):  # (ffn*d, d): old rows, the rest random (as built)
            new[k][:src.shape[0]] = src
        elif k.endswith("linear1.bias"):
            new[k][:src.shape[0]] = src
        elif k.endswith("linear2.weight"):  # (d, ffn*d): old columns, the rest zero
            new[k].zero_()
            new[k][:, :src.shape[1]] = src
        else:
            raise SystemExit(f"unexpected shape change: {k} {tuple(src.shape)} -> {tuple(v.shape)}")
    wide.load_state_dict(new)
    return wide


@torch.no_grad()
def check(net, wide, n=256, seed=3):
    """The largest difference in logits and value over `n` real decisions."""
    from advisor.train import CONFIG, BatchEnv
    env = BatchEnv(8, seed=seed, controlled=list(range(8)), config=CONFIG, threads=1)
    rng = np.random.default_rng(seed)
    obs = env.observe()
    worst_l = worst_v = 0.0
    seen = 0
    while seen < n:
        ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
        if len(ready):
            f = torch.from_numpy(obs["features"][ready])
            c = torch.from_numpy(obs["cards"][ready])
            m = torch.from_numpy(obs["action_mask"][ready])
            l1, v1 = net(f, c, m)
            l2, v2 = wide(f, c, m)
            ok = m.bool()
            worst_l = max(worst_l, float((l1 - l2)[ok].abs().max()))
            worst_v = max(worst_v, float((v1 - v2).abs().max()))
            seen += len(ready)
        a = np.zeros(env.n_slots, dtype=np.int64)
        for i in ready:
            a[i] = rng.choice(np.flatnonzero(obs["action_mask"][i]))
        env.step(a)
        obs = env.observe()
    return worst_l, worst_v, seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--ffn", type=int, default=4)
    a = ap.parse_args()
    torch.manual_seed(0)
    net, ck = load(a.src, "cpu")
    net.eval()
    wide = widen(net, a.ffn).eval()
    dl, dv, n = check(net, wide)
    p0 = sum(p.numel() for p in net.parameters())
    p1 = sum(p.numel() for p in wide.parameters())
    print(f"params {p0:,} -> {p1:,}; over {n} decisions the largest logit difference {dl:.2e}, value {dv:.2e}")
    if dl > 1e-3 or dv > 1e-3:
        raise SystemExit("the wider network doesn't play as the old one: not saved")
    extra = {k: v for k, v in ck.items() if k not in ("config", "state", "obs", "opt")}
    save(wide, a.dst, {**extra, "adapted": f"widened ffn {net.config.get('ffn', 2)} -> {a.ffn}",
                       "source": f"{a.src} (iteration {ck.get('iteration')}), widened"})
    print("saved", a.dst)


if __name__ == "__main__":
    main()
