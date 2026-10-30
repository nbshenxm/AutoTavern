"""Recruit-phase fidelity: replay the player's own actions in TavernGym and compare the warband
with the log. At each logged decision the bridge rebuilds the state, the option the player
chose is played in the simulator (buys, sells, playing a card at its position, Activates and
Hero Powers, with their target), and every warband minion's stats then are compared with the
next logged decision of the same turn. Mismatches are counted by the card that acted: a card
whose effect the simulator gets wrong (too weak, too strong, not at all) stands out; random
effects ("a random minion") mismatch now and then.

    python -X utf8 -m advisor.recruit_diff
"""

import argparse
import collections
import json
from pathlib import Path

from advisor import bridge
from advisor.state import CAT, normal_form

ROOT = Path(__file__).resolve().parents[1]
L = None


def chosen_actions(d):
    """The simulator actions for the option chosen at decision `d` ([action], target eid in
    the log or None, the acting card), or None for what can't be compared (End turn, a
    Refresh, Freeze, a level, the Dark Gift: random or no stats)."""
    ch = d.get("chosen")
    if not isinstance(ch, dict):
        return None
    opt = next((o for o in d["options"] if o["id"] == ch.get("option")), None)
    if opt is None or not opt["legal"]:
        return None
    s = d["state"]
    shop = {x["eid"]: i for i, x in enumerate(s["shop"])}
    board = {m["eid"]: i for i, m in enumerate(s["friendly"]["board"])}
    hand = {h["eid"]: i for i, h in enumerate(bridge.hand_cards(s["friendly"]))}
    e = opt["entity"] or {}
    card = e.get("card") or ""
    target = (ch.get("target") or {}).get("eid") if isinstance(ch.get("target"), dict) else None
    if card.startswith("TB_BaconShop_DragBuy") and target in shop:
        return [8 + shop[target]], None, s["shop"][shop[target]]["card"]
    if card == "TB_BaconShop_DragSell" and target in board:
        return [16 + board[target]], None, s["friendly"]["board"][board[target]]["card"]
    if e.get("owner") == "friendly" and e.get("zone") == "HAND" and e.get("eid") in hand:
        h = hand[e["eid"]]
        n = len(s["friendly"]["board"])
        pos = ch.get("position") or 0
        pos = min(n, max(0, pos - 1)) if pos > 0 else n
        return [46 + h * 8 + pos], target, card
    if e.get("owner") == "friendly" and e.get("zone") == "PLAY" and e.get("type") == "MINION" \
            and e.get("eid") in board and opt["targets"]:
        return [23 + board[e["eid"]]], target, card
    if e.get("type") == "HERO_POWER" and e.get("owner") == "friendly":
        return [4], target, card
    return None


def _target_choice(g, d, target):
    """The choice index of the logged target in the simulator's pending target, or None."""
    v = json.loads(g.view(0))
    pend = v["me"]["pending"] or {}
    if pend.get("kind") != "target":
        return None
    logged = d["state"]["friendly"]["board"]
    pos = next((i for i, m in enumerate(logged) if m["eid"] == target), None)
    if pos is None or pos >= len(v["me"]["board"]):
        return None
    eid = v["me"]["board"][pos]["eid"]
    opts = pend.get("targets") or [o.get("eid") for o in pend.get("options") or []]
    return opts.index(eid) if eid in opts else None


def compare(d, nxt, combats):
    """[(acting card, minion card, real (atk, hp), simulated (atk, hp))] for the warband after
    the chosen action, or None when it can't be replayed."""
    acts = chosen_actions(d)
    if acts is None:
        return None
    actions, target, acting = acts
    g, gaps = bridge.build(d, bridge.game_combats(combats, d))
    if gaps:
        return None
    try:
        for a in actions:
            g.step(0, a)
        if target is not None:
            i = _target_choice(g, d, target)
            if i is not None:
                g.step(0, L["A_CHOOSE"] + i)
    except ValueError:
        return None
    v = json.loads(g.view(0))
    if v["me"]["pending"]:
        return None  # a Discover or the like: what comes next is random
    real, sim = nxt["state"]["friendly"]["board"], v["me"]["board"]
    if len(real) != len(sim):
        return [(acting, "(warband size)", (len(real), 0), (len(sim), 0))]
    out = []
    for r, m in zip(real, sim):
        if normal_form(r["card"])[0] != normal_form(m["id"])[0]:
            return [(acting, "(warband order)", (0, 0), (0, 0))]
        out.append((acting, r["card"], (r["atk"], r["hp"]), (m["atk"], m["hp"])))
    return out


def main():
    global L
    import taverngym
    L = dict(taverngym.layout())
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisions", default=str(ROOT / "data" / "replay" / "decisions.jsonl"))
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.decisions, encoding="utf-8")]
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    rows = [d for d in rows if d["kind"] == "options" and d["turn"] % 2 == 1]
    by_card = collections.defaultdict(lambda: [0, 0, 0, 0])  # replays, mismatching, sum real, sum sim
    examples = {}
    n = ok = 0
    for d, nxt in zip(rows, rows[1:]):
        if (d["log"], d["segment"], d["turn"]) != (nxt["log"], nxt["segment"], nxt["turn"]):
            continue
        res = compare(d, nxt, combats)
        if res is None:
            continue
        n += 1
        acting = normal_form(res[0][0])[0] if res else None
        bad = [x for x in res if x[2] != x[3]]
        c = by_card[acting]
        c[0] += 1
        if bad:
            c[1] += 1
            c[2] += sum(x[2][0] + x[2][1] for x in bad)
            c[3] += sum(x[3][0] + x[3][1] for x in bad)
            examples.setdefault(acting, bad[:2])
        else:
            ok += 1
    print(f"{n} actions replayed; the warband matched the log exactly after {ok} ({ok / max(1, n):.1%})")
    print("acting card: replays, mismatching, real vs simulated stats of the mismatching minions")
    worst = sorted(by_card.items(), key=lambda kv: (-kv[1][1], -kv[1][0]))[:a.top]
    for card, (r, b, sr, ss) in worst:
        if not b:
            continue
        name = CAT.get(card, {}).get("name", card)
        ex = examples.get(card, [])
        print(f"  {name:28s} {r:4d} {b:4d}   real {sr:7d}  simulated {ss:7d}   e.g. "
              + "; ".join(f"{CAT.get(normal_form(x[1])[0], {}).get('name', x[1])} {x[2]} vs {x[3]}" for x in ex))


if __name__ == "__main__":
    main()
