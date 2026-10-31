"""Plan search at advice time: several candidate plans for the turn, each played out on its own
copy of the game, scored by the network's value of where it leaves the player.

The copies only hold what the player knows (`fair_copy`): the other players' warbands are what
the player last saw of them in combat, and the random seed is re-rolled, so a plan can't profit
from the simulator's hidden state (AutoTavern's warning: a search over copies that kept the seed
looked far better than it was). A plan stops at a random step (a Refresh, an offer), as the live
advice does; the value is then taken after that step, one sample of its outcome.
"""

import json
import random

import numpy as np
import taverngym
import torch

from advisor.policy import observe

A_MOVE = 196


def fair_copy(g, p=0, seed=None):
    """A copy of game `g` with only what seat `p` knows: every other warband replaced by the
    one `p` scouted (empty when never seen), and a new random seed."""
    st = json.loads(g.state_json())
    me = st["players"][p]
    scouted = me.get("scouted") or []
    for o, other in enumerate(st["players"]):
        if o == p:
            continue
        seen = scouted[o]["board"] if o < len(scouted) and scouted[o] else []
        other["board"] = seen
        other["hand"] = []
    # The generator's state is {"s": [four 64-bit words]} (xoshiro): new words, a new future
    r = random.Random(seed)
    rng = st.get("rng")
    if isinstance(rng, dict) and isinstance(rng.get("s"), list):
        rng["s"] = [r.getrandbits(64) | 1 for _ in rng["s"]]
    st["seed"] = r.getrandbits(48)
    return taverngym.Game.from_json(json.dumps(st))


@torch.no_grad()
def _policy(net, g, p, mask=None):
    f, c, m = observe(g, p)
    if mask is not None:
        m = m & mask
    logits, value = net(torch.from_numpy(f)[None], torch.from_numpy(c)[None],
                        torch.from_numpy(m)[None])
    return torch.softmax(logits[0], 0).numpy(), float(value[0])


def _no_battlecry(card):
    from advisor.state import CAT, normal_form
    return "BATTLECRY" not in (CAT.get(normal_form(card or "")[0], {}).get("mech") or [])


# Minions whose effect works from the hand and do nothing more on the warband: playing one throws
# its effect away (Flighty Scout summons a copy of itself at Start of Combat while in hand)
HAND_ONLY = {"BG32_330", "BG32_330_G"}


def detour_mask(view, seen):
    """The legal actions minus this plan's detours, or None when there are none: a plan doesn't
    both sell a minion and play the same card (golden or not) from hand, in either order (sell
    the warband's copy and play the hand's, or the other way round: one gold for what the sold
    one had gained), unless the card has a Battlecry to trigger again; and no card that works from
    the hand is played (HAND_ONLY). `seen`: what note_sold recorded."""
    from advisor.policy import L
    sold, played = seen.setdefault("sold", set()), seen.setdefault("played", set())
    hand_only = [h for h, card in enumerate(view["me"]["hand"]) if card.get("id") in HAND_ONLY]
    if not sold and not played and not hand_only:
        return None
    mask = np.array(view["mask"], bool)
    changed = False
    for h in hand_only:  # a card that works from the hand stays there
        lo = L["A_PLAY"] + h * L["N_POS"]
        changed |= bool(mask[lo:lo + L["N_POS"]].any())
        mask[lo:lo + L["N_POS"]] = False
    for h, card in enumerate(view["me"]["hand"]):
        if card.get("id") in sold and _no_battlecry(card.get("id")):
            lo = L["A_PLAY"] + h * L["N_POS"]
            changed |= bool(mask[lo:lo + L["N_POS"]].any())
            mask[lo:lo + L["N_POS"]] = False
    for i, m in enumerate(view["me"]["board"]):
        if m.get("id") in played and mask[L["A_SELL"] + i]:
            mask[L["A_SELL"] + i] = False
            changed = True
    return mask if changed and mask.any() else None


def note_sold(view, a, seen):
    """Record in `seen` the card action `a` sells in `view`, or plays from hand when it has no
    Battlecry."""
    from advisor.policy import L
    me = view["me"]
    if L["A_SELL"] <= a < L["A_SELL"] + L["N_BOARD"] and a - L["A_SELL"] < len(me["board"]):
        seen.setdefault("sold", set()).add(me["board"][a - L["A_SELL"]].get("id"))
    elif L["A_PLAY"] <= a < L["A_MAGNETIZE"]:
        h = (a - L["A_PLAY"]) // L["N_POS"]
        if h < len(me["hand"]) and me["hand"][h].get("type", "minion") == "minion"                 and _no_battlecry(me["hand"][h].get("id")):
            seen.setdefault("played", set()).add(me["hand"][h].get("id"))


def rollout(g, net, p=0, allowed=None, temperature=0.0, rng=None, max_steps=80):
    """One plan on a copy: [actions], the value where it ends. `temperature` 0 is the
    network's most likely action at each step; above 0, sampled (sharpened or flattened).
    No detours (`detour_mask`)."""
    c = g.copy()
    actions, value, sold = [], None, {}
    for step in range(max_steps):
        if not c.needs_action(p):
            break
        view = json.loads(c.view(p))
        mask = detour_mask(view, sold)
        if step == 0 and allowed is not None:
            mask = np.array(allowed) & (mask if mask is not None else True)
        probs, value = _policy(net, c, p, mask)
        if temperature <= 0:
            a = int(probs.argmax())
        else:
            w = probs ** (1.0 / temperature)
            w /= w.sum()
            a = int(rng.choice(len(w), p=w))
        if a == 0:  # End Turn: the value of the warband as it will fight
            actions.append(a)
            break
        before = c.view(p) if not (30 <= a <= 45) else None
        note_sold(view, a, sold)
        c.step(p, a)
        actions.append(a)
        if a == 1 or _opened_offer(before, c.view(p)):
            _, value = _policy(net, c, p)  # one sample of the random outcome
            break
    return actions, value


def _opened_offer(before, after):
    if before is None:
        return False
    pending = json.loads(after)["me"].get("pending") or {}
    return bool(pending) and pending.get("kind") != "target"


def best_plan(g, net, p=0, allowed=None, k=8, temperature=1.0, seed=None):
    """The best of the greedy plan and `k` sampled ones, each on its own fair copy:
    (actions, value, every candidate's (actions, value))."""
    rng = np.random.default_rng(seed)
    candidates = []
    for i in range(k + 1):
        copy = fair_copy(g, p, seed=None if seed is None else seed * 1000 + i)
        candidates.append(rollout(copy, net, p, allowed, 0.0 if i == 0 else temperature, rng))
    seen = {}
    for acts, v in candidates:  # the same plan sampled twice: average its values
        seen.setdefault(tuple(acts), []).append(v if v is not None else -1.0)
    scored = sorted(((float(np.mean(vs)), list(a)) for a, vs in seen.items()), reverse=True)
    best_value, best_actions = scored[0]
    return best_actions, best_value, candidates

