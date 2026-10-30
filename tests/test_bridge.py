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


def test_a_hero_offer_is_rebuilt_at_the_games_start():
    # The four heroes offered (a skin counts as its base hero) are the player's hero choice
    import json as _json

    from advisor import bridge
    from advisor.state import CAT

    heroes = [c["id"] for c in CAT.values() if c.get("kind") == "hero" and c.get("in_pool")][:4]
    d = {"kind": "choices", "turn": 0, "choice_type": "MULLIGAN",
         "options": [{"card": h, "type": "HERO"} for h in heroes], "state": {}}
    assert bridge.choice_options(d) == ("hero", heroes)
    g, gaps = bridge.build(d)
    v = _json.loads(g.view(0))
    assert not gaps and v["me"]["pending"]["kind"] == "hero"
    assert [o["id"] for o in v["me"]["pending"]["options"]] == heroes


def test_the_logged_spell_bonus_is_the_total():
    # The client's Tavern spell bonus counts the warband's auras; TavernGym adds those itself,
    # so the this-game part it keeps is the total minus them
    import json as _json

    from advisor.state import CAT, debug, recruit_game, set_side

    gozz = "BG32_341"  # Humon'gozz: your Tavern spells give an extra +1/+2
    assert gozz in CAT
    side = {"hero": None, "hero_powers": [], "trinkets": [], "board": [
        {"card": gozz, "atk": 4, "hp": 4, "golden": False, "keywords": [], "ench": [], "data": [0, 0]}],
        "hand": [], "tier": 4, "health": 30, "armor": 0, "player_ench": [],
        "spell_atk": 3, "spell_hp": 4}
    g = recruit_game(1)
    set_side(g, 0, side, [], "me")
    assert debug(g, cmd="spell_extra", p=0) == [3, 4]
    assert _json.loads(g.state_json())["players"][0]["stats"]["spell_atk"] == 2


def test_an_activate_used_this_turn_is_not_offered_again():
    # The log drops an Activate minion's INTERACTABLE_OBJECT to 0 once it was used this turn
    # (once a turn); the rebuilt minion must not offer it again
    import copy
    import json as _json

    import taverngym

    from advisor import bridge

    acts = {c["id"] for c in _json.loads(taverngym.catalog_json()) if "ACTIVATE" in (c.get("mech") or [])}
    rows = [_json.loads(line) for line in DECISIONS.read_text(encoding="utf-8").splitlines()]
    for d in rows:
        if d["kind"] != "options" or d["turn"] % 2 == 0:
            continue
        board = d["state"]["friendly"]["board"]
        i = next((i for i, m in enumerate(board) if m["card"] in acts), None)
        if i is None:
            continue
        g, gaps = bridge.build(d, [])
        if gaps or not _json.loads(g.view(0))["mask"][23 + i]:
            continue  # this Activate isn't usable here anyway (gold, targets)
        used = copy.deepcopy(d)
        used["state"]["friendly"]["board"][i]["interactable"] = 0
        g2, _ = bridge.build(used, [])
        assert not _json.loads(g2.view(0))["mask"][23 + i]
        return
    pytest.skip("no usable Activate minion in the logged decisions")
