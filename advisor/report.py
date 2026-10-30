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
RUNS = {  # the runs worth a line on the chart, oldest first: what each one is
    "office2": "self-play (old rules)",
    "office3": "self-play, fixed rules",
    "teach1": "hot start: copying the teacher",
}
# Checks of the simulator against your logs (docs/REPLAY.md); remade by hand when rerun
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
    out, items, intro = [], [], True
    def flush():
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            items.clear()
    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            intro = False
            out.append(f"<h3>{inline(line[3:])}</h3>")
        elif intro:
            continue  # the title and the note about the note
        elif line.startswith("- "):
            flush() if False else None
            items.append(line[2:])
        elif line.startswith("  ") and items:
            items[-1] += " " + line.strip()
        elif not line.strip():
            flush()
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
        m = re.search(r"-m advisor\.(\w+).*?(?:--run (\S+))?(?:\s|$)", l)
        run = re.search(r"--run (\S+)", l)
        hours = re.search(r"--hours (\S+)", l)
        if m:
            jobs.append((m.group(1), run.group(1) if run else "", hours.group(1) if hours else ""))
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


def render():
    net = _network()
    promos, promo_pts = _promotions()
    runs = _runs()
    jobs, synced = _running()
    games = _games()
    status = (ROOT / "docs" / "STATUS.md")
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
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
    parts.append(_tiles(tiles))

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
    series, classes = [], ["s1", "s2", "s3"]
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

    parts.append("<h2>Can the simulator be trusted?</h2>" + _tiles(SIMULATOR))

    parts.append("<h2>Running now</h2>")
    if jobs:
        rows = []
        for kind, run, hours in jobs:
            last = (_jsonl(PROGRESS / "train" / run / "log.jsonl") or [{}])[-1] if run else {}
            what = RUNS.get(run, {"promote": "judging candidates", "search_eval": "testing plan search"}.get(kind, kind))
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
