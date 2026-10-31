"""The overlay's genre panel: a few curated comps (Tavern Link's catalog, the ones training plays)
with a recommendation share and the one or two cards each needs most. Score of a comp: the share
of its core cards you own (twice) and of its other cards (once), with one free point so an empty
start still ranks, times its guide tier (S 1, A 0.85, B 0.7); none when its types aren't in your
lobby (as far as seen). The top three are shown as shares of their sum. Needed: its core cards you
don't own, of a Tavern Tier you have or reach next, lowest first.
"""

import json

from advisor import bridge, meta
from advisor.state import CAT, normal_form

TIER_WEIGHT = {"S": 1.0, "A": 0.85, "B": 0.7}
_COMPS = None


def comps():
    """[{name, tier, types, core (ids), cards (ids)}] from Tavern Link's catalog, built once."""
    global _COMPS
    if _COMPS is None:
        _COMPS = []
        if meta.TAVERN_LINK.exists():
            cat = json.loads(meta.TAVERN_LINK.read_text(encoding="utf-8"))
            by_name = {m["name"]: m for m in cat.get("minions", [])}
            zh_type = {z: e.upper() for m in cat.get("minions", [])
                       for z, e in zip(m.get("racesZh") or [], m.get("races") or [])}

            def ids(names):
                out = []
                for n in names:
                    c = meta._DBF.get((by_name.get(n) or {}).get("id"))
                    x = normal_form(c["id"])[0] if c else None
                    if x in CAT and x not in out:
                        out.append(x)
                return out

            for comp in cat.get("comps", []):
                others = [x for st in comp.get("stages", []) for x in st.get("cards", [])]
                others += [c for sl in comp.get("finalBoard", []) for c in sl.get("choices", [])]
                _COMPS.append({"name": comp["name"], "tier": comp.get("tier") or "B",
                               "types": [zh_type[t] for t in comp.get("tribes") or [] if t in zh_type],
                               "core": ids(comp.get("core", [])), "cards": ids(others)})
    return _COMPS


def hints(d, combats, locale="zhCN", name_of=None, top=3):
    """[{name, pct, card_id, need: [{card_id, name}]}] for Options decision `d`."""
    me = d["state"]["friendly"]
    owned = {normal_form(m["card"])[0] for m in me["board"]}
    owned |= {normal_form(h.get("card") or "")[0] for h in bridge.hand_cards(me)}
    lobby = set(bridge.lobby_types(d, combats))
    tier = me.get("tier") or 1
    scored = []
    for c in comps():
        if c["types"] and lobby and not set(c["types"]) & lobby:
            continue
        core = [x for x in c["core"] if x in owned]
        other = [x for x in c["cards"] if x in owned and x not in c["core"]]
        raw = (2 * len(core) + len(other) + 1) / (2 * len(c["core"]) + len(set(c["cards"])) + 1)
        raw *= TIER_WEIGHT.get(c["tier"], 0.7)
        need = sorted((x for x in c["core"] if x not in owned and (CAT[x].get("tier") or 7) <= tier + 1),
                      key=lambda x: CAT[x].get("tier") or 7)[:2]
        scored.append((raw, c, need))
    scored.sort(key=lambda t: -t[0])
    best = scored[:top]
    total = sum(r for r, _, _ in best) or 1
    name = name_of or (lambda cid, loc: CAT.get(cid, {}).get("name_zh" if loc.startswith("zh") else "name", cid))
    def picture(c):  # a key card you own, else its first core card
        mine = [x for x in c["core"] + c["cards"] if x in owned]
        return (mine or c["core"] or c["cards"] or [None])[0]
    return [{"name": c["name"], "pct": round(100 * r / total), "card_id": picture(c),
             "need": [{"card_id": x, "name": name(x, locale)} for x in need]} for r, c, need in best]
