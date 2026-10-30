"""The teacher bot's plan (TavernGym `RulesConfig.teacher`, crates/taverngym/src/teacher.rs),
from the player's advice: level on a curve; early, take economy cards and Dark Gifts that give
free Refreshes or win early fights; complete triples (their Discover reaches the higher Tiers,
where the key cards are, and Tier 6 has few copies); from the mid game build toward the meta
comp (advisor.meta) the warband is closest to.

    python -X utf8 -m advisor.teacher teacher.json    # write a config with the teacher
"""

import json
import sys
from pathlib import Path

from advisor import meta
from advisor.state import GAME_CONFIG

LEVEL_TURNS = [2, 5, 7, 9, 11]  # Tavern Tier 2, 3, 4, 5, 6 by these turns
EARLY_TURNS = 5
COMMIT_TURN = 7
ECONOMY = {  # value added through EARLY_TURNS
    "BG26_135": 8,   # Southsea Busker: Gain 1 Gold next turn
    "BG36_354": 6,   # Decoy Conjurer: Activate (2), steal the highest-Attack Tavern minion
    "BG35_150": 3,   # Laboratory Assistant: Fodder in the next 3 Refreshes
    "BG36_330": 4,   # Sly Infiltrator: 2 free Refreshes
    "BGS_116": 4,    # Refreshing Anomaly: 2 free Refreshes
    "BG28_810": 3,   # Tavern Coin
    "BG28_800": 4,   # Careful Investment: 2 Gold next turn
    "BG28_827": 4,   # Leaf Through the Pages: 2 free Refreshes
    "BG28_805": 5,   # Strike Oil: +1 maximum Gold
    "BG33_815": 3,   # Wealthy Bounty: Gain 2 Gold
}
GIFTS = {  # Dark Gifts, value added through EARLY_TURNS
    "BG36_MidGameEffect_000t52": 10,  # Fresh Perspective: Deathrattle, 2 free Refreshes
    "BG36_MidGameEffect_000t13": 8,   # Harpy's Talons: Divine Shield, Windfury
    "BG36_MidGameEffect_000t73": 5,   # Fortitude: +5/+5
    "BG36_MidGameEffect_000t74": 5,   # Sharpened Sword: +3 Attack per card played
    "BG36_MidGameEffect_000t75": 4,   # Toughened Shield: +3 Health per card played
    "BG36_MidGameEffect_000t82": 4,   # Affinity: a minion of its type every 2 turns
    "BG36_MidGameEffect_000t80": 3,   # Consanguinity: Rally, 2 Blood Gems
}


def config(seats=()):
    meta.fetch()
    return {"level_turns": LEVEL_TURNS, "early_turns": EARLY_TURNS, "economy": ECONOMY,
            "gifts": GIFTS, "commit_turn": COMMIT_TURN, "seats": list(seats),
            "comps": [{"core": c["core"], "addon": c["addon"]} for c in meta.comps()]}


if __name__ == "__main__":
    Path(sys.argv[1]).write_text(json.dumps({**GAME_CONFIG, "teacher": config()}))
