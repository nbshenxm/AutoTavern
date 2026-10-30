"""Meta compositions from HSReplay's public Battlegrounds comp guides
(https://hsreplay.net/api/v1/battlegrounds/comp_guides/: name, tier, core and add-on cards, play
advice), and the one a player's cards are closest to.

    python -X utf8 -m advisor.meta          # fetch (at most once a day) and list the comps
"""

import gzip
import json
import sys
import time
import urllib.request
from pathlib import Path

from advisor.state import CARDS

URL = "https://hsreplay.net/api/v1/battlegrounds/comp_guides/?format=json"
# Firestone's public trinket stats (the last 7 days: average placement and pick rate, overall and
# by MMR bracket); no stated license: for this personal tool only, never redistributed
TRINKET_URL = "https://static.zerotoheroes.com/api/bgs/trinket-stats/past-seven/overview-from-hourly.gz.json"
HERO_URL = "https://static.zerotoheroes.com/api/bgs/hero-stats/mmr-100/past-seven/overview-from-hourly.gz.json"
# The same for the top 1% of players by MMR (their warband strength by turn: library seats'
# target, advisor.library)
TOP_HERO_URL = HERO_URL.replace("mmr-100", "mmr-1")
# Tavern Link's catalog (tavern-link.pages.dev, from bg-db.pages.dev): 19 curated comps for the
# current patch (from Jeef's guides) with their stages and final boards, and the card list; no
# stated license: personal use only, never redistributed (data/ is not in the repository)
TAVERN_LINK_URL = "https://tavern-link.pages.dev/catalog.json"
# Firestone's minion type codes (Hearthstone's Race enum) -> TavernGym's names
RACE_CODES = {11: "UNDEAD", 14: "MURLOC", 15: "DEMON", 17: "MECHANICAL", 18: "ELEMENTAL",
              20: "BEAST", 23: "PIRATE", 24: "DRAGON", 43: "QUILBOAR", 92: "NAGA", 126: "ABERRATION"}
META = Path(__file__).resolve().parents[1] / "data" / "meta"
GUIDES = META / "comp_guides.json"
TRINKETS = META / "trinket_stats.json"
HEROES = META / "hero_stats.json"
TOP_HEROES = META / "hero_stats_top1.json"
TAVERN_LINK = META / "tavern_link_catalog.json"
MAX_AGE = 24 * 3600

_DBF = {c["dbf"]: c for c in json.loads(CARDS.read_text(encoding="utf-8"))["cards"]}
_NORMAL = {c["id"]: (c["normal"] or c["id"]) for c in _DBF.values()}


def _download(url, path, force=False):
    """`url`'s JSON into `path` when missing or older than a day; the last copy when offline.
    Returns `path`, or None when there is none."""
    if path.exists() and not force and time.time() - path.stat().st_mtime < MAX_AGE:
        return path
    META.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TavernAdvisor (personal use)",
                                                   "Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
        if raw[:2] == b"\x1f\x8b":  # gzip magic: the trinket stats come compressed
            raw = gzip.decompress(raw)
        data = json.loads(raw.decode("utf-8"))
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:  # offline: keep the last copy
        print(f"{path.name} not fetched: {type(e).__name__}: {e}", flush=True)
    return path if path.exists() else None


def fetch(force=False):
    """The comp guides and the trinket stats, downloaded when missing or older than a day."""
    _download(TRINKET_URL, TRINKETS, force)
    _download(HERO_URL, HEROES, force)
    _download(TOP_HERO_URL, TOP_HEROES, force)
    _download(TAVERN_LINK_URL, TAVERN_LINK, force)
    return _download(URL, GUIDES, force)


def warband_curve(path=TOP_HEROES):
    """turn -> average warband Attack+Health over every hero (weighted by games), from a hero
    stats file (default: the top 1% of players); {} without it."""
    if not Path(path).exists():
        return {}
    acc = {}
    for h in json.loads(Path(path).read_text(encoding="utf-8")).get("heroStats") or []:
        n = h.get("dataPoints") or 0
        for w in h.get("warbandStats") or []:
            if n and w.get("averageStats") is not None:
                a = acc.setdefault(int(w["turn"]), [0.0, 0])
                a[0] += w["averageStats"] * n
                a[1] += n
    return {t: x / n for t, (x, n) in sorted(acc.items()) if n}


def hero_stats():
    """hero card id -> {"place": average placement, "pick": pick rate when offered, "n": games,
    "types": {type: change in average placement when that type is in the lobby},
    "warband": {turn: average warband Attack+Health}} (the last 7 days, all MMRs); {} without
    the file."""
    if not HEROES.exists():
        return {}
    out = {}
    for h in json.loads(HEROES.read_text(encoding="utf-8")).get("heroStats") or []:
        if not h.get("heroCardId"):
            continue
        out[h["heroCardId"]] = {
            "place": h["averagePosition"], "n": h["dataPoints"],
            "pick": h["totalPicked"] / h["totalOffered"] if h.get("totalOffered") else None,
            "types": {RACE_CODES[t["tribe"]]: t.get("impactAveragePosition", 0)
                      for t in h.get("tribeStats") or [] if t.get("tribe") in RACE_CODES},
            "warband": {w["turn"]: w["averageStats"] for w in h.get("warbandStats") or []}}
    return out


def hero_place(stats, lobby=()):
    """A hero's expected placement, its type impacts added for the lobby's known types."""
    return stats["place"] + sum(stats["types"].get(t, 0) for t in lobby)


def trinket_stats():
    """card id -> {"place": average placement, "pick": pick rate, "n": games} (the last 7 days,
    all MMRs); {} without the file."""
    if not TRINKETS.exists():
        return {}
    rows = json.loads(TRINKETS.read_text(encoding="utf-8")).get("trinketStats") or []
    return {r["trinketCardId"]: {"place": r["averagePlacement"], "pick": r["pickRate"],
                                 "n": r["dataPoints"]} for r in rows if r.get("trinketCardId")}


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


def main():
    fetch(force="--force" in sys.argv)
    for g in sorted(comps(), key=lambda g: g["tier"]):
        print(g["tier"], g["name"], g["core"])


if __name__ == "__main__":
    main()
