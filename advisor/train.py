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
# network ending late turns with 4-9 gold (advisor.train docstring). A frozen Tavern counts too:
# the network learned to freeze and end with the Gold (advisor.continue_test: 14 Gold; from the
# player's round 13+ positions it froze 1.5 times a turn and ended with 9 Gold where the player
# refreshed 4.3 times and kept 4.7, advisor.compare_play)
WASTED_GOLD = 0.003
F_GOLD, F_FROZEN = 7, 15  # global observation features (obs.rs): gold / 10, Tavern frozen
A_END, A_REFRESH, A_BUY, N_SHOP, A_UPGRADE, A_FREEZE = (dict(layout())[k] for k in
                                                        ("A_END", "A_REFRESH", "A_BUY", "N_SHOP", "A_UPGRADE", "A_FREEZE"))


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


_LAST_CHECK = [0.0]


def pause_if_playing(every=15.0):
    """wait_while_playing at most every `every` seconds: cheap enough for a worker to call at
    every decision. (A check between long rounds came too late: a round of late-game searches
    ran half an hour into your game and the advice took 17 s instead of 1.5.)"""
    now = time.monotonic()
    if now - _LAST_CHECK[0] >= every:
        wait_while_playing(lambda *_: None)
        _LAST_CHECK[0] = time.monotonic()


class Seat:
    """One slot's transitions: obs, cards, mask, action, logp, value, reward, done."""
    __slots__ = ("items",)

    def __init__(self):
        self.items = []


def wasted_gold(obs, i, a):
    """The shaping cost of slot `i` taking action `a` (WASTED_GOLD)."""
    f, m = obs["features"][i], obs["action_mask"][i]
    if a != A_END or not (m[A_REFRESH] or m[A_BUY:A_BUY + N_SHOP].any()):
        return 0.0
    return WASTED_GOLD * round(float(f[F_GOLD]) * 10)


_L = dict(layout())
A_CANCEL = _L["A_CANCEL"]
A_HERO_POWER, A_CHOOSE, N_CHOICE = _L["A_HERO_POWER"], _L["A_CHOOSE"], _L["N_CHOICE"]
A_ACTIVATE, N_BOARD = _L["A_ACTIVATE"], _L["N_BOARD"]


def action_mix(actions):
    """Shares of the training games' actions by kind (docs/ROBUSTNESS.md section 5: a cost the
    network learns to dodge shows as a share drifting away from a real player's)."""
    a = np.asarray(actions)
    n = max(1, len(a))
    spans = {"refresh": (_L["A_REFRESH"], _L["A_REFRESH"] + 1), "freeze": (_L["A_FREEZE"], _L["A_FREEZE"] + 1),
             "upgrade": (_L["A_UPGRADE"], _L["A_UPGRADE"] + 1), "end": (_L["A_END"], _L["A_END"] + 1),
             "buy": (_L["A_BUY"], _L["A_BUY"] + _L["N_SHOP"]), "sell": (_L["A_SELL"], _L["A_SELL"] + _L["N_BOARD"]),
             "play": (_L["A_PLAY"], _L["A_MOVE"]), "move": (_L["A_MOVE"], _L["A_MOVE"] + 49)}
    return {k: round(float(((a >= lo) & (a < hi)).sum()) / n, 4) for k, (lo, hi) in spans.items()}


def hero_offers(env, obs, own, fresh):
    """The rows of `own` (slots) that stand at the game's hero offer (only choices legal, the
    pending choice is the hero select). `fresh`: the rows with no action yet this game (the
    offer is the first decision; reading every offer's view each step ran collect at 98
    decisions/s instead of ~1,500, Nov 3)."""
    m = obs["action_mask"][own]
    only = m[:, A_CHOOSE:A_CHOOSE + N_CHOICE].any(1) & (m.sum(1) == m[:, A_CHOOSE:A_CHOOSE + N_CHOICE].sum(1))
    only &= fresh
    k = len(env.controlled)
    out = []
    for j in np.flatnonzero(only):
        i = int(own[j])
        v = json.loads(env.game(i // k).view(env.controlled[i % k]))
        if v.get("phase") == "hero_select":
            out.append(j)
    return out


_TRIBE = {}


def _tribe_tables():
    """Per card embedding index (1 + cid): its races (CARD_RACES order, the last is ALL), whether
    it's a minion, its Tier."""
    if not _TRIBE:
        import taverngym
        from advisor.policy import CARD_RACES, N_MISC
        cat = json.loads(taverngym.catalog_json())
        n = max(c["cid"] for c in cat) + 2
        races, minion, tier = np.zeros((n, len(CARD_RACES)), bool), np.zeros(n, bool), np.zeros(n, np.int64)
        for c in cat:
            for j, r in enumerate(CARD_RACES):
                races[c["cid"] + 1, j] = r in (c.get("races") or [])
            minion[c["cid"] + 1] = c["kind"] == "minion"
            tier[c["cid"] + 1] = c.get("tier") or 0
        # Card slots in observation order: misc, warband, hand, Tavern, ... (policy.EntityNet.forward)
        board0 = N_MISC
        _TRIBE.update(races=races, minion=minion, tier=tier, board=board0, shop=board0 + N_BOARD + _L["N_HAND"])
    return _TRIBE


def tribe_buys(cards, mask, a):
    """Per row: the buy of the warband's main tribe to take instead of `a`, or -1. Where `a` buys an
    off-tribe minion and a legal (affordable) minion of the tribe is in the Tavern: the one of the
    highest Tier. The tribe: the most common type on the warband (ALL counts for every type but
    doesn't make one). From the observation's card slots, not the game's view (a view per buy made
    the collection 3x slower)."""
    t = _tribe_tables()
    board = cards[:, t["board"]:t["board"] + N_BOARD]
    shop = cards[:, t["shop"]:t["shop"] + N_SHOP]
    br = t["races"][board]  # (n, 7, R)
    counts = br[:, :, :-1].sum(1)
    tribe = counts.argmax(1)
    has = counts.max(1) > 0
    sr = t["races"][shop]  # (n, 8, R)
    rows = np.arange(len(cards))
    on = (sr[rows, :, tribe] | sr[:, :, -1]) & t["minion"][shop]
    legal = mask[:, A_BUY:A_BUY + N_SHOP]
    slot = a - A_BUY
    buying = (a >= A_BUY) & (a < A_BUY + N_SHOP)
    s = np.clip(slot, 0, N_SHOP - 1)
    off = buying & t["minion"][shop[rows, s]] & ~on[rows, s]
    cand = on & legal
    score = np.where(cand, t["tier"][shop] * 100 + 1, 0)
    best = score.argmax(1)
    ok = has & off & cand.any(1)
    return np.where(ok, A_BUY + best, -1)


def collect(env, net, obs, seats, n_transitions, device, opponent_of=None, starts=None, explore=None,
            random_hero=0.0, amp=False, explore_tribe=0.0):
    """Step the batch until `n_transitions` new transitions are stored. Returns the next obs and
    stats (finished episodes' placements of the current network's seats). `opponent_of` maps a
    slot to the frozen network playing it (a pool snapshot); those seats aren't learned from.
    `starts` (RealStarts) replaces some of the games that begin anew. `explore` = (p_refresh,
    p_upgrade[, p_hero_power[, p_activate]]): a legal Refresh or Upgrade is taken in place of the sampled action with that
    probability (the network almost never samples a Refresh, so it never learns what one finds);
    such a step is marked forced: its consequences are learned from, the step itself isn't.
    `explore_tribe`: with this probability a buy of an off-tribe minion becomes a buy of the warband's
    main tribe where an affordable one is in the Tavern (forced, as `explore`; --explore-sil imitates
    it where it did better than expected). The buy audit (Nov 5): offered one in rounds 7-9, main1
    takes it 35% of the time, you 72%.
    `amp`: the network's forward pass in bfloat16 (the collection waits on it: 6.7 of 9.8 s in fp32
    on 64k decisions), its outputs back in float32 for the sampling."""
    opponent_of = opponent_of or {}
    stored, placements = 0, []
    last = getattr(env, "_last_action", None)
    if last is None or len(last) != env.n_slots:
        last = env._last_action = np.full(env.n_slots, -1, dtype=np.int64)
    while stored < n_transitions:
        ready = np.flatnonzero(obs["ready"] & obs["action_mask"].any(1))
        actions = np.zeros(env.n_slots, dtype=np.int64)
        own = np.array([i for i in ready if i not in opponent_of], dtype=np.int64)
        if len(own):
            f = torch.from_numpy(obs["features"][own]).to(device)
            c = torch.from_numpy(obs["cards"][own]).to(device)
            mask = obs["action_mask"][own].copy()
            # A second Freeze straight after one is a no-op (it unfreezes what was just frozen)
            again = (last[own] == A_FREEZE) & (mask.sum(1) > 1)
            mask[again, A_FREEZE] = False
            # Cancel undoes the play that asked for a target: a no-op. Played and cancelled in a
            # loop, it burned a turn's actions until the cap ended the turn without an End Turn
            # (and its wasted-Gold cost): solo1 and emb1 learned that loop (Nov 1)
            undo = mask[:, A_CANCEL] & (mask.sum(1) > 1)
            mask[undo, A_CANCEL] = False
            obs["action_mask"][own] = mask
            m = torch.from_numpy(mask).to(device)
            with torch.no_grad():
                with torch.autocast("cuda", dtype=torch.bfloat16, enabled=amp and device.startswith("cuda")):
                    logits, v = net(f, c, m)
                logits, v = logits.float(), v.float()
                dist = torch.distributions.Categorical(logits=logits)
                a = dist.sample()
                lp = dist.log_prob(a)
            a, lp, v = a.cpu().numpy(), lp.cpu().numpy(), v.cpu().numpy()
            forced = np.zeros(len(own), bool)
            if explore:
                m_own = obs["action_mask"][own]
                pairs = [(A_REFRESH, explore[0]), (A_UPGRADE, explore[1])]
                if len(explore) > 2:  # (a third probability: the Hero Power, either slot)
                    pairs += [(A_HERO_POWER, explore[2]), (A_HERO_POWER + 1, explore[2])]
                for which, p_x in pairs:
                    pick = (np.random.random(len(own)) < p_x) & m_own[:, which] & ~forced
                    a[pick], forced[pick] = which, True
                if len(explore) > 3:
                    # (a fourth: a legal Activate, the one of a random minion that has one. The
                    # late-game case study: R3 activated Lurking Lionfish 0.6 times a turn where
                    # you did 3.1, and forcing it grew its Beast warbands 18%)
                    acts = m_own[:, A_ACTIVATE:A_ACTIVATE + N_BOARD]
                    pick = (np.random.random(len(own)) < explore[3]) & acts.any(1) & ~forced
                    for j in np.flatnonzero(pick):
                        a[j], forced[j] = A_ACTIVATE + int(np.random.choice(np.flatnonzero(acts[j]))), True
            if explore_tribe > 0:
                b = tribe_buys(obs["cards"][own], obs["action_mask"][own], a)
                pick = (b >= 0) & ~forced & (np.random.random(len(own)) < explore_tribe)
                a[pick], forced[pick] = b[pick], True
                env._tribe_forced = getattr(env, "_tribe_forced", 0) + int(pick.sum())
            if random_hero > 0:
                # A random hero instead of the network's pick: it never picked 48 of the 116
                # (Captain Hooktusk among them), so their Hero Powers went unpractised. Forced:
                # the game is learned from, the pick isn't
                for j in hero_offers(env, obs, own, last[own] < 0):
                    if np.random.random() < random_hero:
                        legal = np.flatnonzero(obs["action_mask"][own[j], A_CHOOSE:A_CHOOSE + N_CHOICE])
                        a[j], forced[j] = A_CHOOSE + int(np.random.choice(legal)), True
            actions[own] = a
            for j, i in enumerate(own):
                seats[i].items.append([obs["features"][i], obs["cards"][i],
                                       obs["action_mask"][i], int(a[j]), float(lp[j]),
                                       float(v[j]), -wasted_gold(obs, i, int(a[j])), False, bool(forced[j])])
            stored += len(own)
        play_frozen(obs, ready, opponent_of, actions, device, sample=True)
        last[ready] = actions[ready]
        rew, done, info = env.step(actions)
        last[done] = -1
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
def collect_behind(stream, copied, *args, **kw):
    """collect on its own CUDA stream, for --overlap's thread (the update keeps the default one):
    its waits for results then don't wait for the update's queued work. `copied`: the event after
    the actor's weights were copied. (obs, placements, seconds)."""
    t = time.time()
    if stream is None:
        return (*collect(*args, **kw), time.time() - t)
    stream.wait_event(copied)
    with torch.cuda.stream(stream):
        out = collect(*args, **kw)
    return (*out, time.time() - t)


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


class GameSil:
    """--sil-games: self-imitation (Oh et al. 2018) of the network's own games that ended high. The
    transitions of games whose return is at least `min_return` (0.6: 1st or 2nd) where the game
    turned out better than the value expected are kept (a ring of `capacity`) and replayed every
    minibatch: -log p(a|s) x max(R - V(s), 0) with the current value, plus a small fit of V up to R
    where it is below. The games where it scales are rare and win (Nov 5: 1.8x+ a round in 2.6% of
    fresh games, place 2.1 against 4.2); PPO sees each once, this replays them until the value
    expects them."""

    def __init__(self, capacity, min_return):
        self.cap, self.min_return = capacity, min_return
        self.n = self.pos = self.added = 0
        self.f = self.c = self.m = self.a = self.r = None

    def add(self, batch):
        rows = [b for b in batch if b[1] >= self.min_return and b[1] > b[0][5]]
        if not rows:
            return 0
        if self.f is None:
            b0 = rows[0][0]
            self.f = np.zeros((self.cap, len(b0[0])), np.float32)
            self.c = np.zeros((self.cap, len(b0[1])), np.int32)
            self.m = np.zeros((self.cap, len(b0[2])), bool)
            self.a = np.zeros(self.cap, np.int64)
            self.r = np.zeros(self.cap, np.float32)
        for b in rows:
            it = b[0]
            i = self.pos
            self.f[i], self.c[i], self.m[i], self.a[i], self.r[i] = it[0], it[1], it[2], it[3], b[1]
            self.pos = (self.pos + 1) % self.cap
            self.n = min(self.n + 1, self.cap)
        self.added += len(rows)
        return len(rows)

    def sample(self, k, rng):
        i = rng.integers(0, self.n, min(k, self.n))
        return self.f[i], self.c[i], self.m[i], self.a[i], self.r[i]


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
           prior=None, prior_coef=0.0, chunk=CHUNK, human=None, human_coef=0.0, sil=0.0,
           games_sil=None, games_sil_coef=0.0):
    """PPO epochs over the batch. `amp`: the network's forward pass in bfloat16 on a GPU (the
    probabilities and losses stay float32). `value_only`: only the value loss (a hot-started
    policy waits until the value fits). `anchor`: a frozen network the policy is kept close to,
    `anchor_coef` times KL(anchor || policy). `search`: a SearchBuffer (advisor.search_games);
    each step also adds `search_coef` times the cross-entropy to the search's choices. `human`:
    the same for the player's own logged choices (advisor.human_data), `human_coef` times.
    `sil`: self-imitation (Oh et al. 2018) of the forced exploration steps that did better than
    the value expected: `sil` times -log p(action) x max(advantage, 0). PPO can't learn a forced
    step (its ratio is meaningless), so an action the network gives ~0 (an Upgrade: 0.000 in
    your round 4-9 positions, Nov 1) stays at ~0 however much it pays; this learns it where it
    pays, and nothing where it doesn't. `games_sil`: a GameSil buffer, replayed `games_sil_coef`
    times each minibatch (its own games that ended high)."""
    f = torch.from_numpy(np.stack([b[0][0] for b in batch]))
    c = torch.from_numpy(np.stack([b[0][1] for b in batch]))
    m = torch.from_numpy(np.stack([b[0][2] for b in batch]))
    a = torch.tensor([b[0][3] for b in batch])
    old_lp = torch.tensor([b[0][4] for b in batch])
    # Exploration steps (collect's `explore`): their value is learned, their action isn't
    learn = torch.tensor([not (len(b[0]) > 8 and b[0][8]) for b in batch], dtype=torch.float32)
    ret = torch.tensor([b[1] for b in batch], dtype=torch.float32)
    adv = torch.tensor([b[2] for b in batch], dtype=torch.float32)
    gain = adv.clamp(min=0) / (adv.std() + 1e-8)  # (self-imitation: better than expected)
    # Normalized over the learned steps only: forced steps that mostly did worse (big3sil's
    # Upgrades) would otherwise shift every learned step's advantage up (its pi loss drifted to -0.17)
    on = learn > 0
    ref = adv[on] if on.sum() > 1 else adv
    adv = (adv - ref.mean()) / (ref.std() + 1e-8)
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
                ad = adv[part].to(device)
                keep = learn[part].to(device)
                # (a forced step's old log-probability is the sampled action's: its ratio is
                # meaningless, so it is left out of the policy loss)
                ratio = ((lp - old_lp[part].to(device)) * keep).exp()
                pi_loss = -(torch.min(ratio * ad, ratio.clamp(1 - clip, 1 + clip) * ad) * keep).sum()                     / keep.sum().clamp(min=1)
                v_loss = (v - ret[part].to(device)).pow(2).mean()
                entropy = dist.entropy().mean()
                loss = vf * v_loss if value_only else pi_loss + vf * v_loss - ent * entropy
                if sil > 0 and not value_only:
                    forced = 1 - keep
                    if forced.any():
                        sil_loss = -(lp * forced * gain[part].to(device)).sum() / len(part)
                        loss = loss + sil * sil_loss
                        stats["sil"] = stats.get("sil", 0.0) + sil_loss.item() * w
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
                    kl = (((old_lp[part].to(device) - lp) * keep).sum() / keep.sum().clamp(min=1)).item()
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
            if games_sil is not None and games_sil_coef > 0 and games_sil.n and not value_only:
                gf, gc, gm, ga, gr = (torch.from_numpy(x).to(device) for x in games_sil.sample(chunk, rng))
                with torch.autocast("cuda", dtype=torch.bfloat16, enabled=amp and device == "cuda"):
                    glog, gv = net(gf, gc, gm)
                glog, gv = glog.float(), gv.float()
                glp = torch.distributions.Categorical(logits=glog).log_prob(ga)
                gap = (gr - gv).clamp(min=0)
                gloss = -(glp * gap.detach()).mean() + 0.01 * 0.5 * gap.pow(2).mean()
                (games_sil_coef * gloss).backward()
                stats["games_sil"] = stats.get("games_sil", 0.0) + gloss.item()
                stats["games_sil_gap"] = stats.get("games_sil_gap", 0.0) + gap.mean().item()
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
    # (one flag per seat the env controls: all eight, or seat 0 alone under --solo)
    env.load(i, json.dumps({"game": st, "index": fresh["index"],
                            "finished": [not st["players"][s]["alive"] for s in env.controlled]}))


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


# RealStarts draws a round from 7 on this many times as often as an earlier one, and one before
# round 7 this much: self-play covers the early game (and it is the easy part), the mid and late
# game is where the network falls behind (advisor.compare_play)
LATE_ROUND, LATE_WEIGHT, EARLY_WEIGHT = 7, 3.0, 0.2


def comp_curriculum(tracks, path=None):
    """Weights (summing to 1) for comp starts of these comp tracks: a comp the network plays
    worse (advisor.genres: warband growth from its midgame against the top 1%; data/library/
    genres.json) is drawn more, from half to twice the median one. Even without a scorecard."""
    from advisor import library
    path = Path(path or library.STARTS.parent / "genres.json")
    growth = {}
    if path.is_file():
        growth = {c["comp"]: c["growth"] for c in json.loads(path.read_text(encoding="utf-8"))["comps"]
                  if c.get("growth")}
    med = float(np.median(list(growth.values()))) if growth else 1.0
    w = np.array([min(2.0, max(0.5, med / max(0.05, growth.get(t, med)))) for t in tracks])
    return w / w.sum()


class RealStarts:
    """--real-starts P: a share P of the new games start where the player stood at the start of a
    logged round (advisor.library.starts, made into games by the bridge) instead of at round 1.
    Self-play games end with warbands a real lobby has by round 8 (advisor.study --curve); from
    a real round-10 position the network stalled - a full board, gold left, cards in hand - where
    the player kept scaling (advisor.continue_test). These games put it in those midgames. Each
    keeps the new game's random state, so the same start plays out differently every time."""

    def __init__(self, p, seed, path=None, log=print, comp_share=0.0, rounds=None, split=None):
        from advisor import library
        import os
        if rounds is None and os.environ.get("BG_ROUNDS"):  # (evaluations: BG_ROUNDS="6 19")
            rounds = tuple(int(x) for x in os.environ["BG_ROUNDS"].split())
        self.rounds, self.split = rounds, split  # (--real-rounds LO HI, --real-split)
        self.p, self.path, self.log = p, Path(path or library.STARTS), log
        self.rng = np.random.default_rng(seed)
        self.version, self.states, self.real, self.seen = None, [], [], None
        # --comp-starts: this share of the draws are curated comps' midgames instead
        # (advisor.library.comp_starts: Beatboxer magnetizing, Undead attack counts...)
        self.comp_share = comp_share
        self.comp_states, self.comp_weights = [], None
        if comp_share:
            tagged = library.comp_starts(tagged=True)
            self.comp_states = [st for _, _, st in tagged]
            self.comp_weights = comp_curriculum([t for t, _, _ in tagged])
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
            from advisor import library
            rnd = (r["d"]["turn"] + 1) // 2
            if not library.in_split(r["d"]["log"], self.split) or                     (self.rounds and not self.rounds[0] <= rnd <= self.rounds[1]):
                continue
            try:
                g, gaps = bridge.build(r["d"], r["combats"])
            except Exception:  # a position the bridge can't build: skip it
                gaps = ["error"]
            if gaps:
                skipped += 1
                continue
            states.append(json.loads(g.state_json()))
        self.real = states  # the player's own positions (evaluate_real reads only these)
        w = np.array([LATE_WEIGHT if st["turn"] >= LATE_ROUND else EARLY_WEIGHT for st in states])
        w = w / w.sum() if len(w) else w
        if self.comp_states:
            share = self.comp_share if len(w) else 1.0
            w = np.concatenate([w * (1 - share), share * self.comp_weights])
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
    ap.add_argument("--amp-collect", action="store_true",
                    help="bfloat16 forward pass in the collection too (the learner's seats)")
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
    ap.add_argument("--search-drop-idle", action="store_true",
                    help="leave out the search's End Turns with 3+ Gold a buy or Refresh could use")
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
    ap.add_argument("--library-adaptive", type=float, default=0.0, metavar="MARGIN",
                    help="the training library's curve: MARGIN x the learner's own median warband by "
                         "round, at most the top 1%%'s (advisor.library.adaptive_curve); evaluations keep "
                         "the full strength")
    ap.add_argument("--library-early", type=int, nargs=2, default=None, metavar=("START", "FULL"),
                    help="the training library at your lobbies' logged strength through round START, "
                         "rising to the top 1%% by round FULL (advisor.library.early_curve)")
    ap.add_argument("--adaptive-every", type=int, default=10, metavar="N",
                    help="iterations between --library-adaptive's recalibrations")
    ap.add_argument("--wasted-gold", type=float, default=WASTED_GOLD, metavar="COEF",
                    help="the cost per Gold left at End Turn while a buy or Refresh is legal (0: placement only, "
                         "AutoTavern's reward)")
    ap.add_argument("--card-lost", type=float, default=0.0, metavar="COEF",
                    help="the cost per card lost to a full hand (the env's card_lost_penalty; big3 lost "
                         "0.8 a game activating card-making minions with 9-10 cards)")
    ap.add_argument("--epochs", type=int, default=3, help="PPO epochs over each batch")
    ap.add_argument("--minibatch", type=int, default=4096)
    ap.add_argument("--solo", action="store_true",
                    help="the learner plays seat 0 alone against library seats 1-7, which skip their "
                         "recruit turns (no self-play; AutoTavern's setup)")
    ap.add_argument("--blind-v4", action="store_true",
                    help="a control: the network doesn't see observation version 4's numbers nor the "
                         "card table's text columns (policy.EntityNet blind_v4)")
    ap.add_argument("--explore", type=float, nargs="+", default=None, metavar="P",
                    help="take a legal Refresh / Upgrade (/ Hero Power: a third value / a minion's "
                         "Activate: a fourth) with these probabilities (collect's explore)")
    ap.add_argument("--explore-tribe", type=float, default=0.0, metavar="P",
                    help="a buy of an off-tribe minion becomes an on-tribe one (offered, affordable) with "
                         "this probability (collect's explore_tribe; forced: --explore-sil learns it where it paid)")
    ap.add_argument("--random-hero", type=float, default=0.0, metavar="P",
                    help="at the hero offer, a random hero with this probability (forced: not learned)")
    ap.add_argument("--sil-games", type=float, default=0.0, metavar="COEF",
                    help="self-imitation of its own games that ended high (GameSil), this times per minibatch")
    ap.add_argument("--sil-games-buffer", type=int, default=65536, metavar="N",
                    help="transitions GameSil keeps (about 0.9 GB at 65,536)")
    ap.add_argument("--sil-games-min", type=float, default=0.6, metavar="R",
                    help="the least return of a kept game's transition (0.6: 1st or 2nd)")
    ap.add_argument("--explore-sil", type=float, default=0.0, metavar="COEF",
                    help="self-imitation of the forced steps that did better than expected (update's sil)")
    ap.add_argument("--real-starts", type=float, default=0.0, metavar="P",
                    help="this share of new games start from a logged round's position (RealStarts)")
    ap.add_argument("--real-rounds", type=int, nargs=2, default=None, metavar=("LO", "HI"),
                    help="real starts only from these rounds (the mid/late specialist: 6 19)")
    ap.add_argument("--real-split", default=None, choices=("all", "train", "test"),
                    help="real starts only from these of your games (library.holdout; default BG_SPLIT or all)")
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
    ap.add_argument("--overlap", action="store_true",
                    help="collect the next batch while the update runs (a thread, with a copy of the weights "
                         "from before the update: the batch is one update behind); with --solo. UNSTABLE at full "
                         "size (Nov 5: the policy's step per update grew from KL 0.001 to 0.1 in 12 iterations, "
                         "the same with the two kept apart in time: the lag itself, not the GPU streams)")
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
    globals()["WASTED_GOLD"] = a.wasted_gold  # (wasted_gold reads it)
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
        if a.blind_v4 and not getattr(net, "blind_v4", True):  # a control: from now on blind
            state = net.state_dict()
            net = make({**ck["config"], "blind_v4": True}).to(a.device)
            net.load_state_dict(state)
        net.train()
        it0, best = ck.get("iteration", 0), ck.get("best", 9.0)
    else:
        net, it0, best = make({"arch": a.arch}).to(a.device), 0, 9.0
    opt = torch.optim.Adam(net.parameters(), lr=a.lr)
    if a.resume and "opt" in ck and "adapted" not in ck:  # an adapted network's shapes changed
        opt.load_state_dict(ck["opt"])
    anchor = load(a.anchor, a.device)[0] if a.anchor else None
    gsil = GameSil(a.sil_games_buffer, a.sil_games_min) if a.sil_games else None
    prior = TrinketPrior(a.device) if a.trinket_prior else None
    sbuf = None
    if a.search_data:
        from advisor.search_games import SearchBuffer
        sbuf = SearchBuffer(a.search_data, a.search_buffer, drop_idle=a.search_drop_idle)
    hbuf = heval = None
    if a.human_data or a.human_eval:
        from advisor.search_games import SearchBuffer
        if a.human_data:
            hbuf = SearchBuffer(a.human_data, 10**7)
        if a.human_eval:
            heval = SearchBuffer([a.human_eval], 10**7)
            heval.refresh()
    train_config = CONFIG
    # --solo: the learner plays seat 0 alone against the library seats (AutoTavern's setup: no
    # self-play; the library seats skip their recruit turns); the others are the scripted bot
    controlled = [0] if a.solo else list(range(8))
    if a.solo and (a.generations or not a.library):
        raise SystemExit("--solo needs --library (seats 1-7) and no --generations")
    if a.overlap and not a.solo:
        raise SystemExit("--overlap needs --solo (opponents assigned per iteration aren't carried over)")
    if a.library:  # their warbands are replaced at every combat: whoever plays them doesn't matter
        from advisor import library
        lib_version = library.BOARDS.stat().st_mtime_ns
        lib_curve = None  # (--library-adaptive: set by the first recalibration)

        base_curve = library.early_curve(*a.library_early) if a.library_early else None

        def lib_config(curve=None):
            curve = curve if curve is not None else base_curve
            floor = 0.02 if curve is not None else 1.0
            return {**CONFIG, "library": {**library.library(a.library, strength=a.library_strength,
                                                            comps=a.library_comps, curve=curve,
                                                            floor=floor),
                                          "skip_recruit": a.solo}}
        train_config = lib_config()
    env = BatchEnv(a.games, seed=a.seed * 1_000_003 + it0, controlled=controlled,
                   config=train_config, threads=a.threads)
    env.card_lost_penalty = -a.card_lost
    seats = [Seat() for _ in range(env.n_slots)]
    obs = env.observe()
    pool = load_pool(out, a.device)
    gen = Generation(a.device) if a.generations else None
    # --solo: no generation opponents, but the same measures as every run (head to head with
    # the current best, from your positions, the library lobby of seats 5-7 with the best in the
    # others), so solo runs compare with the office's and advisor.promote reads their best.pt
    judge = gen or (Generation(a.device) if a.solo else None)
    lib_eval_config = train_config
    if a.solo:
        from advisor import library
        lib_eval_config = {**CONFIG, "library": library.library([5, 6, 7], strength=a.library_strength,
                                                                comps=a.library_comps)}
    starts = RealStarts(a.real_starts, a.seed + it0, log=log, comp_share=a.comp_starts,
                        rounds=a.real_rounds, split=a.real_split) if a.real_starts else None
    real_base = (None, None)  # evaluate_real of the best itself, per best and starts file
    best_h2h = ck.get("best_h2h", 4.5) if a.resume else 4.5  # place vs the best (generations)
    # The anchor fades from where it was first applied, across restarts
    anchor_from = (ck.get("anchor_from") if a.resume else None) or it0 + a.critic_warmup
    log({"start": a.run, "params": sum(p.numel() for p in net.parameters()), "device": a.device,
         "iteration": it0, "slots": env.n_slots})
    # --library-adaptive: the learner's warband (seat 0's Attack+Health) by round, recent games
    import collections
    learner = collections.defaultdict(lambda: collections.deque(maxlen=3000))
    if it0 == 0:
        log({"iteration": 0, "eval": evaluate(net, a.device, a.eval_episodes, threads=a.threads)})
    # --overlap: the next batch, collected while the update runs (a future, by `actor`, a copy of
    # the weights before the update); None when nothing is collected ahead
    ahead, actor, stream, behind = None, None, None, None
    if a.overlap:
        from concurrent.futures import ThreadPoolExecutor
        behind = ThreadPoolExecutor(1)
        actor = make(net.config).to(a.device)
        actor.eval()
        stream = torch.cuda.Stream() if a.device.startswith("cuda") else None
    it = it0
    while budget == 0 or time.time() - t0 < budget:
        wait_while_playing(log)
        it += 1
        ts = time.time()
        recalibrate = (a.library_adaptive and it % a.adaptive_every == 0
                       and sum(len(x) for x in learner.values()) >= 1000)
        if a.library and (library.BOARDS.stat().st_mtime_ns != lib_version or recalibrate):
            # New real warbands (the home sync uploads them after you play), or the adaptive
            # library's new curve: new games with them (a batch collected ahead on the old games
            # is dropped)
            if ahead is not None:
                ahead.result()
                ahead = None
            lib_version = library.BOARDS.stat().st_mtime_ns
            if recalibrate:
                lib_curve = library.adaptive_curve(learner, a.library_adaptive, base_curve)
                log({"adaptive": {r: round(v) for r, v in lib_curve.items()},
                     "learner": {r: round(float(np.median(x))) for r, x in sorted(learner.items()) if len(x) >= 50}})
            train_config = lib_config(lib_curve)
            env = BatchEnv(a.games, seed=a.seed * 1_000_003 + it, controlled=controlled,
                           config=train_config, threads=a.threads)
            env.card_lost_penalty = -a.card_lost
            seats = [Seat() for _ in range(env.n_slots)]
            obs = env.observe()
            log({"library": len(train_config["library"]["boards"])})
        if judge and judge.refresh(log):
            best_h2h = 4.5  # a new generation: the record against the old best is void
        opponents = gen.assign(env, it, pool) if gen else ({} if a.solo else assign_opponents(env, pool, it))
        if ahead is not None:
            obs, placements, collect_s = ahead.result()
            ahead = None
        else:
            if starts is not None:
                starts.refresh()
            obs, placements, collect_s = collect_behind(None, None, env, net, obs, seats, a.transitions, a.device,
                                                        opponents, starts, explore=a.explore,
                                                        random_hero=a.random_hero, amp=a.amp_collect,
                                                        explore_tribe=a.explore_tribe)
        for i in opponents:  # a seat that changes hands starts its trajectory anew
            seats[i].items = []
        if a.library_adaptive:  # one look at each game's seat 0, wherever it is
            for gi in range(env.n_games):
                v = json.loads(env.game(gi).view(0))
                if v["me"]["alive"] and v["turn"] and v["me"]["board"]:
                    learner[v["turn"]].append(sum(m["atk"] + m["hp"] for m in v["me"]["board"]))
        batch = advantages(seats, a.gamma, a.lam)
        sil_added = gsil.add(batch) if gsil is not None else 0
        tc = time.time()
        if a.overlap:  # the next batch, by the weights before this update
            if starts is not None:
                starts.refresh()
            actor.load_state_dict(net.state_dict())
            copied = None
            if stream is not None:
                copied = torch.cuda.Event()
                copied.record()
            ahead = behind.submit(collect_behind, stream, copied, env, actor, obs, seats, a.transitions, a.device,
                                  opponents, starts, explore=a.explore, random_hero=a.random_hero,
                                  amp=a.amp_collect, explore_tribe=a.explore_tribe)
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
        stats = update(net, opt, batch, a.device, epochs=a.epochs, minibatch=a.minibatch, ent=a.ent, amp=a.amp, value_only=warm,
                       anchor=step_anchor, anchor_coef=coef, search=sbuf, search_coef=a.search_coef,
                       prior=prior, prior_coef=a.trinket_prior, chunk=a.chunk,
                       human=hbuf, human_coef=a.human_coef, sil=a.explore_sil,
                       games_sil=gsil, games_sil_coef=a.sil_games)
        if sbuf is not None:
            stats["search_buffer"] = len(sbuf)
            if sbuf.drop_idle:
                stats["search_dropped"] = sbuf.dropped
        if warm:
            stats["critic_warmup"] = True
        net.eval()
        stats["mix"] = action_mix([b[0][3] for b in batch])
        row = {"iteration": it, "batch": len(batch), "episodes": len(placements),
               "place": round(float(np.mean(placements)), 3) if placements else None,
               "collect_s": round(collect_s, 1), "update_s": round(time.time() - tc, 1),
               "decisions_per_s": round(len(batch) / max(1e-6, collect_s)), **stats}
        if gsil is not None:
            row["sil_games_added"], row["sil_games_buffer"] = sil_added, gsil.n
        if a.explore_tribe:
            row["tribe_forced"] = getattr(env, "_tribe_forced", 0)
            env._tribe_forced = 0
        if a.overlap:  # what the update waited for the batch (the rest of collect_s ran beside it)
            row["wait_s"] = round(tc - ts, 1)
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
            if judge and judge.best is not None:
                gen_e = judge
                vs = evaluate_league(net, [gen_e.best], a.device, a.eval_episodes, threads=a.threads)
                vs.pop("pool", None)
                row["vs_best"] = vs
                if heval is not None and len(heval):
                    row["human_agree"] = human_agreement(net, heval, a.device)
                if starts is not None and starts.real:  # the player's own positions
                    if real_base[0] != (gen_e.version, starts.version):
                        real_base = ((gen_e.version, starts.version),
                                     evaluate_real(gen_e.best, gen_e.best, starts.real, a.device,
                                                   threads=a.threads))
                    vr = evaluate_real(net, gen_e.best, starts.real, a.device, threads=a.threads)
                    row["vs_best_real"] = {**vr, "best": real_base[1]["mean_place"]}
                if a.library:  # one seat against the best and real warbands: closest to a lobby
                    vl = evaluate_league(net, [gen_e.best], a.device, a.eval_episodes,
                                         threads=a.threads, config=lib_eval_config)
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
