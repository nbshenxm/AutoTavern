"""The progress page: data/report.html, written to be read without knowing the code: what the
overlay plays with, whether training makes it stronger, how good its decisions are, whether the
simulator can be trusted, what runs now. The home sync (scripts/sync_model.ps1) remakes it every
hour, like the constructed advisor's model_report.html.

Its sources, all at home:
- the network in the overlay: data/models/best.pt, its promotions data/models/promotions.jsonl;
- training on the office: data/progress/train/RUN/log.jsonl and data/progress/running.txt
  (copied by the home sync);
- your games: %LOCALAPPDATA%/TavernAdvisor/history.jsonl and flagged.jsonl (the live advisor);
- the plain-words note: docs/STATUS.md.

    python -X utf8 -m advisor.report        # writes data/report.html
"""

import html
import json
import os
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PROGRESS = DATA / "progress"
LIVE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TavernAdvisor"
RUNS = {  # the runs worth a line on the chart: what each one is
    "office3": "self-play, fixed rules",
    "gen1": "generations: against the frozen best",
    "gensearch1": "generations + the search's choices",
    "teach1": "hot start: copying the teacher",
    "teachppo1": "generations from the hot start",
    "safe1": "generations, small steps from the best",
    "lib1": "generations + real warbands from your logs",
    "search2": "generations + learning the plan search's choices",
    "lib2": "real warbands + a longer horizon (gamma 1, lambda 0.995)",
    "big1": "a larger network (8.6M) copying the best",
    "big2": "the larger network: real starts, library seats + comps, comp starts, your choices",
    "sig1": "search2 continued with the same signals as big2 (the small network, faster)",
    "emb1": "sig1 with observation version 4 and the card text (the A/B against sig1)",
    "solo1": "AutoTavern's setup: alone against seven library seats, their PPO settings (cluster)",
}
# Checks of the simulator against your logs (docs/REPLAY.md); remade by hand when rerun
# Bugs the audits found and fixed (docs/ROBUSTNESS.md): date, what was wrong, what it did, found by
AUDIT_FIXES = [
    ("Oct 30", "An Activate could be advised twice in a turn", "the plan reused a minion's once-a-turn Activate", "your report"),
    ("Oct 30", "No hero-pick advice", "the hero offer never reached the advisor", "your report"),
    ("Oct 30", "Sell a minion, then play the same card from hand", "plans with a pointless detour (31 of 325 that day)", "your report"),
    ("Oct 30", "A random card used as if known", "after Auto Reveille's random Volumizer the plan went on with one you didn't have", "your report"),
    ("Oct 30", "Free trinket offers charged", "a trinket's or Hero Power's offer cost Gold in the rebuild (12 became 6)", "whole-turn replay"),
    ("Oct 30", "Ambassador Faelin's minions never unlocked", "the held minions stayed locked after reaching their Tier", "whole-turn replay"),
    ("Oct 30", "Baller improvements lost", "a Baller sold at round 14 gave +2/+2 instead of +14/+14", "whole-turn replay"),
    ("Oct 30", "Maximum Gold bonuses lost", "16 of 126 turns had a Gold or two less to spend", "turn-transition check"),
    ("Oct 30", "Discounted Tavern spells at full price", "a buy you could afford was refused (Ominous Seer's discount)", "legality check"),
    ("Oct 30", "Who attacks first, Dark Gifts, triples in a rebuilt hand", "combats and warbands rebuilt wrong", "combat replay"),
    ("Oct 30", "Trinket stealth cost in training: Freeze + End with Gold", "the network learned to dodge the unspent-Gold cost by freezing", "case study"),
    ("Oct 31", "The simulator check stopped running unnoticed", "a broken line in advisor.fidelity made it crash after every game since Oct 30 evening, while the page said no drop", "audit self-check"),
    ("Oct 31", "Magnetize replayed as a play", "a Magnetic card dropped on a Mech was replayed beside it (refused on a full warband)", "trinket audit"),
    ("Oct 31", "Round-6 trinket offer never advised", "the live tracker skipped offers that weren't between minions while unanswered", "your report"),
    ("Oct 31", "Unspent Gold at the end of a plan never counted", "read after End Turn, when nothing is legal: the review and the play audit missed 10% of late plans ending with 3+ Gold", "audit self-check"),
]
SIMULATOR = [
    ("Combats replayed from your logs", "92.5-95%", "of 106 logged combats end as the simulator predicts (win, tie or loss)"),
    ("Actions offered", "94%", "of your logged decisions: the simulator allows exactly the actions the game offered"),
    ("Recruit rules", "all agree", "gold, costs, Tavern size and Tier odds checked against the logs"),
    ("Patch 37.0", "no changes", "no Battlegrounds card or rule changed from the simulator's 36.6.3"),
]
CSS = """
:root { color-scheme: light; --surface: #fcfcfb; --text: #0b0b0b; --text-2: #52514e; --muted: #8a8984; --grid: #e6e5e0;
  --mid: #b9b8b1; --s1: #2a78d6; --s2: #eb6834; --s3: #1f9e6e; --s4: #8a4fc7; --card: #ffffff; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { color-scheme: dark; --surface: #1a1a19; --text: #f0efec;
  --text-2: #c3c2b7; --muted: #8f8e88; --grid: #2e2e2c; --mid: #55544f; --s1: #3987e5; --s2: #d95926; --s3: #2bb381; --s4: #a77ee6; --card: #222221; } }
:root[data-theme="dark"] { color-scheme: dark; --surface: #1a1a19; --text: #f0efec; --text-2: #c3c2b7; --muted: #8f8e88;
  --grid: #2e2e2c; --mid: #55544f; --s1: #3987e5; --s2: #d95926; --s3: #2bb381; --s4: #a77ee6; --card: #222221; }
body { margin: 0; background: var(--surface); color: var(--text); font: 15px/1.5 system-ui, sans-serif; }
main { max-width: 920px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 24px; margin: 0 0 4px; } h2 { font-size: 18px; margin: 36px 0 6px; } h3 { font-size: 15px; margin: 22px 0 4px; }
.lead { color: var(--text-2); margin: 0 0 12px; max-width: 70ch; }
.sub, .muted, .note { color: var(--text-2); } .sub { margin: 4px 0 12px; font-size: 13px; max-width: 80ch; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 8px 0; }
.tile { background: var(--card); border: 1px solid var(--grid); border-radius: 8px; padding: 12px 14px; }
.bar { height: 8px; background: var(--grid); border-radius: 4px; overflow: hidden; margin: 8px 0 3px; }
.bar .fill { height: 100%; background: var(--s1); }
.job { font-weight: 600; margin: 2px 0; } .small { font-size: 12px; }
ul.check { list-style: none; padding-left: 0; } ul.check li { margin: 3px 0; } ul.check li.done { color: var(--muted); }
.label { font-size: 13px; color: var(--text-2); } .value { font-size: 28px; font-weight: 600; margin: 2px 0; font-variant-numeric: tabular-nums; }
.value small { font-size: 15px; font-weight: 400; color: var(--text-2); } .note { font-size: 12px; }
.chart { width: 100%; height: auto; margin-top: 8px; } .grid { stroke: var(--grid); } .mid { stroke: var(--mid); stroke-dasharray: 4 3; }
.tick { fill: var(--muted); font-size: 11px; } .direct { fill: var(--text-2); font-size: 12px; }
.line { fill: none; stroke-width: 2; } .s1 { stroke: var(--s1); } .s2 { stroke: var(--s2); } .s3 { stroke: var(--s3); } .s4 { stroke: var(--s4); }
.dash { stroke-dasharray: 5 4; }
.promo { fill: var(--s1); stroke: var(--surface); stroke-width: 2; } .hit { fill: transparent; } .hit:hover { fill: var(--grid); opacity: .5; }
.legend { display: flex; gap: 18px; font-size: 13px; color: var(--text-2); margin: 4px 0 0; flex-wrap: wrap; }
.key { display: inline-block; width: 14px; height: 3px; vertical-align: middle; margin-right: 6px; border-radius: 2px; }
.k1 { background: var(--s1); } .k2 { background: var(--s2); } .k3 { background: var(--s3); } .k4 { background: var(--s4); }
.verdict { background: var(--card); border: 1px solid var(--grid); border-radius: 8px; padding: 10px 14px; margin: 8px 0 14px; }
.verdict p { margin: 6px 0; } .warn { color: #c2410c; font-size: 13px; } .bar-rule { fill: #d9480f; } .bar-signal { fill: #e8a33d; }
.dot { stroke: none; } .dot.s1 { fill: var(--s1); } .dot.s2 { fill: var(--s2); } .dot.s3 { fill: var(--s3); } .dot.s4 { fill: var(--s4); }
.wrap { overflow-x: auto; } table { border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 6px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--grid); vertical-align: top; }
th { color: var(--text-2); font-weight: 500; } td.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
code { font-size: 13px; } ul { padding-left: 20px; } li { margin: 4px 0; }
"""


def _jsonl(path):
    rows = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def _esc(s):
    return html.escape(str(s))


def _when(stamp):
    try:
        return datetime.fromisoformat(stamp).strftime("%b %d, %H:%M")
    except (TypeError, ValueError):
        return "?"


def _tiles(tiles):
    return '<div class="tiles">' + "".join(
        f'<div class="tile"><div class="label">{a}</div><div class="value">{b}</div>'
        f'<div class="note">{c}</div></div>' for a, b, c in tiles) + "</div>"


def _markdown(text):
    """docs/STATUS.md's sections (## headings, - bullets, **bold**, `code`, [links])."""
    def inline(s):
        s = _esc(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
        return re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", s)
    out, items, rows, para, intro = [], [], [], [], True
    def flush():
        if para:
            out.append(f'<p class="sub">{inline(" ".join(para))}</p>')
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            items.clear()
        if rows:
            cells = [[x.strip() for x in r.strip().strip("|").split("|")] for r in rows
                     if not set(r.replace("|", "").strip()) <= set("- ")]
            head, body = cells[0], cells[1:]
            out.append('<div class="wrap"><table><tr>' + "".join(f"<th>{inline(h)}</th>" for h in head)
                       + "</tr>" + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
                                           for r in body) + "</table></div>")
            rows.clear()
    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            intro = False
            out.append(f"<h3>{inline(line[3:])}</h3>")
        elif intro:
            continue  # the title and the note about the note
        elif line.startswith("|"):
            rows.append(line)
        elif line.startswith("- "):
            items.append(line[2:])
        elif line.startswith("  ") and items:
            items[-1] += " " + line.strip()
        elif not line.strip():
            flush()
        else:
            para.append(line.strip())
    flush()
    return "".join(out)


def _chart(series, label, lo=1.0, hi=None, reference=(4.5, "the bots' average")):
    """Mean placement (lower is better) per x: `series` = [(name, css class, [(x, y, tip)])]."""
    pts = [p for _, _, s in series for p in s]
    if not pts:
        return '<p class="sub">No data yet.</p>'
    w, h, left, right, top, bottom = 760, 260, 40, 190, 12, 30
    pw, ph = w - left - right, h - top - bottom
    xs = [p[0] for p in pts]
    x0, x1 = min(xs), max(xs) if max(xs) > min(xs) else min(xs) + 1
    hi = hi or max(5.0, max(p[1] for p in pts) + 0.3)
    x = lambda v: left + pw * (v - x0) / (x1 - x0)
    y = lambda v: top + ph * (v - lo) / (hi - lo)  # 1st at the top
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{_esc(label)}" class="chart">']
    for k in range(int(lo), int(hi) + 1):
        out.append(f'<line x1="{left}" x2="{left + pw}" y1="{y(k):.1f}" y2="{y(k):.1f}" class="grid"/>'
                   f'<text x="{left - 6}" y="{y(k) + 4:.1f}" class="tick" text-anchor="end">{k}</text>')
    if reference:
        out.append(f'<line x1="{left}" x2="{left + pw}" y1="{y(reference[0]):.1f}" y2="{y(reference[0]):.1f}" class="mid"/>'
                   f'<text x="{left + pw + 6}" y="{y(reference[0]) + 4:.1f}" class="direct">{reference[1]}</text>')
    for name, cls, s in series:
        if not s:
            continue
        s = sorted(s)
        d = " ".join(f'{"M" if j == 0 else "L"}{x(a):.1f},{y(b):.1f}' for j, (a, b, _) in enumerate(s))
        out.append(f'<path d="{d}" class="line {cls}"/>')
        for a, b, tip in s:
            out.append(f'<circle cx="{x(a):.1f}" cy="{y(b):.1f}" r="7" class="hit"><title>{_esc(tip)}</title></circle>')
        a, b, _ = s[-1]
        out.append(f'<text x="{x(a) + 8:.1f}" y="{y(b) + 4:.1f}" class="direct">{_esc(name)} {b:.2f}</text>')
    out.append("</svg>")
    return "".join(out)


def _overview(rows):
    """Over time: the network in the overlay against seven plain bots (a step at each
    promotion), every candidate judged (faint), and each promoted network head to head against
    the one it replaced (under 4.5: stronger). Placements, lower is better."""
    pts = []
    for r in rows:
        try:
            t = datetime.fromisoformat(r["time"]).timestamp()
        except (KeyError, TypeError, ValueError):
            continue
        pts.append((t, r))
    if not pts:
        return '<p class="sub">No promotions yet.</p>'
    w, h, left, right, top, bottom = 760, 300, 40, 200, 14, 34
    pw, ph = w - left - right, h - top - bottom
    t0, t1 = pts[0][0], max(pts[-1][0], datetime.now().timestamp())
    lo, hi = 1.0, 5.0
    x = lambda t: left + pw * (t - t0) / max(1.0, t1 - t0)
    y = lambda v: top + ph * (min(max(v, lo), hi) - lo) / (hi - lo)
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Strength over time" class="chart">']
    for k in range(int(lo), int(hi) + 1):
        out.append(f'<line x1="{left}" x2="{left + pw}" y1="{y(k):.1f}" y2="{y(k):.1f}" class="grid"/>'
                   f'<text x="{left - 6}" y="{y(k) + 4:.1f}" class="tick" text-anchor="end">{k}</text>')
    out.append(f'<line x1="{left}" x2="{left + pw}" y1="{y(4.5):.1f}" y2="{y(4.5):.1f}" class="mid"/>'
               f'<text x="{left + pw + 6}" y="{y(4.5) + 4:.1f}" class="direct">4.5: even</text>')
    span = t1 - t0
    step = next((s for s in (3600, 3 * 3600, 6 * 3600, 12 * 3600, 86400, 2 * 86400) if span / s <= 8), 7 * 86400)
    tick = (int(t0) // step + 1) * step
    while tick < t1:
        d = datetime.fromtimestamp(tick)
        label = d.strftime("%b %d") if d.hour == 0 or step >= 86400 else d.strftime("%H:%M")
        out.append(f'<line x1="{x(tick):.1f}" x2="{x(tick):.1f}" y1="{top}" y2="{top + ph}" class="grid"/>'
                   f'<text x="{x(tick):.1f}" y="{h - 12}" class="tick" text-anchor="middle">{label}</text>')
        tick += step
    out.append(f'<text x="{left}" y="{h - 1}" class="tick">{datetime.fromtimestamp(t0):%b %d %H:%M}</text>')
    for t, r in pts:  # every candidate judged
        if r.get("gate") and not r.get("promoted"):
            out.append(f'<circle cx="{x(t):.1f}" cy="{y(r["gate"]["mean_place"]):.1f}" r="2.5" '
                       f'style="fill: var(--mid)"><title>{_esc(_when(r["time"]))}: '
                       f'{_esc(r.get("candidate", ""))} {r["gate"]["mean_place"]:.2f}, not promoted</title></circle>')
    promo = [(t, r) for t, r in pts if r.get("promoted") and r.get("gate")]
    if promo:
        d, prev = "", None
        for t, r in promo:
            v = r["gate"]["mean_place"]
            d += f"M{x(t):.1f},{y(v):.1f}" if prev is None else f" H{x(t):.1f} V{y(v):.1f}"
            prev = v
        d += f" H{x(t1):.1f}"
        out.append(f'<path d="{d}" class="line s1"/>')
        for t, r in promo:
            v = r["gate"]["mean_place"]
            src = r.get("candidate", "").split("/")[-2] if "/" in r.get("candidate", "") else r.get("candidate", "")
            out.append(f'<circle cx="{x(t):.1f}" cy="{y(v):.1f}" r="5" class="promo"><title>'
                       f'{_esc(_when(r["time"]))}: {_esc(src)} iteration {r.get("iteration")} promoted, '
                       f'{v:.2f} against the bots</title></circle>')
        out.append(f'<text x="{x(t1) + 8:.1f}" y="{y(prev) + 4:.1f}" class="direct">vs plain bots {prev:.2f}</text>')
        hh = [(t, r["head_to_head"]["mean_place"]) for t, r in promo if (r.get("head_to_head") or {}).get("mean_place")]
        for t, v in hh:
            out.append(f'<circle cx="{x(t):.1f}" cy="{y(v):.1f}" r="5" style="fill: var(--s2)"><title>'
                       f'head to head against the network it replaced: {v:.2f}</title></circle>')
        if hh:
            out.append(f'<text x="{x(hh[-1][0]) + 8:.1f}" y="{y(hh[-1][1]) - 8:.1f}" class="direct">'
                       f'vs the one it replaced {hh[-1][1]:.2f}</text>')
    out.append("</svg>")
    legend = ('<div class="legend"><span><span class="key k1"></span>the network in your overlay, '
              'against seven plain bots (a dot: promoted)</span><span><span class="key k2"></span>'
              'a promoted network against seven copies of the one it replaced</span>'
              '<span><span class="key" style="background: var(--mid)"></span>candidates not promoted'
              '</span></div>')
    return "".join(out) + legend


def _curve_chart(curve):
    """Warband Attack+Health by round on a log scale: the network's own games, the real lobbies
    in your logs, the public average."""
    import math
    rows = curve.get("rounds") or []
    series = [("network", "s1", "the network"), ("your_lobbies", "s2", "your lobbies"),
              ("public", "s3", "public average")]
    w, h, left, right, top, bottom = 760, 280, 52, 190, 12, 30
    pw, ph = w - left - right, h - top - bottom
    lo, hi = 0.0, 5.0  # 1 .. 100,000
    x = lambda r: left + pw * (r - 1) / 15
    y = lambda v: top + ph * (1 - (math.log10(max(v, 1)) - lo) / (hi - lo))
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Warband strength by round" class="chart">']
    for k in range(6):
        out.append(f'<line x1="{left}" x2="{left + pw}" y1="{y(10 ** k):.1f}" y2="{y(10 ** k):.1f}" class="grid"/>'
                   f'<text x="{left - 6}" y="{y(10 ** k) + 4:.1f}" class="tick" text-anchor="end">{10 ** k:,}</text>')
    for r in range(1, 17, 2):
        out.append(f'<text x="{x(r):.1f}" y="{h - 10}" class="tick" text-anchor="middle">{r}</text>')
    for key, cls, label in series:
        pts = [(row["round"], row[key]["stats"]) for row in rows if row.get(key)]
        if len(pts) < 2:
            continue
        d = " ".join(f'{"M" if i == 0 else "L"}{x(a):.1f},{y(b):.1f}' for i, (a, b) in enumerate(pts))
        out.append(f'<path d="{d}" class="line {cls}"/>')
        for a, b in pts:
            out.append(f'<circle cx="{x(a):.1f}" cy="{y(b):.1f}" r="6" class="hit"><title>round {a}: '
                       f'{_esc(label)} {b:,.0f}</title></circle>')
        a, b = pts[-1]
        out.append(f'<text x="{x(a) + 8:.1f}" y="{y(b) + 4:.1f}" class="direct">{_esc(label)} {b:,.0f}</text>')
    out.append("</svg>")
    return "".join(out)


def _network():
    path = DATA / "models" / "best.pt"
    if not path.is_file():
        return None
    import torch
    ck = torch.load(path, map_location="cpu", weights_only=False)
    return {"source": ck.get("source"), "gate": ck.get("gate") or {}, "h2h": ck.get("head_to_head"),
            "mtime": datetime.fromtimestamp(path.stat().st_mtime)}


def _promotions():
    rows = [r for r in _jsonl(DATA / "models" / "promotions.jsonl") if r.get("promoted")]
    pts = [(i + 1, r["gate"]["mean_place"], f"{_when(r.get('time'))}: {r.get('candidate')} "
            f"iteration {r.get('iteration')}, {r['gate']['mean_place']:.2f} ± {r['gate']['se']:.2f}")
           for i, r in enumerate(rows) if r.get("gate")]
    return rows, pts


def _h2h(r):
    h = r.get("head_to_head") or {}
    return f"{h['mean_place']:.2f} ± {h['se']:.2f}" if "mean_place" in h else "first"


def _runs():
    out = {}
    for run in RUNS:
        rows = _jsonl(PROGRESS / "train" / run / "log.jsonl")
        if rows:
            out[run] = rows
    return out


def _running():
    path = PROGRESS / "running.txt"
    if not path.is_file():
        return [], None
    lines = [l for l in path.read_text(encoding="utf-8-sig", errors="replace").splitlines() if l.strip()]
    synced = datetime.fromtimestamp(path.stat().st_mtime)
    jobs = []
    for l in lines:
        m = re.search(r"-m advisor\.(\w+)", l)
        run = re.search(r"--run (\S+)", l)
        hours = re.search(r"--hours (\S+)", l)
        job = (m.group(1), run.group(1) if run else "", hours.group(1) if hours else "") if m else None
        if job and job not in jobs:  # a pool's workers repeat its command line
            jobs.append(job)
    return jobs, synced


def _games():
    """Your games with the advisor: advice given, flagged, plans with a Refresh."""
    rows = _jsonl(LIVE / "history.jsonl")
    flagged = len(_jsonl(LIVE / "flagged.jsonl"))
    recruit = [r for r in rows if (r.get("seen") or {}).get("kind") != "choices"]
    refresh = sum(1 for r in recruit if any(p.startswith(("Refresh", "刷新"))
                                            for p in (r["advice"].get("plan") or [])))
    games = len({(r["seen"].get("log"), r["seen"].get("segment")) for r in rows if r.get("seen")})
    return {"advice": len(rows), "games": games, "flagged": flagged,
            "refresh": refresh / len(recruit) if recruit else None}


FIDELITY_LABELS = [
    ("legal", "Allowed actions", "of your logged decisions: the simulator allows exactly what the game offered"),
    ("actions", "Single actions", "of your actions, replayed one at a time: the warband matches the game's next"),
    ("turns", "Whole turns", "of your turns, replayed from their start: never part from the game (random draws aside)"),
    ("transitions", "Between turns", "of turn changes: Gold, Tier and costs at the next turn match"),
    ("combat", "Combats", "how likely the simulator finds each combat's real result (average)"),
]


def _pct_chart(history, keys, label, lo=0.8):
    """Shares over time, higher is better (top): `history` = [{time, key: share}], one line per key."""
    w, h, left, right, top, bottom = 760, 220, 44, 150, 10, 26
    pw, ph = w - left - right, h - top - bottom
    n = len(history)
    x = lambda i: left + (pw * i / (n - 1) if n > 1 else pw / 2)
    y = lambda v: top + ph * (1 - (max(lo, v) - lo) / (1 - lo))
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{_esc(label)}" class="chart">']
    for t in (lo, (lo + 1) / 2, 1.0):
        out.append(f'<line x1="{left}" x2="{left + pw}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/>'
                   f'<text x="{left - 6}" y="{y(t) + 4:.1f}" class="tick" text-anchor="end">{t:.0%}</text>')
    for k, (key, name) in enumerate(keys):
        pts = [(i, r[key]) for i, r in enumerate(history) if r.get(key) is not None]
        if not pts:
            continue
        cls = f"s{1 + k % 4}"
        d = " ".join(f'{"M" if j == 0 else "L"}{x(i):.1f},{y(v):.1f}' for j, (i, v) in enumerate(pts))
        out.append(f'<path d="{d}" class="line {cls}"/>')
        for i, v in pts:
            out.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="4" class="dot {cls}"><title>'
                       f'{_esc(name)}: {v:.1%} ({_esc(history[i]["time"].replace("T", " "))})</title></circle>')
        i, v = pts[-1]
        out.append(f'<text x="{x(i) + 8:.1f}" y="{y(v) + 4:.1f}" class="direct">{_esc(name)} {v:.1%}</text>')
    if n:
        for i in sorted({0, n - 1}):
            out.append(f'<text x="{x(i):.1f}" y="{h - 6}" class="tick" text-anchor="middle">'
                       f'{_esc(history[i]["time"][5:16].replace("T", " "))}</text>')
    out.append("</svg>")
    return "".join(out)


def _bars(rows, label):
    """Stacked bars per game: `rows` = [(name, rules, signals)]; rules broken on top in the warning
    colour, signals below."""
    w, h, left, top, bottom = 760, 200, 44, 10, 40
    pw, ph = w - left - 20, h - top - bottom
    hi = max([r + s for _, r, s in rows] + [4])
    bw = min(70, pw / max(1, len(rows)) * 0.6)
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{_esc(label)}" class="chart">']
    for t in (0, hi // 2, hi):
        yy = top + ph * (1 - t / hi)
        out.append(f'<line x1="{left}" x2="{left + pw}" y1="{yy:.1f}" y2="{yy:.1f}" class="grid"/>'
                   f'<text x="{left - 6}" y="{yy + 4:.1f}" class="tick" text-anchor="end">{t}</text>')
    for i, (name, rules, signals) in enumerate(rows):
        cx = left + pw * (i + 0.5) / len(rows)
        y0 = top + ph
        for val, cls, what in ((signals, "bar-signal", "signals"), (rules, "bar-rule", "rules broken")):
            if val:
                hh = ph * val / hi
                out.append(f'<rect x="{cx - bw / 2:.1f}" y="{y0 - hh:.1f}" width="{bw:.1f}" height="{hh:.1f}" '
                           f'class="{cls}"><title>{_esc(name)}: {val} {what}</title></rect>')
                y0 -= hh
        out.append(f'<text x="{cx:.1f}" y="{y0 - 5:.1f}" class="direct" text-anchor="middle">{rules + signals}</text>'
                   f'<text x="{cx:.1f}" y="{h - 22}" class="tick" text-anchor="middle">{_esc(name)}</text>')
    out.append("</svg>")
    return "".join(out)


PHASES = [("Early game", "rounds 3-6", range(3, 7)), ("Mid game", "rounds 7-9", range(7, 10)),
          ("Late game", "rounds 10-13", range(10, 14))]


TARGET_RX = {"late": r"late >= ([0-9.]+)", "real": r"real < ([0-9.]+)", "gold": r"Gold left <= ([0-9.]+)",
             "ontype": r"on-type >= ([0-9.]+)%"}


def _current():
    """The release numbers now (docs/ROADMAP.md, Releases): late (the curve's median ratio,
    rounds 10-13), real (the best's placement from your positions, latest evaluation), Gold left
    (rounds 13+) and on-type (minion buys, rounds 10-12 and 13+) from compare_play."""
    now = {}
    curve_path = PROGRESS / "curve.json"
    if curve_path.exists():
        curve = {r["round"]: r for r in json.loads(curve_path.read_text(encoding="utf-8"))["rounds"]}
        q = sorted(curve[r]["network"]["stats"] / curve[r]["your_lobbies"]["stats"] for r in range(10, 14)
                   if r in curve and curve[r].get("your_lobbies") and curve[r]["your_lobbies"]["stats"])
        if q:
            now["late"] = q[len(q) // 2]
    reals = [r["vs_best_real"]["best"] for run in RUNS for r in _jsonl(PROGRESS / "train" / run / "log.jsonl")
             if isinstance(r.get("vs_best_real"), dict) and r["vs_best_real"].get("best")]
    if reals:
        now["real"] = reals[-1]
    cmp_path = PROGRESS / "compare_play.json"
    if cmp_path.exists():
        bands = json.loads(cmp_path.read_text(encoding="utf-8")).get("bands") or {}
        late = bands.get("rounds 13+") or {}
        if late.get("gold left"):
            now["gold"] = late["gold left"][1]
        on = [b["bought on-tribe"][1] for k, b in bands.items() if k != "rounds 7-9" and b.get("bought on-tribe")]
        if on:
            now["ontype"] = 100 * sum(on) / len(on)
    return now


def _bar(frac, label):
    pct = max(0.0, min(1.0, frac)) * 100
    return (f'<div class="bar"><div class="fill" style="width:{pct:.0f}%"></div></div>'
            f'<div class="muted small">{_esc(label)}</div>')


def _live():
    """Where we are: every job running now (data/progress/jobs.json, kept by whoever starts one)
    with a progress bar, where it runs, what it's for and its latest numbers; then the checklists
    of docs/NOW.md (next up, later)."""
    out = ["<h2>Where we are</h2>"]
    jobs_path = PROGRESS / "jobs.json"
    jobs = json.loads(jobs_path.read_text(encoding="utf-8")).get("jobs", []) if jobs_path.exists() else []
    now = datetime.now()
    cards = []
    for j in jobs:
        start = datetime.fromisoformat(j["started"])
        end = datetime.fromisoformat(j["ends"]) if j.get("ends") else None
        detail = ""
        frac, label = None, f"running since {start:%b %d %H:%M}"
        if end:
            frac = (now - start) / (end - start)
            left = end - now
            label = (f"{start:%H:%M} to {end:%b %d %H:%M}, " +
                     (f"{left.total_seconds() / 3600:.1f} h left" if left.total_seconds() > 0 else "due"))
        res = j.get("results") and ROOT / j["results"]  # one line per finished case, of `total`
        if res and res.exists() and j.get("total"):
            n_done = sum(1 for line in open(res, encoding="utf-8") if line.strip())
            frac, label = n_done / j["total"], f"{n_done} of {j['total']} cases done; " + label
        prog = j.get("progress") and ROOT / j["progress"]
        if prog and prog.exists():
            x = json.loads(prog.read_text(encoding="utf-8"))
            frac = x["done"] / max(1, x["total"])
            label = f"{x['done']} of {x['total']} done; " + label
        log = j.get("log") and ROOT / j["log"]
        if log and log.exists():
            rows = _jsonl(log)
            it = next((r for r in reversed(rows) if "batch" in r), None)
            ev = next((r for r in reversed(rows) if isinstance(r.get("vs_best_real"), dict)), None)
            bits = []
            if it:
                bits.append(f"iteration {it['iteration']}")
            if ev:
                bits.append(f"head to head {ev['vs_best']['mean_place']:.2f}" if ev.get("vs_best") else "")
                bits.append(f"from your positions {ev['vs_best_real']['mean_place']:.2f} "
                            f"(best {ev['vs_best_real'].get('best', 0):.2f})")
                if ev.get("vs_library"):
                    bits.append(f"top-1% lobbies {ev['vs_library']['mean_place']:.2f}")
            detail = ", ".join(b for b in bits if b)
        cards.append(f'<div class="tile"><div class="muted small">{_esc(j.get("kind", ""))} · {_esc(j.get("where", ""))}</div>'
                     f'<div class="job">{_esc(j["name"])}</div><div class="sub">{_esc(j.get("purpose", ""))}</div>'
                     + (_bar(frac, label) if frac is not None else f'<div class="muted small">{_esc(label)}</div>')
                     + (f'<div class="small">{_esc(detail)}</div>' if detail else "") + "</div>")
    out.append('<h3>Running now</h3>' + (f'<div class="tiles">{"".join(cards)}</div>' if cards
                                          else '<p class="sub">Nothing running.</p>'))
    now_md = ROOT / "docs" / "NOW.md"
    if now_md.exists():
        section, lists = None, {}
        for line in now_md.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                section = line[3:].strip()
            elif section and line.lstrip().startswith(("- [ ]", "- [x]", "- [X]")):
                done = line.lstrip()[3] in "xX"
                lists.setdefault(section, []).append((done, line.lstrip()[6:].strip()))
        for name, items in lists.items():
            out.append(f"<h3>{_esc(name)}</h3><ul class=\"check\">" + "".join(
                f'<li class="{"done" if d else ""}">{"&#9745;" if d else "&#9744;"} {_esc(t)}</li>' for d, t in items)
                + "</ul>")
    return "".join(out)


def _targets():
    """The release table (docs/ROADMAP.md) with each target against the numbers now."""
    import re
    road = ROOT / "docs" / "ROADMAP.md"
    if not road.exists():
        return ""
    rows = [l.split("|")[1:-1] for l in road.read_text(encoding="utf-8").splitlines()
            if re.match(r"\| R\d+ \|", l)]
    if not rows:
        return ""
    now = _current()
    names = {"late": "late game", "real": "from your positions", "gold": "Gold left, rounds 13+", "ontype": "on-type buys"}
    shown = {"late": lambda x: f"{x:.2f}x", "real": lambda x: f"{x:.2f}", "gold": lambda x: f"{x:.1f}",
             "ontype": lambda x: f"{x:.0f}%"}
    better = {"late": lambda v, t: v >= t, "real": lambda v, t: v < t, "gold": lambda v, t: v <= t,
              "ontype": lambda v, t: v >= t}
    out = ["<h2>Releases</h2>", '<p class="sub">One a day at 20:00 with dated targets (docs/ROADMAP.md); '
           'each target against the number now. Now: ' + ", ".join(f"{names[k]} {shown[k](v)}" for k, v in now.items())
           + ".</p><table><tr><th>Release</th><th>Date</th><th>Target</th><th>Now</th><th>State</th></tr>"]
    for rel, date, target, state in (r[:4] for r in rows if len(r) >= 4):
        checks = []
        for k, rx in TARGET_RX.items():
            m = re.search(rx, target)
            if m and k in now:
                ok = better[k](now[k], float(m.group(1)))
                checks.append(f"{names[k]} {shown[k](now[k])} {'meets' if ok else 'misses'} {m.group(1)}")
        out.append(f"<tr><td>{_esc(rel.strip())}</td><td>{_esc(date.strip())}</td><td>{_esc(target.strip())}</td>"
                   f"<td>{_esc('; '.join(checks)) or '-'}</td><td>{_esc(state.strip()) or '-'}</td></tr>")
    return "".join(out) + "</table>"


def _verdict():
    """The bottom line, from the live numbers: how reliable the advice is, and how strong by phase
    (the network's warband in its games against the real lobbies in your logs, by round)."""
    out = ["<h2>Bottom line</h2>"]
    curve_path = PROGRESS / "curve.json"
    rows = []
    if curve_path.exists():
        curve = {r["round"]: r for r in json.loads(curve_path.read_text(encoding="utf-8"))["rounds"]}
        for name, when, rounds in PHASES:
            ratios = [curve[r]["network"]["stats"] / curve[r]["your_lobbies"]["stats"] for r in rounds
                      if r in curve and curve[r].get("network") and curve[r].get("your_lobbies")
                      and curve[r]["your_lobbies"]["stats"]]
            if not ratios:
                continue
            q = sorted(ratios)[len(ratios) // 2]
            verdict = ("stronger than your lobbies" if q >= 1.1 else "about even with your lobbies" if q >= 0.8
                       else "weaker than your lobbies" if q >= 0.4 else "far weaker than your lobbies")
            rows.append((name, when, q, verdict))
    reviews = sorted((DATA / "review").glob("*.json")) if (DATA / "review").is_dir() else []
    found = [x for f in reviews for x in json.loads(f.read_text(encoding="utf-8"))]
    rules = sum(1 for x in found if x.get("rule"))
    base_path = DATA / "replay" / "fidelity_baseline.json"
    fid = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else {}
    last_path = DATA / "replay" / "fidelity_last.json"
    if last_path.exists():
        fid = json.loads(last_path.read_text(encoding="utf-8")).get("now") or fid
    reliable = []
    if reviews:
        reliable.append(f"{rules} rule-breaking pieces of advice in the {len(reviews)} game(s) reviewed")
    if fid:
        reliable.append("the simulator matches your games in " + ", ".join(
            f"{fid[k]['rate']:.0%} of {lbl}" for k, lbl in (("actions", "single actions"), ("turns", "whole turns"),
                                                             ("transitions", "turn changes")) if k in fid))
    genres = PROGRESS / "genres.json"
    g_med = None
    if genres.exists():
        gs = sorted(x["growth"] for x in json.loads(genres.read_text(encoding="utf-8"))["comps"] if x.get("growth"))
        g_med = gs[len(gs) // 2] if gs else None
    weak_late = rows and rows[-1][2] < 0.8
    out.append('<div class="verdict">')
    out.append("<p><strong>Reliable?</strong> " + ("Mostly, mechanically: " + "; ".join(reliable) + "."
                                                    if reliable else "Not measured yet.") + "</p>")
    if rows:
        out.append("<table><tr><th>Phase</th><th>Its warband vs your lobbies</th><th>So</th></tr>" + "".join(
            f"<tr><td>{a} ({b})</td><td>{q:.2f}x</td><td>{v}</td></tr>" for a, b, q, v in rows) + "</table>")
    if g_med is not None:
        out.append(f"<p>From the 19 curated comps' midgames, two rounds later its warband is {g_med:.2f}x the top 1% "
                   f"players' (median over comps; 1.0 would keep up).</p>")
    cmp_path = PROGRESS / "compare_play.json"
    if cmp_path.exists():
        bands = json.loads(cmp_path.read_text(encoding="utf-8"))["bands"]
        out.append("<p><strong>Its habits against yours</strong> (from your own positions, per turn, you vs it):</p>"
                   "<table><tr><th>Rounds</th><th>Refreshes</th><th>Buys</th><th>Upgrades</th><th>Freezes</th>"
                   "<th>Gold left at End</th><th>Buys fitting the warband's type</th></tr>" + "".join(
                       f"<tr><td>{_esc(b.replace('rounds ', ''))}</td>" + "".join(
                           f"<td>{x[k][0]:.1f} vs {x[k][1]:.1f}</td>" for k in ("refresh", "buy", "upgrade", "freeze", "gold left"))
                       + (f"<td>{x['bought on-tribe'][0]:.0%} vs {x['bought on-tribe'][1]:.0%}</td>" if "bought on-tribe" in x else "<td>-</td>")
                       + "</tr>" for b, x in bands.items()) + "</table>")
    use = ("<strong>Use it for</strong> the early game, hero picks, combat odds and the lineup; "
           "<strong>treat as a second opinion</strong> its late-game plans (it scales too slowly, refreshes too "
           "rarely and buys what is there).") if weak_late else (
           "<strong>Use it</strong> through the game; the late game has caught up with your lobbies.")
    out.append(f"<p>{use}</p></div>")
    return "".join(out)


def _audit_section():
    """The audit's state in plain words: the simulator against your games, the advice reviewed,
    what was found and fixed, the last promotion's play audit (docs/ROBUSTNESS.md)."""
    out = ["<h2>Audit: is it faithful, and is the advice sensible?</h2>",
           '<p class="sub">Checked by itself after every game you play (docs/ROBUSTNESS.md). The simulator is '
           'compared with your real games; every piece of advice the overlay showed is re-checked; a network '
           'reaches the overlay only after a play audit.</p>']
    base_path, last_path = DATA / "replay" / "fidelity_baseline.json", DATA / "replay" / "fidelity_last.json"
    reviews = sorted((DATA / "review").glob("*.json"), key=lambda f: f.name)[-6:] if (DATA / "review").is_dir() else []
    last_rev = json.loads(reviews[-1].read_text(encoding="utf-8")) if reviews else None
    reg = (json.loads(last_path.read_text(encoding="utf-8")).get("regressions") or []) if last_path.exists() else []
    audited = [r for r in _jsonl(DATA / "models" / "promotions.jsonl") if r.get("play_audit")]
    # When the simulator was last checked, and whether games came after it: a check that stops
    # running must not read as "no drop"
    checked = datetime.fromtimestamp(last_path.stat().st_mtime) if last_path.exists() else None
    newest = max((f.stat().st_mtime for f in (DATA / "replay").glob("decisions.jsonl")), default=0)
    stale = checked is None or newest > checked.timestamp() + 60
    if stale:
        sim_box = ("Simulator vs your games", "not checked",
                   f"last check {checked:%b %d %H:%M}, games since" if checked else "the check hasn't run")
    else:
        sim_box = ("Simulator vs your games", "no drop" if not reg else f"{len(reg)} drops",
                   f"the five checks against their baseline, {checked:%b %d %H:%M}" if not reg else "; ".join(reg[:2]))
    boxes = [("Bugs found and fixed", str(len(AUDIT_FIXES)), "in the simulator, the bridge and the advice (list below)"),
             sim_box]
    if last_rev is not None:
        rules = sum(1 for x in last_rev if x.get("rule"))
        boxes.append(("Advice rules broken, last game", str(rules),
                      f"{len(last_rev) - rules} usually-wrong signals to look at"))
    if audited:
        worse = audited[-1]["play_audit"].get("worse") or {}
        boxes.append(("Last play audit", "passed" if not worse else "failed",
                      ", ".join(worse) or "a network reaches the overlay only after it"))
    else:
        boxes.append(("Play audit", "waiting", "runs once a network passes the training gates"))
    out.append(_tiles(boxes))
    if base_path.exists():
        base = json.loads(base_path.read_text(encoding="utf-8"))
        last = json.loads(last_path.read_text(encoding="utf-8")) if last_path.exists() else {"now": base, "regressions": []}
        now = last.get("now") or base
        tiles = []
        for key, label, note in FIDELITY_LABELS:
            if key not in now:
                continue
            r, b = now[key]["rate"], base.get(key, {}).get("rate", now[key]["rate"])
            change = "" if abs(r - b) < 0.0005 else f" ({'+' if r > b else ''}{(r - b) * 100:.1f} vs baseline)"
            tiles.append((label, f"{r:.1%}", f"{note}; {now[key]['n']} cases{change}"))
        out.append("<h3>The simulator against your games</h3>" + _tiles(tiles))
        hist = _jsonl(DATA / "replay" / "fidelity_history.jsonl")
        if hist:
            out.append('<p class="sub">Over time (each check after a game; higher is better):</p>')
            out.append(_pct_chart(hist, [(k, label) for k, label, _ in FIDELITY_LABELS], "Simulator agreement over time"))
        reg = last.get("regressions") or []
        if reg:
            out.append('<p class="warn">Worse than the baseline since the last check: ' +
                       "; ".join(_esc(x) for x in reg[:8]) + "</p>")
        else:
            out.append('<p class="sub">No drop against the baseline in the last check.</p>')
    if reviews:
        out.append("<h3>The advice in your recent games, re-checked</h3>")
        bar_rows = []
        for f in reviews:
            found = json.loads(f.read_text(encoding="utf-8"))
            bar_rows.append((f.stem.replace("Hearthstone_2026_", "")[:11].replace("_", " "),
                             sum(1 for x in found if x.get("rule")), sum(1 for x in found if not x.get("rule"))))
        out.append(_bars(bar_rows, "Findings per game"))
        out.append('<p class="sub">Rules are things advice must never do (a bug when broken); signals are '
                   'usually wrong and worth a look; "you did better" means your own turn beat the advised one '
                   'against the next opponent.</p><table><tr><th>Game</th><th>Rules broken</th>'
                   '<th>Signals</th><th>Examples</th></tr>')
        for f in reversed(reviews):
            found = json.loads(f.read_text(encoding="utf-8"))
            rules = [x for x in found if x.get("rule")]
            signals = [x for x in found if not x.get("rule")]
            ex = "; ".join(f"round {x['round']}: {x['kind']} ({x['detail']})" for x in (rules + signals)[:3])
            name = f.stem.replace("Hearthstone_", "").replace("_", " ")
            out.append(f"<tr><td>{_esc(name)}</td><td>{len(rules)}</td><td>{len(signals)}</td><td>{_esc(ex) or '-'}</td></tr>")
        out.append("</table>")
    use_path = PROGRESS / "usefulness.json"
    if use_path.exists():
        use = json.loads(use_path.read_text(encoding="utf-8"))
        out.append("<h3>Did you follow it?</h3>"
                   '<p class="sub">At each decision the overlay advised on, its first step against what you did '
                   'next (advisor.usefulness): the same step, or the same step later in that turn (the same idea in '
                   'another order). Where you went another way: the advice\'s step, then yours.</p>'
                   "<table><tr><th>Game</th><th>Decisions</th><th>Your next step</th><th>Later that turn</th>"
                   "<th>Most often instead</th></tr>")
        for log, r in sorted(use.items(), reverse=True)[:8]:
            other = ", ".join(f"{k} ({v})" for k, v in list(r["otherwise"].items())[:3])
            out.append(f"<tr><td>{_esc(log.replace('Hearthstone_', '').replace('_', ' '))}</td><td>{r['decisions']}</td>"
                       f"<td>{r['followed']:.0%}</td><td>{r.get('in_turn', 0):.0%}</td><td>{_esc(other)}</td></tr>")
        out.append("</table>")
    out.append("<h3>Found and fixed</h3><table><tr><th>When</th><th>What was wrong</th><th>What it did</th>"
               "<th>Found by</th></tr>" + "".join(
                   f"<tr><td>{a}</td><td>{_esc(b)}</td><td>{_esc(c)}</td><td>{_esc(d)}</td></tr>"
                   for a, b, c, d in AUDIT_FIXES) + "</table>")
    if audited:
        r = audited[-1]
        worse = r["play_audit"].get("worse") or {}
        verdict = "passed" if not worse else "failed: " + ", ".join(worse)
        out.append(f'<p class="sub">Last play audit ({_esc(r["time"][:16].replace("T", " "))}, '
                   f'{_esc(str(r["candidate"]))}): {_esc(verdict)}.</p>')
    else:
        out.append('<p class="sub">Play audit: no candidate has reached it yet since it began (it runs once a '
                   'network passes the training gates).</p>')
    return "".join(out)


def render():
    net = _network()
    promos, promo_pts = _promotions()
    runs = _runs()
    jobs, synced = _running()
    games = _games()
    status = (ROOT / "docs" / "STATUS.md")
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
             f"<meta http-equiv='refresh' content='300'>"  # (the data is refreshed every 10 minutes)
             f"<title>Battlegrounds Advisor Progress</title><style>{CSS}</style></head><body><main>",
             "<h1>Battlegrounds advisor: progress</h1>",
             f'<p class="lead">Made {datetime.now():%b %d, %H:%M}. Placements are out of 8: 1 is first, '
             f'lower is better; seven plain bots average 4.5.</p>']

    tiles = []
    if net:
        g = net["gate"]
        tiles.append(("The network in the overlay", f"{g.get('mean_place', 0):.2f}<small> place</small>",
                      f"against seven plain bots, {g.get('n', '?')} test games; "
                      f"{_esc(net['source'] or '')}"))
    tiles.append(("Plan search", "on", "tries 8 more plans each decision; 0.48 places better in 200 test games"))
    if games["advice"]:
        tiles.append(("Your games with it", f"{games['games']}<small> games</small>",
                      f"{games['advice']} pieces of advice, {games['flagged']} flagged with Ctrl+Shift+B"))
    tiles.append(("Training now", str(len([j for j in jobs if j[0] in ('train', 'pretrain')])),
                  ", ".join(j[1] for j in jobs if j[1]) or "nothing running"))
    parts.append(_live())
    parts.append(_verdict())
    parts.append(_targets())
    parts.append(_tiles(tiles))
    parts.append("<h2>Strength over time</h2>")
    parts.append('<p class="sub">Placement out of 8, lower is better (1 at the top). Against plain bots '
                 'the curve flattens near the top as networks get strong, so each promotion also shows '
                 'how it did head to head against the network it replaced: under 4.5 means stronger.</p>')
    parts.append(_overview(_jsonl(DATA / "models" / "promotions.jsonl")))
    curve_path = PROGRESS / "curve.json"
    if curve_path.exists():
        curve = json.loads(curve_path.read_text(encoding="utf-8"))
        parts.append("<h3>Warband strength by round, against real lobbies</h3>")
        parts.append(f'<p class="sub">Median Attack+Health of the warbands, by round (log scale): the network '
                     f'in its own games ({_esc(curve.get("network") or "")}), the real lobbies in your logs, '
                     f'and the public average over all players. Real lobbies scale explosively late; the '
                     f'network has to learn to keep up (the real-warband training is aimed at this).</p>')
        parts.append(_curve_chart(curve))

    parts.append(_audit_section())

    if status.is_file():
        parts.append("<h2>In plain words</h2>" + _markdown(status.read_text(encoding="utf-8")))

    parts.append("<h2>Is training making it stronger?</h2>")
    parts.append('<p class="sub">Each promotion is a network that beat the one before it head to head '
                 '(on one seat against seven copies of it, clearly under 4.5) and then again on fresh games. '
                 'The line is its place against seven plain bots.</p>')
    parts.append(_chart([("promoted networks", "s1", promo_pts)], "Place of each promoted network"))
    if promos:
        parts.append('<div class="wrap"><table><tr><th>When</th><th>From</th><th>vs plain bots</th>'
                     '<th>vs seven copies of the one before</th></tr>' + "".join(
                         f"<tr><td>{_when(r.get('time'))}</td><td>{_esc(r.get('candidate', '').split('/')[-2] if '/' in r.get('candidate', '') else r.get('candidate'))}"
                         f" <small>iteration {r.get('iteration')}</small></td>"
                         f"<td class='num'>{r['gate']['mean_place']:.2f} ± {r['gate']['se']:.2f}</td>"
                         f"<td class='num'>{_h2h(r)}</td></tr>"
                         for r in reversed(promos[-8:])) + "</table></div>")

    parts.append("<h3>The training runs</h3>")
    parts.append('<p class="sub">Each run is tested every few iterations: its network on one seat against '
                 'seven plain bots. The hot start is also tested against seven teachers (dashed).</p>')
    series, classes = [], ["s1", "s2", "s3"]  # cycles past three runs
    for k, (run, rows) in enumerate(runs.items()):
        pts = [(r["iteration"], r["eval"]["mean_place"], f"{run} iteration {r['iteration']}: "
                f"{r['eval']['mean_place']:.2f}") for r in rows if r.get("eval")]
        series.append((run, classes[list(RUNS).index(run) % 3], pts))
        tpts = [(r["iteration"], r["eval_teachers"]["mean_place"], f"{run} iteration {r['iteration']} "
                 f"vs teachers: {r['eval_teachers']['mean_place']:.2f}") for r in rows if r.get("eval_teachers")]
        if tpts:
            series.append((f"{run} vs teachers", "s4 dash", tpts))
    parts.append(_chart(series, "Place during training", hi=8.0))
    parts.append('<div class="legend">' + "".join(
        f'<span><span class="key k{1 + list(RUNS).index(r) % 3}"></span>{r}: {_esc(RUNS[r])}</span>'
        for r in runs) + "</div>")
    gens = [(run, rows) for run, rows in runs.items() if any(r.get("vs_best") for r in rows)]
    if gens:
        parts.append("<h3>Against the network it has to beat</h3>")
        parts.append('<p class="sub">A generation run trains against the frozen current best and is tested '
                     'on one seat against seven copies of it: 4.5 is even, lower means it is pulling ahead. '
                     'Clearly under 4.5, and again on fresh games, and it is promoted.</p>')
        parts.append(_chart([(run, f"s{1 + k % 4}", [(r["iteration"], r["vs_best"]["mean_place"],
                                           f"{run} iteration {r['iteration']}: {r['vs_best']['mean_place']:.2f}")
                                          for r in rows if r.get("vs_best")]) for k, (run, rows) in enumerate(gens)],
                            "Place against the current best", lo=3.0, hi=5.5, reference=(4.5, "even")))

    libs = [(run, rows) for run, rows in runs.items() if any(r.get("vs_library") for r in rows)]
    if libs:
        parts.append("<h3>In lobbies with real warbands</h3>")
        parts.append('<p class="sub">One seat against copies of the current best, two of them playing real '
                     'warbands from your games (library seats). Closest to a real lobby; lower is better. '
                     'Clearly better here than the best, twice, also earns a promotion.</p>')
        parts.append(_chart([(run, f"s{1 + k % 4}", [(r["iteration"], r["vs_library"]["mean_place"],
                                                      f"{run} iteration {r['iteration']}: "
                                                      f"{r['vs_library']['mean_place']:.2f}")
                                                     for r in rows if r.get("vs_library")])
                             for k, (run, rows) in enumerate(libs)],
                            "Place in lobbies with real warbands", lo=3.0, hi=6.0, reference=None))

    reals = [(run, rows) for run, rows in runs.items() if any(r.get("vs_best_real") for r in rows)]
    if reals:
        base = [r["vs_best_real"]["best"] for _, rows in reals for r in rows if r.get("vs_best_real")][-1]
        parts.append("<h3>From your own positions</h3>")
        parts.append('<p class="sub">From the start of every round of your logged games, the network plays '
                     'your seat on and copies of the current best play the others: its mean final place, '
                     f'lower is better. The line is the current best in your seat ({base:.2f}). Clearly under '
                     'it, twice, also earns a promotion.</p>')
        parts.append(_chart([(run, f"s{1 + k % 4}", [(r["iteration"], r["vs_best_real"]["mean_place"],
                                                      f"{run} iteration {r['iteration']}: "
                                                      f"{r['vs_best_real']['mean_place']:.2f}")
                                                     for r in rows if r.get("vs_best_real")])
                             for k, (run, rows) in enumerate(reals)],
                            "Place from your positions", lo=1.5, hi=4.5, reference=(base, "the best")))

    pat_path = Path(__file__).resolve().parents[1] / "data" / "progress" / "patterns.jsonl"
    if pat_path.exists():
        pats = []
        for line in pat_path.read_text(encoding="utf-8-sig").splitlines():
            try:
                pats.append(json.loads(line))
            except ValueError:
                pass
        if pats:
            parts.append("<h3>Strong-player patterns</h3>")
            parts.append('<p class="sub">Your points, measured on each promoted network '
                         '(docs/PLAY_PLAN.md). Beatboxer: of its probability for magnetizing, the share '
                         'onto another Mech (random: 75%). Late turns: from your positions at round 9+ '
                         'with a full warband, per turn.</p>')
            parts.append("<table><tr><th>Network</th><th>Beatboxer: onto another</th><th>Refreshes</th>"
                         "<th>Buys</th><th>Bought, then sold</th></tr>")
            for x in pats[-8:]:
                b, lt = x.get("beatboxer", {}), x.get("late_turns", {})
                parts.append(f"<tr><td>{_esc(str(x.get('source')))}</td><td>{b.get('prob_onto_other', 0):.0%}</td>"
                             f"<td>{lt.get('refreshes')}</td><td>{lt.get('buys')}</td><td>{lt.get('bought_then_sold')}</td></tr>")
            parts.append("</table>")

    parts.append("<h2>How good are its decisions?</h2><ul>")
    parts.append("<li><strong>Plan search</strong>: the network alone 2.47, with plan search 1.99, in 200 "
                 "test games against seven plain bots (0.48 ± 0.13 places better).</li>")
    parts.append("<li><strong>The teacher</strong> (your strategy, scripted) against the old bot: 3.52 vs 5.06 "
                 "when four of each play. Leveling a turn earlier cost 0.35; without the Dark Gift rule, 0.9.</li>")
    parts.append("<li><strong>The network against seven teachers</strong>: 2.18 (200 games). It already plays "
                 "better than the scripted version of your strategy; the hot start is a test of whether "
                 "starting from your strategy leads further after PPO.</li>")
    if games["refresh"] is not None:
        parts.append(f"<li><strong>In your games</strong>, {games['refresh']:.0%} of the advised plans had a "
                     "Refresh (the self-play habit; newer networks should refresh more).</li>")
    parts.append("</ul>")



    parts.append("<h2>Running now</h2>")
    if jobs:
        rows = []
        for kind, run, hours in jobs:
            last = (_jsonl(PROGRESS / "train" / run / "log.jsonl") or [{}])[-1] if run else {}
            what = RUNS.get(run, {"promote": "judging candidates", "search_eval": "testing plan search",
                                     "search_games": "search games: targets for search-guided training"}.get(kind, kind))
            rows.append(f"<tr><td>{_esc(run or kind)}</td><td>{_esc(what)}</td>"
                        f"<td class='num'>{last.get('iteration', '–')}</td>"
                        f"<td class='num'>{float(last.get('t', 0)) / 3600:.1f} of {hours or '?'} h</td></tr>")
        parts.append('<div class="wrap"><table><tr><th>Run</th><th>What</th><th>Iteration</th>'
                     '<th>Time</th></tr>' + "".join(rows) + "</table></div>")
    else:
        parts.append('<p class="sub">Nothing running on the office.</p>')
    if synced:
        parts.append(f'<p class="sub">Office status copied {synced:%b %d, %H:%M}.</p>')
    parts.append("</main></body></html>")
    return "".join(parts)


def write(out=None):
    out = Path(out or DATA / "report.html")
    tmp = out.with_suffix(".tmp")
    tmp.write_text(render(), encoding="utf-8")
    os.replace(tmp, out)
    return out


if __name__ == "__main__":
    print(write())
