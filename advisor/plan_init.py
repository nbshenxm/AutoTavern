"""A checkpoint made plan-conditioned (plan1, Nov 7) without changing what it plays: the network gets a
plan embedding (EntityNet plans=N_PLANS: none, or a tribe the game is committed to), zero at first,
and optionally growth heads (aux=2: the warband's log growth 2 and 4 rounds on, advisor.aux_probe).
Every plan then plays exactly as the source: checked on real decisions with random plans before it
is saved; marked "adapted" so a resumed run starts a fresh optimizer.

    python -X utf8 -m advisor.plan_init data/train/main1/last.pt data/models/archive/plan1_start.pt --aux 2
"""

import argparse

import numpy as np
import torch

from advisor.policy import N_PLANS, load, make, save


@torch.no_grad()
def check(net, planned, n=256, seed=3):
    """The largest logit and value difference over `n` real decisions, each with a random plan."""
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
            p = torch.from_numpy(rng.integers(0, N_PLANS, len(ready)))
            l1, v1 = net(f, c, m)
            l2, v2 = planned(f, c, m, plan=p)
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
    ap.add_argument("--aux", type=int, default=0, help="growth heads (2: 2 and 4 rounds on)")
    ap.add_argument("--cards", action="store_true", help="plan2: the plan marked on its tribe's cards too")
    a = ap.parse_args()
    torch.manual_seed(0)
    net, ck = load(a.src, "cpu")
    planned = make({**net.config, "plans": N_PLANS, **({"aux": a.aux} if a.aux else {}),
                    **({"plan_cards": True} if a.cards else {})})
    missing, unexpected = planned.load_state_dict(net.state_dict(), strict=False)
    if unexpected or any(not k.startswith(("plan_emb.", "plan_card", "aux.")) for k in missing):
        raise SystemExit(f"weights don't fit: {missing} {unexpected}")
    planned.eval()
    dl, dv, n = check(net.eval(), planned)
    print(f"over {n} decisions with random plans: the largest logit difference {dl:.2e}, value {dv:.2e}")
    if dl > 1e-4 or dv > 1e-4:
        raise SystemExit("the planned network doesn't play as the source: not saved")
    extra = {k: v for k, v in ck.items() if k not in ("config", "state", "obs", "opt")}
    save(planned, a.dst, {**extra, "adapted": "plans" + (" + cards" if a.cards else "") + (f" + aux {a.aux}" if a.aux else ""),
                          "source": f"{a.src} (iteration {ck.get('iteration')}), plan-conditioned"})
    print("saved", a.dst)


if __name__ == "__main__":
    main()
