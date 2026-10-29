"""The live advisor (advisor.live) on a recorded Power.log: it finds the same recruit decisions
as the offline extractor (advisor.decisions) and advises at each, well under a second.

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
    advice = []
    with open(LOG, encoding="utf-8", errors="replace") as f:
        for line in f:
            d = tr.feed(line)
            if d is not None:
                advice.append(live.advise(d, tr.combats()))
    assert len(advice) == len(offline)
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
