"""The live bridge (advisor.bridge): TavernGym's legal actions at logged recruit decisions
match the options the client offered.

The decisions come from the player's own Power.logs (advisor.decisions) and stay out of the
repository; point TAVERNGYM_DECISIONS at a decisions.jsonl (default
data/replay/decisions.jsonl) or the test skips. Thresholds sit a little under the first
measured baseline (10 games, 1,870 recruit decisions): identical legal sets in 89%, every
action kind 97% or better.
"""

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = Path(os.environ.get("TAVERNGYM_DECISIONS",
                                ROOT / "data" / "replay" / "decisions.jsonl"))

pytestmark = pytest.mark.skipif(not DECISIONS.is_file(), reason=f"no decisions at {DECISIONS}")


@pytest.fixture(scope="module")
def result():
    sys.path.insert(0, str(ROOT))
    from advisor import bridge

    lines = DECISIONS.read_text(encoding="utf-8").splitlines()
    decisions = [json.loads(line) for line in lines[::3]]  # a third keeps the test quick
    combats_file = DECISIONS.with_name("combats.jsonl")
    combats = ([json.loads(line) for line in combats_file.read_text(encoding="utf-8").splitlines()]
               if combats_file.is_file() else [])
    return bridge.parity(decisions, combats=combats)


def test_legal_sets_mostly_identical(result):
    n, exact, _, _ = result
    assert n > 100
    assert exact / n >= 0.85, exact / n


@pytest.mark.parametrize("kind", ["end", "refresh", "freeze", "upgrade", "hero_power", "buy",
                                  "sell", "play", "dark_gift"])
def test_each_action_kind_agrees(result, kind):
    _, _, by_kind, examples = result
    both, client_only, tavern_only = by_kind.get(kind, [0, 0, 0])
    total = both + client_only + tavern_only
    if total == 0:
        pytest.skip(f"no {kind} options in these decisions")
    assert both / total >= 0.95, (kind, by_kind[kind], examples.get(kind))


def test_lobby_types_from_what_was_seen():
    # The Tavern only offers the lobby's types: single-type minions seen tell them, most seen
    # first, at most five; dual-type and Amalgam minions don't count
    from advisor.bridge import lobby_types
    from advisor.state import CAT

    by_race = {}
    for c in CAT.values():
        r = c.get("races") or []
        if c.get("kind") == "minion" and c.get("in_pool") and len(r) == 1 and not c.get("normal_id"):
            by_race.setdefault(r[0], []).append(c["id"])
    shop = [{"card": by_race["MURLOC"][0]}, {"card": by_race["BEAST"][0]}]
    d = {"state": {"shop": shop, "friendly": {"board": [{"card": by_race["MURLOC"][1]}], "hand": []}},
         "tavern_seen": [by_race["UNDEAD"][0]]}
    assert lobby_types(d) == ["MURLOC", "BEAST", "UNDEAD"]


def test_a_trinket_offer_is_rebuilt_for_advice():
    # A logged trinket choice: the player's pending choice is that offer, priced by TavernGym
    import json as _json

    from advisor import bridge
    from advisor.state import CAT

    tr = [c["id"] for c in CAT.values() if c.get("kind") == "trinket_lesser" and c.get("in_pool")][:4]
    d = {"kind": "choices", "turn": 11, "log": "x", "segment": 0, "player_id": 1,
         "source": {"card": None}, "options": [{"card": t} for t in tr],
         "state": {"friendly": {"board": [], "hand": [], "hand_all": [], "gold": 8, "hero_powers": [],
                                "trinkets": [], "player_ench": [], "health": 30, "armor": 0,
                                "tier": 3, "hero": None},
                   "shop": [], "leaderboard": {}, "costs": {}}}
    assert bridge.choice_options(d) == ("trinket", tr)
