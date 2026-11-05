"""Why did a candidate win or lose? The audit after every gate verdict, candidate against its
control (the network it branched from at the same iteration, or the champion): the gate's own
games, the same seeds, seat 0 the candidate in one arm and the control in the other, the seven
other seats the control. Per game and round, seat 0's health, Tier, warband, the main tribe's share
of the warband that fought, Gold at the turn's start and when it ends, and its actions by kind. Then:

- where the place difference is made: the paired games split by the first round seat 0's health
  differs between the arms (the outcome's divergence), each band's share of the total difference;
- the two arms round by round (alive, health, Tier, warband, tribe share, Gold left, actions);
- the user's habits next to them (advisor.compare_play / mid_exam / engine_exam, run by the
  wrapper scripts/hpc/post_audit.sh).

Each chunk of games is saved when it ends (data/audit/NAME/games.jsonl), so a run resumes.

    python -X utf8 -m advisor.post_audit CAND CONTROL --name comp2_end --workers 60
    python -X utf8 -m advisor.post_audit --report data/audit/comp2_end     # the tables again
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from advisor.gate import CONFIG, library_config
from advisor.policy import load
from advisor.train import BatchEnv, RealStarts, load_start, play_frozen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "audit"
SEED = 61_000_000
# Action index ranges (taverngym.layout()): the kind of each action
KINDS = [("end", 0, 1), ("refresh", 1, 2), ("freeze", 2, 3), ("upgrade", 3, 4), ("hero_power", 4, 6),
         ("dark_gift", 6, 7), ("cancel", 7, 8), ("buy", 8, 16), ("sell", 16, 23), ("activate", 23, 30),
         ("choose", 30, 46), ("play", 46, 126), ("magnetize", 126, 196), ("move", 196, 245)]
KIND_OF = {}
for _k, _lo, _hi in KINDS:
    for _a in range(_lo, _hi):
        KIND_OF[_a] = _k
SHOWN = ["refresh", "buy", "sell", "play", "upgrade", "freeze", "hero_power", "dark_gift", "activate", "magnetize"]
BANDS = [("rounds 1-5", 1, 6), ("rounds 6-9", 6, 10), ("rounds 10-13", 10, 14), ("rounds 14+", 14, 99)]


def _turn_row(v):
    me = v["me"]
    lw = me.get("last_warband") or {}
    counts = [c["count"] for c in lw.get("counts") or []]
    st = me.get("stats") or {}
    return {"hp": me["health"] + me.get("armor", 0), "tier": me["tier"], "gold": me["gold"],
            "n": len(me["board"]), "stats": sum(m["atk"] + m["hp"] for m in me["board"]),
            "tribe": (max(counts) / lw["size"]) if counts and lw.get("size") else None,
            "spent": st.get("gold_spent_total", 0), "lost": st.get("cards_lost", 0)}


@torch.no_grad()
def trace(net, other, m, seed, config, states=None):
    """gate.play's games (seat 0 `net`, the rest `other`, greedy), with seat 0's rounds kept."""
    env = BatchEnv(m, seed=seed, controlled=list(range(8)), config=config, threads=1)
    if states is not None:
        for i in range(m):
            load_start(env, i, states[i])
    net_of = {i: (net if i % 8 == 0 else other) for i in range(env.n_slots)}
    obs = env.observe()
    place, turns, acts = {}, [dict() for _ in range(m)], [dict() for _ in range(m)]
    for step in range(200_000):
        if len(place) == m:
            break
        ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
        ready = np.array([i for i in ready if i // 8 not in place], dtype=np.int64)
        actions = np.zeros(env.n_slots, dtype=np.int64)
        play_frozen(obs, ready, net_of, actions, "cpu")
        for i in ready[ready % 8 == 0]:
            g = int(i // 8)
            t = env.game(g).turn
            if t not in turns[g]:
                v = json.loads(env.game(g).view(0))
                if v["phase"].lower() == "recruit":
                    turns[g][t] = _turn_row(v)
            k = KIND_OF.get(int(actions[i]), "other")
            if k == "end" and t in turns[g]:  # the Gold the turn ends with
                turns[g][t]["left"] = json.loads(env.game(g).view(0))["me"]["gold"]
            a = acts[g].setdefault(t, {})
            a[k] = a.get(k, 0) + 1
        _, done, info = env.step(actions)
        for i in np.flatnonzero(done):
            if i % 8 == 0 and i // 8 not in place:
                place[int(i // 8)] = int(info["placement"][i]) or 4.5
        obs = env.observe()
    return [{"place": place.get(g, 4.5), "turns": turns[g], "acts": acts[g]} for g in range(m)]


_W = {}


def _init(paths):
    torch.set_num_threads(1)
    _W["nets"] = {p: load(p, "cpu")[0].eval() for p in paths}
    _W["lib"] = library_config()
    _W["starts"] = RealStarts(1.0, 0, log=lambda r: None).real


def _work(job):
    arm, net, other, m, seed, suite, lo = job
    states = _W["starts"][lo:lo + m] if suite == "real" else None
    games = trace(_W["nets"][net], _W["nets"][other], m, seed, _W["lib"], states)
    return {"arm": arm, "suite": suite, "seed": seed, "lo": lo, "games": games}


def jobs(cand, control, fresh, n_real, seed, chunk):
    out = []
    for suite, n in (("fresh", fresh), ("real", n_real)):
        for lo in range(0, n, chunk):
            s = seed + (0 if suite == "fresh" else 500_000) + lo
            for arm, net in (("cand", cand), ("ctrl", control)):
                out.append((arm, net, control, min(chunk, n - lo), s, suite, lo))
    return out


def run(cand, control, name, fresh=512, seed=SEED, workers=60, chunk=8, real=None):
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "args.json").write_text(json.dumps({"cand": cand, "control": control, "fresh": fresh,
                                             "real": real, "seed": seed, "chunk": chunk}))
    path = d / "games.jsonl"
    done = {(r["arm"], r["suite"], r["seed"]) for r in map(json.loads, open(path, encoding="utf-8"))} \
        if path.is_file() else set()
    n_real = len(RealStarts(1.0, 0, log=lambda r: None).real)
    n_real = min(n_real, real) if real is not None else n_real
    todo = [j for j in jobs(cand, control, fresh, n_real, seed, chunk) if (j[0], j[5], j[4]) not in done]
    print(f"{len(done)} chunks done, {len(todo)} to play ({n_real} real starts)", flush=True)
    import multiprocessing as mp
    with mp.get_context("spawn").Pool(workers, _init, ([cand, control],)) as pool, \
            open(path, "a", encoding="utf-8") as f:
        for k, r in enumerate(pool.imap_unordered(_work, todo, chunksize=1)):
            f.write(json.dumps(r) + "\n")
            f.flush()
            if k % 20 == 0:
                print(f"{k + 1}/{len(todo)}", flush=True)
    return report(d)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(float(np.mean(xs)), 2) if xs else None


def report(d):
    d = Path(d)
    rows = [json.loads(l) for l in open(d / "games.jsonl", encoding="utf-8")]
    games = {}  # (suite, seed, index) -> {arm: game}
    for r in rows:
        for i, g in enumerate(r["games"]):
            g["turns"] = {int(t): x for t, x in g["turns"].items()}
            g["acts"] = {int(t): x for t, x in g["acts"].items()}
            games.setdefault((r["suite"], r["seed"], i), {})[r["arm"]] = g
    pairs = {k: v for k, v in games.items() if len(v) == 2}
    out = {"pairs": len(pairs), "suites": {}, "divergence": {}, "rounds": {}}
    lines = [f"# Post-evaluation audit: {d.name}", "", json.dumps(json.loads((d / "args.json").read_text())), ""]
    for suite in ("fresh", "real", "all"):
        ps = [v for k, v in pairs.items() if suite == "all" or k[0] == suite]
        if not ps:
            continue
        diff = np.array([p["cand"]["place"] - p["ctrl"]["place"] for p in ps], float)
        se = float(diff.std(ddof=1) / np.sqrt(len(diff))) if len(diff) > 1 else float("nan")
        s = {"n": len(ps), "diff": round(float(diff.mean()), 3), "se": round(se, 3)}
        for arm in ("cand", "ctrl"):
            pl = np.array([p[arm]["place"] for p in ps], float)
            s[arm] = {"place": round(float(pl.mean()), 3), "top4": round(float((pl <= 4).mean()), 3),
                      "win": round(float((pl == 1).mean()), 3)}
        out["suites"][suite] = s
        # Where the difference is made: the first round seat 0's health differs between the arms
        div = {}
        for p in ps:
            a, b = p["cand"]["turns"], p["ctrl"]["turns"]
            first = None
            for t in sorted(set(a) | set(b)):
                if t not in a or t not in b or a[t]["hp"] != b[t]["hp"]:
                    first = t
                    break
            band = "never" if first is None else next(n for n, lo, hi in BANDS if lo <= first < hi)
            div.setdefault(band, []).append(p["cand"]["place"] - p["ctrl"]["place"])
        out["divergence"][suite] = {b: {"share": round(len(x) / len(ps), 3), "mean": round(float(np.mean(x)), 3),
                                        "part": round(float(np.sum(x)) / len(ps), 3)} for b, x in div.items()}
    for suite in ("fresh", "real"):
        ps = [v for k, v in pairs.items() if k[0] == suite]
        if not ps:
            continue
        table = {}
        for t in range(1, 19):
            row = {}
            for arm in ("cand", "ctrl"):
                alive = [p[arm] for p in ps if t in p[arm]["turns"]]
                if not alive:
                    continue
                tr = [g["turns"][t] for g in alive]
                left = [x.get("left") for x in tr]
                act = {k: _mean([g["acts"].get(t, {}).get(k, 0) for g in alive]) for k in SHOWN}
                row[arm] = {"alive": round(len(alive) / len(ps), 3), "hp": _mean([x["hp"] for x in tr]),
                            "tier": _mean([x["tier"] for x in tr]), "minions": _mean([x["n"] for x in tr]),
                            "stats": _mean([x["stats"] for x in tr]), "tribe": _mean([x["tribe"] for x in tr]),
                            "gold_left": _mean(left), **act}
            table[t] = row
        out["rounds"][suite] = table
    for suite, s in out["suites"].items():
        lines.append(f"## {suite}: candidate - control {s['diff']:+.3f} ± {s['se']:.3f} places ({s['n']} pairs)")
        lines.append(f"cand place {s['cand']['place']} top4 {s['cand']['top4']} win {s['cand']['win']}; "
                     f"ctrl place {s['ctrl']['place']} top4 {s['ctrl']['top4']} win {s['ctrl']['win']}")
        lines.append("")
        lines.append("| first round the health differs | share of pairs | mean diff there | part of the total |")
        lines.append("| --- | --- | --- | --- |")
        for b in [n for n, _, _ in BANDS] + ["never"]:
            x = out["divergence"][suite].get(b)
            if x:
                lines.append(f"| {b} | {x['share']:.2f} | {x['mean']:+.3f} | {x['part']:+.3f} |")
        lines.append("")
    cols = ["alive", "hp", "tier", "minions", "stats", "tribe", "gold_left"] + SHOWN
    for suite, table in out["rounds"].items():
        lines.append(f"## {suite}, round by round (candidate / control)")
        lines.append("| round | " + " | ".join(cols) + " |")
        lines.append("| --- |" + " --- |" * len(cols))
        for t, row in table.items():
            if "cand" in row and "ctrl" in row:
                lines.append(f"| {t} | " + " | ".join(f"{row['cand'][c]} / {row['ctrl'][c]}" for c in cols) + " |")
        lines.append("")
    (d / "report.json").write_text(json.dumps(out, indent=1))
    (d / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cand", nargs="?")
    ap.add_argument("control", nargs="?")
    ap.add_argument("--name")
    ap.add_argument("--fresh", type=int, default=512, help="fresh games (from round 1); the real starts are all played")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--workers", type=int, default=60)
    ap.add_argument("--chunk", type=int, default=8)
    ap.add_argument("--real", type=int, help="at most this many of the real starts (a smoke test)")
    ap.add_argument("--report", help="only the tables, from this audit's folder")
    a = ap.parse_args()
    if a.report:
        report(a.report)
        return
    if not (a.cand and a.control and a.name):
        raise SystemExit("CAND CONTROL --name NAME (or --report DIR)")
    run(a.cand, a.control, a.name, a.fresh, a.seed, a.workers, a.chunk, a.real)


if __name__ == "__main__":
    main()
