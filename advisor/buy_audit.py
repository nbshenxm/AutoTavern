"""What does the network buy and sell where you built? Every probe on Nov 5 puts main1's gap in its
own mid-game play (an Upgrade is worth nothing to it in any lobby; its value head is right about
it). From your logged turns in rounds 5-12, your buys and sells and the network's greedy turn from
the same rebuilt start, each judged against the tribe your warband had at the turn's start:

- buys: on-tribe share; how often an affordable on-tribe minion was in the Tavern at the moment of
  a buy, and when it was, how often the buy took one (does it see the synergy, or not get offered);
- sells: the share that were on-tribe minions, golden ones;
- the warband at End Turn: on-tribe minions kept.

    python -X utf8 -m advisor.buy_audit data/models/archive/main1_it1400.pt --out data/audit/buys_main1.json
"""

import argparse
import collections
import json
from pathlib import Path

import numpy as np
import taverngym
import torch

from advisor import bridge, search
from advisor.compare_play import kind_of
from advisor.policy import load

ROOT = Path(__file__).resolve().parents[1]
L = dict(taverngym.layout())
BANDS = [("rounds 5-6", 5, 7), ("rounds 7-9", 7, 10), ("rounds 10-12", 10, 13)]


def races(m):
    return set(m.get("races") or [])


def on(m, tribe):
    r = races(m)
    return bool(tribe) and (tribe in r or "ALL" in r)


def top_tribe(board):
    c = collections.Counter(r for x in board for r in races(x) if r != "ALL")
    return c.most_common(1)[0][0] if c else None


def offered(view, tribe):
    """An affordable on-tribe minion in the Tavern."""
    me = view["me"]
    return any(x.get("type", "minion") == "minion" and on(x, tribe) and me["gold"] >= (x.get("price") or me["minion_price"])
               for x in me["shop"])


def buy_row(view, slot, tribe):
    me = view["me"]
    if slot >= len(me["shop"]) or me["shop"][slot].get("type", "minion") != "minion":
        return None
    m = me["shop"][slot]
    return {"on": on(m, tribe), "offered": offered(view, tribe), "tier": m.get("tier") or 0}


def sell_row(view, slot, tribe):
    me = view["me"]
    if slot >= len(me["board"]):
        return None
    m = me["board"][slot]
    return {"on": on(m, tribe), "golden": bool(m.get("golden")), "tier": m.get("tier") or 0}


def network_turn(g, net, tribe, max_steps=120):
    c = g.copy()
    buys, sells = [], []
    board = None
    for _ in range(max_steps):
        if not c.needs_action(0):
            break
        v = json.loads(c.view(0))
        probs, _ = search._policy(net, c, 0)
        a = int(probs.argmax())
        k = kind_of(a)
        if k == "buy":
            r = buy_row(v, a - L["A_BUY"], tribe)
            if r:
                buys.append(r)
        elif k == "sell":
            r = sell_row(v, a - L["A_SELL"], tribe)
            if r:
                sells.append(r)
        if a == L["A_END"] and not v["me"]["pending"]:
            board = v["me"]["board"]
            break
        c.step(0, a)
    return buys, sells, board


def logged_turn(ds, combats, tribe):
    """Your buys and sells in a turn, each judged on the state rebuilt where it was made."""
    buys, sells = [], []
    for d in ds:
        if d["kind"] != "options":
            continue
        ch = d.get("chosen") or {}
        opt = next((o for o in d["options"] if isinstance(ch, dict) and o["id"] == ch.get("option")), None)
        card = ((opt or {}).get("entity") or {}).get("card") or ""
        target = (ch.get("target") or {}).get("eid") if isinstance(ch.get("target"), dict) else None
        if target is None:
            continue
        if card.startswith("TB_BaconShop_DragBuy"):
            zone, rows, fn = "shop", buys, buy_row
        elif card == "TB_BaconShop_DragSell":
            zone, rows, fn = "board", sells, sell_row
        else:
            continue
        logged = d["state"]["shop"] if zone == "shop" else d["state"]["friendly"]["board"]
        slot = next((i for i, x in enumerate(logged) if x["eid"] == target), None)
        if slot is None:
            continue
        g, gaps = bridge.build(d, bridge.game_combats(combats, d))
        if gaps:
            continue
        r = fn(json.loads(g.view(0)), slot, tribe)
        if r:
            rows.append(r)
    return buys, sells


def summary(rows):
    out = {}
    for name, lo, hi in BANDS:
        rs = [r for r in rows if lo <= r["round"] < hi]
        if not rs:
            continue
        band = {"turns": len(rs)}
        for who in ("you", "net"):
            b = [x for r in rs for x in r[who]["buys"]]
            s = [x for r in rs for x in r[who]["sells"]]
            off = [x for x in b if x["offered"]]
            band[who] = {
                "buys_per_turn": round(len(b) / len(rs), 2),
                "on_tribe_share": round(float(np.mean([x["on"] for x in b])), 3) if b else None,
                "offered_at_buy": round(len(off) / len(b), 3) if b else None,
                "took_on_tribe_when_offered": round(float(np.mean([x["on"] for x in off])), 3) if off else None,
                "buy_tier": round(float(np.mean([x["tier"] for x in b])), 2) if b else None,
                "sells_per_turn": round(len(s) / len(rs), 2),
                "sold_on_tribe_share": round(float(np.mean([x["on"] for x in s])), 3) if s else None,
                "sold_golden_per_turn": round(sum(x["golden"] for x in s) / len(rs), 3),
                "on_tribe_kept_at_end": round(float(np.mean([r[who]["kept"] for r in rs if r[who]["kept"] is not None])), 2),
            }
        out[name] = band
    return out


@torch.no_grad()
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("--decisions", default=str(ROOT / "data" / "replay" / "decisions.jsonl"))
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    torch.set_num_threads(4)
    net = load(a.checkpoint, "cpu")[0].eval()
    decisions = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    turns = {}
    for d in decisions:
        if d["turn"] % 2 == 1 and 5 <= (d["turn"] + 1) // 2 <= 12:
            turns.setdefault((d["log"], d["segment"], d["turn"]), []).append(d)
    by_turn = {}
    for (log, seg, t), ds in turns.items():  # a reconnect splits a turn: its longest segment
        if len(ds) > len(by_turn.get((log, t), [])):
            by_turn[(log, t)] = ds
    rows = []
    for (log, t), ds in sorted(by_turn.items()):
        if a.limit and len(rows) >= a.limit:
            break
        d0 = next((d for d in ds if d["kind"] == "options"), None)
        if d0 is None:
            continue
        g, gaps = bridge.build(d0, bridge.game_combats(combats, d0))
        if gaps:
            continue
        v0 = json.loads(g.view(0))
        tribe = top_tribe(v0["me"]["board"])  # the rebuilt board's tribes (the log's may lack races)
        if not tribe:
            continue
        nb, ns, nboard = network_turn(g, net, tribe)
        yb, ys = logged_turn(ds, combats, tribe)
        last = ds[-1]
        ylast, gaps = bridge.build(last, bridge.game_combats(combats, last))
        yboard = None if gaps else json.loads(ylast.view(0))["me"]["board"]
        rows.append({"log": log, "round": (t + 1) // 2, "tribe": tribe,
                     "you": {"buys": yb, "sells": ys, "kept": sum(on(m, tribe) for m in yboard) if yboard else None},
                     "net": {"buys": nb, "sells": ns, "kept": sum(on(m, tribe) for m in nboard) if nboard else None}})
        if len(rows) % 25 == 0:
            print(len(rows), "turns", flush=True)
    res = {"checkpoint": a.checkpoint, "summary": summary(rows), "rows": rows}
    Path(a.out).write_text(json.dumps(res), encoding="utf-8")
    print(json.dumps(res["summary"], indent=1))


if __name__ == "__main__":
    main()
