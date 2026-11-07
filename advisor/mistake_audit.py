"""Plainly wasted plays in the network's turns, counted from your logged positions (Nov 6: you
found a buff on a Tavern minion it then neither bought nor froze). From the start of every logged
recruit turn (its first decision, rebuilt), the network's greedy turn as the advice plans it
(live's masks: no sell-and-replay detours, no double Freeze), but played on past random outcomes
to End Turn. Counted per turn:

- tavern_buff_unkept: a buff on a Tavern minion it then refreshes away or leaves in an unfrozen
  Tavern (not bought) (live.Waste, the advice's guardrail since Nov 6);
- buff_then_sold: a buff on a warband minion it then sells (live.Waste);
- freeze_then_refresh: a Freeze it undoes with a Refresh (live.Waste);
- refresh_then_broke: a paid Refresh after which it can't afford anything in the new Tavern and
  buys nothing more (the gold for the look is all it gets);
- gold_left: End Turn with gold for a minion in the Tavern and room in hand (unspent gold is
  lost; a bought minion can at least be sold for 1 next turn);
- minion_in_hand: End Turn with a minion in hand and a free warband slot;
- free_refresh_left: End Turn with a free Refresh unused and the Tavern not frozen;
- buy_then_sell: a minion bought and sold again in the same turn;
- hero_power_left / activate_left: End Turn with a Hero Power / a minion's Activate usable and
  affordable (gold left is lost); spell_in_hand: a Tavern spell kept in hand; hand_full: the
  hand at its limit (next turn's cards are lost).

Your rate of the End Turn checks comes from your own turns' last decision, rebuilt. Each kind
that is frequent for the network and rare for you is a guardrail candidate (live.plan_turn).

    python -X utf8 -m advisor.mistake_audit data/models/best.pt data/models/archive/R3.pt --out data/audit/mistakes.json
"""

import argparse
import json
from pathlib import Path

import numpy as np
import taverngym
import torch

from advisor import bridge, live, search
from advisor.policy import act, load

ROOT = Path(__file__).resolve().parents[1]
L = dict(taverngym.layout())
KINDS = ("tavern_buff_unkept", "buff_then_sold", "freeze_then_refresh", "refresh_then_broke", "gold_left", "minion_in_hand",
         "free_refresh_left", "buy_then_sell", "hero_power_left", "activate_left", "spell_in_hand", "hand_full")
END_KINDS = ("gold_left", "minion_in_hand", "free_refresh_left", "hero_power_left", "activate_left",
             "spell_in_hand", "hand_full")


def end_checks(view):
    """The End Turn checks on the view End Turn is pressed in."""
    me = view["me"]
    gold = me["gold"]
    mask = view.get("mask") or []
    legal = lambda a: a < len(mask) and bool(mask[a])
    minions = [m for m in me["shop"] if m.get("type", "minion") == "minion"]
    room = len(me["hand"]) < (me.get("hand_limit") or 10)
    return {
        "hero_power_left": any(not h.get("passive") and h.get("usable") and (h.get("price") or 0) <= gold
                               and legal(h.get("action", L["A_HERO_POWER"])) for h in me.get("hero_powers") or []),
        "activate_left": any(m.get("activate_cost") is not None and m["activate_cost"] <= gold and legal(L["A_ACTIVATE"] + i)
                             for i, m in enumerate(me["board"])),
        "spell_in_hand": any(h.get("type") == "spell" for h in me["hand"]),
        "hand_full": len(me["hand"]) >= (me.get("hand_limit") or 10),
        "gold_left": bool(room and any((m.get("price") or me["minion_price"]) <= gold for m in minions)),
        "minion_in_hand": bool(len(me["board"]) < 7 and any(h.get("type", "minion") == "minion" for h in me["hand"])),
        "free_refresh_left": bool((me.get("free_refreshes") or 0) > 0 and not me.get("frozen")
                                  and not any(m.get("frozen") for m in me["shop"])),
    }


def cheapest(me):
    return min([(m.get("price") if m.get("price") is not None else me["minion_price"]) for m in me["shop"]] or [99])


def network_turn(g, net, max_steps=120):
    """The counts of one greedy turn from `g` (seat 0), and the actions."""
    c = g.copy()
    found = dict.fromkeys(KINDS, False)
    sold, bought, steps = {}, set(), []
    waste = live.Waste()
    broke_after = None  # gold after a paid Refresh left nothing affordable: wasted unless a buy follows
    view = json.loads(c.view(0))
    for _ in range(max_steps):
        if not c.needs_action(0):
            break
        mask = search.detour_mask(view, sold)
        a, _, _ = act(net, c, 0, mask)
        a = int(a)
        search.note_sold(view, a, sold)
        me = view["me"]
        if L["A_BUY"] <= a < L["A_SELL"] and a - L["A_BUY"] < len(me["shop"]):
            bought.add(me["shop"][a - L["A_BUY"]].get("eid"))
            broke_after = None
        if L["A_SELL"] <= a < L["A_ACTIVATE"] and a - L["A_SELL"] < len(me["board"]):
            if me["board"][a - L["A_SELL"]].get("eid") in bought:
                found["buy_then_sell"] = True
        if a == L["A_END"] and not me.get("pending"):
            found.update(end_checks(view))
            waste.step(len(steps), view, a, view)
            if broke_after is not None:
                found["refresh_then_broke"] = True
            steps.append(a)
            break
        paid = a == L["A_REFRESH"] and not (me.get("free_refreshes") or 0) and (me.get("refresh_price") or 0) > 0
        c.step(0, a)
        steps.append(a)
        after = json.loads(c.view(0))
        waste.step(len(steps) - 1, view, a, after)
        if paid:
            broke_after = after["me"]["gold"] if after["me"]["gold"] < cheapest(after["me"]) else None
        view = after
    for kind in waste.kinds:
        found[{"board": "buff_then_sold", "freeze": "freeze_then_refresh"}.get(kind, "tavern_buff_unkept")] = True
    return found, steps


def turns(decisions):
    """{(log, turn): the turn's decisions} for recruit turns, a reconnect's longest segment."""
    by = {}
    for d in decisions:
        if d["turn"] % 2 == 1:
            by.setdefault((d["log"], d["segment"], d["turn"]), []).append(d)
    out = {}
    for (log, seg, t), ds in by.items():
        if len(ds) > len(out.get((log, t), [])):
            out[(log, t)] = ds
    return out


@torch.no_grad()
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoints", nargs="+")
    ap.add_argument("--decisions", default=str(ROOT / "data" / "replay" / "decisions.jsonl"))
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    torch.set_num_threads(4)
    nets = {p: load(p, "cpu")[0].eval() for p in a.checkpoints}
    decisions = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    rows = []
    for (log, t), ds in sorted(turns(decisions).items()):
        if a.limit and len(rows) >= a.limit:
            break
        d0 = next((d for d in ds if d["kind"] == "options"), None)
        last = next((d for d in reversed(ds) if d["kind"] == "options"), None)
        if d0 is None:
            continue
        g, gaps = bridge.build(d0, bridge.game_combats(combats, d0))
        if gaps:
            continue
        row = {"log": log, "round": (t + 1) // 2, "net": {}}
        for p, net in nets.items():
            found, steps = network_turn(g, net)
            row["net"][p] = {"found": found, "steps": steps}
        gy, gaps = bridge.build(last, bridge.game_combats(combats, last))
        row["you"] = None if gaps else end_checks(json.loads(gy.view(0)))
        rows.append(row)
        if len(rows) % 50 == 0:
            print(len(rows), "turns", flush=True)
    summary = {"turns": len(rows)}
    for p in nets:
        summary[p] = {k: round(float(np.mean([r["net"][p]["found"][k] for r in rows])), 3) for k in KINDS}
        summary[p]["by_round"] = {
            band: {k: round(float(np.mean([r["net"][p]["found"][k] for r in rows if lo <= r["round"] <= hi] or [0])), 3) for k in KINDS}
            for band, lo, hi in (("1-4", 1, 4), ("5-8", 5, 8), ("9+", 9, 99))}
    yours = [r["you"] for r in rows if r["you"]]
    summary["you"] = {k: round(float(np.mean([y[k] for y in yours])), 3) for k in END_KINDS} if yours else None
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"summary": summary, "rows": rows}), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
