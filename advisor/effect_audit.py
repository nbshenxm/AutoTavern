"""Cards in action: full games with every stat change recorded (RulesConfig::record_log: each
minion's `mods`, the card that caused it), and per card what it actually did against the numbers
its text gives. Unit tests pin a card in one set-up; here every card meets whatever the games bring
(golden copies, auras, improvements, odd boards). The network plays every seat (sampled); heroes
and trinket offers are picked at random so the rare ones get played too.

Per source card: how often it changed stats, which changes were the text's numbers (or whole
multiples of them: golden, improvements, "for each"), the share that wasn't; and the pool cards
that never fired at all.

    python -X utf8 -m advisor.effect_audit --games 200 --out data/progress/effect_audit.json
    python -X utf8 -m advisor.effect_audit --report data/progress/effect_audit.json
"""

import argparse
import collections
import json
import re
from pathlib import Path

import numpy as np
import torch

import taverngym
from advisor import search
from advisor.policy import load
from advisor.state import CAT, GAME_CONFIG, debug

ROOT = Path(__file__).resolve().parents[1]
L = dict(taverngym.layout())
BY_CID = None


def card_of(cid):
    global BY_CID
    if BY_CID is None:
        BY_CID = {c["cid"]: k for k, c in CAT.items()}
    return BY_CID.get(cid)


def text_pairs(card):
    """The (Attack, Health) amounts a card's text (and its golden form's) gives: "+3/+2" -> (3, 2),
    "+3 Attack" -> (3, 0), "+2 Health" -> (0, 2)."""
    out = set()
    for k in (card, (CAT.get(card) or {}).get("golden_id")):
        t = (CAT.get(k) or {}).get("text") or ""
        out |= {(int(a), int(b)) for a, b in re.findall(r"\+(\d+)/\+(\d+)", t)}
        out |= {(int(a), 0) for a in re.findall(r"\+(\d+) Attack", t)}
        out |= {(0, int(b)) for b in re.findall(r"\+(\d+) Health", t)}
    return {x for x in out if x != (0, 0)}


def matches(delta, pairs, extra=(0, 0)):
    """A change is the text's when it is a whole multiple of one of its amounts, each part raised
    by at most `extra` (a Tavern spell: the player's Tavern-spell bonus when it was counted)."""
    a, h = delta
    for x, y in pairs:
        for ea in range(extra[0] + 1):
            for eh in range(extra[1] + 1):
                for k in range(1, 400):
                    if ((x + ea) * k, (y + eh) * k) == (a, h):
                        return True
                    if (x + ea) * k > abs(a) and (y + eh) * k > abs(h):
                        break
    return False


@torch.no_grad()
def play(net, seed, rng, stats):
    cfg = {**GAME_CONFIG, "record_log": True}
    g = taverngym.Game(seed, json.dumps(cfg))
    seen = set()  # (eid, mod index) already counted
    for _ in range(60_000):
        if g.is_over():
            break
        stepped = False
        for seat in range(g.num_players):
            if not g.needs_action(seat):
                continue
            v = json.loads(g.view(seat))
            p = v["me"]["pending"]
            mask = np.array(v["mask"], bool)
            kind = p.get("kind") if isinstance(p, dict) else None
            if kind in ("hero", "trinket") and mask.any():  # the rare ones get played too
                a = int(rng.choice(np.flatnonzero(mask)))
            else:
                probs, _ = search._policy(net, g, seat)
                a = int(rng.choice(len(probs), p=probs / probs.sum()))
            if v["phase"].lower() == "recruit" and not p and a == v["actions"]["END"]:
                pl = json.loads(g.state_json())["players"][seat]
                ea, eh = debug(g, cmd="spell_extra", p=seat)
                for zone in ("board", "hand"):
                    for x in pl.get(zone, []):
                        m = x["item"].get("Minion") if zone == "hand" else x
                        if not m:
                            continue
                        for i, mod in enumerate(m.get("mods") or []):
                            if (m["eid"], i) in seen or mod.get("src") is None:
                                continue
                            seen.add((m["eid"], i))
                            src = card_of(mod["src"])
                            spell = (CAT.get(src) or {}).get("kind") == "tavern_spell"
                            key = (mod["atk"], mod["hp"]) + ((min(ea, 20), min(eh, 20)) if spell else (0, 0))
                            stats[src][mod["kind"]][key] += 1
            g.step(seat, a)
            stepped = True
        if not stepped:
            break


def run_chunk(job):
    """Games `first` .. `first + n - 1` in one process: their stats as plain dicts."""
    checkpoint, seed, first, n = job
    torch.set_num_threads(1)
    net, _ = load(checkpoint, "cpu")
    net.eval()
    rng = np.random.default_rng(seed * 1_000 + first)
    stats = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for k in range(first, first + n):
        play(net, seed * 100_000 + k, rng, stats)
    return first, {s: {kind: dict(v) for kind, v in kinds.items()} for s, kinds in stats.items() if s}


def report(stats):
    rows = []
    for src, kinds in stats.items():
        if not src or src not in CAT:
            continue
        adds = kinds.get("Add", collections.Counter())
        n = sum(adds.values())
        pairs = text_pairs(src)
        if not n or not pairs:
            continue
        off = sum(c for d, c in adds.items() if not matches(d[:2], pairs, d[2:4] if len(d) > 2 else (0, 0)))
        rows.append({"card": src, "name": CAT[src]["name"], "kind": CAT[src]["kind"], "n": n,
                     "off_text": round(off / n, 3), "text": sorted(pairs),
                     "top": [[list(d[:2]), c] for d, c in adds.most_common(5)]})
    rows.sort(key=lambda r: -r["off_text"] * min(r["n"], 50))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint", nargs="?", default=str(ROOT / "data" / "models" / "best.pt"))
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=str(ROOT / "data" / "progress" / "effect_audit.json"))
    ap.add_argument("--report", help="only print the report of a saved run (or several, merged: comma-separated)")
    ap.add_argument("--workers", type=int, default=1, help="processes (the cluster's CPUs)")
    ap.add_argument("--chunk", type=int, default=4, help="games a chunk (the unit saved and resumed)")
    a = ap.parse_args()
    stats = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    if a.report:
        for f in a.report.split(","):
            for src, kinds in json.loads(Path(f).read_text(encoding="utf-8"))["stats"].items():
                for kind, deltas in kinds.items():
                    for d, c in deltas.items():
                        stats[src][kind][tuple(json.loads(d))] += c
    else:
        # Small chunks, the totals saved after each one (a cluster job's hour can end mid-run):
        # a rerun with the same --out and --seed skips the chunks already in it.
        import multiprocessing as mp
        out = Path(a.out)
        done_chunks = set()
        if out.exists():
            saved = json.loads(out.read_text(encoding="utf-8"))
            if saved.get("seed") == a.seed and saved.get("chunk") == a.chunk:
                done_chunks = set(saved.get("done", []))
                for src, kinds in saved["stats"].items():
                    for kind, deltas in kinds.items():
                        for d, c in deltas.items():
                            stats[src][kind][tuple(json.loads(d))] += c
        jobs = [(a.checkpoint, a.seed, k, min(a.chunk, a.games - k)) for k in range(0, a.games, a.chunk)
                if k not in done_chunks]
        print(f"{len(done_chunks)} chunks already saved, {len(jobs)} to play", flush=True)

        def save():
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".part")
            tmp.write_text(json.dumps({"games": a.chunk * len(done_chunks), "seed": a.seed, "chunk": a.chunk,
                                       "done": sorted(done_chunks), "stats": {
                s: {k: {json.dumps(list(d)): c for d, c in v.items()} for k, v in kinds.items()}
                for s, kinds in stats.items() if s}}), encoding="utf-8")
            tmp.replace(out)
        with mp.get_context("spawn").Pool(max(1, a.workers)) as pool:
            for first, part in pool.imap_unordered(run_chunk, jobs):
                for src, kinds in part.items():
                    for kind, deltas in kinds.items():
                        for d, c in deltas.items():
                            stats[src][kind][tuple(d) if isinstance(d, list) else d] += c
                done_chunks.add(first)
                save()
                print(f"{len(done_chunks)} chunks, {len(stats)} cards seen changing stats", flush=True)
    rows = report(stats)
    fired = {r["card"] for r in rows} | set(stats)
    pool = [k for k, c in CAT.items() if c.get("in_pool") and not c.get("normal_id") and text_pairs(k)
            and c.get("kind") in ("minion", "tavern_spell", "trinket_lesser", "trinket_greater")]
    never = [k for k in pool if k not in fired]
    print(f"{len(rows)} cards changed stats; pool cards with stat text that never did: {len(never)} of {len(pool)}")
    for r in rows[:30]:
        if r["off_text"] > 0.2:
            print(f"  {r['name']:28s} {r['card']:20s} n {r['n']:5d}  off the text {r['off_text']:.0%}  text {r['text'][:3]}  top {r['top'][:3]}")


if __name__ == "__main__":
    main()
