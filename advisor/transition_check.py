"""Turn transitions against the log: from the player's last decision of a turn (End Turn), TavernGym
plays the end of the turn, the combat (against the stand-ins the bridge builds) and the next
turn's start; the player's state there is compared with the log's first decision of that next
turn. What doesn't depend on the combat's random outcome is compared: Gold, maximum Gold, the
upgrade cost, Tier, the Tavern's size, the hand (cards that arrive at the start of a turn or the
end of one) and the warband's stats when the log shows the same minions (end-of-turn effects;
combat effects that last make some of these legitimately differ: listed apart).

    python -X utf8 -m advisor.transition_check
"""

import argparse
import collections
import json
from pathlib import Path

from advisor import bridge
from advisor.state import CAT, normal_form

ROOT = Path(__file__).resolve().parents[1]


def _key(c):
    return normal_form(c or "")[0]


def next_turn(g, max_steps=5000):
    """Play End Turn for seat 0, the stand-ins' turns (scripted bot) and the combat, until seat 0
    is in its next recruit turn; the view then, or None."""
    turn = g.turn
    g.step(0, 0)
    for _ in range(max_steps):
        if g.is_over():
            return None
        if g.turn > turn and g.needs_action(0):
            v = json.loads(g.view(0))
            if v["phase"].lower() == "recruit":
                return v
        moved = False
        for p in range(g.num_players):
            if g.needs_action(p) and not (p == 0 and g.turn > turn):
                g.step(p, g.bot_action(p))
                moved = True
        if not moved and g.needs_action(0):
            g.step(0, g.bot_action(0))  # a choice at the turn's start (an offer)
    return None


def compare(v, d):
    me, real = v["me"], d["state"]["friendly"]
    out = {}
    for f, sim, log in (("gold", me["gold"], real.get("gold")), ("max gold", me.get("max_gold"), real.get("max_gold")),
                        ("tier", me["tier"], real.get("tier")),
                        ("upgrade cost", me.get("upgrade_price", me.get("upgrade_cost")), (real.get("costs") or {}).get("upgrade")),
                        ("tavern size", len(me.get("shop") or v.get("shop") or []), len(d["state"]["shop"]))):
        if log is not None and sim is not None and sim != log:
            out[f] = (log, sim)
    rh = sorted(_key(h["card"]) for h in bridge.hand_cards(real) if h.get("card"))
    sh = sorted(_key(h.get("id")) for h in me["hand"] if h.get("id"))
    if rh != sh:
        out["hand"] = (rh, sh)
    rb, sb = real["board"], me["board"]
    if [_key(m["card"]) for m in rb] == [_key(m["id"]) for m in sb]:
        diff = [(m["card"], (m["atk"], m["hp"]), (x["atk"], x["hp"])) for m, x in zip(rb, sb)
                if (m["atk"], m["hp"]) != (x["atk"], x["hp"])]
        if diff:
            out["warband stats"] = diff
    else:
        out["warband cards (combat)"] = ([m["card"] for m in rb], [m["id"] for m in sb])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisions", default=str(ROOT / "data" / "replay" / "decisions.jsonl"))
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--examples", type=int, default=4)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    by_turn = collections.defaultdict(list)
    for d in rows:
        if d["kind"] == "options" and d["turn"] % 2 == 1:
            by_turn[(d["log"], d["segment"], d["turn"])].append(d)
    fields, examples = collections.Counter(), collections.defaultdict(list)
    n = clean = 0
    for (log, seg, turn), ds in sorted(by_turn.items()):
        nxt = by_turn.get((log, seg, turn + 2))
        last = ds[-1]
        ch = last.get("chosen") or {}
        opt = next((o for o in last["options"] if o["id"] == ch.get("option")), None)
        # (the log doesn't record the End Turn answer: a turn's last decision has none)
        if not nxt or (opt is not None and opt["type"] != "END_TURN"):
            continue
        g, gaps = bridge.build(last, bridge.game_combats(combats, last))
        if gaps:
            continue
        try:
            v = next_turn(g)
        except ValueError:
            continue
        if v is None:
            continue
        n += 1
        diff = compare(v, nxt[0])
        clean += not {f for f in diff if not f.startswith("warband cards")}
        for f, x in diff.items():
            fields[f] += 1
            if len(examples[f]) < a.examples:
                hero = CAT.get(last["state"]["friendly"]["hero"], {}).get("name")
                examples[f].append((log[-8:], seg, (turn + 1) // 2, hero, x))
    print(f"{n} turn transitions; {clean} ({clean / max(1, n):.1%}) match the log (combat-dependent warband changes aside)")
    print("mismatches by field:", dict(fields.most_common()))
    for f, ex in examples.items():
        print(f"\n{f}:")
        for e in ex:
            print("  ", str(e)[:350])


if __name__ == "__main__":
    main()
