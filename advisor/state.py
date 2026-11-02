"""TavernGym games built from logged state (advisor.logs / advisor.decisions snapshots).

Cards are created with the debug commands, so every field TavernGym keeps is filled the way
the engine fills it; logged stats and keywords then overwrite the created ones. Player-level
counters are set before the minions, so minions created afterwards carry them.
"""

import json
import re
from pathlib import Path

import taverngym

CAT = {c["id"]: c for c in json.loads(taverngym._core.catalog_json())}
RULES = json.loads(taverngym._core.default_config_json())
# The rules the network trains under (advisor.train) and the live advisor plans under: the same,
# or the network plays a game it never learned
GAME_CONFIG = {
    "hero_choices": 4,  # the player's season-pass offer (docs/REPLAY.md, recruit rules)
    # Moves and Freeze never advance the game: a turn ends after this many actions. Set with room
    # above the most the player took in a logged turn (by round 6, 6, 11, 11, 16, 36, 37, 47, 57,
    # 60...: round 10 hit the old cap of 60): strong players' economy turns buy, play and sell
    # more; Freeze presses (10) and moves (moves_per_turn) have their own limits
    "turn_action_caps": [10, 10, 16, 16, 24, 50, 60, 80, 100],
    # Moves outside that budget, at most 7 a turn (any order of 7 minions takes 6): the network
    # spent most of its turns rearranging and ended them, budget gone, with gold left
    "moves_per_turn": 7,
}
try:  # a module built before moves_per_turn (rebuilt only while nothing has it loaded)
    taverngym.Game(0, json.dumps(GAME_CONFIG))
except ValueError:
    del GAME_CONFIG["moves_per_turn"]
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
    # (found by advisor.recruit_diff: these "this game" bonuses were missing from the bridge)
    "BG26_159pe": ("gem_atk", "gem_hp"),  # Blood Gem size: a gem gives 1 more than these
    "BG_ShopBuff": ("tavern_atk", "tavern_hp"),  # Tavern minions have +a/+h this game
    "BG_ShopBuff_Elemental": ("tavern_elemental_atk", "tavern_elemental_hp"),
    "BG31_816pe": ("baller_bonus", None),  # Ballers improved (each sale: +1 to the next ones)
}
TASTY_LOBSTER = "BG36_202"
VOLUMIZERS = ("BG34_170t", "BG34_170t2", "BG34_170t3")  # Red, Blue, Green
# Enchantments whose first number is Attack until the owner's next turn: shown in the logged
# Attack, gone at the next turn's start (advisor.carry_test: the only such one in the logs, 27 of
# 29 drops equal to it). Rebuilt as permanent, a swapped minion kept thousands of Attack.
TEMP_ATTACK = {"BG20_HERO_201p2e2"}  # Vol'jin's Spirit Swap
# Hero Powers used in the Recruit phase for an effect in the next combat (TavernGym: the power's
# counter is 1 while armed): used this turn, a rebuilt one must be armed. Y'Shaarj's Embrace
# Your Rage unarmed lost combats the log won (a summoned minion short; advisor.replay, Nov 2)
ARMED_POWERS = {"TB_BaconShop_HP_103", "TB_BaconShop_HP_053"}  # Y'Shaarj, Arch-Villain Rafaam


def set_deities(st, card, sides):
    """The lobby's Deity `card` in state JSON `st`, and each seat's Deity at its logged size:
    `sides` = [(seat, logged side)]. Rebuilt lobbies drew a random Deity at its printed size (a
    Y'Shaarj where the lobby had a 7/4 C'Thun lost fights the log won; advisor.bb_real, Nov 2)."""
    if card not in CAT:
        return
    cid = CAT[card]["cid"]
    st["deity"] = cid
    for p, s in sides:
        atk, hp = (s.get("deity") or [0, 0])[:2]
        if not (atk or hp) and st["players"][p].get("deity") is None:
            continue
        st["players"][p]["deity"] = {"card": cid, "atk": max(atk, CAT[card]["atk"]), "hp": max(hp, CAT[card]["hp"]),
                                     "golden": False, "reborn": False}


def arm_powers(powers, logged, used):
    """Arm the ARMED_POWERS among `powers` (a player's state JSON powers, in the order of the
    logged `logged` hero powers) that `used(logged power)` says were used this turn."""
    for power, h in zip(powers, logged):
        if h.get("card") in ARMED_POWERS and used(h):
            power["counter"] = 1
BLOOD_GEM = "BG20_GEM"
SURVEYOR_PORTRAIT = "BG30_MagicItem_943"
# A two-step Hero Power shows its second step as another card; TavernGym asks both steps
# within one use, so the setup restarts the use
HERO_POWER_STEPS = {
    "BG20_HERO_201p2": "BG20_HERO_201p",  # Vol'jin's Spirit Swap after its first minion
}


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
    """The TavernGym card an enchantment stands for, if it carries behaviour: a Dark Gift
    ("<gift>e", also "<gift>e2", "e3": the log numbers some gifts' enchantments) or a magnetized
    minion ("<card>e"). Stat-only enchantments are in the logged stats."""
    m = re.match(r"^(.+?)e(\d*)$", ench)
    if not m:
        return None
    base, n = m.groups()
    c = CAT.get(base)
    if c is None:
        return None
    if c["kind"] == "dark_gift":
        return base
    if not n and c["kind"] == "minion" and "MAGNETIC" in KEYWORDS.get(base, ()):
        return base
    return None


# The client's Satellite (Glambot's, Reusable Batteries', Inductive Gyroblade's): one
# enchantment holds all of a minion's Satellites, its data their summed stats
SATELLITE = "BG31_171t"


def satellites(e):
    """How many Satellites a logged Satellite enchantment stands for: its summed Attack over a
    4/4 Satellite's (an improved Gyroblade's are bigger: then fewer than the real count). Each
    is a Magnetization (Utility Drone counts them: a Glambot with [76, 76] took 19, Nov 2)."""
    data = e.get("data") or [0]
    return max(1, round(data[0] / 4))


def player_stats(s):
    """PlayerStats fields recoverable from a logged side."""
    out = {}
    for e in s.get("player_ench", []):
        fields = PLAYER_ENCHANTMENTS.get(e["card"])
        if fields:
            for f, v in zip(fields, e["data"]):
                if f:
                    out[f] = v
    # A Blood Gem in hand shows what it gives: (1 + gem_atk, 1 + gem_hp), plus 6/6 from the hand
    # with Surveyor Portrait (TavernGym's gem_stats)
    # Tavern spells' bonus ("your Tavern spells give an extra +1 Attack"): player tags
    for f in ("spell_atk", "spell_hp"):
        if s.get(f):
            out[f] = s[f]
    surveyor = any(t["card"].startswith(SURVEYOR_PORTRAIT) for t in s.get("trinkets", []))
    for h in s.get("hand_all", []):
        if h.get("card") == BLOOD_GEM and len(h.get("data") or []) >= 2 and h["data"][0] > 0:
            a, hp = (x - 6 if surveyor else x for x in h["data"][:2])
            out["gem_atk"] = max(out.get("gem_atk", 0), a - 1)
            out["gem_hp"] = max(out.get("gem_hp", 0), hp - 1)
    # A Tasty Lobster shows the buff its Deathrattle gives: (2, 1) x (1 + improvements),
    # doubled when golden
    for m in s["board"] + s.get("hand", []):
        cid, golden = normal_form(m["card"])
        if cid == TASTY_LOBSTER and m["data"][0] > 0:
            g = 2 if golden or m["golden"] else 1
            out["lobster_bonus"] = max(out.get("lobster_bonus", 0), m["data"][0] // (2 * g) - 1)
    # "Your Volumizers have +X this game": a Volumizer in hand shows it over its printed stats
    # (the log's Volumizer player enchantment, BG34_170pe, keeps no number). Missing, a rebuilt
    # Resourceful Robot or Auto Reveille Magnetized printed-size Volumizers: half the real growth
    # (advisor.carry_test, Nov 2)
    # The log's player tags hold it (advisor.logs, from Nov 2); older records: a Volumizer in hand
    if s.get("volumizer"):
        out["volumizer_atk"], out["volumizer_hp"] = s["volumizer"][:2]
        return out
    for m in s.get("hand", []):
        cid, golden = normal_form(m["card"])
        if cid in VOLUMIZERS and not (golden or m.get("golden")):
            out["volumizer_atk"] = max(out.get("volumizer_atk", 0), m["atk"] - CAT[cid]["atk"])
            out["volumizer_hp"] = max(out.get("volumizer_hp", 0), m["hp"] - CAT[cid]["hp"])
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
        # (no_triple: the log shows the zones as they were; three copies there hadn't combined)
        debug(g, cmd="add_minion", p=p, zone=where, card=cid, golden=golden or m["golden"],
              no_triple=True)
    except ValueError as e:  # full zone and the like
        gaps.append(f"{label} minion {m['card']}: {e}")
        return False
    idx = len(zone(g, p, where)) - 1
    gifts = set()
    for e in m["ench"]:
        a = attachment(e["card"])
        if a and not (a in gifts and CAT[a]["kind"] == "dark_gift"):  # a gift once, its e2/e3 too
            gifts.add(a)
            for _ in range(satellites(e) if a == SATELLITE else 1):
                debug(g, cmd="edit_minion", p=p, zone=where, index=idx, attach=a)
    kept = [k for k in zone(g, p, where)[idx].get("keywords", []) if k not in LOGGED_KW]
    temp = sum(e["data"][0] for e in m["ench"] if e["card"] in TEMP_ATTACK and e.get("data"))
    debug(g, cmd="edit_minion", p=p, zone=where, index=idx, atk=m["atk"], hp=max(1, m["hp"]),
          keywords=sorted(set(m["keywords"]) | set(kept)), **({"temp_atk": temp} if temp else {}))
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
        card = HERO_POWER_STEPS.get(hp["card"], hp["card"])
        if card != hp["card"]:
            gaps.append(f"{label} hero power {hp['card']} mid-use: restarted")
        if card in CAT and CAT[card]["kind"] == "hero_power":
            debug(g, cmd="set_hero_power", p=p, slot=i, card=card)
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
    # The client's Tavern spell bonus is the total; TavernGym adds the warband's and trinkets'
    # part (Humon'gozz, Enchanted Sentinel, Heart of the Forest...) to its this-game bonus
    if s.get("spell_atk") or s.get("spell_hp"):
        a, h = debug(g, cmd="spell_extra", p=p)
        debug(g, cmd="set_stats", p=p, stats={"spell_atk": max(0, 2 * s.get("spell_atk", 0) - a),
                                              "spell_hp": max(0, 2 * s.get("spell_hp", 0) - h)})
