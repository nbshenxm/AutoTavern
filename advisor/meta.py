"""Meta compositions from HSReplay's public Battlegrounds comp guides
(https://hsreplay.net/api/v1/battlegrounds/comp_guides/: name, tier, core and add-on cards, play
advice), and the one a player's cards are closest to.

    python -X utf8 -m advisor.meta          # fetch (at most once a day) and list the comps
    python -X utf8 -m advisor.meta --bot-config comp_bots.json   # and write a bot config
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

from advisor.state import CARDS

URL = "https://hsreplay.net/api/v1/battlegrounds/comp_guides/?format=json"
META = Path(__file__).resolve().parents[1] / "data" / "meta"
GUIDES = META / "comp_guides.json"
MAX_AGE = 24 * 3600

_DBF = {c["dbf"]: c for c in json.loads(CARDS.read_text(encoding="utf-8"))["cards"]}
_NORMAL = {c["id"]: (c["normal"] or c["id"]) for c in _DBF.values()}


def fetch(force=False):
    """The guides file, downloaded when missing or older than a day. Returns its path, or
    None when there is none and the download failed."""
    if GUIDES.exists() and not force and time.time() - GUIDES.stat().st_mtime < MAX_AGE:
        return GUIDES
    META.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "TavernAdvisor (personal use)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        tmp = GUIDES.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(GUIDES)
    except Exception as e:  # offline: keep the last copy
        print(f"comp guides not fetched: {type(e).__name__}: {e}", flush=True)
    return GUIDES if GUIDES.exists() else None


def comps():
    """[{name, tier, core: [card ids], addon: [card ids], ...}] from the local guides file."""
    if not GUIDES.exists():
        return []
    out = []
    for g in json.loads(GUIDES.read_text(encoding="utf-8")):
        if g.get("hidden"):
            continue
        ids = lambda dbfs: [_DBF[d]["id"] for d in dbfs if d in _DBF]
        out.append({"name": g["name"], "tier": g["tier"], "core": ids(g["core_cards"]),
                    "addon": ids(g["addon_cards"]), "updated": g.get("last_updated")})
    return out


def closest(cards, guides=None):
    """The comp `cards` (the player's warband and hand, card ids) are closest to: core cards
    count twice, add-ons once; None below two core cards. {name, tier, have, missing}."""
    owned = {_NORMAL.get(c, c) for c in cards}
    best = None
    for g in guides if guides is not None else comps():
        core = [c for c in g["core"] if c in owned]
        addon = [c for c in g["addon"] if c in owned]
        if len(core) < 2:
            continue
        score = (2 * len(core) + len(addon)) / (2 * len(g["core"]) + len(g["addon"]) or 1)
        if best is None or score > best[0]:
            best = (score, g, core)
    if best is None:
        return None
    _, g, core = best
    return {"name": g["name"], "tier": g["tier"], "have": len(core), "of": len(g["core"]),
            "missing": [c for c in g["core"] if c not in owned]}


TIER_WEIGHT = {1: 3.0, 2: 2.0, 3: 1.0}  # how often a bot takes a comp of each HSReplay tier


def bot_comps(guides=None):
    """The comps for TavernGym's scripted bots (RulesConfig.bot_comps), weighted by tier."""
    return [{"core": g["core"], "addon": g["addon"], "weight": TIER_WEIGHT.get(g["tier"], 1.0)}
            for g in (guides if guides is not None else comps())]


def main():
    fetch(force="--force" in sys.argv)
    for g in sorted(comps(), key=lambda g: g["tier"]):
        print(g["tier"], g["name"], g["core"])
    if "--bot-config" in sys.argv:  # a RulesConfig for examples/comp_bots.rs
        from advisor.state import GAME_CONFIG
        out = Path(sys.argv[sys.argv.index("--bot-config") + 1])
        out.write_text(json.dumps({**GAME_CONFIG, "bot_comps": bot_comps(), "bot_comp_pct": 50}))


if __name__ == "__main__":
    main()
