"""Whole-turn fidelity: the player's logged turn replayed in TavernGym from its first decision
alone, and the state compared with the log after every action. advisor.recruit_diff rebuilds
the state before each action, so it can't see what builds up over a turn: gold spent and
gained, per-turn limits (an Activate used, free Refreshes, Freeze presses), counters that
advance, cards that arrive in hand at the end of an effect. Here nothing is rebuilt but what is
random: after a Refresh (or any action) the Tavern is set to the next logged one, and a Discover
takes the card the player picked. Whatever still differs piles up from TavernGym's own rules.

Mismatches are counted by field (gold, Tavern Tier, warband stats, warband cards, hand cards)
and by the card that acted just before the state first parted, with examples.

    python -X utf8 -m advisor.turn_replay
"""

import argparse
import collections
import json
from pathlib import Path

from advisor import bridge, recruit_diff
from advisor.state import CAT, add_minion, debug, normal_form

ROOT = Path(__file__).resolve().parents[1]


def _key(c):
    return normal_form(c or "")[0]


def action_of(d, L, g=None):
    """([actions], target eid or None, acting card) for the option chosen at Options decision
    `d`, or None for what isn't replayed (End Turn: the turn is over). With TavernGym's game `g`,
    a card played from hand is found there by what it is (the two hands may be in another
    order: a fresh golden goes to the end in one and not the other)."""
    acts = recruit_diff.chosen_actions(d)
    if acts is not None:
        actions, target, card = acts
        a = actions[0]
        if g is not None and L["A_PLAY"] <= a < L["A_MAGNETIZE"]:
            h, pos = divmod(a - L["A_PLAY"], L["N_POS"])
            hand = json.loads(g.view(0))["me"]["hand"]
            if not (h < len(hand) and _key(hand[h].get("id")) == _key(card)):
                same = [i for i, x in enumerate(hand) if _key(x.get("id")) == _key(card)]
                if same:
                    actions = [L["A_PLAY"] + same[0] * L["N_POS"] + pos] + actions[1:]
        return actions, target, card
    ch = d.get("chosen")
    opt = next((o for o in d["options"] if isinstance(ch, dict) and o["id"] == ch.get("option")), None)
    if opt is None:
        return None
    card = ((opt.get("entity") or {}).get("card")) or ""
    for part, a in (("Reroll", "A_REFRESH"), ("LockAll", "A_FREEZE"), ("TechUp", "A_UPGRADE")):
        if part in card:
            return [L[a]], None, card
    if card == "BG36_Button_DarkGift":
        return [L["A_DARK_GIFT"]], None, card
    return None


def compare(v, s):
    """{field: (logged, simulated)} where TavernGym's view `v` and logged state `s` differ."""
    me, real = v["me"], s["friendly"]
    out = {}
    if me["gold"] != real.get("gold", me["gold"]):
        out["gold"] = (real.get("gold"), me["gold"])
    if real.get("tier") and me["tier"] != real["tier"]:
        out["tier"] = (real["tier"], me["tier"])
    rb, sb = real["board"], me["board"]
    if [_key(m["card"]) for m in rb] != [_key(m["id"]) for m in sb]:
        out["board cards"] = ([m["card"] for m in rb], [m["id"] for m in sb])
    else:
        diff = [(m["card"], (m["atk"], m["hp"]), (x["atk"], x["hp"])) for m, x in zip(rb, sb)
                if (m["atk"], m["hp"]) != (x["atk"], x["hp"])]
        if diff:
            out["board stats"] = diff
    rh = sorted(_key(h["card"]) for h in bridge.hand_cards(real) if h.get("card"))
    sh = sorted(_key(h.get("id")) for h in me["hand"] if h.get("id"))
    if rh != sh:
        out["hand cards"] = (rh, sh)
    return out


def set_shop(g, s):
    """TavernGym's Tavern set to the logged one (what a Refresh or a Tavern effect drew)."""
    debug(g, cmd="clear_zone", p=0, zone="shop")
    gaps = []
    for x in s["shop"]:
        if x["kind"] == "minion":
            add_minion(g, 0, "shop", x, gaps, "shop")
        else:
            bridge.add_spell(g, "shop", x["card"], x.get("data", [0])[0], gaps)
    st = json.loads(g.state_json())
    for slot, x in zip(st["players"][0]["shop"], s["shop"]):
        slot["frozen"] = bool(x.get("frozen"))
    import taverngym
    return taverngym.Game.from_json(json.dumps(st))


def pick(g, choice, L):
    """Answer TavernGym's open choice with the card the player picked; False when it can't."""
    v = json.loads(g.view(0))
    pend = v["me"]["pending"]
    if not pend:
        return False
    chosen = [c.get("card") for c in (choice.get("chosen") or []) if isinstance(c, dict)]
    want = _key(chosen[0]) if chosen else None
    for i, o in enumerate(pend.get("options") or []):
        card = o.get("id") if isinstance(o, dict) else o
        if want and _key(card) == want:
            g.step(0, L["A_CHOOSE"] + i)
            return True
    return False


def replay_turn(turn, combats, L):
    """[(step, acting card, {field: (logged, simulated)})] for one turn's decisions (Options and
    choices in log order): at each Options decision the simulated state is compared with the
    logged one (first mismatch per field only), then its Tavern is set to the logged one and the
    player's action is played; a choice is answered with the player's pick. None when the turn
    can't start."""
    # A turn's leading choices (a trinket offer, a turn-start Discover) are skipped: their state
    # is a snapshot taken mid-block, not the turn's start
    while turn and turn[0]["kind"] != "options":
        turn = turn[1:]
    if not turn:
        return None
    first = turn[0]
    g, gaps = bridge.build(first, bridge.game_combats(combats, first))
    if gaps:
        return None
    out, parted, acting = [], set(), None
    for k, d in enumerate(turn):
        v = json.loads(g.view(0))
        if d["kind"] != "options":
            if v["me"]["pending"] and not pick(g, d, L):
                break  # TavernGym offers other cards (random) or another kind of choice
            continue
        if v["me"]["pending"]:
            break  # a choice TavernGym opened that the log doesn't show
        if k:
            diff = {f: x for f, x in compare(v, d["state"]).items() if f not in parted}
            if diff:
                out.append((k, acting, diff))
                parted |= set(diff)
            g = set_shop(g, d["state"])  # random draws follow the log
        act = action_of(d, L, g)
        if act is None:
            break
        actions, target, acting = act
        try:
            for a in actions:
                g.step(0, a)
            if target is not None:
                i = recruit_diff._target_choice(g, d, target)
                if i is not None:
                    g.step(0, L["A_CHOOSE"] + i)
        except ValueError:
            out.append((k, acting, {"refused": (_key(acting), "TavernGym refused the logged action")}))
            break
    return out


def main():
    import taverngym
    L = dict(taverngym.layout())
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisions", default=str(ROOT / "data" / "replay" / "decisions.jsonl"))
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--examples", type=int, default=3)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    turns = collections.defaultdict(list)
    for d in rows:
        if d["turn"] % 2 == 1 and d["turn"] > 0:
            turns[(d["log"], d["segment"], d["turn"])].append(d)
    fields, by_card, examples = collections.Counter(), collections.Counter(), collections.defaultdict(list)
    n = clean = 0
    for key, turn in sorted(turns.items()):
        res = replay_turn(turn, combats, L)
        if res is None:
            continue
        n += 1
        clean += not res
        for k, acting, diff in res:
            for f, x in diff.items():
                fields[f] += 1
                by_card[(f, str(CAT.get(_key(acting), {}).get("name", acting)))] += 1
                if len(examples[f]) < a.examples:
                    examples[f].append((key[0][-8:], key[1], (key[2] + 1) // 2, k,
                                        CAT.get(_key(acting), {}).get("name", acting), x))
    print(f"{n} turns replayed whole; {clean} ({clean / max(1, n):.1%}) never parted from the log")
    print("first mismatch per turn and field:", dict(fields.most_common()))
    print("by field and the card that acted just before:")
    for (f, card), c in by_card.most_common(25):
        print(f"  {f:12s} {card:30s} {c}")
    for f, ex in examples.items():
        print(f"\n{f}:")
        for e in ex:
            print("  ", str(e)[:400])


if __name__ == "__main__":
    main()
