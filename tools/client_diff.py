"""Diff TavernGym's content against a live client build.

Pools: the client's pool flags are not the pool itself (the server ruleset rotates types and
bans cards), so the expected pool for the new build is TavernGym's pool plus the flag changes
between TavernGym's own build and the new one. Stats and texts: a change between the two
client builds is a patch change; a TavernGym value that already differed from its own build's
client data is listed apart (server-side values, or a TavernGym discrepancy).

Inputs are HearthstoneJSON exports (enUS.json, zhCN.json, CardDefs.xml) for both builds.
Run:    python -X utf8 tools/client_diff.py --base data/client/253932 \
            --new D:/GitHub/Hearthstone_AI_Advisor/data/cards/255790 --out docs/patches/37.0
Writes OUT.md (report) and OUT.json (machine-readable lists for the patch pipeline).
"""

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from gen_carddb import RACES, clean, split_variants  # noqa: E402

CARDS = ROOT / "crates" / "taverngym" / "data" / "cards.json"
CATEGORIES = ["minion", "tier7", "hero", "spell", "trinket", "dark_gift", "timewarp"]
# CardDefs tags the pools are read from (HearthstoneJSON leaves trinkets out of its flags)
XML_TAGS = {"BACON_TRINKET", "SPELL_SCHOOL", "IS_BACON_DUOS_EXCLUSIVE", "TECH_LEVEL",
            "BACON_TRIPLED_BASE_MINION_ID"}


def load_build(d):
    d = Path(d)
    en = {c["id"]: c for c in json.loads((d / "enUS.json").read_text(encoding="utf-8"))}
    zh_path = d / "zhCN.json"
    zh = {}
    if zh_path.exists():
        zh = {c["id"]: c for c in json.loads(zh_path.read_text(encoding="utf-8"))}
    tags = {}
    for _, el in ET.iterparse(d / "CardDefs.xml", events=("end",)):
        if el.tag != "Entity":
            continue
        t = {x.get("name"): x.get("value") for x in el.findall("Tag") if x.get("name") in XML_TAGS}
        if t:
            tags[el.get("CardID")] = t
        el.clear()
    with open(d / "CardDefs.xml", encoding="utf-8") as f:
        head = f.read(200)
    build = head.split('build="', 1)[1].split('"', 1)[0] if 'build="' in head else d.name
    return {"build": build, "en": en, "zh": zh, "tags": tags}


def flags(b):
    """Pool-candidate flags per category, as the client data marks them (solo only)."""
    out = {k: set() for k in CATEGORIES}
    for cid, c in b["en"].items():
        t = b["tags"].get(cid, {})
        duos = c.get("isBattlegroundsDuosExclusive") or t.get("IS_BACON_DUOS_EXCLUSIVE") == "1"
        if duos:
            continue
        if c.get("battlegroundsTimewarpCard"):  # normal and golden forms, minions and spells
            out["timewarp"].add(cid)
            continue
        if c.get("isBattlegroundsPoolMinion") and not c.get("battlegroundsNormalDbfId"):
            out["tier7" if c.get("techLevel", 0) == 7 else "minion"].add(cid)
        if c.get("battlegroundsHero") and c.get("type") == "HERO":
            out["hero"].add(cid)
        if c.get("isBattlegroundsPoolSpell"):
            out["spell"].add(cid)
        if c.get("isBattlegroundsDarkGift"):
            out["dark_gift"].add(cid)
        if t.get("BACON_TRINKET") == "1":
            out["trinket"].add(cid)
    return out


def tg_pools(tg):
    out = {k: set() for k in CATEGORIES}
    for c in tg.values():
        for p in c["pools"]:
            out[p].add(c["id"])
        if c["kind"] == "dark_gift" and c.get("window") and c["reachable"]:
            out["dark_gift"].add(c["id"])
    return out


def card_fields(c, zh=None):
    """The comparable fields of a HearthstoneJSON card, in TavernGym's terms."""
    races = c.get("races") or ([c["race"]] if c.get("race") else [])
    return {
        "tier": c.get("techLevel", 0),
        "atk": c.get("attack", 0),
        "hp": c.get("health", 0),
        "armor": c.get("armor", 0),
        "cost": c.get("cost", 0),
        "races": sorted(r for r in races if r in RACES),
        # A card with a progress counter carries both variants glued together; TavernGym
        # keeps the first as its text (gen_carddb.set_texts)
        "text": split_variants(clean(c.get("text", "")))[0],
    }


def tg_fields(c):
    return {k: (sorted(c[k]) if k == "races" else c[k])
            for k in ("tier", "atk", "hp", "armor", "cost", "races", "text")}


def norm_text(t):
    # Counters and placeholders differ in form between the bundle and HearthstoneJSON
    # ("(3 left!)" vs "(@ left!)", "$3", "{0}"): compare without digits and markers.
    import re
    return re.sub(r"[\d@$#{}]+", "", t).replace(" ", "").lower()


def diff_fields(a, b):
    out = {}
    for k in a:
        va, vb = a[k], b[k]
        if k == "text":
            if norm_text(va) != norm_text(vb) or _nums(va) != _nums(vb) and "@" not in va + vb:
                out[k] = [va, vb]
        elif k == "cost":
            continue  # BG costs are server rules (minions cost 3), not card data
        elif va != vb:
            out[k] = [va, vb]
    return out


def _nums(t):
    import re
    return re.findall(r"\d+", t)


def implementation_status():
    try:
        import taverngym
        return {c["id"]: c for c in json.loads(taverngym._core.catalog_json())}
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="HearthstoneJSON dir of TavernGym's build")
    ap.add_argument("--new", required=True, help="HearthstoneJSON dir of the live build")
    ap.add_argument("--out", required=True, help="output path without extension")
    a = ap.parse_args()

    tg = {c["id"]: c for c in json.loads(CARDS.read_text(encoding="utf-8"))["cards"]}
    meta = json.loads(CARDS.read_text(encoding="utf-8"))["meta"]
    base, new = load_build(a.base), load_build(a.new)
    status = implementation_status()
    fb, fn, pools = flags(base), flags(new), tg_pools(tg)

    def name(cid):
        c = new["en"].get(cid) or base["en"].get(cid) or tg.get(cid) or {}
        return c.get("name", cid)

    def name_zh(cid):
        return (new["zh"].get(cid) or {}).get("name") or (tg.get(cid) or {}).get("name_zh", "")

    def tier(cid):
        return (new["en"].get(cid) or {}).get("techLevel") or (tg.get(cid) or {}).get("tier", 0)

    def state(cid):
        if cid not in tg:
            return "new card"
        s = status.get(cid)
        if s is None:
            return "in DB"
        return "scripted" if s["scripted"] else ("implemented" if s["implemented"] else "in DB, not scripted")

    result = {"tavern_build": meta["client_version"], "base": base["build"], "new": new["build"],
              "pools": {}, "changes": [], "tg_differs": []}
    for cat in CATEGORIES:
        added = sorted(fn[cat] - fb[cat])
        removed = sorted(fb[cat] - fn[cat])
        expected = (pools[cat] | set(added)) - set(removed)
        # Flags TavernGym's pool disagreed with already at its own build (server rules)
        result["pools"][cat] = {
            "tavern_pool": len(pools[cat]),
            "expected": len(expected),
            "added": [{"id": c, "name": name(c), "name_zh": name_zh(c), "tier": tier(c),
                       "state": state(c)} for c in added],
            "removed": [{"id": c, "name": name(c), "name_zh": name_zh(c), "tier": tier(c),
                         "in_tavern_pool": c in pools[cat]} for c in removed],
            "expected_ids": sorted(expected),
        }

    # Stats and texts of every TavernGym card some pool or effect can reach (normal forms)
    for cid, c in sorted(tg.items()):
        if c["normal"] or not (c["pools"] or c["reachable"]) or cid not in new["en"]:
            continue
        cur = card_fields(new["en"][cid])
        if cid in base["en"]:
            old = card_fields(base["en"][cid])
            d = diff_fields(old, cur)
            if d:
                result["changes"].append({"id": cid, "name": c["name"], "kind": c["kind"],
                                          "diff": d, "tavern": {k: tg_fields(c)[k] for k in d}})
            d0 = diff_fields(tg_fields(c), old)
            if d0:
                result["tg_differs"].append({"id": cid, "name": c["name"], "kind": c["kind"],
                                             "diff": d0})

    md, js = Path(a.out + ".md"), Path(a.out + ".json")  # not with_suffix: "37.0" has a dot
    md.parent.mkdir(parents=True, exist_ok=True)
    js.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    md.write_text(render(result), encoding="utf-8")
    for cat, p in result["pools"].items():
        new_cards = sum(1 for x in p["added"] if x["state"] == "new card")
        print(f"{cat:10s} pool {p['tavern_pool']:4d} -> expected {p['expected']:4d}: "
              f"+{len(p['added'])} ({new_cards} new cards) -{len(p['removed'])}")
    print(f"changed in patch: {len(result['changes'])}; TavernGym already differed: "
          f"{len(result['tg_differs'])}")
    print(f"wrote {md} and {js}")


LABELS = {"minion": "Shop minions (tiers 1-6)", "tier7": "Tier 7 minions", "hero": "Heroes",
          "spell": "Tavern spells", "trinket": "Trinkets", "dark_gift": "Dark Gifts",
          "timewarp": "Timewarp cards"}


def render(r):
    L = [f"# Content diff: TavernGym {r['tavern_build']} vs client {r['new']}", "",
         f"Generated by `tools/client_diff.py` (client flags of build {r['base']} vs {r['new']}).",
         "Expected pool = TavernGym's pool + client flag changes; the server ruleset can still",
         "differ (type rotation, bans), so confirm against logged shops before relying on it.", "",
         "| Category | TavernGym pool | Expected | Added | of which new cards | Removed |",
         "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for cat, p in r["pools"].items():
        n = sum(1 for x in p["added"] if x["state"] == "new card")
        L.append(f"| {LABELS[cat]} | {p['tavern_pool']} | {p['expected']} | {len(p['added'])} | "
                 f"{n} | {len(p['removed'])} |")
    L.append(f"\nStat or text changes in the patch: {len(r['changes'])}. TavernGym values that "
             f"already differed from its own build's client data: {len(r['tg_differs'])}.")
    for cat, p in r["pools"].items():
        if not (p["added"] or p["removed"]):
            continue
        L += ["", f"## {LABELS[cat]}"]
        if p["added"]:
            L += ["", "Added:", "", "| Tier | Card ID | Name | 中文名 | TavernGym |",
                  "| ---: | --- | --- | --- | --- |"]
            for x in sorted(p["added"], key=lambda x: (x["tier"], x["id"])):
                L.append(f"| {x['tier']} | {x['id']} | {x['name']} | {x['name_zh']} | {x['state']} |")
        if p["removed"]:
            L += ["", "Removed:", "", "| Tier | Card ID | Name | 中文名 | Was in TavernGym pool |",
                  "| ---: | --- | --- | --- | --- |"]
            for x in sorted(p["removed"], key=lambda x: (x["tier"], x["id"])):
                L.append(f"| {x['tier']} | {x['id']} | {x['name']} | {x['name_zh']} | "
                         f"{'yes' if x['in_tavern_pool'] else 'no'} |")
    for title, rows in (("Changed in the patch", r["changes"]),
                        ("TavernGym differs from its own build's client data", r["tg_differs"])):
        if not rows:
            continue
        L += ["", f"## {title}", "", "| Card ID | Name | Kind | Field | Before | After |",
              "| --- | --- | --- | --- | --- | --- |"]
        for x in rows:
            for k, (va, vb) in x["diff"].items():
                L.append(f"| {x['id']} | {x['name']} | {x['kind']} | {k} | {va} | {vb} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
