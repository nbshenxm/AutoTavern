"""TavernGym games built from logged state (advisor.logs / advisor.decisions snapshots).

Cards are created with the debug commands, so every field TavernGym keeps is filled the way
the engine fills it; logged stats and keywords then overwrite the created ones. Player-level
counters are set before the minions, so minions created afterwards carry them.
"""

import json
from pathlib import Path

import taverngym

CAT = {c["id"]: c for c in json.loads(taverngym._core.catalog_json())}
RULES = json.loads(taverngym._core.default_config_json())
CARDS = Path(__file__).resolve().parents[1] / "crates" / "taverngym" / "data" / "cards.json"
KEYWORDS = {c["id"]: c["keywords"]
            for c in json.loads(CARDS.read_text(encoding="utf-8"))["cards"]}

# The keywords the log carries as tags (advisor.logs.KEYWORD_TAGS); a printed keyword outside
# this set (Cleave, Magnetic...) is kept from the created card
LOGGED_KW = {"TAUNT", "DIVINE_SHIELD", "REBORN", "VENOMOUS", "POISONOUS", "STEALTH",
             "WINDFURY", "MEGA_WINDFURY"}

# "This game" counters the log shows on player enchantments: card -> PlayerStats fields
# filled from the enchantment's TAG_SCRIPT_DATA_NUM_1 and _2
PLAYER_ENCHANTMENTS = {
    "BG25_011pe": ("undead_atk", None),  # Nerubian Deathswarmer
    "BG25_008pe": ("eternal_knight_deaths", None),  # Eternal Knight
    "BG31_808pe": ("beetle_atk", "beetle_hp"),  # Runed Progenitor and other Beetle buffs
}
TASTY_LOBSTER = "BG36_202"


def damage_cap(turn, alive):
    """RulesConfig::damage_cap."""
    if alive <= RULES["damage_cap_until_alive"]:
        return None
    cap = None
    for first, c in RULES["damage_caps"]:
        if turn >= first:
            cap = c
    return cap


def recruit_game(seed, config=None):
    """A game in its first recruit turn with every hero chosen (tests/test_debug.py)."""
    g = taverngym.Game(seed, json.dumps(config) if config else None)
    for p in range(8):
        g.step(p, json.loads(g.view(p))["actions"]["CHOOSE"])
    for p in range(8):
        for _ in range(4):
            v = json.loads(g.view(p))
            if v["me"]["pending"] is None:
                break
            g.step(p, v["actions"]["CHOOSE"])
    return g


def debug(g, **cmd):
    return json.loads(g.debug(json.dumps(cmd)))


def normal_form(cid):
    """(normal card id, golden) of a logged card id."""
    c = CAT.get(cid)
    if c and c.get("normal_id"):
        return c["normal_id"], True
    return cid, False


def attachment(ench):
    """The TavernGym card an enchantment stands for, if it carries behaviour: a Dark Gift or
    a magnetized minion ("<card>e"). Stat-only enchantments are in the logged stats."""
    base = ench[:-1] if ench.endswith("e") else None
    c = CAT.get(base) if base else None
    if c is None:
        return None
    if c["kind"] == "dark_gift" or (c["kind"] == "minion" and "MAGNETIC" in KEYWORDS.get(base, ())):
        return base
    return None


def player_stats(s):
    """PlayerStats fields recoverable from a logged side."""
    out = {}
    for e in s.get("player_ench", []):
        fields = PLAYER_ENCHANTMENTS.get(e["card"])
        if fields:
            for f, v in zip(fields, e["data"]):
                if f:
                    out[f] = v
    # A Tasty Lobster shows the buff its Deathrattle gives: (2, 1) x (1 + improvements),
    # doubled when golden
    for m in s["board"] + s.get("hand", []):
        cid, golden = normal_form(m["card"])
        if cid == TASTY_LOBSTER and m["data"][0] > 0:
            g = 2 if golden or m["golden"] else 1
            out["lobster_bonus"] = max(out.get("lobster_bonus", 0), m["data"][0] // (2 * g) - 1)
    return out


def zone(g, p, name):
    return json.loads(g.view(p))["me"][name]


def add_minion(g, p, where, m, gaps, label):
    """Create logged minion `m` at the end of zone `where` (board, hand or shop) with its
    logged stats, keywords and behaviour attachments. Returns False when TavernGym lacks it."""
    cid, golden = normal_form(m["card"])
    if cid not in CAT or CAT[cid]["kind"] != "minion":
        gaps.append(f"{label} minion {m['card']}")
        return False
    try:
        debug(g, cmd="add_minion", p=p, zone=where, card=cid, golden=golden or m["golden"])
    except ValueError as e:  # full zone and the like
        gaps.append(f"{label} minion {m['card']}: {e}")
        return False
    idx = len(zone(g, p, where)) - 1
    for e in m["ench"]:
        a = attachment(e["card"])
        if a:
            debug(g, cmd="edit_minion", p=p, zone=where, index=idx, attach=a)
    kept = [k for k in zone(g, p, where)[idx].get("keywords", []) if k not in LOGGED_KW]
    debug(g, cmd="edit_minion", p=p, zone=where, index=idx, atk=m["atk"], hp=max(1, m["hp"]),
          keywords=sorted(set(m["keywords"]) | set(kept)))
    if not CAT[cid]["implemented"]:
        gaps.append(f"{label} unscripted {cid}")
    return True


def set_side(g, p, s, gaps, label):
    """Seat `p` takes logged side `s`: hero, Hero Powers, trinkets, Tier, health, armor,
    counters, warband and the minions in hand."""
    hero = s.get("hero")
    if hero in CAT and CAT[hero]["kind"] == "hero":
        debug(g, cmd="set_hero", p=p, hero=hero)
    else:
        gaps.append(f"{label} hero {hero}")
    for i, hp in enumerate(s["hero_powers"]):
        if hp["card"] in CAT and CAT[hp["card"]]["kind"] == "hero_power":
            debug(g, cmd="set_hero_power", p=p, slot=i, card=hp["card"])
        else:
            gaps.append(f"{label} hero power {hp['card']}")
    # Trinkets before the warband: an on-attach buff must not hit the logged stats, and the
    # cards an on-attach effect gives ("Get 2 random...") are cleared with the zones
    for t in s["trinkets"]:
        if t["card"] in CAT and CAT[t["card"]]["kind"].startswith("trinket"):
            debug(g, cmd="give_trinket", p=p, card=t["card"])
        else:
            gaps.append(f"{label} trinket {t['card']}")
    debug(g, cmd="clear_zone", p=p, zone="board")
    debug(g, cmd="clear_zone", p=p, zone="hand")
    debug(g, cmd="set_player", p=p, tier=max(1, s.get("tier", 1)), health=s.get("health", 30),
          armor=s.get("armor", 0))
    stats = player_stats(s)
    if stats:
        debug(g, cmd="set_stats", p=p, stats=stats)
    for m in s["board"][:7]:
        add_minion(g, p, "board", m, gaps, label)
    for m in s.get("hand", [])[:10]:
        add_minion(g, p, "hand", m, gaps, label)
