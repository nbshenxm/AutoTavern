"""How well does the network play each genre? For every curated comp (Tavern Link's catalog,
advisor.library.comp_starts), from its midgame at the given rounds, the network plays on in a
lobby like training's (three library seats: real players and comps at the top 1%'s strength).
Per comp:
- growth: seat 0's warband Attack+Health a few rounds later over the top 1%'s average then
  (1.0 = keeps up with the best players; the comp's own engine is what gets it there);
- core buys: of the turns the Tavern offered one of the comp's core cards it could afford, the
  share where it bought one;
- place: its final placement in those games.
The worst comps are the ones to train more (advisor.train --comp-starts weights them).

    python -X utf8 -m advisor.genres data/models/best.pt --rounds 7 9 --ahead 3 --trials 2
"""

import argparse
import collections
import json
from pathlib import Path

import numpy as np
import taverngym
import torch

from advisor import library, meta, search
from advisor.policy import load
from advisor.state import CAT, GAME_CONFIG, normal_form

ROOT = Path(__file__).resolve().parents[1]
L = dict(taverngym.layout())


def core_cards():
    """comp track -> the TavernGym card ids of its core cards."""
    cat = json.loads(meta.TAVERN_LINK.read_text(encoding="utf-8"))
    by_name = {m["name"]: m for m in cat.get("minions", [])}
    out = {}
    for comp in cat.get("comps", []):
        ids = set()
        for name in comp.get("core", []):
            m = by_name.get(name)
            c = meta._DBF.get(m["id"]) if m else None
            if c:
                ids.add(normal_form(c["id"])[0])
        out[f"comp:{comp['id']}"] = ids
    return out


_CFG = {}


def lobby_cfg():
    """The full rules of a training lobby with three library seats (comps included), built once."""
    if not _CFG:
        cfg = {**GAME_CONFIG, "library": library.library([5, 6, 7], comps=True)}
        _CFG.update(json.loads(taverngym.Game(1, json.dumps(cfg)).state_json())["cfg"])
    return _CFG


def play_comp(state, net, ahead, core, seed):
    """One game from a comp start: {growth, offered, bought, place}."""
    fresh = taverngym.Game(seed, json.dumps(GAME_CONFIG))
    st = json.loads(json.dumps(state))
    st["cfg"] = {**lobby_cfg(), "lobby_types": st["cfg"].get("lobby_types")}
    st["rng"] = json.loads(fresh.state_json())["rng"]
    g = taverngym.Game.from_json(json.dumps(st))
    start = g.turn
    curve = meta.warband_curve()
    offered = bought = 0
    end_stats = None
    turn_seen = None
    turn_offer, turn_bought = False, False
    for _ in range(200_000):
        if g.is_over():
            break
        moved = False
        for seat in range(g.num_players):
            if not g.needs_action(seat):
                continue
            v = json.loads(g.view(seat))
            if seat == 0 and v["turn"] > start + ahead:
                return finish(g, end_stats, curve, start + ahead, offered, bought)
            probs, _ = search._policy(net, g, seat)
            a = int(probs.argmax())
            if seat == 0 and v["phase"].lower() == "recruit" and not v["me"]["pending"]:
                me = v["me"]
                if turn_seen != v["turn"]:
                    if turn_seen is not None:
                        offered += turn_offer
                        bought += turn_bought
                    turn_seen, turn_offer, turn_bought = v["turn"], False, False
                room = len(me["hand"]) < 10
                for i, x in enumerate(me["shop"]):
                    if normal_form(x.get("id") or "")[0] in core and room and v["mask"][L["A_BUY"] + i]:
                        turn_offer = True
                        if a == L["A_BUY"] + i:
                            turn_bought = True
                if a == L["A_END"]:
                    end_stats = (v["turn"], sum(m["atk"] + m["hp"] for m in me["board"]))
            g.step(seat, a)
            moved = True
        if not moved:
            break
    return finish(g, end_stats, curve, start + ahead, offered, bought)


def finish(g, end_stats, curve, last, offered, bought):
    growth = None
    if end_stats and curve.get(end_stats[0]):
        growth = end_stats[1] / curve[end_stats[0]]
    place = g.placements()[0] if g.is_over() else None
    return {"growth": growth, "offered": offered, "bought": bought, "place": place}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("--rounds", type=int, nargs="+", default=[7, 9])
    ap.add_argument("--ahead", type=int, default=3)
    ap.add_argument("--trials", type=int, default=2)
    ap.add_argument("--json", help="write the scorecard here too")
    a = ap.parse_args()
    torch.set_num_threads(4)
    net, ck = load(a.checkpoint)
    cores = core_cards()
    rows = collections.defaultdict(list)
    for track, rnd, st in library.comp_starts(rounds=a.rounds, tagged=True):
        for t in range(a.trials):
            rows[track].append(play_comp(st, net, a.ahead, cores.get(track, set()), 1000 * rnd + t))
    names = {f"comp:{c['id']}": c["name"] for c in json.loads(meta.TAVERN_LINK.read_text(encoding="utf-8"))["comps"]}
    card = []
    for track, rs in rows.items():
        gr = [r["growth"] for r in rs if r["growth"] is not None]
        off = sum(r["offered"] for r in rs)
        card.append({"comp": track, "name": names.get(track, track),
                     "growth": round(float(np.median(gr)), 2) if gr else None,
                     "core_buys": round(sum(r["bought"] for r in rs) / off, 2) if off else None,
                     "offered_turns": off, "games": len(rs)})
    card.sort(key=lambda x: x["growth"] if x["growth"] is not None else 9)
    print(f"{a.checkpoint} ({ck.get('source') or ck.get('iteration')}): {a.ahead} rounds from rounds {a.rounds}")
    print(f"{'comp':34s} growth  core buys (turns offered)")
    for x in card:
        print(f"{x['name']:30s} {x['growth'] if x['growth'] is not None else '-':>8} "
              f"{x['core_buys'] if x['core_buys'] is not None else '-':>8} ({x['offered_turns']})")
    if a.json:
        Path(a.json).write_text(json.dumps({"checkpoint": a.checkpoint, "source": ck.get("source"),
                                            "comps": card}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
