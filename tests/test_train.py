"""advisor.train: per-seat advantages and a tiny end-to-end PPO step."""

import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advisor import train  # noqa: E402
from advisor.policy import EntityNet, PolicyNet  # noqa: E402


def item(v, r=0.0, done=False):
    # [features, cards, mask, action, logp, value, reward, done]
    return [None, None, None, 0, 0.0, v, r, done]


def test_advantages_bootstrap_and_carry_over():
    s = train.Seat()
    # one finished episode (reward 1 at its end), then the next episode's first two steps
    s.items = [item(0.5), item(0.5, 1.0, True), item(0.2), item(0.3)]
    batch = train.advantages([s], gamma=1.0, lam=1.0)
    returns = [ret for _, ret, _ in batch]
    # the finished episode returns its reward; the unfinished step bootstraps from the next
    # step's value, and that last step waits for the next rollout
    assert returns == pytest.approx([1.0, 1.0, 0.3])
    assert len(s.items) == 1 and s.items[0][5] == 0.3


def test_one_ppo_iteration_runs():
    from taverngym import BatchEnv

    net = PolicyNet(card_dim=4, hidden=64)
    env = BatchEnv(2, seed=3, controlled=list(range(8)), config=train.CONFIG)
    seats = [train.Seat() for _ in range(env.n_slots)]
    obs, _ = train.collect(env, net, env.observe(), seats, 256, "cpu")
    batch = train.advantages(seats, 0.995, 0.95)
    assert batch
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    stats = train.update(net, opt, batch, "cpu", epochs=1, minibatch=128)
    assert all(abs(v) < 1e6 for v in stats.values())


def test_league_gate_and_opponent_seats():
    from taverngym import BatchEnv

    small = lambda: PolicyNet(card_dim=4, hidden=64).eval()
    pool = [small(), small()]
    ev = train.evaluate_league(small(), pool, "cpu", episodes=4, games=2, threads=1)
    assert ev["n"] == 4 and 1 <= ev["mean_place"] <= 8
    env = BatchEnv(2, seed=4, controlled=list(range(8)), config=train.CONFIG)
    opp = train.assign_opponents(env, pool, it=3)
    assert sorted(opp) == [6, 7, 14, 15]
    seats = [train.Seat() for _ in range(env.n_slots)]
    train.collect(env, small(), env.observe(), seats, 128, "cpu", opp)
    assert all(not seats[i].items for i in opp)  # frozen seats aren't learned from


def test_entity_network_trains_a_step():
    from taverngym import BatchEnv

    net = EntityNet(card_dim=8, d=32, layers=1, heads=2)
    env = BatchEnv(2, seed=5, controlled=list(range(8)), config=train.CONFIG)
    seats = [train.Seat() for _ in range(env.n_slots)]
    train.collect(env, net, env.observe(), seats, 256, "cpu")
    batch = train.advantages(seats, 0.995, 0.95)
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    stats = train.update(net, opt, batch, "cpu", epochs=1, minibatch=128)
    assert all(abs(v) < 1e6 for v in stats.values())
