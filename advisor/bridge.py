"""Live bridge: a logged recruit decision (advisor.decisions) as a TavernGym game.

Seat 0 is the player: hero, Hero Powers (used or not), trinkets, counters, Tier, health, armor,
Gold, upgrade cost, free refreshes, warband, hand (minions and spells in logged order) and the
Tavern (frozen flags). The other seats are the rest of the lobby.

`parity` compares TavernGym's legal actions at that state with the options the client offered,
by action kind and slot (docs/ROADMAP.md, M2):

    python -X utf8 -m advisor.bridge data/replay/decisions.jsonl
"""

import argparse
import collections
import json
import sys

import taverngym

from advisor.state import CAT, add_minion, debug, normal_form, recruit_game, set_side

SPELL_TYPES = ("SPELL", "BATTLEGROUND_SPELL")


def build(d, seed=7):
    """(game, gaps) for decision `d`."""
    s = d["state"]
    me = s["friendly"]
    gaps = []
    g = recruit_game(seed)
    debug(g, cmd="set_turn", turn=max(1, (d["turn"] + 1) // 2))
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
    debug(g, cmd="set_player", p=0, gold=me.get("gold", 0),
          upgrade_cost=costs.get("upgrade", 0),
          free_refreshes=1 if costs.get("refresh", 1) == 0 else 0)
    # Fields no debug command reaches: patched in the saved state
    st = json.loads(g.state_json())
    p0 = st["players"][0]
    # At an Options packet the player is not in a choice: drop what the stand-in hero opened
    p0["pending"] = []
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
    for card, logged in zip(p0["hand"], hand_cards(me)):
        if logged.get("unplayable"):
            card["locked"] = max(1, card.get("locked", 0))
    g = taverngym.Game.from_json(json.dumps(st))
    return g, gaps


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

def tavern_actions(mask):
    """Action kinds TavernGym allows: {(kind, slot)} from a legal mask (docs/TAVERNGYM.md)."""
    out = set()
    for a, ok in enumerate(mask):
        if not ok:
            continue
        if a <= 3:
            out.add((("end", "refresh", "freeze", "upgrade")[a], 0))
        elif a <= 5:
            out.add(("hero_power", a - 4))
        elif a == 6:
            out.add(("dark_gift", 0))
        elif 8 <= a <= 15:
            out.add(("buy", a - 8))
        elif 16 <= a <= 22:
            out.add(("sell", a - 16))
        elif 23 <= a <= 29:
            out.add(("activate", a - 23))
        elif 46 <= a <= 125:
            out.add(("play", (a - 46) // 8))
        elif 126 <= a <= 195:
            out.add(("play", (a - 126) // 7))  # magnetize: a way to play the hand card
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


def parity(decisions, limit=None):
    """Per action kind: (both, client only, TavernGym only) over the decisions."""
    by_kind = collections.defaultdict(lambda: [0, 0, 0])
    examples = collections.defaultdict(list)
    n = exact = 0
    for d in decisions:
        if d["kind"] != "options" or d["turn"] % 2 == 0:
            continue
        g, gaps = build(d)
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
    n, exact, by_kind, examples = parity(decisions, a.limit)
    print(f"{n} recruit decisions; legal sets identical in {exact} ({exact / max(1, n):.1%})")
    print(f"{'kind':12s} {'both':>6s} {'client only':>12s} {'TavernGym only':>15s}")
    for kind, (both, c_only, t_only) in sorted(by_kind.items()):
        print(f"{kind:12s} {both:6d} {c_only:12d} {t_only:15d}")
    for kind, ex in examples.items():
        for e in ex[:3]:
            print("  ", kind, e)


if __name__ == "__main__":
    sys.exit(main())
