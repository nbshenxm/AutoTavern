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
    rec, car, bb = c.get("recruit"), c.get("carry"), c.get("bb")
    bad = []
    if rec and rec["replays"] >= 3 and rec["mismatching"] / rec["replays"] > 0.3:
        bad.append("recruit")
    if car and car["n"] >= 3 and abs(car["real"] - car["sim"]) > max(20, 0.15 * abs(car["real"])):
        bad.append("carry")
    if bb and bb["n"] >= 20 and abs(bb["z"]) >= 3:
        bad.append("bb")
    if bad:
        return "suspect: " + ", ".join(bad)
    if (rec and rec["replays"] >= 3) or (car and car["n"] >= 3) or (bb and bb["n"] >= 20):
        return "checked"
    return "unchecked"


def main():
    dec_path = ROOT / "data" / "replay" / "decisions.jsonl"
    decisions = [json.loads(l) for l in open(dec_path, encoding="utf-8")] if dec_path.exists() else []
    plays = played(decisions)
    recruit, carry, bb = _load("recruit_cards.json"), _load("carry_cards.json"), _load("bb_cards.json")
    out = {}
    for k, c in CAT.items():
        if c.get("kind") not in KINDS or c.get("normal_id"):
            continue
        if c["kind"] == "minion" and not c.get("in_pool"):
            continue
        row = {"name": c.get("name"), "kind": c["kind"], "tier": c.get("tier"), "played": plays.get(k, 0)}
        if k in recruit:
            row["recruit"] = recruit[k]
        if k in carry:
            row["carry"] = {"n": round(carry[k]["n"], 1), "real": round(carry[k]["real"]), "sim": round(carry[k]["sim"])}
        if k in bb:
            row["bb"] = bb[k]
        row["status"] = status(row)
        out[k] = row
    (PROGRESS / "coverage.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    by = collections.defaultdict(collections.Counter)
    for r in out.values():
        by[r["kind"]][r["status"].split(":")[0]] += 1
    print("kind: checked / suspect / unchecked")
    for kind in KINDS:
        b = by[kind]
        print(f"  {kind:16s} {b['checked']:4d} {b['suspect']:4d} {b['unchecked']:4d}")
    for k, r in sorted(out.items(), key=lambda kv: kv[1]["status"]):
        if r["status"].startswith("suspect"):
            print(f"  suspect {r['name']:28s} {k:18s} {r['status']}")


if __name__ == "__main__":
    main()
