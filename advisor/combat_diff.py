"""Where does a simulated combat part from the real one? For a logged combat (its attacks as the
log recorded them: attacker, defender, both with their stats), many simulated trials from the
same start (advisor.replay's setup, the logged first attacker); the trial that follows the real
attacks longest; and the first attack where it parts: a different attacker (the simulator's
order), a defender no trial picked (Taunt, Stealth...), or the same pair with different stats
(an effect the simulator gets wrong). Targets are random, so a trial only matches as far as
its random picks happen to.

    python -X utf8 -m advisor.combat_diff                 # the combats the simulator found least likely
    python -X utf8 -m advisor.combat_diff --log 09_51_50 --segment 7 --turn 18
"""

import argparse
import json
from pathlib import Path

from advisor import replay
from advisor.state import CAT, debug, normal_form

ROOT = Path(__file__).resolve().parents[1]


def _id(card):
    return normal_form(card or "")[0]


def sim_attacks(c, seed):
    """One simulated trial's attacks: [{side, attacker, atk, hp, defender, datk, dhp}]."""
    g, _ = replay.setup(c, c["start"], seed)
    first = 0 if c["first_attacker"] == "friendly" else 1
    r = debug(g, cmd="combat_preview", a=0, b=1, n=1, after_start=False)
    frames = (r.get("sample") or {}).get("frames") or []
    out, before = [], {}
    for f in frames:
        for side, board in enumerate(f["boards"]):
            for m in board:
                before.setdefault(m["eid"], (side, m))
        for a, d in f.get("attacks") or []:
            sa, ma = before.get(a, (None, {}))
            _, md = before.get(d, (None, {}))
            out.append({"side": "friendly" if sa == 0 else "opponent", "attacker": ma.get("id"),
                        "atk": ma.get("atk"), "hp": ma.get("hp"), "defender": md.get("id"),
                        "datk": md.get("atk"), "dhp": md.get("hp")})
        before = {m["eid"]: (side, m) for side, board in enumerate(f["boards"]) for m in board}
    return out, first


def diff(c, trials=300):
    """{matched: attacks the best trial follows, of: real attacks, part: what differs first}."""
    real = c.get("attacks") or []
    best, best_sim = -1, []
    for t in range(trials):
        sim, _ = sim_attacks(c, 1000 + t)
        k = 0
        while k < min(len(real), len(sim)):
            a, b = real[k], sim[k]
            same = (a["side"] == b["side"] and _id(a["attacker"]) == _id(b["attacker"])
                    and _id(a["defender"]) == _id(b["defender"])
                    and (a["atk"], a["hp"], a["datk"], a["dhp"]) == (b["atk"], b["hp"], b["datk"], b["dhp"]))
            if not same:
                break
            k += 1
        if k > best:
            best, best_sim = k, sim
        if best == len(real):
            break
    part = None
    if best < len(real):
        a = real[best]
        b = best_sim[best] if best < len(best_sim) else None
        name = lambda x: CAT.get(_id(x), {}).get("name", x)
        if b is None:
            part = f"attack {best + 1}: the simulated combat ended; the real one went on ({name(a['attacker'])} attacks)"
        elif _id(a["attacker"]) != _id(b["attacker"]) or a["side"] != b["side"]:
            part = (f"attack {best + 1}: real {a['side']} {name(a['attacker'])} {a['atk']}/{a['hp']}, "
                    f"simulated {b['side']} {name(b['attacker'])} {b['atk']}/{b['hp']}")
        elif _id(a["defender"]) != _id(b["defender"]):
            part = (f"attack {best + 1}: {name(a['attacker'])} hits {name(a['defender'])} for real, "
                    f"{name(b['defender'])} in the closest trial")
        else:
            part = (f"attack {best + 1}: {name(a['attacker'])} {a['atk']}/{a['hp']} on {name(a['defender'])} "
                    f"{a['datk']}/{a['dhp']} for real; simulated {b['atk']}/{b['hp']} on {b['datk']}/{b['dhp']}")
    return {"matched": best, "of": len(real), "part": part}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--combats", default=str(ROOT / "data" / "replay" / "combats.jsonl"))
    ap.add_argument("--log")
    ap.add_argument("--segment", type=int)
    ap.add_argument("--turn", type=int)
    ap.add_argument("--worst", type=int, default=8, help="the N least likely combats (replay report)")
    ap.add_argument("--trials", type=int, default=300)
    a = ap.parse_args()
    combats = [json.loads(l) for l in open(a.combats, encoding="utf-8")]
    if a.log:
        pick = [c for c in combats if c["log"].endswith(a.log) and c["turn"] == a.turn
                and (a.segment is None or c["segment"] == a.segment)]
    else:
        rep = json.loads((Path(a.combats).parent / "replay_report.json").read_text(encoding="utf-8"))
        worst = sorted((r for r in rep["rows"] if r["mode"] == "start"), key=lambda r: r["p_win"])[:a.worst]
        keys = {(r["log"], r["segment"], r["turn"]) for r in worst}
        pick = [c for c in combats if (c["log"], c["segment"], c["turn"]) in keys]
    for c in pick:
        if not c.get("attacks"):
            continue
        r = diff(c, a.trials)
        print(f"{c['log'][-8:]} seg {c['segment']} round {(c['turn'] + 1) // 2} ({c['winner']} won): "
              f"{r['matched']} of {r['of']} attacks reproduced; {r['part'] or 'all of them'}", flush=True)


if __name__ == "__main__":
    main()
