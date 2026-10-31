"""The live advisor (advisor.live) on a recorded Power.log: it finds the same recruit decisions
as the offline extractor (advisor.decisions) plus the open Discovers, and advises at each, well
under a second.

The log is the player's own and stays out of the repository; point TAVERNGYM_LOG at a
Battlegrounds Power.log or the test skips.
"""

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(os.environ.get("TAVERNGYM_LOG", r"D:\GitHub\Hearthstone_AI_Advisor\data\logs"
                          r"\Hearthstone_2026_10_26_22_59_26\Power.log"))
CARDS = Path(os.environ.get("TAVERNGYM_CARDS", r"D:\GitHub\Hearthstone_AI_Advisor\data\cards\255790"))

pytestmark = pytest.mark.skipif(not (LOG.is_file() and (CARDS / "CardDefs.xml").is_file()),
                                reason="no recorded Battlegrounds log or client card data")


def test_replayed_log_gets_advice_at_every_recruit_decision():
    sys.path.insert(0, str(ROOT))
    from advisor import decisions, live, logs

    skins = logs.skin_parents(CARDS)
    offline = [d for d in decisions.extract(LOG, skins)
               if d["kind"] == "options" and d["turn"] % 2 == 1]
    tr = live.Tracker(skins, name=LOG.parent.name)
    advice, kinds = [], []
    with open(LOG, encoding="utf-8", errors="replace") as f:
        for line in f:
            d = tr.feed(line)
            if d is not None:
                advice.append(live.advise(d, tr.combats()))
                kinds.append(d["kind"])
                if d["kind"] == "options":  # the plan's actions, every move kept, replay as given
                    from advisor import bridge
                    g, gaps = bridge.build(d, tr.combats())
                    if not gaps:
                        for x in advice[-1]["actions"]:
                            g.step(0, x)
                        if not advice[-1]["arranged"]:  # the warband in the plan's order
                            board = [m["id"] for m in json.loads(g.view(0))["me"]["board"]]
                            assert board == [e["card_id"] for e in advice[-1]["display"]["lineup"]]
    # Every recruit Options decision, and the Discovers between minions on top
    assert kinds.count("options") == len(offline)
    assert kinds.count("choices") >= 1
    assert all(a["plan"] and a["action"] for a in advice)
    # The overlay's rows (the constructed advisor's format): numbered, each with a verb, and a
    # buy or a play names its card by its slot
    for a in advice:
        rows = a["display"]["rows"]
        assert rows and [r["n"] for r in rows] == list(range(1, len(rows) + 1))
        assert all(r["verb"] for r in rows)
        for r in rows:
            if r["verb"] in ("Buy", "Play"):
                assert r["badge"][0] in "TH" and r["card_id"], r
    # What the plan leaves is read before its End Turn (after it nothing is legal): over a game
    # some plan ends with Gold a Refresh could use (the review's "ended with spendable Gold")
    ended = [a for a in advice if a["plan"][-1].startswith("End")]
    assert any(a["could_spend"] for a in ended)
    assert all(a["gold_left"] <= a["gold"] + 10 for a in ended)
    # (the first advice of a session loads the card data and the public stats: seconds, once)
    assert max(a["ms"] for a in advice[1:]) < 1000
    json.dumps(advice)  # what the plugin reads


def test_arrange_finds_a_better_order_or_nothing():
    # The arrangement search returns None or an order at least min_gain better (same seeds)
    import json as _json

    from advisor import bridge, live

    rows = [_json.loads(l) for l in open(ROOT / "data" / "replay" / "decisions.jsonl", encoding="utf-8")]
    combats = [_json.loads(l) for l in open(ROOT / "data" / "replay" / "combats.jsonl", encoding="utf-8")]
    tried = 0
    for d in rows[::25]:
        if d["kind"] != "options" or d["turn"] < 9:
            continue
        g, _ = bridge.build(d, bridge.game_combats(combats, d))
        r = live.arrange(g)
        tried += 1
        if r is not None:
            game, before, after = r
            assert after >= before + live.ARRANGE["min_gain"]
            assert sorted(m["id"] for m in _json.loads(game.view(0))["me"]["board"]) == \
                sorted(m["id"] for m in _json.loads(g.view(0))["me"]["board"])
    assert tried > 0


def test_the_hero_offer_reaches_the_advice_live():
    # The heroes offered at the start sit inside the game's opening block until picked: the
    # live reader still reports them, and the advice ranks them with public data and the network
    sys.path.insert(0, str(ROOT))
    import torch

    from advisor import bridge, live, logs
    from advisor.policy import EntityNet

    tracker = live.Tracker(logs.skin_parents(CARDS), name=LOG.parent.name)
    offers = []
    with open(LOG, encoding="utf-8", errors="replace") as f:
        for line in f:
            d = tracker.feed(line)
            if d is not None and bridge.choice_options(d)[0] == "hero":
                offers.append(d)
    assert offers, "no hero offer reported"
    torch.manual_seed(0)
    a = live.advise(offers[0], [], locale="enUS", net=EntityNet().eval())
    assert a["plan"] and a["plan"][0].startswith("Choose")
    assert a["display"]["notes"][0].startswith("Heroes (public")


def test_a_plan_does_not_sell_a_minion_to_play_the_same_card():
    # After selling a Battlecry-less minion, its copy in hand can't be played in the same plan;
    # after playing one from hand, the warband's copy can't be sold (search.detour_mask)
    sys.path.insert(0, str(ROOT))
    import json as _json

    import taverngym

    from advisor import search
    from advisor.state import debug, recruit_game

    L = dict(taverngym.layout())
    g = recruit_game(1)
    debug(g, cmd="set_player", p=0, gold=10)
    debug(g, cmd="add_minion", p=0, zone="board", card="BG26_152")
    debug(g, cmd="add_minion", p=0, zone="hand", card="BG26_152", no_triple=True)
    v = _json.loads(g.view(0))
    seen = {}
    search.note_sold(v, L["A_SELL"] + 0, seen)
    g.step(0, L["A_SELL"] + 0)
    m = search.detour_mask(_json.loads(g.view(0)), seen)
    assert m is not None and not m[L["A_PLAY"]:L["A_PLAY"] + L["N_POS"]].any()
    g2 = recruit_game(1)
    debug(g2, cmd="add_minion", p=0, zone="board", card="BG26_152")
    debug(g2, cmd="add_minion", p=0, zone="hand", card="BG26_152", no_triple=True)
    seen = {}
    v = _json.loads(g2.view(0))
    search.note_sold(v, L["A_PLAY"] + 1, seen)
    g2.step(0, L["A_PLAY"] + 1)
    m = search.detour_mask(_json.loads(g2.view(0)), seen)
    assert m is not None and not m[L["A_SELL"]] and not m[L["A_SELL"] + 1]



def test_a_step_that_draws_at_random_ends_the_plan():
    # A Refresh draws a new Tavern: under another seed it differs (random_cards says so); an
    # End Turn decided nothing random
    sys.path.insert(0, str(ROOT))
    import json as _json

    import taverngym

    from advisor import live, search
    from advisor.state import debug, recruit_game

    L = dict(taverngym.layout())
    g = recruit_game(4)
    debug(g, cmd="set_player", p=0, gold=5)
    alt = search.fair_copy(g, 0, seed=99)
    c = g.copy()
    c.step(0, L["A_REFRESH"])
    assert live.random_cards(alt, L["A_REFRESH"], _json.loads(c.view(0))) == "cards"
    debug(g, cmd="add_minion", p=0, zone="hand", card="BG26_152", no_triple=True)
    alt = search.fair_copy(g, 0, seed=99)
    c = g.copy()
    c.step(0, L["A_PLAY"])
    assert live.random_cards(alt, L["A_PLAY"], _json.loads(c.view(0))) is None


def test_a_plans_actions_keep_every_move():
    # A run of moves is one "Arrange" entry of the plan, but the actions (what the review and
    # the end-of-turn Gold replay) keep every move: replayed, they give the plan's warband
    sys.path.insert(0, str(ROOT))
    import json as _json

    import numpy as np
    import taverngym

    from advisor import live
    from advisor.state import debug, recruit_game

    L = dict(taverngym.layout())
    g = recruit_game(1)
    for card in ("BG26_152", "BGS_004", "BGS_039"):
        debug(g, cmd="add_minion", p=0, zone="board", card=card, no_triple=True)
    c, script = g.copy(), []
    for _ in range(2):  # two different legal moves in a row
        moves = np.flatnonzero(np.array(_json.loads(c.view(0))["mask"][L["A_MOVE"]:])) + L["A_MOVE"]
        a = int(moves[len(script)])
        c.step(0, a)
        script.append(a)
    plan, _, after, steps = live.plan_turn(g, "enUS", script=script + [L["A_END"]])
    assert len(plan) == 2 and steps == script + [L["A_END"]]
    r = g.copy()
    for x in steps:
        r.step(0, x)
    board = lambda x: [m["id"] for m in _json.loads(x.view(0))["me"]["board"]]
    assert board(r) == board(after) == board(c)
