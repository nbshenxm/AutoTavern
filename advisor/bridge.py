"""Live bridge: a logged recruit decision (advisor.decisions) as a TavernGym game.

Seat 0 is the player: hero, Hero Powers (used or not), trinkets, counters, Tier, health, armor,
Gold, upgrade cost, free refreshes, warband, hand (minions and spells in logged order) and the
Tavern (frozen flags). Seats 1-7 are the other players in PLAYER_ID order: hero, health,
armor, Tier, eliminated with their place, and the warband the player last saw them with
(from the game's earlier combats), which is also what the player has scouted of them.

`parity` compares TavernGym's legal actions at that state with the options the client offered,
by action kind and slot (docs/ROADMAP.md, M2):

    python -X utf8 -m advisor.bridge data/replay/decisions.jsonl
"""

import argparse
import collections
import json
import sys
from pathlib import Path

import taverngym

from advisor.state import (CAT, GAME_CONFIG, RULES, add_minion, debug, normal_form, recruit_game,
                           set_side)

SPELL_TYPES = ("SPELL", "BATTLEGROUND_SPELL")
RACE_NAMES = ("BEAST", "DEMON", "DRAGON", "ELEMENTAL", "MECHANICAL", "MURLOC", "PIRATE", "QUILBOAR",
              "UNDEAD", "ABERRATION", "NAGA")  # TavernGym's Races::NAMES
# Trinket -> its uses per turn; its TAG_SCRIPT_DATA_NUM_1 is the uses left this turn
TRINKET_USES_LEFT = {
    "BG32_MagicItem_822": 1,  # Bazaar Sticker: one Tavern spell a turn costs Health
}
# Minion -> the TAG_SCRIPT_DATA_NUM index holding TavernGym's `counter` for it
COUNTER_FROM_DATA = {
    "BG26_524": 0,  # Malchezaar, Prince of Dance: Refreshes paid with Health left this turn
}


def seats(d):
    """PLAYER_ID -> seat: the player on 0, the others in PLAYER_ID order on 1-7."""
    me = d.get("player_id") or d["state"]["friendly"].get("player_id")
    others = sorted(int(k) for k in d["state"].get("leaderboard", {}) if int(k) != me)
    return {me: 0} | {pid: i + 1 for i, pid in enumerate(others[:7])}


def game_combats(combats, d):
    """The player's combats of decision `d`'s game before it (advisor.logs records)."""
    return [c for c in combats if c["log"] == d["log"] and c["player_id"] == d["player_id"]
            and c["turn"] < d["turn"]]


def lobby_types(d, combats=()):
    """The lobby's minion types as far as the player has seen them: those of the single-type
    minions in the Tavern now and earlier this game (`d["tavern_seen"]`, kept by the live
    Tracker), on the player's warband and hand, and on the warbands met in combat. A Tavern
    only offers the lobby's types; the most seen first, at most the lobby's number. The game
    can't tell them itself (no tag in the log), so the rest stay random."""
    s = d["state"]
    me = s["friendly"]
    cards = [x["card"] for x in s.get("shop", [])] + list(d.get("tavern_seen", ()))
    cards += [m["card"] for m in me["board"]] + [h.get("card") for h in hand_cards(me)]
    for c in combats:
        for side in ("friendly", "opponent"):
            cards += [m["card"] for m in c["start"][side]["board"]]
    count = collections.Counter()
    for card in cards:
        c = CAT.get(normal_form(card)[0]) if card else None
        races = (c or {}).get("races") or []
        if c and c.get("kind") == "minion" and len(races) == 1 and races[0] in RACE_NAMES:
            count[races[0]] += 1
    return [r for r, _ in count.most_common(RULES["lobby_races"])]


_SKINS = None


def base_hero(card):
    """A hero skin's base hero (CardDefs' BACON_SKIN_PARENT_ID), else the card itself."""
    global _SKINS
    if _SKINS is None:
        from advisor import logs
        from advisor.live import CARDS
        try:
            _SKINS = logs.skin_parents(CARDS)
        except OSError:
            _SKINS = {}
    return _SKINS.get(card, card)


def hero_game(d, seed=7):
    """(game, gaps) at the game's start: the player choosing among the logged heroes (the
    other seats' offers stay random; the lobby isn't known yet)."""
    g = taverngym.Game(seed, json.dumps(GAME_CONFIG))
    st = json.loads(g.state_json())
    heroes = [base_hero(o.get("card") or "") for o in d["options"]]
    cids = [CAT[h]["cid"] for h in heroes if h in CAT and CAT[h]["kind"] == "hero"]
    gaps = [f"hero {h}" for h in heroes if h not in CAT]
    if len(cids) == len(heroes):
        st["players"][0]["pending"] = [{"HeroSelect": {"options": cids}}]
    return taverngym.Game.from_json(json.dumps(st)), gaps


def build(d, combats=(), seed=7):
    """(game, gaps) for decision `d`; `combats` are the game's earlier combats
    (`game_combats`), which give the opponents' last seen warbands."""
    if choice_options(d)[0] == "hero":
        return hero_game(d, seed)
    s = d["state"]
    me = s["friendly"]
    gaps = []
    g = recruit_game(seed, {**GAME_CONFIG, "lobby_types": lobby_types(d, combats)})
    turn = max(1, (d["turn"] + 1) // 2)
    debug(g, cmd="set_turn", turn=turn)
    seat_of = seats(d)
    # Opponents: leaderboard values, and the warband last seen against each (it also stands in
    # for their current one, which the player can't see)
    last_seen = {}
    for c in sorted(combats, key=lambda c: c["turn"]):
        pid = c["start"]["opponent"].get("player_id")
        if pid in seat_of and seat_of[pid] != 0:
            last_seen[pid] = c
    for pid, seat in seat_of.items():
        if seat == 0:
            continue
        row = s["leaderboard"][str(pid)]
        if row["hero"] in CAT and CAT[row["hero"]]["kind"] == "hero":
            debug(g, cmd="set_hero", p=seat, hero=row["hero"])
        else:
            gaps.append(f"opponent hero {row['hero']}")
        debug(g, cmd="clear_zone", p=seat, zone="board")
        debug(g, cmd="clear_zone", p=seat, zone="hand")
        debug(g, cmd="set_player", p=seat, health=max(row["health"], 1), armor=row["armor"],
              tier=max(1, row["tier"]))
        if pid in last_seen:
            for m in last_seen[pid]["start"]["opponent"]["board"][:7]:
                add_minion(g, seat, "board", m, [], "seen")
    set_side(g, 0, {**me, "hand": []}, gaps, "me")
    minions = {m["eid"]: m for m in me.get("hand", [])}
    for h in hand_cards(me):
        if h.get("type") == "MINION" and h["eid"] in minions:
            add_minion(g, 0, "hand", minions[h["eid"]], gaps, "hand")
        elif h.get("type") in SPELL_TYPES:
            add_spell(g, "hand", h["card"], h.get("data", [0])[0], gaps)
        else:
            gaps.append(f"hand {h.get('type')} {h.get('card')}")
    debug(g, cmd="clear_zone", p=0, zone="shop")
    for x in s["shop"]:
        if x["kind"] == "minion":
            add_minion(g, 0, "shop", x, gaps, "shop")
        else:
            add_spell(g, "shop", x["card"], x.get("data", [0])[0], gaps)
    costs = me.get("costs", {})
    # Free Refreshes: the Refresh button's count when the log has it (older exports: a Refresh
    # that costs nothing is one); gold next turn from the player (a Southsea Busker...)
    free = costs.get("free_refreshes")
    if free is None:
        free = 1 if costs.get("refresh", 1) == 0 else 0
    debug(g, cmd="set_player", p=0, gold=me.get("gold", 0),
          upgrade_cost=costs.get("upgrade", 0), free_refreshes=free,
          gold_next_turn=me.get("gold_next_turn", 0))
    # A Discover the player is choosing in (Dark Discovery, a Discover card): its logged
    # options are created on an empty seat's hand, then moved into the player's pending choice
    offer = discover_options(d)
    spare = max(seat_of.values()) + 1 if len(seat_of) < 8 else None
    if offer and spare is None:
        spare = 7  # a full lobby: the last seat's hand (cleared above) holds them for a moment
    if offer:
        debug(g, cmd="clear_zone", p=spare, zone="hand")
        for m in offer:
            add_minion(g, spare, "hand", m, gaps, "offer")
    # Fields no debug command reaches: patched in the saved state
    st = json.loads(g.state_json())
    p0 = st["players"][0]
    # At an Options packet the player is not in a choice: drop what the stand-in hero opened,
    # and a turn it skipped (A. F. Kay) or the actions it took (the turn's budget starts now)
    p0["pending"] = []
    p0["skipping"], p0["actions_this_turn"], p0["moves_this_turn"] = False, 0, 0
    if offer:
        holder = st["players"][spare]
        options = [h["item"] for h in holder["hand"]]
        holder["hand"] = []
        gift = next((a for o in options for a in o.get("Minion", {}).get("attached", [])), 0)
        p0["pending"] = [{"Discover": {"source": gift, "options": options}}]
    kind, cards = choice_options(d)
    cids = ([CAT[normal_form(c)[0]]["cid"] for c in cards if normal_form(c)[0] in CAT]
            if kind in ("trinket", "spell") else [])
    if kind == "trinket" and len(cids) == len(cards):
        # A trinket offer: TavernGym prices each one as the game does (discounts included)
        p0["pending"] = [{"Trinket": {"options": cids, "free": False, "replace": None}}]
    elif kind == "spell" and len(cids) == len(cards):
        source = d.get("source")
        source = source.get("card") if isinstance(source, dict) else source
        src = CAT.get(normal_form(source or "")[0])
        p0["pending"] = [{"Discover": {"source": src["cid"] if src else cids[0],
                                       "options": [{"Spell": {"card": c, "data": 0}} for c in cids]}}]
    scouted = [{"board": [], "turn": 0} for _ in st["players"]]
    for pid, seat in seat_of.items():
        if seat == 0:
            continue
        o = st["players"][seat]
        o["pending"] = []
        row = s["leaderboard"][str(pid)]
        if row["health"] <= 0:
            o["alive"], o["placement"], o["health"] = False, row["place"], row["health"]
        if pid in last_seen:
            scouted[seat] = {"board": o["board"], "turn": (last_seen[pid]["turn"] + 1) // 2}
    p0["scouted"] = scouted
    combat_pids = [c["start"]["opponent"].get("player_id") for c in sorted(combats, key=lambda c: c["turn"])]
    p0["last_opponent"] = seat_of.get(combat_pids[-1]) if combat_pids else None
    p0["next_opponent"] = seat_of.get(me.get("next_opponent"))
    if combats:  # the recent combats (the network reads them): last result, damage, streak
        ordered = sorted(combats, key=lambda c: c["turn"])
        last = ordered[-1]
        st_ = p0["stats"]
        st_["won_last"], st_["lost_last"] = last["winner"] == "friendly", last["winner"] == "opponent"
        st_["tied_last"] = last["winner"] == "tie"
        sign = {"friendly": 1, "opponent": -1}.get(last["winner"], 0)
        st_["last_damage"] = sign * int(last.get("damage") or 0)
        streak = 0
        for c in ordered:
            w = {"friendly": 1, "opponent": -1}.get(c["winner"], 0)
            streak = 0 if w == 0 else (streak + w if streak * w > 0 else w)
        st_["streak"] = streak
    if costs.get("dark_gift_exhausted"):
        p0["dark_gift_used_turn"] = True
    for slot, x in zip(p0["shop"], s["shop"]):
        slot["frozen"] = bool(x.get("frozen"))
    for power, logged in zip(p0["powers"], me["hero_powers"]):
        if logged.get("exhausted"):
            power["uses_turn"] = max(1, power.get("uses_turn", 0))
        if logged.get("disabled"):  # a once-per-game power after its use
            power["uses_game"] = max(1, power.get("uses_game", 0))
            power["uses_turn"] = max(1, power.get("uses_turn", 0))
    # Per-minion counters the log shows in the card's script data
    if len(p0["board"]) == len(me["board"]):
        for m, logged in zip(p0["board"], me["board"]):
            k = COUNTER_FROM_DATA.get(normal_form(logged["card"])[0])
            if k is not None:
                m["counter"] = logged["data"][k]
    # Trinkets with a per-turn use the log counts down ("(1 left!)"): spent ones marked used
    for t in me["trinkets"]:
        if t["card"] in TRINKET_USES_LEFT and t["data"][0] == 0 and t["card"] in CAT:
            p0["turn_data"].append([CAT[t["card"]]["cid"], TRINKET_USES_LEFT[t["card"]]])
    for card, logged in zip(p0["hand"], hand_cards(me)):
        if logged.get("unplayable"):
            card["locked"] = max(1, card.get("locked", 0))
    g = taverngym.Game.from_json(json.dumps(st))
    return g, gaps


def choice_options(d):
    """(kind, offered) at a choice decision the advice can rebuild: "minion" (a Discover of
    minions: the logged minions), "trinket" (a trinket offer: card ids), "spell" (a Discover of
    Tavern spells: card ids) or "hero" (the heroes offered at the start: base hero ids);
    (None, []) for an Options decision and other choices (Hero Powers, mixed offers)."""
    if d.get("kind") != "choices":
        return None, []
    opts = d.get("options") or []
    if not opts:
        return None, []
    if all("minion" in o for o in opts):
        return "minion", [o["minion"] for o in opts]
    if d.get("choice_type") == "MULLIGAN" and all(o.get("type") == "HERO" for o in opts):
        return "hero", [base_hero(o.get("card") or "") for o in opts]
    kinds = {(CAT.get(normal_form(o.get("card") or "")[0]) or {}).get("kind") for o in opts}
    if kinds <= {"trinket_lesser", "trinket_greater"}:
        return "trinket", [o["card"] for o in opts]
    if kinds <= {"tavern_spell"}:
        return "spell", [o["card"] for o in opts]
    return None, []


def discover_options(d):
    """The minions offered at a choice decision (a Discover), or [] (an Options decision, or a
    choice that isn't between minions: trinkets, heroes)."""
    if d.get("kind") != "choices":
        return []
    opts = d.get("options") or []
    if not opts or any("minion" not in o for o in opts):
        return []
    return [o["minion"] for o in opts]


def hand_cards(me):
    """The cards in the logged hand, in order (the HAND zone also keeps the heroes not
    chosen at the start of the game)."""
    return [h for h in me.get("hand_all", []) if h.get("type") in ("MINION",) + SPELL_TYPES]


def add_spell(g, where, card, data, gaps):
    cid, _ = normal_form(card)
    if cid not in CAT or not CAT[cid]["kind"] in ("tavern_spell", "spell"):
        gaps.append(f"{where} spell {card}")
        return False
    try:
        debug(g, cmd="add_spell", p=0, zone=where, card=cid, data=int(data or 0))
    except ValueError as e:
        gaps.append(f"{where} spell {card}: {e}")
        return False
    return True


# ---------------------------------------------------------------------- legal actions

def action_kind(a):
    """(kind, slot) of TavernGym action `a` as the client's options name it, or None for the
    actions the client doesn't list (moves, choices, backing out)."""
    if a <= 3:
        return (("end", "refresh", "freeze", "upgrade")[a], 0)
    if a <= 5:
        return ("hero_power", a - 4)
    if a == 6:
        return ("dark_gift", 0)
    if 8 <= a <= 15:
        return ("buy", a - 8)
    if 16 <= a <= 22:
        return ("sell", a - 16)
    if 23 <= a <= 29:
        return ("activate", a - 23)
    if 46 <= a <= 125:
        return ("play", (a - 46) // 8)
    if 126 <= a <= 195:
        return ("play", (a - 126) // 7)  # magnetize: a way to play the hand card
    return None


def tavern_actions(mask):
    """Action kinds TavernGym allows: {(kind, slot)} from a legal mask (docs/TAVERNGYM.md)."""
    return {k for a, ok in enumerate(mask) if ok and (k := action_kind(a)) is not None}


def allowed_mask(mask, d):
    """TavernGym's legal mask restricted to what the client offers at decision `d` (moves,
    choices and Activates without a target can't be checked and stay allowed)."""
    client = client_actions(d)
    movable = movable_slots(d)
    out = []
    for a, ok in enumerate(mask):
        k = action_kind(a)
        out.append(bool(ok) and (k is None or k in client
                                 or (k[0] == "activate" and k[1] in movable)))
    return out


def client_actions(d):
    """The same kinds from the options the client offered (legal ones only)."""
    s = d["state"]
    shop = {x["eid"]: i for i, x in enumerate(s["shop"])}
    board = {m["eid"]: i for i, m in enumerate(s["friendly"]["board"])}
    hand = {h["eid"]: i for i, h in enumerate(hand_cards(s["friendly"]))}
    powers = {}
    out = set()
    for o in d["options"]:
        if not o["legal"]:
            continue
        e = o["entity"] or {}
        card = e.get("card") or ""
        if o["type"] == "END_TURN":
            out.add(("end", 0))
        elif "Reroll" in card:
            out.add(("refresh", 0))
        elif "LockAll" in card:
            out.add(("freeze", 0))
        elif "TechUp" in card:
            out.add(("upgrade", 0))
        elif card == "BG36_Button_DarkGift":
            out.add(("dark_gift", 0))
        elif e.get("type") == "HERO_POWER" and e.get("owner") == "friendly":
            out.add(("hero_power", powers.setdefault(e["eid"], len(powers))))
        elif card.startswith("TB_BaconShop_DragBuy"):
            for t in o["targets"]:
                if t["legal"] and t["entity"].get("eid") in shop:
                    out.add(("buy", shop[t["entity"]["eid"]]))
        elif card == "TB_BaconShop_DragSell":
            for t in o["targets"]:
                if t["legal"] and t["entity"].get("eid") in board:
                    out.add(("sell", board[t["entity"]["eid"]]))
        elif e.get("owner") == "friendly" and e.get("zone") == "HAND" and e["eid"] in hand:
            out.add(("play", hand[e["eid"]]))
        elif e.get("owner") == "friendly" and e.get("zone") == "PLAY" and e.get("type") == "MINION":
            # A warband minion: with targets an Activate, without one a move (not compared)
            if any(t["legal"] for t in o["targets"]) and e["eid"] in board:
                out.add(("activate", board[e["eid"]]))
    return out


def movable_slots(d):
    """Warband slots the client lists with a legal option and no target (move or Activate)."""
    board = {m["eid"]: i for i, m in enumerate(d["state"]["friendly"]["board"])}
    return {board[o["entity"]["eid"]] for o in d["options"]
            if o["legal"] and o["entity"] and o["entity"].get("eid") in board
            and o["entity"].get("zone") == "PLAY" and not o["targets"]}


def parity(decisions, limit=None, combats=()):
    """Per action kind: (both, client only, TavernGym only) over the decisions."""
    by_kind = collections.defaultdict(lambda: [0, 0, 0])
    examples = collections.defaultdict(list)
    n = exact = 0
    for d in decisions:
        if d["kind"] != "options" or d["turn"] % 2 == 0:
            continue
        g, gaps = build(d, game_combats(combats, d))
        tg = tavern_actions(json.loads(g.view(0))["mask"])
        cl = client_actions(d)
        # An Activate without a target looks like a move in the log: unverifiable, not a miss
        movable = movable_slots(d)
        unverified = {x for x in tg - cl if x[0] == "activate" and x[1] in movable}
        by_kind["activate (no target)"][0] += len(unverified)
        tg -= unverified
        n += 1
        exact += tg == cl
        for kind in {k for k, _ in tg | cl}:
            a = {x for x in tg if x[0] == kind}
            b = {x for x in cl if x[0] == kind}
            by_kind[kind][0] += len(a & b)
            by_kind[kind][1] += len(b - a)
            by_kind[kind][2] += len(a - b)
            if a != b and len(examples[kind]) < 5:
                examples[kind].append({"log": d["log"][-8:], "seg": d["segment"], "turn": d["turn"],
                                       "client_only": sorted(b - a), "tavern_only": sorted(a - b),
                                       "gaps": gaps})
        if limit and n >= limit:
            break
    return n, exact, dict(by_kind), dict(examples)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("decisions")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    decisions = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    combats_file = Path(a.decisions).with_name("combats.jsonl")
    combats = ([json.loads(l) for l in open(combats_file, encoding="utf-8")]
               if combats_file.is_file() else [])
    n, exact, by_kind, examples = parity(decisions, a.limit, combats)
    print(f"{n} recruit decisions; legal sets identical in {exact} ({exact / max(1, n):.1%})")
    print(f"{'kind':12s} {'both':>6s} {'client only':>12s} {'TavernGym only':>15s}")
    for kind, (both, c_only, t_only) in sorted(by_kind.items()):
        print(f"{kind:12s} {both:6d} {c_only:12d} {t_only:15d}")
    for kind, ex in examples.items():
        for e in ex[:3]:
            print("  ", kind, e)


if __name__ == "__main__":
    sys.exit(main())
