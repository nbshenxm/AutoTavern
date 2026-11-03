"""Build a patch overlay from two client builds and apply it to cards.json.

The resource bundle gen_carddb.py reads is the 36.6.1 pack and can't take a later patch, so a
patch is an overlay (tools/overlays/<patch>.json) on top of the committed cards.json. The card
fields come from the client data: every TavernGym card whose stats, Tier, cost (Trinket and Tavern
spell prices), text, keywords or Trinket kind changed between the base build and the new one,
golden and pool-less cards included (client_diff.py lists pool cards only). Server-side changes
(pools, Dark Gift windows) come from `--manual`, a JSON with the same layout, from the patch notes.

    python -X utf8 tools/patch_overlay.py --base data/client/253932 --new data/client/256589 \\
        --manual tools/overlays/37.0.2_manual.json --patch 37.0.2
Writes tools/overlays/<patch>.json and rewrites crates/taverngym/data/cards.json.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from gen_carddb import OUT, apply_overlay, clean, render, set_texts  # noqa: E402

# Client mechanics that are TavernGym keywords (the rest are rules text).
KEYWORDS = {"DIVINE_SHIELD", "TAUNT", "WINDFURY", "MEGA_WINDFURY", "REBORN", "POISONOUS",
            "VENOMOUS", "STEALTH", "CLEAVE", "MAGNETIC", "BACON_RALLY", "DEATHRATTLE",
            "BATTLECRY", "AVENGE", "START_OF_COMBAT", "END_OF_TURN_TRIGGER", "TRIGGER_VISUAL"}
SCHOOL = {"LESSER_TRINKET": "trinket_lesser", "GREATER_TRINKET": "trinket_greater"}


def load(d):
    out = {}
    for lang in ("enUS", "zhCN"):
        p = Path(d) / f"{lang}.json"
        out[lang] = {c["id"]: c for c in json.loads(p.read_text(encoding="utf-8"))} if p.is_file() else {}
    return out


def card_changes(db, base, new):
    """{card id: fields} for every TavernGym card the client changed."""
    out = {}
    for c in db["cards"]:
        o, w = base["enUS"].get(c["id"]), new["enUS"].get(c["id"])
        if not o or not w or not c["id"].startswith(("BG", "TB_Bacon")):
            continue
        f = {}
        for k, ck in (("attack", "atk"), ("health", "hp"), ("techLevel", "tier")):
            if o.get(k) != w.get(k) and w.get(k) is not None:
                f[ck] = w[k]
        if o.get("cost", 0) != w.get("cost", 0) and c["kind"] in (
                "trinket_lesser", "trinket_greater", "tavern_spell"):
            f["cost"] = w.get("cost", 0)
        # "&" is a client line-break hint, not a text change
        if clean(o.get("text")).replace("&", "") != clean(w.get("text")).replace("&", ""):
            f["text"] = clean(w.get("text"))
            f["text_zh"] = clean(new["zhCN"].get(c["id"], {}).get("text"))
        om, wm = set(o.get("mechanics") or []) & KEYWORDS, set(w.get("mechanics") or []) & KEYWORDS
        if wm - om:
            f["keywords_add"] = sorted(wm - om)
        if om - wm:
            f["keywords_remove"] = sorted(om - wm)
        if o.get("spellSchool") != w.get("spellSchool") and w.get("spellSchool") in SCHOOL:
            f["kind"] = SCHOOL[w["spellSchool"]]
        if f:
            out[c["id"]] = f
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--manual", required=True)
    ap.add_argument("--patch", required=True)
    a = ap.parse_args()
    text = OUT.read_text(encoding="utf-8")
    db = json.loads(text)
    if render(db) != text:
        sys.exit(f"{OUT} doesn't round-trip through render(): not applying")
    base, new = load(a.base), load(a.new)
    manual = json.loads(Path(a.manual).read_text(encoding="utf-8"))
    cards = card_changes(db, base, new)
    for cid, f in manual.get("cards", {}).items():
        cards.setdefault(cid, {}).update(f)
    build = Path(a.new).name
    meta = {"client_version": f"{a.patch}.{build}", "server_patch": a.patch,
            "overlay": db["meta"]["overlay"] + f"; tools/overlays/{a.patch}.json (HearthstoneJSON {build})"}
    overlay = {"cards": dict(sorted(cards.items())), "meta": meta, "pools": manual.get("pools", {})}
    path = ROOT / "tools" / "overlays" / f"{a.patch}.json"
    path.write_text(json.dumps(overlay, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    db = apply_overlay(db, overlay)
    for c in db["cards"]:
        if c["id"] in cards and "text" in cards[c["id"]]:
            for k in ("text_alt", "text_alt_zh"):
                c.pop(k, None)
            set_texts(c)
    OUT.write_bytes(render(db).encode("utf-8"))
    print(f"wrote {path} ({len(cards)} cards) and {OUT}")


if __name__ == "__main__":
    main()
