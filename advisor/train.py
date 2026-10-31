"""PPO self-play in TavernGym (docs/ROADMAP.md, M5).

Every seat of every game is played by the current network (BatchEnv with all eight seats
controlled); a seat's episode ends with the placement reward (1st = 1, 8th = -1). Seats act
asynchronously, so each one keeps its own trajectory; the last unfinished transition of a seat
waits for the next rollout, where its value bootstraps the one before it.

The gate: the greedy network on one seat against seven scripted bots, mean placement over fresh
seeds (bots against bots average 4.5). Pause-aware: waits while Hearthstone runs (home rule).

    python -X utf8 -m advisor.train --run smoke --minutes 10
    python -X utf8 -m advisor.train --run office1 --hours 4 --resume data/train/office1/last.pt
    python -X utf8 -m advisor.train --evaluate data/train/office1/best.pt --eval-episodes 1000
"""

import argparse
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import torch

from advisor.policy import load, make, save
from advisor.state import GAME_CONFIG
from taverngym import BatchEnv, layout

CONFIG = GAME_CONFIG  # advisor.state: shared with the live advisor
# Ending a turn with gold left while Refresh is legal and the Tavern isn't frozen costs this much
# reward per gold: gold doesn't carry over, so a Refresh is free then. Self-play alone left the
# network ending late turns with 4-9 gold (advisor.train docstring). A frozen Tavern with a buy
# it can afford counts too: the network had learned to freeze and end with 14 gold
# (advisor.continue_test)
WASTED_GOLD = 0.003
F_GOLD, F_FROZEN = 7, 15  # global observation features (obs.rs): gold / 10, Tavern frozen
A_END, A_REFRESH, A_BUY, N_SHOP = (dict(layout())[k] for k in ("A_END", "A_REFRESH", "A_BUY", "N_SHOP"))


def cap_gpu_memory(device, fraction):
    """At most `fraction` of the GPU for this process: two runs share the office's GPU, and
    PyTorch keeps what it once used, leaving nothing for the hourly promotion's tests."""
    if device.startswith("cuda") and fraction:
        torch.cuda.set_per_process_memory_fraction(fraction)


def hearthstone_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Hearthstone.exe", "/NH"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False  # no tasklist (Linux): no game to wait for
    return "Hearthstone.exe" in out


def wait_while_playing(log):
    if hearthstone_running():
        log({"paused": "Hearthstone is running"})
        while hearthstone_running():
            time.sleep(30)
        log({"resumed": True})


class Seat:
    """One slot's transitions: obs, cards, mask, action, logp, value, reward, done."""
    __slots__ = ("items",)

    def __init__(self):
        self.items = []


def wasted_gold(obs, i, a):
    """The shaping cost of slot `i` taking action `a` (WASTED_GOLD)."""
    f, m = obs["features"][i], obs["action_mask"][i]
    if a != A_END:
        return 0.0
    if f[F_FROZEN] > 0.5 and not m[A_BUY:A_BUY + N_SHOP].any():
        return 0.0
    if f[F_FROZEN] <= 0.5 and not m[A_REFRESH]:
        return 0.0
    return WASTED_GOLD * round(float(f[F_GOLD]) * 10)


def collect(env, net, obs, seats, n_transitions, device, opponent_of=None, starts=None):
    """Step the batch until `n_transitions` new transitions are stored. Returns the next obs and
    stats (finished episodes' placements of the current network's seats). `opponent_of` maps a
    slot to the frozen network playing it (a pool snapshot); those seats aren't learned from.
    `starts` (RealStarts) replaces some of the games that begin anew."""
    opponent_of = opponent_of or {}
    stored, placements = 0, []
    while stored < n_transitions:
        ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
        actions = np.zeros(env.n_slots, dtype=np.int64)
        own = np.array([i for i in ready if i not in opponent_of], dtype=np.int64)
        if len(own):
            f = torch.from_numpy(obs["features"][own]).to(device)
            c = torch.from_numpy(obs["cards"][own]).to(device)
            m = torch.from_numpy(obs["action_mask"][own]).to(device)
            with torch.no_grad():
                logits, v = net(f, c, m)
                dist = torch.distributions.Categorical(logits=logits)
                a = dist.sample()
                lp = dist.log_prob(a)
            a, lp, v = a.cpu().numpy(), lp.cpu().numpy(), v.cpu().numpy()
            actions[own] = a
            for j, i in enumerate(own):
                seats[i].items.append([obs["features"][i], obs["cards"][i],
                                       obs["action_mask"][i], int(a[j]), float(lp[j]),
                                       float(v[j]), -wasted_gold(obs, i, int(a[j])), False])
            stored += len(own)
        play_frozen(obs, ready, opponent_of, actions, device, sample=True)
        rew, done, info = env.step(actions)
        for i in np.flatnonzero((rew != 0) | done):
            if i in opponent_of:
                continue
            if seats[i].items:
                seats[i].items[-1][6] += float(rew[i])
                if done[i]:
                    seats[i].items[-1][7] = True
            if done[i] and info["placement"][i]:
                placements.append(int(info["placement"][i]))
        if starts is not None:
            starts.apply(env)
        obs = env.observe()
    return obs, placements


@torch.no_grad()
def play_frozen(obs, ready, net_of, actions, device, sample=False):
    """Actions of the ready slots that frozen networks play (`net_of`: slot -> network)."""
    groups = {}
    for i in ready:
        if i in net_of:
            groups.setdefault(id(net_of[i]), (net_of[i], []))[1].append(i)
    for n, idx in groups.values():
        idx = np.array(idx)
        logits, _ = n(torch.from_numpy(obs["features"][idx]).to(device),
                      torch.from_numpy(obs["cards"][idx]).to(device),
                      torch.from_numpy(obs["action_mask"][idx]).to(device))
        a = torch.distributions.Categorical(logits=logits).sample() if sample else logits.argmax(1)
        actions[idx] = a.cpu().numpy()


def advantages(seats, gamma, lam):
    """GAE over every seat's finished part; the unfinished last transition stays behind."""
    batch = []
    for s in seats:
        items = s.items
        if not items:
            continue
        keep = [] if items[-1][7] else [items[-1]]
        use = items if items[-1][7] else items[:-1]
        next_v = 0.0 if items[-1][7] else items[-1][5]
        gae = 0.0
        out = []
        for it in reversed(use):
            v, r, d = it[5], it[6], it[7]
            if d:
                next_v, gae = 0.0, 0.0
            delta = r + gamma * next_v - v
            gae = delta + gamma * lam * gae
            out.append((it, gae + v, gae))
            next_v = v
        batch.extend(reversed(out))
        s.items = keep
    return batch


CHUNK = 1024  # rows per forward pass in an update: the GPU's memory, not the step size


class TrinketPrior:
    """Public play data as a warm start for trinket picks (advisor.meta: Firestone's average
    placement of each trinket): at a trinket offer, the target is a softmax over the offered,
    affordable trinkets of (4.5 - average placement) / TEMPERATURE. advisor.train
    --trinket-prior COEF adds COEF x its cross-entropy at those decisions."""
    TEMPERATURE = 0.25  # places: a trinket 0.25 better is e times likelier

    def __init__(self, device):
        import taverngym
        from advisor import meta
        from advisor.policy import N_MISC, L as PL
        cat = json.loads(taverngym.catalog_json())
        stats = meta.trinket_stats()
        score = torch.full((taverngym.N_CARDS + 1,), float("nan"))
        for c in cat:
            if c["id"] in stats:
                score[c["cid"] + 1] = 4.5 - stats[c["id"]]["place"]
        self.score = score.to(device)
        self.flag = PL["GLOBAL_F"] + PL["N_QUESTS"] * PL["QUEST_F"] + 6  # pending kind: trinket
        self.choice = N_MISC + PL["N_BOARD"] + PL["N_HAND"] + PL["N_SHOP"]  # first option card
        self.a = PL["A_CHOOSE"]

    def targets(self, features, cards, mask):
        """(row indices of the trinket decisions with two or more known affordable options,
        their target over the 16 option slots), or None."""
        rows = torch.nonzero(features[:, self.flag] > 0.5).flatten()
        if not len(rows):
            return None
        s = self.score[cards[rows, self.choice:self.choice + 16].clamp(min=0)]
        legal = mask[rows, self.a:self.a + 16] & ~torch.isnan(s)
        keep = legal.sum(1) >= 2
        if not keep.any():
            return None
        target = torch.softmax(torch.where(legal, s / self.TEMPERATURE, -1e9)[keep], 1)
        return rows[keep], target

    def loss(self, features, cards, mask, logits):
        """(cross-entropy over the trinket decisions among these rows, how many), or None.
        `logits`: the network's, illegal actions masked."""
        t = self.targets(features, cards, mask)
        if t is None:
            return None
        rows, target = t
        logp = torch.log_softmax(logits[rows], 1)[:, self.a:self.a + 16]
        return -(target * logp).sum(1).mean(), len(rows)


def update(net, opt, batch, device, epochs=3, minibatch=4096, clip=0.2, vf=0.5, ent=0.01,
           amp=False, value_only=False, anchor=None, anchor_coef=0.0, search=None, search_coef=0.0,
           prior=None, prior_coef=0.0, chunk=CHUNK, human=None, human_coef=0.0):
    """PPO epochs over the batch. `amp`: the network's forward pass in bfloat16 on a GPU (the
    probabilities and losses stay float32). `value_only`: only the value loss (a hot-started
    policy waits until the value fits). `anchor`: a frozen network the policy is kept close to,
    `anchor_coef` times KL(anchor || policy). `search`: a SearchBuffer (advisor.search_games);
    each step also adds `search_coef` times the cross-entropy to the search's choices. `human`:
    the same for the player's own logged choices (advisor.human_data), `human_coef` times."""
    f = torch.from_numpy(np.stack([b[0][0] for b in batch]))
    c = torch.from_numpy(np.stack([b[0][1] for b in batch]))
    m = torch.from_numpy(np.stack([b[0][2] for b in batch]))
    a = torch.tensor([b[0][3] for b in batch])
    old_lp = torch.tensor([b[0][4] for b in batch])
    ret = torch.tensor([b[1] for b in batch], dtype=torch.float32)
    adv = torch.tensor([b[2] for b in batch], dtype=torch.float32)
    adv = (adv - adv.mean()) / (adv.std() + 1e-8)
    n = len(batch)
    stats = {"pi": 0.0, "v": 0.0, "ent": 0.0, "kl": 0.0}
    rng = np.random.default_rng()
    if search is not None:
        stats.update(search_ce=0.0, search_acc=0.0)
    if human is not None:
        stats.update(human_ce=0.0, human_acc=0.0)
    steps = 0
    for _ in range(epochs):
        for idx in torch.randperm(n).split(minibatch):
            opt.zero_grad()
            for part in idx.split(chunk):  # gradients added up: one step per minibatch
                w = len(part) / len(idx)
                fp, cp, mp = f[part].to(device), c[part].to(device), m[part].to(device)
                with torch.autocast("cuda", dtype=torch.bfloat16, enabled=amp and device == "cuda"):
                    logits, v = net(fp, cp, mp)
                logits, v = logits.float(), v.float()
                dist = torch.distributions.Categorical(logits=logits)
                lp = dist.log_prob(a[part].to(device))
                ratio = (lp - old_lp[part].to(device)).exp()
                ad = adv[part].to(device)
                pi_loss = -torch.min(ratio * ad, ratio.clamp(1 - clip, 1 + clip) * ad).mean()
                v_loss = (v - ret[part].to(device)).pow(2).mean()
                entropy = dist.entropy().mean()
                loss = vf * v_loss if value_only else pi_loss + vf * v_loss - ent * entropy
                if anchor is not None and anchor_coef > 0:  # in the warmup too: it holds the policy
                    with torch.no_grad():
                        al, _ = anchor(fp, cp, mp)
                        ap = torch.softmax(al.float(), 1)
                    anchor_kl = (ap * (torch.log_softmax(al.float(), 1)
                                       - torch.log_softmax(logits, 1))).sum(1).mean()
                    loss = loss + anchor_coef * anchor_kl
                if prior is not None and prior_coef > 0:
                    pl = prior.loss(fp, cp, mp, logits)
                    if pl is not None:
                        loss = loss + prior_coef * pl[0] * pl[1] / len(part)
                        stats["trinket_ce"] = stats.get("trinket_ce", 0.0) + pl[0].item() * w
                (loss * w).backward()
                with torch.no_grad():
                    kl = (old_lp[part].to(device) - lp).mean().item()
                for k, x in (("pi", pi_loss.item()), ("v", v_loss.item()), ("ent", entropy.item()), ("kl", kl)):
                    stats[k] += x * w
            if search is not None and search_coef > 0 and len(search) and not value_only:
                sf, sc, sm, sa = (torch.from_numpy(x).to(device)
                                  for x in search.sample(min(len(idx), chunk), rng))
                with torch.autocast("cuda", dtype=torch.bfloat16, enabled=amp and device == "cuda"):
                    slog, _ = net(sf, sc, sm)
                slog = slog.float()
                ce = torch.nn.functional.cross_entropy(slog, sa)
                (search_coef * ce).backward()
                stats["search_ce"] += ce.item()
                stats["search_acc"] += (slog.argmax(1) == sa).float().mean().item()
            if human is not None and human_coef > 0 and len(human) and not value_only:
                hf, hc, hm, ha = (torch.from_numpy(x).to(device)
                                  for x in human.sample(min(len(idx), chunk, 128), rng))
                with torch.autocast("cuda", dtype=torch.bfloat16, enabled=amp and device == "cuda"):
                    hlog, _ = net(hf, hc, hm)
                hlog = hlog.float()
                ce = torch.nn.functional.cross_entropy(hlog, ha)
                (human_coef * ce).backward()
                stats["human_ce"] += ce.item()
                stats["human_acc"] += (hlog.argmax(1) == ha).float().mean().item()
            grads = [p.grad for p in net.parameters() if p.grad is not None]
            if not all(torch.isfinite(g).all() for g in grads):
                opt.zero_grad()  # a bad batch must not ruin the network: skip the step
                stats["skipped"] = stats.get("skipped", 0) + 1
                continue
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
            steps += 1
    return {k: v if k == "skipped" else round(v / max(1, steps), 4) for k, v in stats.items()}


@torch.no_grad()
def human_agreement(net, buf, device):
    """{all, refresh}: how often the network's first choice is the player's logged one, over
    `buf` (held-out games), and over the decisions where the player refreshed."""
    f, c, m, a = buf.all()
    preds = []
    with torch.no_grad():
        for i in range(0, len(a), 512):
            logits, _ = net(*(torch.from_numpy(x[i:i + 512]).to(device) for x in (f, c, m)))
            preds.append(logits.argmax(1).cpu().numpy())
    p = np.concatenate(preds)
    ref = a == A_REFRESH
    return {"all": round(float((p == a).mean()), 3),
            "refresh": round(float((p[ref] == A_REFRESH).mean()), 3) if ref.any() else None,
            "net_refreshes": round(float((p == A_REFRESH).mean()), 3), "n": int(len(a))}


@torch.no_grad()
def evaluate(net, device, episodes=200, games=32, seed=10_000_000, threads=8, config=None):
    """Mean placement of the greedy network on seat 0 against seven scripted bots (`config`'s
    teacher bots when it has one)."""
    env = BatchEnv(games, seed=seed, controlled=[0], config=config or CONFIG, threads=threads)
    obs = env.observe()
    places = []
    while len(places) < episodes:
        ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
        actions = np.zeros(env.n_slots, dtype=np.int64)
        if len(ready):
            logits, _ = net(torch.from_numpy(obs["features"][ready]).to(device),
                            torch.from_numpy(obs["cards"][ready]).to(device),
                            torch.from_numpy(obs["action_mask"][ready]).to(device))
            actions[ready] = logits.argmax(1).cpu().numpy()
        _, done, info = env.step(actions)
        places += [int(p) for p in info["placement"][done] if p]
        obs = env.observe()
    places = places[:episodes]
    return {"mean_place": round(float(np.mean(places)), 3),
            "se": round(float(np.std(places) / np.sqrt(len(places))), 3),
            "top4": round(float(np.mean([p <= 4 for p in places])), 3), "n": len(places)}


@torch.no_grad()
def evaluate_league(net, pool, device, episodes=200, games=32, seed=30_000_000, threads=8,
                    config=None):
    """Mean placement of the greedy network on seat 0 against seven pool snapshots (greedy too):
    under 4.5 beats its own past versions. `config`: other rules (library seats...)."""
    env = BatchEnv(games, seed=seed, controlled=list(range(8)), config=config or CONFIG,
                   threads=threads)
    net_of = {i: pool[(i // 8 + i % 8) % len(pool)] for i in range(env.n_slots) if i % 8}
    net_of.update({i: net for i in range(env.n_slots) if i % 8 == 0})
    obs = env.observe()
    places = []
    while len(places) < episodes:
        ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
        actions = np.zeros(env.n_slots, dtype=np.int64)
        play_frozen(obs, ready, net_of, actions, device)
        _, done, info = env.step(actions)
        places += [int(info["placement"][i]) for i in np.flatnonzero(done)
                   if i % 8 == 0 and info["placement"][i]]
        obs = env.observe()
    places = places[:episodes]
    return {"mean_place": round(float(np.mean(places)), 3),
            "se": round(float(np.std(places) / np.sqrt(len(places))), 3),
            "top4": round(float(np.mean([p <= 4 for p in places])), 3), "n": len(places),
            "pool": len(pool)}


POOL_SIZE = 6
OPPONENT_SEATS = (6, 7)  # of each game's eight, played by pool snapshots in training


def load_pool(out, device):
    pool = []
    for f in sorted((out / "pool").glob("it_*.pt"), key=lambda f: int(f.stem[3:]))[-POOL_SIZE:]:
        n, _ = load(f, device)
        pool.append(n)
    return pool


def assign_opponents(env, pool, it):
    """Slot -> pool snapshot for the opponent seats of every game, rotating by iteration."""
    if not pool:
        return {}
    return {g * 8 + seat: pool[(g + it) % len(pool)]
            for g in range(env.n_games) for seat in OPPONENT_SEATS}


MODELS = Path(__file__).resolve().parents[1] / "data" / "models"  # advisor.promote's
GEN_BEST_SEATS, GEN_PAST_SEATS = (4, 5, 6), (7,)


class Generation:
    """--generations: each game's seats 4-6 play the frozen current best (data/models/best.pt,
    reloaded when a promotion replaces it), seat 7 an older promoted network (archive/), and
    the learner the other four. A generation trains against the network it has to beat."""

    def __init__(self, device, models=MODELS):
        self.device, self.best_path, self.archive = device, models / "best.pt", models / "archive"
        self.version, self.best, self.past = None, None, []

    def refresh(self, log):
        """Reload when a promotion replaced the best; True then."""
        if not self.best_path.is_file():
            return False
        version = self.best_path.stat().st_mtime_ns
        if version == self.version:
            return False
        self.best, ck = load(self.best_path, self.device)
        self.past = []
        for f in sorted(self.archive.glob("best_*.pt"))[-POOL_SIZE:]:
            try:
                self.past.append(load(f, self.device)[0])
            except ValueError:  # an old MLP: it can't read the current observation layout
                pass
        self.version = version
        log({"opponents": "generation", "best": ck.get("source"), "past": len(self.past)})
        return True

    def assign(self, env, it, pool):
        past = self.past or pool
        out = {}
        for g in range(env.n_games):
            if self.best is not None:
                out.update({g * 8 + s: self.best for s in GEN_BEST_SEATS})
            if past:
                out.update({g * 8 + s: past[(g + it) % len(past)] for s in GEN_PAST_SEATS})
        return out


def load_start(env, i, state):
    """Game `i` of `env` replaced by the stored position `state` (Game.state_json), with the
    env's rules (library seats and all) and the logged lobby's tribes, and the random state of
    the game it replaces."""
    fresh = json.loads(env.save(i))
    st = json.loads(json.dumps(state))
    st["cfg"] = {**fresh["game"]["cfg"], "lobby_types": st["cfg"].get("lobby_types")}
    st["rng"] = fresh["game"]["rng"]
    env.load(i, json.dumps({"game": st, "index": fresh["index"],
                            "finished": [not p["alive"] for p in st["players"]]}))


def evaluate_real(net, other, states, device, games=64, seed=31_000_000, threads=8,
                  places_out=None):
    """From every stored real position once (RealStarts.states): mean placement of the greedy
    network in the player's seat (0) with `other` (greedy) in the seven others. Paired: the
    same starts and seeds for every network, so two networks' numbers compare directly.
    `places_out` (a list) gets each start's placement, in order."""
    places = []
    for k in range(0, len(states), games):
        chunk = states[k:k + games]
        env = BatchEnv(len(chunk), seed=seed + k, controlled=list(range(8)), config=CONFIG,
                       threads=threads)
        for i, st in enumerate(chunk):
            load_start(env, i, st)
        net_of = {i: (net if i % 8 == 0 else other) for i in range(env.n_slots)}
        obs = env.observe()
        got = {}
        for _ in range(100_000):  # a guard: games end long before
            if len(got) == len(chunk):
                break
            ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
            ready = np.array([i for i in ready if i // 8 not in got], dtype=np.int64)
            actions = np.zeros(env.n_slots, dtype=np.int64)
            play_frozen(obs, ready, net_of, actions, device)
            _, done, info = env.step(actions)
            for i in np.flatnonzero(done):
                if i % 8 == 0 and i // 8 not in got:  # a stopped game has no placement: 4.5
                    got[i // 8] = int(info["placement"][i]) or 4.5
            obs = env.observe()
        places += [got.get(i, 4.5) for i in range(len(chunk))]
    if places_out is not None:
        places_out.extend(places)
    return {"mean_place": round(float(np.mean(places)), 3),
            "se": round(float(np.std(places) / np.sqrt(len(places))), 3), "n": len(places)}


# RealStarts draws a round from 8 on this many times as often as an earlier one: self-play
# covers the early game, and the late game is where the network stalled
LATE_ROUND, LATE_WEIGHT = 8, 3.0


class RealStarts:
    """--real-starts P: a share P of the new games start where the player stood at the start of a
    logged round (advisor.library.starts, made into games by the bridge) instead of at round 1.
    Self-play games end with warbands a real lobby has by round 8 (advisor.study --curve); from
    a real round-10 position the network stalled - a full board, gold left, cards in hand - where
    the player kept scaling (advisor.continue_test). These games put it in those midgames. Each
    keeps the new game's random state, so the same start plays out differently every time."""

    def __init__(self, p, seed, path=None, log=print, comp_share=0.0):
        from advisor import library
        self.p, self.path, self.log = p, Path(path or library.STARTS), log
        self.rng = np.random.default_rng(seed)
        self.version, self.states, self.real, self.seen = None, [], [], None
        # --comp-starts: this share of the draws are curated comps' midgames instead
        # (advisor.library.comp_starts: Beatboxer magnetizing, Undead attack counts...)
        self.comp_share = comp_share
        self.comp_states = library.comp_starts() if comp_share else []
        if self.comp_states:
            log({"comp_starts": len(self.comp_states)})
        self.refresh()

    def refresh(self):
        """Rebuild the games when the file changed (the home sync sends new ones after you play)."""
        from advisor import bridge
        if not self.path.is_file() or self.path.stat().st_mtime_ns == self.version:
            return
        self.version = self.path.stat().st_mtime_ns
        states, skipped = [], 0
        for line in open(self.path, encoding="utf-8"):
            r = json.loads(line)
            try:
                g, gaps = bridge.build(r["d"], r["combats"])
            except Exception:  # a position the bridge can't build: skip it
                gaps = ["error"]
            if gaps:
                skipped += 1
                continue
            states.append(json.loads(g.state_json()))
        self.real = states  # the player's own positions (evaluate_real reads only these)
        w = np.array([LATE_WEIGHT if st["turn"] >= LATE_ROUND else 1.0 for st in states])
        w = w / w.sum() if len(w) else w
        if self.comp_states:
            share = self.comp_share if len(w) else 1.0
            w = np.concatenate([w * (1 - share), np.full(len(self.comp_states), share / len(self.comp_states))])
            states = states + self.comp_states
        self.states, self.weights = states, w
        self.log({"real_starts": len(self.real), "skipped": skipped,
                  "late": int(sum(st["turn"] >= LATE_ROUND for st in self.real))})

    def apply(self, env):
        """After env.step: the games that just began anew start from a real position instead,
        each with probability p. The number replaced."""
        idx = [env.episode_index(i) for i in range(env.n_games)]
        if self.seen is None or len(self.seen) != len(idx):
            self.seen = idx
            return 0
        n = 0
        for i, (was, now) in enumerate(zip(self.seen, idx)):
            if was == now or not self.states or self.rng.random() >= self.p:
                continue
            load_start(env, i, self.states[self.rng.choice(len(self.states), p=self.weights)])
            n += 1
        self.seen = idx
        return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", help="run name (data/train/RUN)")
    ap.add_argument("--evaluate", metavar="CKPT",
                    help="only the gate: CKPT against seven bots on --eval-episodes fresh games")
    ap.add_argument("--out", default="data/train")
    ap.add_argument("--minutes", type=float, default=0)
    ap.add_argument("--hours", type=float, default=0)
    ap.add_argument("--games", type=int, default=128)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--transitions", type=int, default=32768, help="per update")
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--gamma", type=float, default=0.995)
    ap.add_argument("--lam", type=float, default=0.95)
    ap.add_argument("--ent", type=float, default=0.01, help="entropy bonus")
    ap.add_argument("--amp", action="store_true", help="bfloat16 forward pass in the updates")
    ap.add_argument("--eval-every", type=int, default=10)
    ap.add_argument("--eval-episodes", type=int, default=200)
    ap.add_argument("--resume")
    ap.add_argument("--arch", default="mlp", choices=["mlp", "entity"], help="a new run's network")
    ap.add_argument("--snapshot-every", type=int, default=50,
                    help="iterations between pool snapshots (opponents and the league gate)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--generations", action="store_true",
                    help="train against the frozen current best (Generation); best.pt by place vs it")
    ap.add_argument("--search-data", nargs="*", metavar="DIR",
                    help="search games (advisor.search_games): also learn the search's choices")
    ap.add_argument("--search-coef", type=float, default=0.2)
    ap.add_argument("--search-buffer", type=int, default=200_000, help="the newest N searched decisions")
    ap.add_argument("--human-data", nargs="*", metavar="DIR",
                    help="the player's own logged choices (advisor.human_data): also learned from")
    ap.add_argument("--human-coef", type=float, default=0.05)
    ap.add_argument("--human-eval", metavar="DIR", help="held-out logged choices: agreement at each test")
    ap.add_argument("--library", type=int, nargs="*", metavar="SEAT",
                    help="these seats fight with real warbands from the logs (advisor.library)")
    ap.add_argument("--library-strength", type=float, default=1.0, metavar="S",
                    help="library warbands scaled toward the top 1%% by round (0 = as logged)")
    ap.add_argument("--library-comps", action="store_true",
                    help="library seats also play the curated comps (advisor.library.comp_boards)")
    ap.add_argument("--real-starts", type=float, default=0.0, metavar="P",
                    help="this share of new games start from a logged round's position (RealStarts)")
    ap.add_argument("--comp-starts", type=float, default=0.0, metavar="SHARE",
                    help="with --real-starts: this share of them are curated comps' midgames")
    ap.add_argument("--trinket-prior", type=float, default=0.0, metavar="COEF",
                    help="pull trinket picks toward the public data's preference (TrinketPrior)")
    ap.add_argument("--critic-warmup", type=int, default=0, metavar="N",
                    help="the first N iterations train only the value (after a hot start)")
    ap.add_argument("--anchor", help="keep the policy close to this checkpoint (a hot start)")
    ap.add_argument("--anchor-best", type=float, default=0.0, metavar="COEF",
                    help="with --generations: keep the policy this close (KL) to the frozen current "
                         "best, all along (small steps from the best instead of wandering)")
    ap.add_argument("--anchor-coef", type=float, default=0.1)
    ap.add_argument("--anchor-iters", type=int, default=200,
                    help="iterations over which the anchor fades out")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--gpu-memory", type=float, default=0.4, help="the most of the GPU it takes")
    ap.add_argument("--chunk", type=int, default=CHUNK, help="rows per forward pass in updates (memory)")
    a = ap.parse_args()
    cap_gpu_memory(a.device, a.gpu_memory)
    from advisor import meta
    meta.fetch()  # the public data the card table (built with each network) and the prior read
    if a.evaluate:
        net, ck = load(a.evaluate, a.device)
        # Seeds apart from the training gate's, so a promotion is judged on unseen games
        ev = evaluate(net, a.device, a.eval_episodes, seed=20_000_000, threads=a.threads)
        print(json.dumps({"checkpoint": a.evaluate, "iteration": ck.get("iteration"), **ev}))
        return
    if not a.run:
        ap.error("--run is required for training")
    budget = a.minutes * 60 + a.hours * 3600
    out = Path(a.out) / a.run
    out.mkdir(parents=True, exist_ok=True)
    logf = open(out / "log.jsonl", "a", encoding="utf-8")

    def log(row):
        row = {"t": round(time.time() - t0, 1), **row}
        logf.write(json.dumps(row) + "\n")
        logf.flush()
        print(json.dumps(row), flush=True)

    t0 = time.time()
    torch.manual_seed(a.seed)
    if a.resume:
        net, ck = load(a.resume, a.device)
        net.train()
        it0, best = ck.get("iteration", 0), ck.get("best", 9.0)
    else:
        net, it0, best = make({"arch": a.arch}).to(a.device), 0, 9.0
    opt = torch.optim.Adam(net.parameters(), lr=a.lr)
    if a.resume and "opt" in ck and "adapted" not in ck:  # an adapted network's shapes changed
        opt.load_state_dict(ck["opt"])
    anchor = load(a.anchor, a.device)[0] if a.anchor else None
    prior = TrinketPrior(a.device) if a.trinket_prior else None
    sbuf = None
    if a.search_data:
        from advisor.search_games import SearchBuffer
        sbuf = SearchBuffer(a.search_data, a.search_buffer)
    hbuf = heval = None
    if a.human_data or a.human_eval:
        from advisor.search_games import SearchBuffer
        if a.human_data:
            hbuf = SearchBuffer(a.human_data, 10**7)
        if a.human_eval:
            heval = SearchBuffer([a.human_eval], 10**7)
            heval.refresh()
    train_config = CONFIG
    if a.library:  # their warbands are replaced at every combat: whoever plays them doesn't matter
        from advisor import library
        lib_version = library.BOARDS.stat().st_mtime_ns
        train_config = {**CONFIG, "library": library.library(a.library, strength=a.library_strength, comps=a.library_comps)}
    env = BatchEnv(a.games, seed=a.seed * 1_000_003 + it0, controlled=list(range(8)),
                   config=train_config, threads=a.threads)
    seats = [Seat() for _ in range(env.n_slots)]
    obs = env.observe()
    pool = load_pool(out, a.device)
    gen = Generation(a.device) if a.generations else None
    starts = RealStarts(a.real_starts, a.seed + it0, log=log, comp_share=a.comp_starts) if a.real_starts else None
    real_base = (None, None)  # evaluate_real of the best itself, per best and starts file
    best_h2h = ck.get("best_h2h", 4.5) if a.resume else 4.5  # place vs the best (generations)
    # The anchor fades from where it was first applied, across restarts
    anchor_from = (ck.get("anchor_from") if a.resume else None) or it0 + a.critic_warmup
    log({"start": a.run, "params": sum(p.numel() for p in net.parameters()), "device": a.device,
         "iteration": it0, "slots": env.n_slots})
    if it0 == 0:
        log({"iteration": 0, "eval": evaluate(net, a.device, a.eval_episodes, threads=a.threads)})
    it = it0
    while budget == 0 or time.time() - t0 < budget:
        wait_while_playing(log)
        it += 1
        ts = time.time()
        if a.library and library.BOARDS.stat().st_mtime_ns != lib_version:
            # New real warbands (the home sync uploads them after you play): new games with them
            lib_version = library.BOARDS.stat().st_mtime_ns
            train_config = {**CONFIG, "library": library.library(a.library, strength=a.library_strength, comps=a.library_comps)}
            env = BatchEnv(a.games, seed=a.seed * 1_000_003 + it, controlled=list(range(8)),
                           config=train_config, threads=a.threads)
            seats = [Seat() for _ in range(env.n_slots)]
            obs = env.observe()
            log({"library": len(train_config["library"]["boards"])})
        if gen and gen.refresh(log):
            best_h2h = 4.5  # a new generation: the record against the old best is void
        opponents = gen.assign(env, it, pool) if gen else assign_opponents(env, pool, it)
        if starts is not None:
            starts.refresh()
        obs, placements = collect(env, net, obs, seats, a.transitions, a.device, opponents, starts)
        for i in opponents:  # a seat that changes hands starts its trajectory anew
            seats[i].items = []
        batch = advantages(seats, a.gamma, a.lam)
        tc = time.time()
        net.train()
        warm = it - it0 <= a.critic_warmup
        fade = max(0, it - anchor_from) / a.anchor_iters  # from the warmup's end
        coef = a.anchor_coef * max(0.0, 1 - fade) if anchor else 0.0
        step_anchor = anchor
        if a.anchor_best and gen and gen.best is not None:
            step_anchor, coef = gen.best, a.anchor_best
        if sbuf is not None:
            sbuf.refresh()
        if hbuf is not None:
            hbuf.refresh()
        stats = update(net, opt, batch, a.device, ent=a.ent, amp=a.amp, value_only=warm,
                       anchor=step_anchor, anchor_coef=coef, search=sbuf, search_coef=a.search_coef,
                       prior=prior, prior_coef=a.trinket_prior, chunk=a.chunk,
                       human=hbuf, human_coef=a.human_coef)
        if sbuf is not None:
            stats["search_buffer"] = len(sbuf)
        if warm:
            stats["critic_warmup"] = True
        net.eval()
        row = {"iteration": it, "batch": len(batch), "episodes": len(placements),
               "place": round(float(np.mean(placements)), 3) if placements else None,
               "collect_s": round(tc - ts, 1), "update_s": round(time.time() - tc, 1),
               "decisions_per_s": round(len(batch) / max(1e-6, tc - ts)), **stats}
        if it % a.snapshot_every == 0:
            save(net, out / "pool" / f"it_{it}.pt", {"iteration": it})
            frozen = make(net.config).to(a.device)
            frozen.load_state_dict(net.state_dict())
            frozen.eval()
            pool = (pool + [frozen])[-POOL_SIZE:]
        if it % a.eval_every == 0:
            ev = evaluate(net, a.device, a.eval_episodes, threads=a.threads)
            row["eval"] = ev
            if pool:
                row["league"] = evaluate_league(net, pool, a.device, a.eval_episodes,
                                                threads=a.threads)
            if gen and gen.best is not None:
                vs = evaluate_league(net, [gen.best], a.device, a.eval_episodes, threads=a.threads)
                vs.pop("pool", None)
                row["vs_best"] = vs
                if heval is not None and len(heval):
                    row["human_agree"] = human_agreement(net, heval, a.device)
                if starts is not None and starts.real:  # the player's own positions
                    if real_base[0] != (gen.version, starts.version):
                        real_base = ((gen.version, starts.version),
                                     evaluate_real(gen.best, gen.best, starts.real, a.device,
                                                   threads=a.threads))
                    vr = evaluate_real(net, gen.best, starts.real, a.device, threads=a.threads)
                    row["vs_best_real"] = {**vr, "best": real_base[1]["mean_place"]}
                if a.library:  # one seat against the best and real warbands: closest to a lobby
                    vl = evaluate_league(net, [gen.best], a.device, a.eval_episodes,
                                         threads=a.threads, config=train_config)
                    vl.pop("pool", None)
                    row["vs_library"] = vl
                if vs["mean_place"] < best_h2h:  # the candidate advisor.promote judges
                    best_h2h = vs["mean_place"]
                    save(net, out / "best.pt", {"iteration": it, "eval": ev, "best": best,
                                                "vs_best": vs, "best_h2h": best_h2h})
            elif ev["mean_place"] < best:
                best = ev["mean_place"]
                save(net, out / "best.pt", {"iteration": it, "eval": ev, "best": best})
            best = min(best, ev["mean_place"])
        log(row)
        save(net, out / "last.pt", {"iteration": it, "best": best, "best_h2h": best_h2h,
                                    "anchor_from": anchor_from if anchor else None,
                                    "opt": opt.state_dict()})
        if budget == 0 and it - it0 >= 1:
            break


if __name__ == "__main__":
    main()
