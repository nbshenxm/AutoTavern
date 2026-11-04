"""The promotion gate: is a candidate network better than the champion, by enough to see?

Training's own checks were 200-260 games (standard error ~0.1 places) and best.pt kept the
lowest reading, so promotions partly picked luck (docs/REVIEW_20261103.md). Here both networks
play seat 0 of the same games, under the same seeds, with the champion in the other seats; the
paired difference in seat 0's place (candidate - champion, negative = better) cancels most of
the luck of the draw. Suites:

- real: from each of your logged round starts (RealStarts), the other seats the champion
- library: the same starts, seats 5-7 real top-1% warbands (training's lib_eval_config)
- fresh: new games from round 1, seats 5-7 library warbands

A round is every suite once under new seeds. After each round (from the second): pass when the
gain is clear (-mean >= Z_PASS x se), stop as not better when even the optimistic end
(-mean + 2 x se) is under MARGIN places; otherwise go on, at most --rounds. A pass is re-run on
fresh seeds (--recheck, the constructed track's lesson: 54.4% on the gate's deals, 51.4% on new
ones) and only both together promote. Rounds are appended to data/gate/<name>.jsonl as they
finish: a stopped gate resumes where it was.

    python -X utf8 -m advisor.gate data/train/big3hero/last.pt data/models/best.pt
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import torch

from advisor.policy import load
from advisor.train import CONFIG, BatchEnv, RealStarts, load_start, pause_if_playing, play_frozen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "gate"
Z_PASS, MARGIN = 2.5, 0.03
SEED, RECHECK_SEED = 41_000_000, 43_000_000
SUITES = ("real", "library", "fresh")


def library_config():
    from advisor import library
    return {**CONFIG, "library": library.library([5, 6, 7], strength=1.0, comps=True)}


@torch.no_grad()
def play(net, other, n, seed, config, states=None, device="cuda", games=64, threads=8, search_k=0):
    """Seat 0's place in `n` games (game i from states[i] when given, else round 1), `net` in
    seat 0, `other` in the rest, all greedy; game i's seed depends on (seed, i, games) only.
    `search_k` > 0: seat 0 plays the plan search's first step (advisor.search.best_plan over
    the greedy plan and k sampled ones, within the env's mask; `net` must be on the CPU)."""
    if search_k:
        from advisor import search
    places = []
    for k in range(0, n, games):
        m = min(games, n - k)
        env = BatchEnv(m, seed=seed + k, controlled=list(range(8)), config=config, threads=threads)
        if states is not None:
            for i in range(m):
                load_start(env, i, states[k + i])
        net_of = {i: (net if i % 8 == 0 else other) for i in range(env.n_slots)}
        obs = env.observe()
        got = {}
        for step in range(200_000):  # a guard: games end long before
            if len(got) == m:
                break
            if step % 500 == 0:
                pause_if_playing()
            ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
            ready = np.array([i for i in ready if i // 8 not in got], dtype=np.int64)
            actions = np.zeros(env.n_slots, dtype=np.int64)
            play_frozen(obs, ready, net_of, actions, device)
            for i in (ready[ready % 8 == 0] if search_k else ()):
                plan, _, _ = search.best_plan(env.game(i // 8), net, 0, obs["action_mask"][i].astype(bool),
                                              search_k, seed=(seed + k + int(i)) * 100_003 + step)
                if plan:
                    actions[i] = plan[0]
            _, done, info = env.step(actions)
            for i in np.flatnonzero(done):
                if i % 8 == 0 and i // 8 not in got:  # a stopped game has no placement: 4.5
                    got[i // 8] = int(info["placement"][i]) or 4.5
            obs = env.observe()
        places += [got.get(i, 4.5) for i in range(m)]
    return places


_WORKER = {}


def _init_worker(paths):
    torch.set_num_threads(1)
    _WORKER["nets"] = {p: load(p, "cpu")[0].eval() for p in paths}
    _WORKER["configs"] = {"real": CONFIG, "library": library_config()}


def _work(job):
    net, other, m, seed, suite, states, search_k = job
    nets, cfg = _WORKER["nets"], _WORKER["configs"]["real" if suite == "real" else "library"]
    return play(nets[net], nets[other], m, seed, cfg, states, "cpu", games=m, threads=1,
                search_k=search_k)


def play_pool(pool, net_path, other_path, n, seed, suite, states, search_k, chunk):
    """play() in chunks of `chunk` games on a worker pool (CPU): the same games as
    play(..., games=chunk), so it pairs with a run at that chunk size."""
    jobs = [(net_path, other_path, min(chunk, n - k), seed + k, suite,
             None if states is None else states[k:k + chunk], search_k) for k in range(0, n, chunk)]
    return [x for part in pool.map(_work, jobs, chunksize=1) for x in part]


def champion_places(champ, champ_path, n, seed, config, states, device, threads, key, compute=None):
    """play(champ, champ, ...), cached: the champion's games depend only on its weights, the
    seeds, the starts and the simulator build, and every candidate is compared on the same ones
    (half a gate's time). `compute`: how to play them (a worker pool; `key` then names its chunk
    size)."""
    import hashlib
    import taverngym
    h = hashlib.md5(Path(champ_path).read_bytes()).hexdigest()[:12]
    from advisor import library
    core = next(Path(taverngym.__file__).parent.glob("_core*"))  # the compiled simulator
    build = "-".join(str(int(Path(f).stat().st_mtime)) for f in (core, library.BOARDS, library.STARTS))
    cache = OUT / "cache" / f"{h}_{key}_{seed}_{n}_{build}.json"
    if cache.is_file():
        return json.loads(cache.read_text())
    places = compute() if compute else play(champ, champ, n, seed, config, states, device, threads=threads)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps(places))
    tmp.replace(cache)
    return places


def summary(diffs):
    d = np.asarray(diffs, float)
    se = float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else float("inf")
    return {"n": len(d), "mean": round(float(d.mean()), 4), "se": round(se, 4)}


def verdict(s, rounds_done, min_rounds=2):
    if rounds_done < min_rounds:
        return "running"
    if s["mean"] < 0 and -s["mean"] >= Z_PASS * s["se"]:
        return "pass"
    if -s["mean"] + 2 * s["se"] < MARGIN:
        return "not better"
    return "running"


def run(cand_path, champ_path, rounds=8, seed=SEED, fresh_games=256, device="cuda", threads=8,
        name=None, log=print, max_starts=None, search_k=0, workers=0, chunk=4):
    """`search_k` > 0: the candidate plays with the plan search (on `workers` CPU processes,
    games in chunks of `chunk`; the champion's games then use the same chunks)."""
    if search_k and not workers:
        raise SystemExit("--search needs --workers (the plan search runs on the CPU)")
    if workers:
        device = "cpu"
    cand, cck = load(cand_path, device)
    champ, hck = load(champ_path, device)
    cand.eval(), champ.eval()
    # The weights' hash in the name: two checkpoints of the same folder and iteration (lr3's and
    # p37's archive-619) resumed each other's rounds
    import hashlib
    md5 = lambda f: hashlib.md5(Path(f).read_bytes()).hexdigest()[:8]
    name = name or (f"{Path(cand_path).parent.name}-{cck.get('iteration')}-{md5(cand_path)}_vs_"
                    f"{Path(champ_path).stem}-{hck.get('iteration')}-{md5(champ_path)}_{seed}")
    if search_k:
        name += f"_search{search_k}"
    elif workers:
        name += f"_c{chunk}"
    pool = None
    if workers:
        import multiprocessing as mp
        pool = mp.get_context("spawn").Pool(workers, _init_worker, ([str(cand_path), str(champ_path)],))
        cand_path, champ_path = str(cand_path), str(champ_path)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.jsonl"
    done = [json.loads(l) for l in open(path, encoding="utf-8")] if path.is_file() else []
    starts = RealStarts(1.0, 0, log=lambda r: None)
    states = starts.real[:max_starts]
    if max_starts:
        name += f"_starts{max_starts}"
        path = OUT / f"{name}.jsonl"
        done = [json.loads(l) for l in open(path, encoding="utf-8")] if path.is_file() else []
    lib = library_config()
    suites = {"real": (CONFIG, states, len(states)), "library": (lib, states, len(states)),
              "fresh": (lib, None, fresh_games)}
    diffs = {k: [x for r in done for x in r["diffs"][k]] for k in SUITES}
    status = "running"
    for r in range(len(done), rounds):
        row = {"round": r, "time": datetime.now().isoformat(timespec="minutes"),
               "cand": str(cand_path), "champ": str(champ_path), "seed": seed, "diffs": {}}
        for k, (config, st, n) in suites.items():
            s = seed + r * 1_000_003 + SUITES.index(k) * 100_003
            if pool:
                a = play_pool(pool, cand_path, champ_path, n, s, k, st, search_k, chunk)
                b = champion_places(champ, champ_path, n, s, config, st, device, threads,
                                    f"{k}{len(states)}_c{chunk}",
                                    compute=lambda: play_pool(pool, champ_path, champ_path, n, s, k, st, 0, chunk))
            else:
                a = play(cand, champ, n, s, config, st, device, threads=threads)
                b = champion_places(champ, champ_path, n, s, config, st, device, threads,
                                    f"{k}{len(states)}")
            row["diffs"][k] = [x - y for x, y in zip(a, b)]
            row.setdefault("cand_place", {})[k] = round(float(np.mean(a)), 3)
            row.setdefault("champ_place", {})[k] = round(float(np.mean(b)), 3)
            diffs[k] += row["diffs"][k]
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        done.append(row)
        total = summary([x for k in SUITES for x in diffs[k]])
        status = verdict(total, len(done))
        log({"round": r, "total": total, **{k: summary(diffs[k]) for k in SUITES},
             "cand_place": row["cand_place"], "champ_place": row["champ_place"], "status": status})
        if status != "running":
            break
    if pool:
        pool.close()
    total = summary([x for k in SUITES for x in diffs[k]])
    if status == "running":
        status = "inconclusive"
    return {"name": name, "status": status, "rounds": len(done), "total": total,
            **{k: summary(diffs[k]) for k in SUITES}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cand")
    ap.add_argument("champ")
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--fresh-games", type=int, default=256)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--no-recheck", action="store_true", help="skip the fresh-seed re-run of a pass")
    ap.add_argument("--starts", type=int, default=None, help="only the first N real starts (a smoke test)")
    ap.add_argument("--search", type=int, default=0, metavar="K",
                    help="the candidate plays with the plan search over K sampled plans (needs --workers)")
    ap.add_argument("--workers", type=int, default=0, help="CPU worker processes (0: one process, GPU)")
    ap.add_argument("--chunk", type=int, default=4, help="games per worker task (with --workers)")
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    log = lambda r: print(json.dumps(r), flush=True)
    opts = dict(log=log, max_starts=a.starts, search_k=a.search, workers=a.workers, chunk=a.chunk)
    res = run(a.cand, a.champ, a.rounds, SEED, a.fresh_games, a.device, a.threads, **opts)
    if res["status"] == "pass" and not a.no_recheck:
        re = run(a.cand, a.champ, a.rounds, RECHECK_SEED, a.fresh_games, a.device, a.threads, **opts)
        res = {**res, "recheck": re, "status": "pass" if re["status"] == "pass" else "failed recheck"}
    res["time"] = datetime.now().isoformat(timespec="minutes")
    with (OUT / "verdicts.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(res) + "\n")
    print(json.dumps(res))


if __name__ == "__main__":
    main()
