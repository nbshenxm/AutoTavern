"""advisor.usefulness: the advice's first step read from its actions, or from its first row's
verb in an older record (before the actions were kept), in either locale."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_the_first_step_is_read_from_the_actions_or_the_verb():
    from advisor import display, usefulness as u

    L = u.L
    assert u.advice_step({"actions": [L["A_END"]]}) == ("end", None)
    assert u.advice_step({"actions": [L["A_MOVE"] + 3]}) == ("move", None)
    buy = {"actions": [L["A_BUY"] + 2], "display": {"rows": [{"verb": "Buy", "card_id": "BG26_152"}]}}
    assert u.advice_step(buy) == ("buy", "BG26_152")
    old = {"display": {"rows": [{"verb": display.t("zhCN", "magnetize"), "card_id": "BG31_174"}]}}
    assert u.advice_step(old) == ("play", "BG31_174")
    freeze = {"display": {"rows": [{"verb": display.t("enUS", "freeze") + " ×2", "card_id": None}]}}
    assert u.advice_step(freeze) == ("freeze", None)
    assert u.same_card("BG26_152_G", "BG26_152") and not u.same_card("BG26_152", "BGS_004")
