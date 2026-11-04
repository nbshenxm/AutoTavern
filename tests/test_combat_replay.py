"""Logged combats replayed in TavernGym (advisor.logs, advisor.replay).

The combats come from the player's own Power.logs and stay out of the repository; point
TAVERNGYM_REPLAY at a combats.jsonl (default data/replay/combats.jsonl) or the test skips.
Thresholds sit a little under the measured baseline (client 37.0, 106 combats, with the
player-level counters set): the most likely outcome was the logged one in 92.5% (start) and
95% (attack) of combats, Brier score 0.045 / 0.038, 1 of 210 logged winners under 2%.
"""

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMBATS = Path(os.environ.get("TAVERNGYM_REPLAY", ROOT / "data" / "replay" / "combats.jsonl"))

pytestmark = pytest.mark.skipif(not COMBATS.is_file(), reason=f"no logged combats at {COMBATS}")


@pytest.fixture(scope="module")
def rows():
    sys.path.insert(0, str(ROOT))
    from advisor import replay as combat_replay

    combats = [json.loads(line) for line in COMBATS.read_text(encoding="utf-8").splitlines()]
    out = []
    for c in combats:
        for mode in ("start", "attack"):
            r = combat_replay.replay(c, 200, mode, seed=7)
            if r is not None:
                out.append(r)
    return out


def predicted(r):
    return max(r["sim"], key=r["sim"].get)


LOGGED = {"friendly": "win", "opponent": "loss", "tie": "tie"}


@pytest.mark.parametrize("mode", ["start", "attack"])
def test_replays_agree_with_logged_winners(rows, mode):
    rs = [r for r in rows if r["mode"] == mode]
    assert rs
    accuracy = sum(predicted(r) == LOGGED[r["winner"]] for r in rs) / len(rs)
    brier = sum((r["sim"]["win"] - (r["winner"] == "friendly")) ** 2 for r in rs) / len(rs)
    surprises = sum(r["surprise"] for r in rs) / len(rs)
    assert accuracy >= 0.88, accuracy
    assert brier <= 0.07, brier
    assert surprises <= 0.03, [r for r in rs if r["surprise"]]


def test_every_logged_card_is_known(rows):
    gaps = sorted({g for r in rows for g in r["gaps"]})
    assert not gaps, gaps


def test_waiting_summons_on_a_full_warband():
    # A replay from the first attack queues what Start of Combat left waiting for space: a Hero
    # Power's on a warband full at both snapshots, a Diremuck Forager's with a Murloc in hand
    sys.path.insert(0, str(ROOT))
    from advisor.replay import waiting_space

    full = [{"card": "BG36_345", "eid": i} for i in range(6)]
    forager = {"card": "BG27_556", "eid": 9}
    side = lambda board, hand=(), powers=(): {"board": board, "hand": list(hand),
                                              "hero_powers": [{"card": p} for p in powers]}
    c = {"start": {"friendly": side(full + [{"card": "BG36_345", "eid": 7}], powers=["BG22_HERO_002p"]),
                   "opponent": side(full[:6] + [forager])},
         "first_attack": {"friendly": side(full + [{"card": "BG36_345", "eid": 7}]),
                          "opponent": side(full[:6] + [forager], hand=[{"card": "BG32_330"}])}}
    assert waiting_space(c) == [[0, "BG22_HERO_002p"], [1, "BG27_556"]]
    c["first_attack"]["friendly"]["board"][-1] = {"card": "BG36_345", "eid": 8}  # made at Start of Combat
    c["first_attack"]["opponent"]["hand"] = [{"card": "BG36_345"}]  # no Murloc left
    assert waiting_space(c) == []
