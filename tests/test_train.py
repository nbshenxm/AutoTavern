"""advisor.train: per-seat advantages and a tiny end-to-end PPO step."""

import os
import sys
from pathlib import Path

import numpy as np

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


def test_wasted_gold():
    # Ending the turn with gold and a legal Refresh or buy costs reward (frozen or not); nothing
    # to spend it on, or any other action, costs nothing
    f = np.zeros((1, 64), np.float32)
    m = np.zeros((1, 245), bool)
    f[0, train.F_GOLD], m[0, train.A_REFRESH] = 0.4, True
    obs = {"features": f, "action_mask": m}
    assert train.wasted_gold(obs, 0, train.A_END) == pytest.approx(4 * train.WASTED_GOLD)
    assert train.wasted_gold(obs, 0, train.A_REFRESH) == 0.0
    f[0, train.F_FROZEN] = 1.0  # frozen: the Gold is still left on the table
    assert train.wasted_gold(obs, 0, train.A_END) == pytest.approx(4 * train.WASTED_GOLD)
    m[0, train.A_REFRESH] = False  # nothing to spend it on: no cost
    assert train.wasted_gold(obs, 0, train.A_END) == 0.0
    m[0, train.A_BUY + 2] = True
    assert train.wasted_gold(obs, 0, train.A_END) == pytest.approx(4 * train.WASTED_GOLD)


def test_value_warmup_with_an_anchor_keeps_the_policy():
    from taverngym import BatchEnv

    torch.manual_seed(0)
    net = EntityNet(card_dim=8, d=32, layers=1, heads=2)
    anchor = EntityNet(card_dim=8, d=32, layers=1, heads=2)
    anchor.load_state_dict(net.state_dict())
    env = BatchEnv(2, seed=6, controlled=list(range(8)), config=train.CONFIG)
    seats = [train.Seat() for _ in range(env.n_slots)]
    train.collect(env, net, env.observe(), seats, 256, "cpu")
    batch = train.advantages(seats, 0.995, 0.95)
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    stats = train.update(net, opt, batch, "cpu", epochs=1, minibatch=128, value_only=True,
                         anchor=anchor, anchor_coef=1.0)
    assert all(abs(v) < 1e6 for v in stats.values())


def test_pretrain_learns_the_teachers_actions():
    from advisor import pretrain
    from taverngym import BatchEnv

    pytest.importorskip("taverngym").BatchEnv.bot_actions  # a module with the teacher
    torch.manual_seed(0)
    net = EntityNet(card_dim=8, d=32, layers=1, heads=2)
    env = BatchEnv(2, seed=7, controlled=list(range(8)), config=pretrain.TEACHER_CONFIG)
    batch, _ = pretrain.collect(env, env.observe(), 512)
    f, c, m, a = batch
    assert len(a) >= 512 and m[np.arange(len(a)), a].all(), "the teacher's actions are legal"
    opt = torch.optim.Adam(net.parameters(), lr=3e-3)
    first = pretrain.train_step(net, opt, batch, "cpu", 256, False)
    for _ in range(5):
        last = pretrain.train_step(net, opt, batch, "cpu", 256, False)
    assert last["loss"] < first["loss"]


def test_generation_opponents(tmp_path):
    # Seats 4-6 of every game play the frozen best, seat 7 an archived one; reloaded on a change
    from taverngym import BatchEnv

    models = tmp_path / "models"
    net = EntityNet(card_dim=8, d=32, layers=1, heads=2)
    train.save(net, models / "best.pt")
    train.save(net, models / "archive" / "best_1.pt")
    gen = train.Generation("cpu", models)
    rows = []
    assert gen.refresh(rows.append) and not gen.refresh(rows.append)
    env = BatchEnv(2, seed=8, controlled=list(range(8)), config=train.CONFIG)
    opp = gen.assign(env, 1, [])
    assert sorted(opp) == [4, 5, 6, 7, 12, 13, 14, 15]
    assert opp[4] is gen.best and opp[7] is gen.past[0]
    seats = [train.Seat() for _ in range(env.n_slots)]
    _, placements = train.collect(env, gen.best, env.observe(), seats, 256, "cpu", opp)
    assert not any(seats[i].items for i in opp), "the frozen seats aren't learned from"


def test_search_targets_flow_into_ppo(tmp_path):
    # Searched decisions go to shards, the buffer reads the newest, and an update learns them
    from advisor import search_games
    from taverngym import BatchEnv

    torch.manual_seed(0)
    net = EntityNet(card_dim=8, d=32, layers=1, heads=2)
    env = BatchEnv(2, seed=9, controlled=list(range(8)), config=train.CONFIG)
    seats = [train.Seat() for _ in range(env.n_slots)]
    train.collect(env, net, env.observe(), seats, 256, "cpu")
    items = [it for s in seats for it in s.items]
    rows = [(f, c, m.astype(bool), int(np.flatnonzero(m)[-1])) for f, c, m, *_ in items[:300]]
    assert len(rows) >= 250
    old = search_games.write_shard(tmp_path, rows[:80])
    os.utime(old, (1, 1))  # older
    search_games.write_shard(tmp_path, rows[80:])
    buf = search_games.SearchBuffer([tmp_path], 150)
    assert buf.refresh() and len(buf) == len(rows) - 80 and not buf.refresh(), "the newest covers 150"
    f, c, m, a = buf.sample(64, np.random.default_rng(0))
    assert m[np.arange(64), a].all() and f.dtype == np.float32
    batch = train.advantages(seats, 0.995, 0.95)
    opt = torch.optim.Adam(net.parameters(), lr=3e-3)
    first = train.update(net, opt, batch, "cpu", epochs=1, minibatch=128, search=buf, search_coef=1.0)
    for _ in range(4):
        last = train.update(net, opt, batch, "cpu", epochs=1, minibatch=128, search=buf,
                            search_coef=1.0)
    assert last["search_ce"] < first["search_ce"]


def test_a_non_finite_batch_skips_the_step(tmp_path):
    # Searched decisions with an infinite feature: the step is skipped, the network stays finite
    from advisor import search_games
    from taverngym import BatchEnv

    torch.manual_seed(0)
    net = EntityNet(card_dim=8, d=32, layers=1, heads=2)
    env = BatchEnv(2, seed=10, controlled=list(range(8)), config=train.CONFIG)
    seats = [train.Seat() for _ in range(env.n_slots)]
    train.collect(env, net, env.observe(), seats, 256, "cpu")
    items = [it for s in seats for it in s.items][:64]
    rows = [(f.copy(), c, m.astype(bool), int(np.flatnonzero(m)[-1])) for f, c, m, *_ in items]
    rows[0][0][7] = 1e6  # clipped on write
    search_games.write_shard(tmp_path, rows)
    buf = search_games.SearchBuffer([tmp_path], 100)
    buf.refresh()
    assert np.isfinite(buf.data[0]).all() and len(buf) == 64
    buf.data[0][:] = np.inf  # as an unclipped old shard would be after loading
    batch = train.advantages(seats, 0.995, 0.95)
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    stats = train.update(net, opt, batch, "cpu", epochs=1, minibatch=128, search=buf, search_coef=1.0)
    assert stats["skipped"] >= 1
    assert all(torch.isfinite(p).all() for p in net.parameters())


def test_library_seats_fight_with_real_warbands(tmp_path):
    # A library seat's warband at combat is one of the library's boards of that round
    import json as _json

    import taverngym
    from advisor import library

    g = taverngym.Game(1, _json.dumps(train.CONFIG))
    for _ in range(200):
        for s in range(8):
            if g.needs_action(s):
                g.step(s, g.bot_action(s))
    st = _json.loads(g.state_json())
    template = next(m for p in st["players"] for m in p["board"])
    boards = []
    for rnd in range(1, 30):
        m = {**template, "atk": 100 + rnd, "hp": 200 + rnd}
        boards.append({"round": rnd, "tier": 3, "minions": [m, dict(m)]})
    path = tmp_path / "boards.json"
    path.write_text(_json.dumps(boards))
    cfg = {**train.CONFIG, "library": library.library([7], path)}
    g = taverngym.Game(2, _json.dumps(cfg))
    while not g.is_over() and g.turn < 6:
        for s in range(8):
            if g.needs_action(s):
                g.step(s, g.bot_action(s))
    p7 = _json.loads(g.state_json())["players"][7]
    seen = [(m["atk"], m["hp"]) for m in p7["last_board"]]
    assert seen and all(a - 100 == h - 200 and 1 <= a - 100 <= g.turn for a, h in seen), seen
    assert p7["tier"] == 3


def test_an_older_layouts_network_plays_the_same():
    # adapt() gives a network built for observation layout 1 zero weights for layout 2's inputs:
    # its outputs can't depend on them (so it computes what it did), and the inserted columns
    # sit exactly where obs.rs appends them
    from advisor import policy
    from taverngym import BatchEnv

    L = policy.L
    torch.manual_seed(0)
    net = EntityNet(card_dim=8, d=32, layers=1, heads=2)
    new = policy.OBS_LAYOUT
    old = policy.V1_LAYOUT
    # Back to layout 1: drop the columns layout 2 added, then adapt them back in
    state = {k: v.clone() for k, v in net.state_dict().items()}
    cut = lambda w, cols: torch.cat([w[:, i:i + 1] for i in range(w.shape[1]) if i not in cols], 1)
    gm, gi, gg, go = (new[k] - old[k] for k in ("MINION_F", "ITEM_F", "GLOBAL_F", "OPP_F"))
    state["glob.weight"] = cut(state["glob.weight"], set(range(old["GLOBAL_F"], new["GLOBAL_F"])))
    for name, extra in (("board", gm), ("oppb", gm), ("hand", gi), ("shop", gi), ("choice", gi),
                        ("opp", go)):
        w = state[f"proj.{name}.weight"]
        state[f"proj.{name}.weight"] = cut(w, set(range(w.shape[1] - extra, w.shape[1])))
    policy.adapt(state, old)
    net.load_state_dict(state, strict=False)
    net.eval()
    env = BatchEnv(1, seed=11, controlled=list(range(8)), config=train.CONFIG)
    for _ in range(60):  # into the game: board, hand, opponents seen
        o = env.observe()
        env.step(np.array([int(np.flatnonzero(m)[0]) if r else 0
                           for m, r in zip(o["action_mask"], o["ready"])]))
    o = env.observe()
    f, c, m = (torch.from_numpy(o[k]) for k in ("features", "cards", "action_mask"))
    # Layout 2's positions: the global additions, and the last float(s) of every occupied slot
    # (an empty slot's are zero, as obs.rs writes them: the network tells empty slots by it)
    g = f.clone()
    g[:, old["GLOBAL_F"]:new["GLOBAL_F"]] = torch.randn(g.shape[0], gg) * 5
    at = policy.GLOBAL_ALL
    for name, n, k in policy.FLOAT_BLOCKS:
        extra = {"board": gm, "oppb": gm, "opp": go}.get(name, gi)
        for s in range(n):
            lo = at + s * k
            occupied = f[:, lo:lo + k].abs().sum(1) > 0
            for e in range(extra):
                g[occupied, lo + k - 1 - e] = torch.randn(int(occupied.sum())) * 5
        at += n * k
    with torch.no_grad():
        (a, va), (b, vb) = net(f, c, m), net(g, c, m)
    assert torch.allclose(a, b, atol=1e-5) and torch.allclose(va, vb, atol=1e-5)
    assert at == L["OBS_FLOATS"]


def test_the_trinket_prior_prefers_the_publicly_better_trinket():
    # At a trinket offer the target favors the option with the lower public average placement
    import json as _json

    import taverngym
    from advisor import meta

    stats = meta.trinket_stats()
    if not stats:
        pytest.skip("no public trinket stats here")
    g = taverngym.Game(4, _json.dumps(train.CONFIG))
    for _ in range(5000):
        v = _json.loads(g.view(0))
        if (v["me"]["pending"] or {}).get("kind") == "trinket":
            break
        for s in range(8):
            if g.needs_action(s):
                g.step(s, g.bot_action(s))
    else:
        pytest.skip("no trinket offer")
    from advisor.policy import observe
    f, c, m = (torch.from_numpy(x)[None] for x in observe(g, 0))
    prior = train.TrinketPrior("cpu")
    rows, target = prior.targets(f, c, m)
    opts = [o["id"] for o in v["me"]["pending"]["options"]]
    best = min((i for i, o in enumerate(opts) if o in stats and m[0, prior.a + i]),
               key=lambda i: stats[opts[i]]["place"])
    assert rows.tolist() == [0] and int(target[0].argmax()) == best
    logits = torch.zeros(1, m.shape[1]).masked_fill(~m, -1e9)
    ce, n = prior.loss(f, c, m, logits)
    assert n == 1 and ce > 0


def test_real_starts_replace_new_games(tmp_path):
    # A game that begins anew starts from a stored position (a round-5 lobby with one player
    # out) with the run's rules; it plays to the end and the survivors take places 1-7
    import json as _json

    import taverngym

    g = taverngym.Game(4, _json.dumps(train.CONFIG))
    while g.turn < 5:
        for s in range(8):
            if g.needs_action(s):
                g.step(s, g.bot_action(s))
    st = _json.loads(g.state_json())
    st["players"][3].update(alive=False, placement=8, health=0)
    st["eliminated"] = [3]
    rs = train.RealStarts(1.0, 0, path=tmp_path / "none.jsonl", log=lambda r: None)
    rs.states, rs.weights = [st], np.array([1.0])
    env = train.BatchEnv(2, seed=9, controlled=list(range(8)), config=train.CONFIG, threads=1)
    assert rs.apply(env) == 0  # the first call only notes where the games are
    rs.seen = [-1, -1]
    assert rs.apply(env) == 2
    loaded = _json.loads(env.save(0))
    assert loaded["game"]["turn"] == 5 and loaded["finished"][3]
    rng = np.random.default_rng(0)
    places = []
    obs = env.observe()
    while env.episode_index(0) == 0:
        acts = np.array([rng.choice(np.flatnonzero(m)) if m.any() else 0 for m in obs["action_mask"]])
        _, done, info = env.step(acts)
        places += [int(info["placement"][j]) for j in np.flatnonzero(done) if j < 8]
        obs = env.observe()
    assert sorted(places) == list(range(1, 8))


def test_evaluate_real_plays_each_start_once():
    import json as _json

    import taverngym

    g = taverngym.Game(5, _json.dumps(train.CONFIG))
    while g.turn < 4:
        for s in range(8):
            if g.needs_action(s):
                g.step(s, g.bot_action(s))
    st = _json.loads(g.state_json())
    net = EntityNet()
    r = train.evaluate_real(net, net, [st, st, st], "cpu", games=2, threads=1)
    assert r["n"] == 3 and 1 <= r["mean_place"] <= 8


def test_the_real_positions_promotion_pair(monkeypatch):
    import json as _json

    import taverngym
    from advisor import promote

    g = taverngym.Game(6, _json.dumps(train.CONFIG))
    while g.turn < 4:
        for s in range(8):
            if g.needs_action(s):
                g.step(s, g.bot_action(s))
    st = _json.loads(g.state_json())

    class Starts:
        def __init__(self, *a, **k):
            self.states = self.real = [st, st]

    monkeypatch.setattr(promote, "RealStarts", Starts)
    monkeypatch.setitem(promote.REAL, "reps", 2)
    net = EntityNet()
    r = promote.real_pair(net, net, "cpu", 1, 47_000_000)
    # the same network on the same seeds: the very same games
    assert r["n"] == 4 and r["diff"] == 0 and not promote.real_better(r)


def test_a_library_seat_follows_one_player(tmp_path):
    # Boards of two tracks (Attack = 100 * track + round): a library seat's warband comes from
    # one track all game, the latest round up to the current one, grown by the curve in between
    import json as _json

    import taverngym
    from advisor import library

    g = taverngym.Game(1, _json.dumps(train.CONFIG))
    for _ in range(200):
        for s in range(8):
            if g.needs_action(s):
                g.step(s, g.bot_action(s))
    template = next(m for p in _json.loads(g.state_json())["players"] for m in p["board"])
    boards = []
    for track in (1, 2):
        for rnd in range(1, 30, 2):  # seen every other round
            m = {**template, "atk": 100 * track + rnd, "hp": 1000, "max_hp": 1000}
            boards.append({"round": rnd, "tier": 3, "minions": [m], "track": f"t{track}"})
    path = tmp_path / "boards.json"
    path.write_text(_json.dumps(boards))
    lib = library.library([7], path, strength=0, curve={r: 100.0 * 2 ** r for r in range(40)})
    cfg = {**train.CONFIG, "library": lib}
    g = taverngym.Game(2, _json.dumps(cfg))
    seen = []
    while not g.is_over() and g.turn < 9:
        turn = g.turn
        for s in range(8):
            if g.needs_action(s):
                g.step(s, g.bot_action(s))
        p7 = _json.loads(g.state_json())["players"][7]
        if p7["last_board"] and g.turn != turn:
            seen.append((turn, p7["last_board"][0]["atk"], p7["last_board"][0]["hp"]))
    tracks = {a // 100 for _, a, h in seen if h == 1000}
    assert seen and len(tracks) <= 1, seen
    # an even round shows the odd round before it, its Health doubled by the curve
    assert any(h == 2000 for _, _, h in seen), seen


def test_a_version_2_network_ignores_opponent_trinkets_and_triples():
    # Loaded under version 3, a network saved for version 2 has zero weights for the opponents'
    # triples and trinkets: its output doesn't depend on them
    import json as _json

    import taverngym
    from advisor import policy

    net = EntityNet()
    st = policy.adapt  # noqa: F841 (the path under test is policy.load)
    old = net.state_dict()
    old = {k: v for k, v in old.items() if not k.startswith(("opp_trinket.", "trinket_count."))}
    w = old["proj.opp.weight"]
    old["proj.opp.weight"] = w[:, :-1]  # as saved under OPP_F 10
    gw = old["glob.weight"]  # and without version 4's global floats
    old["glob.weight"] = torch.cat([gw[:, :policy.V4_AT], gw[:, policy.V4_AT + policy.V4_F:]], 1)
    path = Path(__import__("tempfile").mkdtemp()) / "v2.pt"
    torch.save({"config": net.config, "state": old, "obs": policy.V2_LAYOUT}, path)
    loaded, ck = policy.load(path)
    assert ck["adapted"] == policy.V2_LAYOUT
    g = taverngym.Game(3, _json.dumps(train.CONFIG))
    while g.turn < 3:
        for s in range(8):
            if g.needs_action(s):
                g.step(s, g.bot_action(s))
    f, c, m = policy.observe(g, 0)
    f2, c2 = f.copy(), c.copy()
    at = policy.GLOBAL_ALL + sum(n * k for _, n, k in policy.FLOAT_BLOCKS[:4])
    for i in range(policy.N_OPP):
        f2[at + i * policy.OPP_F + policy.OPP_F - 1] = 0.6  # 3 triples
    c2[-policy.N_OPP * policy.N_OPP_TRINKETS:] = 5
    with torch.no_grad():
        a = loaded(*(torch.from_numpy(x)[None] for x in (f, c, m)))
        b = loaded(*(torch.from_numpy(x)[None] for x in (f2, c2, m)))
    assert torch.allclose(a[0], b[0]) and torch.allclose(a[1], b[1])


def test_version_2_shards_are_widened():
    from advisor import policy

    n, v4, at4 = 3, policy.V4_F, policy.V4_AT
    f = np.random.rand(n, policy.OBS_FLOATS - v4 - policy.N_OPP).astype(np.float16)
    c = np.ones((n, policy.OBS_CARDS - policy.N_OPP * policy.N_OPP_TRINKETS), np.int32)
    f3, c3 = policy.widen_obs(f, c)
    assert f3.shape[1] == policy.OBS_FLOATS and c3.shape[1] == policy.OBS_CARDS
    at = policy.GLOBAL_ALL + sum(k * m for _, k, m in policy.FLOAT_BLOCKS[:4])
    old = policy.OPP_F - 1
    assert np.array_equal(f3[:, :at4], f[:, :at4]) and (f3[:, at4:at4 + v4] == 0).all()
    assert np.array_equal(f3[:, at4 + v4:at], f[:, at4:at - v4])
    assert (f3[:, at + old] == 0).all() and np.array_equal(f3[:, at:at + old], f[:, at - v4:at - v4 + old])
    assert np.array_equal(f3[:, at + policy.N_OPP * policy.OPP_F:], f[:, at - v4 + policy.N_OPP * old:])


def test_version_3_shards_are_widened():
    # Version 4's global floats (what the player's cards count) come in as zeros
    from advisor import policy

    f = np.random.rand(3, policy.OBS_FLOATS - policy.V4_F).astype(np.float16)
    c = np.ones((3, policy.OBS_CARDS), np.int32)
    f4, c4 = policy.widen_obs(f, c)
    at, v4 = policy.V4_AT, policy.V4_F
    assert f4.shape[1] == policy.OBS_FLOATS and np.array_equal(c4, c)
    assert np.array_equal(f4[:, :at], f[:, :at]) and (f4[:, at:at + v4] == 0).all()
    assert np.array_equal(f4[:, at + v4:], f[:, at:])


def test_a_version_3_network_ignores_what_the_cards_count():
    # Loaded under version 4 (and the card table's text columns), a network saved for version
    # 3 has zero weights for the new numbers: its output doesn't depend on them
    import json as _json

    import taverngym
    from advisor import policy

    net = EntityNet()
    old = {k: v for k, v in net.state_dict().items() if not k.startswith("trinket_count.")}
    gw = old["glob.weight"]
    old["glob.weight"] = torch.cat([gw[:, :policy.V4_AT], gw[:, policy.V4_AT + policy.V4_F:]], 1)
    n_text = len(policy.CARD_TEXT) + len(policy.CARD_TEXT_RACES) + 2
    old["card_proj.weight"] = old["card_proj.weight"][:, :-n_text]
    path = Path(__import__("tempfile").mkdtemp()) / "v3.pt"
    torch.save({"config": net.config, "state": old, "obs": policy.V3_LAYOUT}, path)
    loaded, ck = policy.load(path)
    assert ck["adapted"] == policy.V3_LAYOUT
    g = taverngym.Game(4, _json.dumps(train.CONFIG))
    while g.turn < 3:
        for s in range(8):
            if g.needs_action(s):
                g.step(s, g.bot_action(s))
    f, c, m = policy.observe(g, 0)
    f2 = f.copy()
    f2[policy.V4_AT:policy.V4_AT + policy.V4_F] = 0.5
    with torch.no_grad():
        a = loaded(*(torch.from_numpy(x)[None] for x in (f, c, m)))
        b = loaded(*(torch.from_numpy(x)[None] for x in (f2, c, m)))
    assert torch.allclose(a[0], b[0]) and torch.allclose(a[1], b[1])


def test_comp_starts_play_the_comp_in_its_lobby():
    import json as _json

    import taverngym
    from advisor import library

    sts = library.comp_starts(rounds=range(8, 9))
    assert sts
    for st in sts[:5]:
        g = taverngym.Game.from_json(_json.dumps(st))
        v = _json.loads(g.view(0))
        assert g.needs_action(0) and v["turn"] == 8 and len(v["me"]["board"]) >= 4
        assert set(st["cfg"]["lobby_types"]) <= set(v["lobby_races"]) if isinstance(v["lobby_races"], list) else True


def test_human_choices_flow_into_ppo(tmp_path):
    # The player's logged choices (advisor.human_data's shard format) add a cross-entropy beside
    # PPO, and the held-out agreement is measured
    from advisor import search_games
    from advisor.policy import OBS_CARDS, OBS_FLOATS

    rows = []
    rng = np.random.default_rng(1)
    for _ in range(40):
        m = np.zeros(245, bool)
        m[[0, 1, 8]] = True
        rows.append((rng.random(OBS_FLOATS).astype(np.float32), np.zeros(OBS_CARDS, np.int32), m, 1))
    search_games.write_shard(tmp_path, rows)
    buf = search_games.SearchBuffer([tmp_path], 1000)
    assert buf.refresh() and len(buf) == 40 and len(buf.all()[3]) == 40
    net = EntityNet()
    agree = train.human_agreement(net, buf, "cpu")
    assert agree["n"] == 40 and 0 <= agree["all"] <= 1



def test_the_search_data_can_leave_out_idle_end_turns(tmp_path):
    # --search-drop-idle: the search's End Turns with 3+ Gold while a Refresh is legal are left
    # out; with 2 Gold, or with nothing to spend on, they stay, and so do other choices
    from advisor import search_games
    from advisor.policy import OBS_CARDS, OBS_FLOATS

    rows = []
    for gold, refresh, a in ((5, True, train.A_END), (2, True, train.A_END), (5, False, train.A_END),
                             (5, True, train.A_REFRESH)):
        f = np.zeros(OBS_FLOATS, np.float32)
        f[train.F_GOLD] = gold / 10
        m = np.zeros(245, bool)
        m[[train.A_END, train.A_FREEZE]] = True
        m[train.A_REFRESH] = refresh
        rows.append((f, np.zeros(OBS_CARDS, np.int32), m, a))
    search_games.write_shard(tmp_path, rows)
    kept = search_games.SearchBuffer([tmp_path], 1000)
    kept.refresh()
    idle = search_games.SearchBuffer([tmp_path], 1000, drop_idle=True)
    idle.refresh()
    assert len(kept) == 4 and len(idle) == 3 and idle.dropped == 1
    assert sorted(np.round(idle.data[0][:, train.F_GOLD].astype(np.float32) * 10)) == [2, 5, 5]

def test_the_play_audit_fails_a_clearly_worse_candidate():
    from advisor import audit_play

    cur = {"detour": 0.0, "end_with_gold": 0.1, "stalled_games": 0, "freeze_share": 0.05, "samples": []}
    assert audit_play.check({**cur, "end_with_gold": 0.15}, cur) == {}
    worse = audit_play.check({**cur, "end_with_gold": 0.3, "stalled_games": 1}, cur)
    assert set(worse) == {"end_with_gold", "stalled_games"}


def test_forced_exploration_steps_are_left_out_of_the_policy_loss():
    # A batch of forced steps only: the policy loss is zero (their ratio means nothing); the value
    # still learns from them
    net = EntityNet()
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    env = train.BatchEnv(2, seed=3, controlled=list(range(8)), config=train.CONFIG, threads=1)
    obs = env.observe()
    seats = [train.Seat() for _ in range(env.n_slots)]
    obs, _ = train.collect(env, net, obs, seats, 64, "cpu", explore=(1.0, 0.0))
    for s in seats:
        for it in s.items:
            it[8] = True
            it[7] = True
    batch = train.advantages(seats, 0.99, 0.95)
    stats = train.update(net, opt, batch, "cpu", epochs=1, minibatch=64)
    assert stats["pi"] == 0.0 and stats["v"] > 0


def test_a_blind_control_never_sees_version_4():
    # --blind-v4: even with weights for them, the network's output doesn't depend on version
    # 4's numbers nor on the card table's text columns
    from advisor import policy

    torch.manual_seed(0)
    net = policy.EntityNet(blind_v4=True)
    with torch.no_grad():
        for p in net.parameters():
            p.add_(torch.randn_like(p) * 0.1)
    assert not net.card_table[:, policy.CARD_F - policy.CARD_TEXT_F:].any()
    f = torch.rand(1, policy.OBS_FLOATS)
    c = torch.randint(1, policy.N_CARDS, (1, policy.OBS_CARDS))
    m = torch.ones(1, policy.L["N_ACTIONS"], dtype=torch.bool)
    f2 = f.clone()
    f2[:, policy.V4_AT:policy.V4_AT + policy.V4_F] = 3.0
    with torch.no_grad():
        a, b = net(f, c, m), net(f2, c, m)
    assert torch.allclose(a[0], b[0]) and torch.allclose(a[1], b[1])
    assert policy.make(net.config).blind_v4


def test_solo_library_seats_skip_their_recruit_turns():
    # --solo: library seats 1-7 skip recruit (done as soon as a turn starts); the game still
    # ends, with seat 0 the only one acting after the hero picks
    import json as _json

    import taverngym

    board = {"round": 1, "tier": 1, "minions": [], "track": 0}
    cfg = {**train.CONFIG, "library": {"seats": list(range(1, 8)), "boards": [board], "growth": [],
                                       "skip_recruit": True}}
    g = taverngym.Game(5, _json.dumps(cfg))
    acted = set()
    for _ in range(200_000):
        if g.is_over():
            break
        for s in range(8):
            if g.needs_action(s):
                if g.turn >= 1 and _json.loads(g.view(s))["phase"].lower() == "recruit":
                    acted.add(s)
                g.step(s, g.bot_action(s))
    assert g.is_over() and acted == {0}
    # and a logged round start loads into a solo env (one controlled seat)
    env = taverngym.BatchEnv(2, seed=3, controlled=[0], config=cfg)
    st = _json.loads(taverngym.Game(9, _json.dumps(cfg)).state_json())
    train.load_start(env, 0, st)
    assert env.observe()["features"].shape[0] == 2


def test_collect_never_samples_cancel_while_anything_else_is_legal():
    # Cancel undoes a play that asked for a target: played and cancelled in a loop, it burned
    # turns until the action cap ended them without End Turn (solo1 and emb1, Nov 1)
    from taverngym import BatchEnv

    torch.manual_seed(0)
    net = EntityNet(card_dim=8, d=32, layers=1, heads=2)
    with torch.no_grad():  # a network that would pick Cancel whenever it can
        net.global_head.bias[5] = 50.0
    env = BatchEnv(4, seed=11, controlled=list(range(8)), config=train.CONFIG)
    seats = [train.Seat() for _ in range(env.n_slots)]
    train.collect(env, net, env.observe(), seats, 4096, "cpu")
    items = [it for s in seats for it in s.items]
    assert items and not any(it[3] == train.A_CANCEL and it[2].sum() > 1 for it in items)


def test_the_plan_search_masks_cancel():
    import numpy as _np
    from advisor import search
    from advisor.policy import L

    mask = _np.zeros(L["N_ACTIONS"], bool)
    mask[[L["A_END"], L["A_CANCEL"]]] = True
    m = search.detour_mask({"mask": mask.tolist(), "me": {"hand": [], "board": []}}, {})
    assert m is not None and not m[L["A_CANCEL"]] and m[L["A_END"]]
    only = _np.zeros(L["N_ACTIONS"], bool)
    only[L["A_CANCEL"]] = True  # nothing else legal: left as it is
    assert search.detour_mask({"mask": only.tolist(), "me": {"hand": [], "board": []}}, {}) is None




def test_a_card_lost_to_a_full_hand_costs_its_penalty():
    # card_lost_penalty: a full hand (10) and Fruit Vendor (Activate (1): get 2 Tavern Dish
    # Bananas): both are lost, so the Activate's reward is 2 x -0.05
    import json as _json

    import taverngym
    from advisor.state import debug, recruit_game

    L = dict(taverngym.layout())
    g = recruit_game(4)
    debug(g, cmd="set_player", p=0, gold=10)
    debug(g, cmd="add_minion", p=0, zone="board", card="BG36_346")
    for _ in range(10 - len(_json.loads(g.view(0))["me"]["hand"])):
        debug(g, cmd="add_minion", p=0, zone="hand", card="BGS_004", no_triple=True)
    board = _json.loads(g.view(0))["me"]["board"]
    a = L["A_ACTIVATE"] + next(i for i, m in enumerate(board) if m["id"] == "BG36_346")
    env = taverngym.BatchEnv(1, seed=21, controlled=[0], config=train.CONFIG)
    env.card_lost_penalty = -0.05
    fresh = _json.loads(env.save(0))
    env.load(0, _json.dumps({"game": _json.loads(g.state_json()), "index": fresh["index"], "finished": [False]}))
    assert env.observe()["action_mask"][0][a]
    r, _, _ = env.step(np.array([a]))
    lost = _json.loads(env.save(0))["game"]["players"][0]["stats"]["cards_lost"]
    assert lost == 2 and abs(float(r[0]) - (-0.10)) < 1e-6, (lost, r)
