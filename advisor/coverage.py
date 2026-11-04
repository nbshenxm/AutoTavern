"""Which cards the simulator audits have actually checked, and what they found. Per card of the
current pool (minions, Tavern spells, trinkets, Hero Powers):
- played: how often your logs show it played, bought or used (an effect only gets checked when
  it fires);
- recruit: advisor.recruit_diff's replays with it acting and how many matched the log;
- carry: advisor.carry_test's turn pairs with it on board and its gain real vs TavernGym;
- bb: advisor.bb_diff's random fights with it and how far TavernGym's result leans from Bob's
  Buddy's for its side (z);
then a status: "suspect" (an audit disagrees), "checked" (audited, agrees), "unchecked".

    python -X utf8 -m advisor.coverage          # data/progress/coverage.json, a summary
"""

import collections
import json
from pathlib import Path

from advisor.state import CAT, normal_form

ROOT = Path(__file__).resolve().parents[1]
PROGRESS = ROOT / "data" / "progress"
KINDS = ("minion", "tavern_spell", "trinket_lesser", "trinket_greater", "hero_power")


def _load(name):
    p = PROGRESS / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def played(decisions):
    """card -> times your logged decisions chose it (played from hand, bought, used, targeted
    with a Hero Power's own card as the chosen option)."""
    out = collections.Counter()
    for d in decisions:
        ch = d.get("chosen") or {}
        opts = d.get("options") or []
        if d.get("kind") != "options" or not isinstance(ch.get("option"), int) or ch["option"] >= len(opts):
            continue
        e = opts[ch["option"]].get("entity") or {}
        if e.get("card"):
            out[normal_form(e["card"])[0]] += 1
    return out


def status(c):
    rec, car, bb, games = c.get("recruit"), c.get("carry"), c.get("bb"), c.get("games")
    bad = []
    # Per-minion exactness alone isn't a fault (random targets, a stat off by one): the totals
    # must disagree too
    if rec and rec["replays"] >= 3 and rec["mismatching"] / rec["replays"] > 0.3             and abs(rec["real"] - rec["sim"]) > max(20, 0.02 * abs(rec["real"])):
        bad.append("recruit")
    if car and car["n"] >= 3 and abs(car["real"] - car["sim"]) > max(20, 0.15 * abs(car["real"])):
        bad.append("carry")
    if bb and bb["n"] >= 20 and abs(bb["z"]) >= 3:
        bad.append("bb")
    # advisor.trinket_audit: the simulator in your games with the trinket (combats and turns)
    if games and games["n"] >= 5 and games["rate"] < 0.75:
        bad.append("games")
    if bad and c.get("patched"):
        return "changed in 37.0.2: " + ", ".join(bad) + " (your logs predate it)"
    if bad:
        return "suspect: " + ", ".join(bad)
    if (rec and rec["replays"] >= 3) or (car and car["n"] >= 3) or (bb and bb["n"] >= 20)             or (games and games["n"] >= 5):
        return "checked"
    if c.get("tested"):
        return "tested"  # a unit test pins it to its text; no log or Bob's Buddy check yet
    return "unchecked"


def main():
    dec_path = ROOT / "data" / "replay" / "decisions.jsonl"
    decisions = [json.loads(l) for l in open(dec_path, encoding="utf-8")] if dec_path.exists() else []
    plays = played(decisions)
    recruit, carry, bb = _load("recruit_cards.json"), _load("carry_cards.json"), _load("bb_cards.json")
    trinket_games = _load("trinket_audit.json").get("trinkets", {})
    patch = ROOT / "tools" / "overlays" / "37.0.2.json"
    patched = set(json.loads(patch.read_text(encoding="utf-8"))["cards"]) if patch.exists() else set()
    import re
    tests = "".join(f.read_text(encoding="utf-8") for f in (ROOT / "crates" / "taverngym" / "tests").glob("*.rs"))
    tests += "".join(f.read_text(encoding="utf-8") for f in (ROOT / "tests").glob("*.py"))
    in_tests = set(re.findall(r'"([A-Za-z0-9_]+)"', tests))
    out = {}
    # The current pool: minions, Tavern spells and trinkets the game deals, the pool heroes' powers
    powers = {c.get("hero_power_id") for c in CAT.values() if c.get("kind") == "hero" and c.get("in_pool")}
    for k, c in CAT.items():
        if c.get("kind") not in KINDS or c.get("normal_id"):
            continue
        if not (c.get("in_pool") or (c["kind"] == "hero_power" and k in powers)):
            continue
        row = {"name": c.get("name"), "kind": c["kind"], "tier": c.get("tier"), "played": plays.get(k, 0)}
        if k in recruit:
            row["recruit"] = recruit[k]
        if k in carry:
            row["carry"] = {"n": round(carry[k]["n"], 1), "real": round(carry[k]["real"]), "sim": round(carry[k]["sim"])}
        if k in bb:
            row["bb"] = bb[k]
        if k in trinket_games:
            t = trinket_games[k]
            parts = [t[f] for f in ("combats", "turns") if t.get(f) and t[f][0] is not None]
            n = sum(x[1] for x in parts)
            hit = sum(x[0] * x[1] for x in parts)
            row["games"] = {"n": n, "rate": round(hit / n, 3) if n else None}
        if k in patched:
            row["patched"] = True
        if k in in_tests or c.get("golden_id") in in_tests:
            row["tested"] = True
        row["status"] = status(row)
        out[k] = row
    (PROGRESS / "coverage.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    by = collections.defaultdict(collections.Counter)
    for r in out.values():
        by[r["kind"]][r["status"].split(":")[0]] += 1
    print("kind: checked / tested only / suspect / changed in 37.0.2 / unchecked")
    for kind in KINDS:
        b = by[kind]
        print(f"  {kind:16s} {b['checked']:4d} {b['tested']:4d} {b['suspect']:4d} {b['changed in 37.0.2']:4d} {b['unchecked']:4d}")
    for k, r in sorted(out.items(), key=lambda kv: kv[1]["status"]):
        if r["status"].startswith(("suspect", "changed")):
            print(f"  suspect {r['name']:28s} {k:18s} {r['status']}")


if __name__ == "__main__":
    main()
