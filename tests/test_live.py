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
    assert max(a["ms"] for a in advice) < 1000
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
