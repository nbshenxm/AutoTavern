"""The simulator checked against every logged game, against a stored baseline
(docs/ROBUSTNESS.md, section 2). Runs the checks that found most bugs on all decisions and
combats in data/replay:

- legal: TavernGym's legal actions vs the client's options (advisor.bridge.parity);
- actions: each logged action replayed on the rebuilt state, the warband after it vs the log
  (advisor.recruit_diff);
- turns: whole turns replayed from their first decision (advisor.turn_replay);
- transitions: End Turn, combat and the next turn's start (advisor.transition_check);
- combat: the logged combats' result, how likely the simulator finds it (advisor.replay), and
  its calibration: predicted wins against actual, in standard deviations (a rule or rebuild gap
  that hurts one side shows here long before single combats look surprising);
- carry: what a warband keeps over combat and the turn change, real vs TavernGym, by round
  (advisor.carry_test: where scaling engines grow);
- bb: TavernGym against Bob's Buddy on a fixed set of random current-pool warbands
  (advisor.bb_diff; skipped where the harness isn't built: home only).

Each number is compared with data/replay/fidelity_baseline.json: one that drops by more than
its tolerance, or a card that newly mismatches, is listed (the to-fix list). `--save` makes the
current numbers the baseline.

    python -X utf8 -m advisor.fidelity            # compare
    python -X utf8 -m advisor.fidelity --save     # after a fix: the new baseline
"""

import argparse
import collections
import json
from pathlib import Path

import taverngym

from advisor import bridge, recruit_diff, replay, transition_check, turn_replay
from advisor.state import CAT, normal_form

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "replay"
BASELINE = DATA / "fidelity_baseline.json"
TOLERANCE = {"legal": 0.01, "actions": 0.01, "turns": 0.02, "transitions": 0.03, "combat": 0.01,
             "carry": 0.02}
CALIBRATION_TOLERANCE = 0.5  # SD the combat calibration may move away from 0
CARRY_TOLERANCE = 0.08  # how much further from 1.0x a round band's growth ratio may move
BB_TOLERANCE = 0.01  # mean |difference| in (win - loss) against Bob's Buddy
BB_FIGHTS = 600


def _name(c):
    return CAT.get(normal_form(c or "")[0], {}).get("name", c)


def check_legal(rows, combats):
    n, exact, by_kind, _ = bridge.parity(rows, combats=combats)
    refused = {k: v[1] for k, v in by_kind.items() if v[1]}
    allowed = {k: v[2] for k, v in by_kind.items() if v[2]}
    return {"rate": round(exact / max(1, n), 4), "n": n,
            "client_only": refused, "tavern_only": allowed}


def check_actions(rows, combats):
    recruit_diff.L = dict(taverngym.layout())
    opts = [d for d in rows if d["kind"] == "options" and d["turn"] % 2 == 1]
    n = ok = 0
    bad = collections.Counter()
    turn, key = [], None
    for d, nxt in zip(opts, opts[1:]):
        k = (d["log"], d["segment"], d["turn"])
        if k != key:
            turn, key = [], k
        earlier = list(turn)
        turn.append(d)
        if k != (nxt["log"], nxt["segment"], nxt["turn"]):
            continue
        # (the turn's earlier decisions, as the live advisor passes them: an armed Prison...)
        res = recruit_diff.compare(d, nxt, combats, earlier)
        if res is None:
            continue
        n += 1
        if any(x[2] != x[3] for x in res):
            bad[_name(res[0][0])] += 1
        else:
            ok += 1
    return {"rate": round(ok / max(1, n), 4), "n": n, "cards": dict(bad.most_common(30))}


def check_turns(rows, combats):
    L = dict(taverngym.layout())
    turns = collections.defaultdict(list)
    for d in rows:
        if d["turn"] % 2 == 1 and d["turn"] > 0:
            turns[(d["log"], d["segment"], d["turn"])].append(d)
    n = clean = 0
    bad = collections.Counter()
    for key, turn in sorted(turns.items()):
        res = turn_replay.replay_turn(turn, combats, L)
        if res is None:
            continue
        n += 1
        clean += not res
        for _, acting, diff in res:
            for f in diff:
                bad[f"{f}: {_name(acting)}"] += 1
    return {"rate": round(clean / max(1, n), 4), "n": n, "cards": dict(bad.most_common(30))}


def check_transitions(rows, combats):
    by_turn = collections.defaultdict(list)
    for d in rows:
        if d["kind"] == "options" and d["turn"] % 2 == 1:
            by_turn[(d["log"], d["segment"], d["turn"])].append(d)
    n = clean = 0
    fields = collections.Counter()
    for (log, seg, turn), ds in sorted(by_turn.items()):
        nxt = by_turn.get((log, seg, turn + 2))
        last = ds[-1]
        ch = last.get("chosen") or {}
        opt = next((o for o in last["options"] if o["id"] == ch.get("option")), None)
        if not nxt or (opt is not None and opt["type"] != "END_TURN"):
            continue
        g, gaps = bridge.build(last, bridge.game_combats(combats, last))
        if gaps:
            continue
        try:
            v = transition_check.next_turn(g)
        except ValueError:
            continue
        if v is None:
            continue
        n += 1
        # Gold at rounds 6 and 9 follows the trinket the stand-in picks; hand and warband stats
        # follow the combat: what doesn't depend on chance is compared
        diff = {f for f in transition_check.compare(v, nxt[0])
                if f in ("max gold", "tier", "upgrade cost", "tavern size")}
        clean += not diff
        fields.update(diff)
    return {"rate": round(clean / max(1, n), 4), "n": n, "fields": dict(fields)}


def check_combat(combats, decisions, n=200):
    import math
    used, owed = replay.used_powers(decisions), replay.owed_minions(decisions)
    rows = []
    for c in combats:
        k = (c["log"], c["player_id"], c["turn"])
        r = replay.replay(c, n, "start", 7, used.get(k, ()), owed.get(k, ()))
        if r is not None:
            rows.append(r)
    s = [r for r in rows if not r["gaps"]]
    pred = sum(r["sim"]["win"] for r in s)
    won = sum(r["winner"] == "friendly" for r in s)
    sd = math.sqrt(sum(r["sim"]["win"] * (1 - r["sim"]["win"]) for r in s)) or 1
    return {"rate": round(sum(r["p_win"] for r in s) / max(1, len(s)), 4), "n": len(s),
            "surprises": sum(r["surprise"] for r in s),
            "calibration_sd": round((won - pred) / sd, 2), "predicted_wins": round(pred, 1), "wins": won}


def check_carry(rows, combats, seeds=2):
    """Over combat and the turn change: the exact share and the growth ratio by round band."""
    from advisor import carry_test
    out = [r for d, nx, e in carry_test.pairs(rows, True) for k in range(seeds)
           if (r := carry_test.carry(d, nx, combats, seed=7 + k, earlier=e))]
    bands = {}
    for name, lo, hi in (("rounds 1-6", 1, 6), ("rounds 7-9", 7, 9), ("rounds 10+", 10, 99)):
        rs = [r for r in out if lo <= r["round"] <= hi]
        real = sum(r["real"] - r["before"] for r in rs)
        sim = sum(r["sim"] - r["before"] for r in rs)
        bands[name] = round(sim / real, 3) if real else None
    return {"rate": round(sum(r["real"] == r["sim"] for r in out) / max(1, len(out)), 4), "n": len(out),
            "ratios": bands}


def check_bb():
    """TavernGym against Bob's Buddy on BB_FIGHTS fixed random warbands (seed 77): the mean
    |difference| in (win - loss). None without the harness (tools/bbdiff: home only)."""
    import random
    import subprocess
    from advisor import bb_diff
    if not bb_diff.EXE.exists():
        return None
    rng, by_tier = random.Random(77), bb_diff.pool()
    fights = [bb_diff.fight(rng, by_tier, k) for k in range(BB_FIGHTS)]
    bb = subprocess.Popen([str(bb_diff.EXE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                          encoding="utf-8")
    diffs = []
    from advisor.train import pause_if_playing
    for f in fights:
        pause_if_playing()  # (home: never while you play)
        bb.stdin.write(json.dumps({**f, "n": 200}) + "\n")
        bb.stdin.flush()
        b = json.loads(bb.stdout.readline())
        if b.get("error"):
            continue
        w, _, lo = bb_diff.taverngym(f, 200, 7_700_000 + f["id"])
        diffs.append(abs((w - lo) - (b["win"] - b["loss"])))
    bb.stdin.close()
    bb.wait()
    mean = sum(diffs) / max(1, len(diffs))
    return {"rate": round(1 - mean, 4), "n": len(diffs), "mean_abs_diff": round(mean, 4)}


def run(combat_trials=200, bb=True):
    rows = [json.loads(l) for l in open(DATA / "decisions.jsonl", encoding="utf-8")]
    combats = [json.loads(l) for l in open(DATA / "combats.jsonl", encoding="utf-8")]
    out = {"legal": check_legal(rows, combats), "actions": check_actions(rows, combats),
           "turns": check_turns(rows, combats), "transitions": check_transitions(rows, combats),
           "combat": check_combat(combats, rows, combat_trials), "carry": check_carry(rows, combats)}
    bb = check_bb() if bb else None
    if bb is not None:
        out["bb"] = bb
    return out


def compare(now, base):
    """The regressions: [str]."""
    out = []
    for k, tol in TOLERANCE.items():
        if k in now and k in base and now[k]["rate"] < base[k]["rate"] - tol:
            out.append(f"{k}: {base[k]['rate']:.1%} -> {now[k]['rate']:.1%}")
    for k in ("actions", "turns"):
        for card, c in (now.get(k, {}).get("cards") or {}).items():
            if card not in (base.get(k, {}).get("cards") or {}):
                out.append(f"{k}: new mismatch {card} ({c})")
    c, b = now.get("combat", {}), base.get("combat", {})
    if "calibration_sd" in c and "calibration_sd" in b \
            and abs(c["calibration_sd"]) > abs(b["calibration_sd"]) + CALIBRATION_TOLERANCE:
        out.append(f"combat calibration: {b['calibration_sd']:+.1f} -> {c['calibration_sd']:+.1f} SD")
    for band, r in (now.get("carry", {}).get("ratios") or {}).items():
        r0 = (base.get("carry", {}).get("ratios") or {}).get(band)
        if r is not None and r0 is not None and abs(r - 1) > abs(r0 - 1) + CARRY_TOLERANCE:
            out.append(f"carry {band}: {r0:.2f}x -> {r:.2f}x the real growth")
    if "bb" in now and "bb" in base and now["bb"]["mean_abs_diff"] > base["bb"]["mean_abs_diff"] + BB_TOLERANCE:
        out.append(f"bb: mean |difference| {base['bb']['mean_abs_diff']:.3f} -> {now['bb']['mean_abs_diff']:.3f}")
    for side in ("client_only", "tavern_only"):
        for kind, c in (now["legal"].get(side) or {}).items():
            if c > (base["legal"].get(side) or {}).get(kind, 0) + 3:
                out.append(f"legal: {side} {kind} {base['legal'].get(side, {}).get(kind, 0)} -> {c}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true", help="make these numbers the baseline")
    ap.add_argument("--combat-trials", type=int, default=200)
    ap.add_argument("--no-bb", action="store_true", help="skip the Bob's Buddy sample (the office)")
    a = ap.parse_args()
    from advisor.train import wait_while_playing
    wait_while_playing(print)
    now = run(a.combat_trials, bb=not a.no_bb)
    for k, v in now.items():
        extra = {x: v[x] for x in ("calibration_sd", "ratios", "mean_abs_diff") if x in v}
        print(f"{k:12s} {v['rate']:.1%} of {v['n']}", extra or "")
    from datetime import datetime
    with open(DATA / "fidelity_history.jsonl", "a", encoding="utf-8") as f:  # the progress page's trend
        f.write(json.dumps({"time": datetime.now().isoformat(timespec="minutes"),
                            **{k: v["rate"] for k, v in now.items()}}) + "\n")
    if a.save or not BASELINE.exists():
        BASELINE.write_text(json.dumps(now, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"baseline saved: {BASELINE}")
        return
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    reg = compare(now, base)
    print("regressions:" if reg else "no regression against the baseline")
    for r in reg:
        print("  " + r)
    (DATA / "fidelity_last.json").write_text(json.dumps({"now": now, "regressions": reg}, ensure_ascii=False,
                                                        indent=1), encoding="utf-8")
    if reg:  # (callers log it: a regression must not pass unnoticed)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
