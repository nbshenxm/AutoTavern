"""Search games: the plan search's choices as training targets (expert iteration, like the
constructed advisor's search-guided PPO). Workers play complete games: seats 0 and 1 follow the
plan search (advisor.search.best_plan, which only sees what that seat knows), the other seats the
network itself (sampled). Every searched decision is kept: what the seat saw (features, cards,
legal mask) and the search's first action. They go to DIR/shard_*.npz, which advisor.train
--search-data DIR reads (the newest --search-buffer decisions) and trains toward.

The network is re-read from --net whenever the file changes (a run's last.pt: the search improves
with the network it searches with). --real-starts P: that share of the games start from the
player's logged round starts (advisor.train.RealStarts, late rounds weighted), seat 0 in the
player's own seat: search targets where the network stalls.

    python -X utf8 -m advisor.search_games --net data/train/gen1/last.pt --out data/search/gen1 \
        --workers 16 --hours 10
"""

import argparse
import json
import os
import time
import zipfile
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import torch

import taverngym
from advisor import search
from advisor.policy import load, observe, widen_obs
from advisor.state import GAME_CONFIG

SEARCHED = (0, 1)
SHARD = 4096  # decisions per file
F16_MAX = 65000.0
_NET = {"path": None, "version": None, "net": None}
_STARTS = {"rs": None}


def _net(path):
    version = os.stat(path).st_mtime_ns
    if _NET["version"] != version:
        for _ in range(3):  # the run may be writing it
            try:
                _NET["net"], _ = load(path, "cpu")
                break
            except Exception:
                time.sleep(2)
        _NET["version"] = version
    return _NET["net"]


def _init():
    torch.set_num_threads(1)


def play(args):
    """One game; the searched seats' (features, cards, mask, action) and their placements."""
    seed, path, k, temperature, real, lib = args
    net = _net(path)
    rng = np.random.default_rng(seed)
    config = GAME_CONFIG
    if lib:
        from advisor import library
        config = {**GAME_CONFIG, "library": library.library(lib, comps=True)}
    g = taverngym.Game(seed, json.dumps(config))
    if real and rng.random() < real:
        if _STARTS["rs"] is None:
            from advisor.train import RealStarts
            _STARTS["rs"] = RealStarts(1.0, 0, log=lambda r: None)
        rs = _STARTS["rs"]
        if rs.states:
            st = json.loads(json.dumps(rs.states[rng.choice(len(rs.states), p=rs.weights)]))
            fresh = json.loads(g.state_json())
            st["rng"] = fresh["rng"]  # this game's own random draws
            st["cfg"] = {**fresh["cfg"], "lobby_types": st["cfg"].get("lobby_types")}
            g = taverngym.Game.from_json(json.dumps(st))
    rows, n = [], 0
    for _ in range(200_000):
        if g.is_over():
            break
        for seat in range(g.num_players):
            if not g.needs_action(seat):
                continue
            if seat in SEARCHED:
                n += 1
                f, c, m = observe(g, seat)
                acts, _, _ = search.best_plan(g, net, seat, None, k, temperature,
                                              seed=seed * 100_003 + n)
                if acts:
                    a = int(acts[0])
                    rows.append((f, c, m, a))
                else:
                    a = int(search._policy(net, g, seat)[0].argmax())
            else:
                probs, _ = search._policy(net, g, seat)
                a = int(rng.choice(len(probs), p=probs / probs.sum()))
            g.step(seat, a)
    places = [int(g.placements()[s]) for s in SEARCHED]
    return rows, places


def write_shard(out, rows):
    f, c, m, a = zip(*rows)
    name = out / f"shard_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}_{len(rows)}.npz"
    tmp = name.with_suffix(".partial.npz")  # SearchBuffer skips it until renamed
    # float16 ends at 65504: late-game stats can pass it (inf, then NaN in training)
    f16 = np.clip(np.stack(f), -F16_MAX, F16_MAX).astype(np.float16)
    np.savez(tmp, features=f16, cards=np.stack(c).astype(np.int32),
             mask=np.packbits(np.stack(m), axis=1), actions=np.array(a, dtype=np.int16))
    os.replace(tmp, name)
    return name


class SearchBuffer:
    """The newest `limit` searched decisions of the shards in `dirs`, kept as stored (float16
    features); `refresh` loads only new files. For advisor.train --search-data."""

    def __init__(self, dirs, limit):
        self.dirs, self.limit, self.loaded, self.data = [Path(d) for d in dirs], limit, {}, None
        self.width = dict(taverngym.layout())["N_ACTIONS"]

    def refresh(self):
        files = sorted((f for d in self.dirs for f in d.glob("shard_*.npz")
                        if not f.name.endswith((".partial.npz", ".tmp.npz"))),
                       key=lambda f: f.stat().st_mtime, reverse=True)
        keep, total = [], 0
        for f in files:
            if total >= self.limit:
                break
            keep.append(f)
            total += int(f.stem.rsplit("_", 1)[1])
        if set(keep) == set(self.loaded):
            return False
        for f in keep:
            if f not in self.loaded:
                try:
                    z = np.load(f)
                    try:  # an older layout: version 2 shards are widened, others skipped
                        feats, cards = widen_obs(z["features"], z["cards"])
                    except ValueError:
                        continue
                    self.loaded[f] = (feats, cards, z["mask"], z["actions"])
                except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile):  # half written
                    continue
        self.loaded = {f: self.loaded[f] for f in keep if f in self.loaded}
        parts = list(self.loaded.values())
        self.data = tuple(np.concatenate(x) for x in zip(*parts)) if parts else None
        if self.data is not None:  # shards written before features were clipped
            ok = np.isfinite(self.data[0]).all(1)
            if not ok.all():
                self.data = tuple(x[ok] for x in self.data)
        return True

    def __len__(self):
        return 0 if self.data is None else len(self.data[3])

    def all(self):
        """Every decision once, in order (as `sample`)."""
        return self._rows(np.arange(len(self)))

    def sample(self, n, rng):
        """`n` random decisions: (features f32, cards, mask bool, actions int64)."""
        return self._rows(rng.integers(0, len(self.data[3]), n))

    def _rows(self, i):
        f, c, m, a = self.data
        return (f[i].astype(np.float32), c[i], np.unpackbits(m[i], axis=1)[:, :self.width].astype(bool),
                a[i].astype(np.int64))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True, help="checkpoint to search with (re-read when it changes)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--hours", type=float, default=0)
    ap.add_argument("--seed", type=int, default=80_000_000)
    ap.add_argument("--real-starts", type=float, default=0.0, metavar="P",
                    help="this share of games start from the player's logged round starts")
    ap.add_argument("--library", type=int, nargs="*", metavar="SEAT",
                    help="these seats fight with real warbands (advisor.library), as in training")
    ap.add_argument("--stop-if-playing", action="store_true",
                    help="stop when Hearthstone runs (a run on the home PC)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0, pending, games, decisions, places = time.time(), [], 0, 0, []
    batch = 4 * a.workers  # games per round (Pool reads all its jobs at once)
    with Pool(a.workers, initializer=_init, maxtasksperchild=50) as pool:
        for r in range(10**9):
            if a.hours and time.time() - t0 > a.hours * 3600:
                break
            if a.stop_if_playing:
                from advisor.train import hearthstone_running
                if hearthstone_running():
                    print("Hearthstone started: stopping", flush=True)
                    break
            jobs = [(a.seed + r * batch + i, a.net, a.k, a.temperature, a.real_starts, a.library)
                    for i in range(batch)]
            for rows, pl in pool.imap_unordered(play, jobs):
                pending += rows
                games, decisions = games + 1, decisions + len(rows)
                places += pl
                while len(pending) >= SHARD:
                    write_shard(out, pending[:SHARD])
                    pending = pending[SHARD:]
            print(json.dumps({"t": round(time.time() - t0), "games": games, "decisions": decisions,
                              "per_hour": round(decisions / max(1, time.time() - t0) * 3600),
                              "searched_place": round(float(np.mean(places[-200:])), 3)}), flush=True)


if __name__ == "__main__":
    main()
