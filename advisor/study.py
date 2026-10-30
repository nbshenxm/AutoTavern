"""Case study of the network's own games: where does it play badly? Complete games with the
network in every seat (sampled, as in training, or greedy), and per seat and turn: the Tavern Tier
reached, the actions taken, and what was left on the table when it ended the turn (gold with a
Refresh possible, an affordable buy with room, an empty slot with a minion in hand, a usable Hero
Power or Dark Gift). `--trace N` prints the first N games turn by turn for seat 0.

    python -X utf8 -m advisor.study data/models/best.pt --games 40 --trace 2
    python -X utf8 -m advisor.study --teacher --games 40      # the teacher bot, for comparison
    python -X utf8 -m advisor.study data/models/best.pt --curve data/progress/curve.json
"""

import argparse
import collections
import json

import numpy as np
import torch

import taverngym
from advisor import search
from advisor.policy import load
from advisor.state import GAME_CONFIG

L = dict(taverngym.layout())
A_BUY, A_SELL, A_PLAY = L["A_BUY"], L["A_SELL"], L["A_PLAY"]
N_SHOP = L["N_SHOP"]


def kind(a):
    return taverngym.action_name(int(a)).split(" ")[0].split("(")[0]


def short(m):
    return f"{'*' if m.get('golden') else ''}{m['name']} {m['atk']}/{m['hp']}"


def play(seed, net, sample, teacher_config=None, trace=False):
    """One game: a record per (seat, turn) and the placements; the trace lines of seat 0."""
    config = teacher_config or GAME_CONFIG
    g = taverngym.Game(seed, json.dumps(config))
    rng = np.random.default_rng(seed)
    recs, lines = {}, []
    for _ in range(200_000):
        if g.is_over():
            break
        for seat in range(g.num_players):
            if not g.needs_action(seat):
                continue
            v = json.loads(g.view(seat))
            me, mask = v["me"], np.array(v["mask"], bool)
            key = (seat, v["turn"])
            r = recs.get(key)
            if r is None and v["phase"].lower() == "recruit":
                r = recs[key] = {"tier0": me["tier"], "gold0": me["gold"], "hp0": me["health"] + me["armor"],
                                 "acts": collections.Counter(), "names": []}
            if net is None:
                a = g.bot_action(seat)
            else:
                probs, _ = search._policy(net, g, seat)
                a = int(rng.choice(len(probs), p=probs / probs.sum())) if sample else int(probs.argmax())
            k = kind(a)
            if r is not None:
                r["acts"][k] += 1
                r["names"].append(taverngym.action_name(int(a)))
                if k == "EndTurn" and not me["pending"]:
                    room = len(me["board"]) < 7
                    hand_minions = [h for h in me["hand"] if h.get("kind", "minion") == "minion" or "atk" in h]
                    r.update(tier=me["tier"], gold=me["gold"], frozen=bool(me["frozen"]),
                             refresh_ok=bool(mask[L["A_REFRESH"]]) and not me["frozen"],
                             buy_ok=bool(mask[A_BUY:A_BUY + N_SHOP].any()) and room,
                             upgrade_ok=bool(mask[L["A_UPGRADE"]]),
                             power_ok=bool(mask[L["A_HERO_POWER"]:L["A_HERO_POWER"] + 2].any()),
                             gift_ok=bool(mask[L["A_DARK_GIFT"]]),
                             unplayed=bool(room and hand_minions), board=len(me["board"]),
                             hand=len(me["hand"]), warband=[short(m) for m in me["board"]],
                             golden=sum(1 for m in me["board"] if m.get("golden")))
            g.step(seat, a)
    places = list(g.placements())
    if trace:
        for (seat, turn), r in sorted(recs.items()):
            if seat or "tier" not in r:
                continue
            acts = " ".join(n.replace(" { ", "{").replace(" }", "}") for n in r["names"])
            lines.append(f"T{turn:<2} tier {r['tier0']}->{r['tier']} gold {r['gold0']} hp {r['hp0']:<3} | "
                         f"{acts[:160]} | left {r['gold']} | {', '.join(r['warband'])}")
        lines.append(f"place {places[0]}")
    return recs, places, lines


def summarize(all_recs, label):
    by_turn = collections.defaultdict(list)
    for recs in all_recs:
        for (seat, turn), r in recs.items():
            if "tier" in r:
                by_turn[turn].append(r)
    cols = ["tier", "up%", "gold left", "refresh?", "buy?", "unplayed", "power?", "gift?", "refr", "buys",
            "sells", "moves", "board"]
    print(f"\n{label}: per turn, over every seat (the '?' columns: share of turns ended with it possible)")
    print("turn " + " ".join(f"{c:>9}" for c in cols))
    for t in sorted(by_turn):
        rs = by_turn[t]
        if t > 16 or len(rs) < 10:
            continue
        m = lambda f: float(np.mean([f(r) for r in rs]))
        vals = [m(lambda r: r["tier"]), 100 * m(lambda r: r["tier"] > r["tier0"]), m(lambda r: r["gold"]),
                100 * m(lambda r: r["refresh_ok"] and r["gold"] > 0), 100 * m(lambda r: r["buy_ok"]),
                100 * m(lambda r: r["unplayed"]), 100 * m(lambda r: r["power_ok"]), 100 * m(lambda r: r["gift_ok"]),
                m(lambda r: r["acts"]["Refresh"]), m(lambda r: r["acts"]["Buy"]), m(lambda r: r["acts"]["Sell"]),
                m(lambda r: r["acts"]["Move"]), m(lambda r: r["board"])]
        print(f"{t:4d} " + " ".join(f"{x:9.2f}" if i in (0, 2, 8, 9, 10, 11, 12) else f"{x:8.0f}%"
                                    for i, x in enumerate(vals)))


def warband_stats(r):
    return sum(int(a) + int(b) for a, b in (x.rsplit(" ", 1)[1].split("/") for x in r["warband"]))


def curve(net, games=16, seed=92_000_000):
    """By round: the median warband Attack+Health and mean Tavern Tier of the network's seats in
    its own games, with the same for the real lobbies in the logs (both warbands of every
    combat) and the public average (Firestone's warband stats over all heroes)."""
    import collections
    from pathlib import Path
    sim = collections.defaultdict(list)
    for i in range(games):
        recs, _, _ = play(seed + i, net, True)
        for (_, turn), r in recs.items():
            if "tier" in r:
                sim[turn].append((warband_stats(r), r["tier"]))
    real = collections.defaultdict(list)
    combats = Path(__file__).resolve().parents[1] / "data" / "replay" / "combats.jsonl"
    if combats.exists():
        for line in open(combats, encoding="utf-8"):
            c = json.loads(line)
            for side in ("friendly", "opponent"):
                b = c["start"][side]["board"]
                real[(c["turn"] + 1) // 2].append((sum(m["atk"] + m["hp"] for m in b),
                                                   c["start"][side]["tier"]))
    from advisor import meta
    public = collections.defaultdict(list)
    for h in meta.hero_stats().values():
        for t, v in h["warband"].items():
            public[int(t)].append((v, h["n"]))
    out = []
    for t in range(1, 17):
        row = {"round": t}
        for name, d in (("network", sim), ("your_lobbies", real)):
            if len(d.get(t, ())) >= 3:
                row[name] = {"stats": float(np.median([x[0] for x in d[t]])),
                             "tier": float(np.mean([x[1] for x in d[t]])), "n": len(d[t])}
        if public.get(t):
            v, w = zip(*public[t])
            row["public"] = {"stats": float(np.average(v, weights=w))}
        out.append(row)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint", nargs="?")
    ap.add_argument("--teacher", action="store_true", help="the teacher bot in every seat instead")
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--greedy", action="store_true", help="the network's first choice (default: sampled)")
    ap.add_argument("--trace", type=int, default=0)
    ap.add_argument("--seed", type=int, default=90_000_000)
    ap.add_argument("--curve", metavar="OUT", help="only the strength curve, as JSON (curve())")
    a = ap.parse_args()
    if a.curve:
        torch.set_num_threads(4)
        net, ck = load(a.checkpoint, "cpu")
        from datetime import datetime
        from pathlib import Path
        Path(a.curve).write_text(json.dumps({"network": ck.get("source"), "made": datetime.now().isoformat(timespec="seconds"),
                                             "rounds": curve(net, a.games)}), encoding="utf-8")
        return
    torch.set_num_threads(4)
    net, teacher_config = None, None
    if a.teacher:
        from advisor.pretrain import TEACHER_CONFIG
        teacher_config = TEACHER_CONFIG
    else:
        net, _ = load(a.checkpoint, "cpu")
    all_recs = []
    for i in range(a.games):
        recs, places, lines = play(a.seed + i, net, not a.greedy, teacher_config, trace=i < a.trace)
        all_recs.append(recs)
        if lines:
            print(f"\n--- game {i} (seed {a.seed + i}), seat 0 ---")
            print("\n".join(lines))
    summarize(all_recs, "teacher" if a.teacher else a.checkpoint)


if __name__ == "__main__":
    main()
