# Playing like a strong player: the plan

Two streams, run side by side: **audit** (the simulator and the bridge against your real games,
so training learns the real game) and **learning** (what the network must learn to grow above
linear in the late game). Each item has a measurement; results go to EXPERIMENTS.md.

## What the network gets wrong (your observations, 2026-10-30)

| Pattern | What a strong player does | Measured how |
| --- | --- | --- |
| Late game, warband in place | Refreshes to find the few cards that strengthen it; doesn't buy whatever is there | late turns (round 9+) with a full warband: Refreshes per turn, buys sold again the same or next turn |
| Polarizing Beatboxer | Magnetizes onto *another* minion (both get it), never onto the Beatboxer | positions with a Beatboxer and a Magnetic card: share magnetized onto another minion |
| Triples | Brings a buffed card back through a triple so it is buffed again | golden minions made from buffed copies, per game |
| Hand limit 10 | Orders plays so that incoming cards aren't lost | cards lost to a full hand, per game (TavernGym counter, to add) |
| Economy turns | Uses gold engines to refresh, buy, play and sell many times in one turn; the order decides the outcome | actions per late turn, gold generated and spent |
| Scaling | Grows the warband faster than linear from round 10 | advisor.continue_test: warband vs the player's from real round-10 positions |
| Opponents | Reads the next opponent's build and answers it (Venomous vs big stats, 火车王, Divine Shield) | library-seat games: buys of answer cards when the next opponent shows the matching build |

## Learning: how each is taught

1. **Strong, readable opponents** (running, `big2`): library seats that follow one real player
   or one of 19 curated comps all game, at the top 1%'s strength. Junk buys lose to them; only
   real scaling wins. The same opponents in the search games.
2. **Real starts** (running): 30% of training games start from your logged round starts (72%
   from round 8 on), so the network plays real late games.
3. **Comp starts** (running since 20:35, `big2 --comp-starts 0.33`): a third of the real-start
   games put your seat in one of 95 comp midgames (19 comps x rounds 6-10: the comp's warband at
   top 1% strength, its Tier, the round's Gold, its tribes in the lobby, real warbands around).
4. **Pattern checks** (`advisor.patterns`, run by the home sync on each new network, shown on
   the progress page). First numbers: the Beatboxer check (share of the magnetizing probability
   onto another Mech; random 75%): 05:23 network 96%, 12:20 76%, today's best 79% - the pattern
   was learned once and lost in self-play. Late turns from your positions (per turn): today's
   best 1.6 Refreshes, 2.5 buys, 0.05 buys sold again (12:20: 1.3, 2.3, 0.23). Cards lost to a
   full hand: counted from the next rebuild.
5. **Your own choices** (running since 20:55, `big2 --human-data`): your 1,912 logged recruit
   decisions as a small imitation target beside PPO (two games held out for testing). Today's
   best agrees with 11% of them; where you refreshed (16.8% of your decisions) it refreshes in
   none (0.5% of its first choices are Refreshes). The held-out agreement is logged at every test.
   The home sync rebuilds them after you play.
6. **Search where it pays**: plan search already finds better turns than the network alone
   (0.48 places); a Refresh lookahead was tried and didn't change how often plans refresh
   (15 of 30 late positions either way) while doubling latency: not used.
7. **Larger network** (running): 8.6M parameters, for the longer, order-dependent late turns.

## Promotion: not on training numbers alone

A network that passes the training gates (head to head, real positions, library lobbies) must also
pass the **play audit** (`advisor.audit_play`) against the current best before it reaches your
overlay: its live advice (with plan search) at your logged round starts, and complete games with it
in every seat. It fails on any of: first steps the client wouldn't allow, sell-and-replay detours,
ending the turn with 3+ Gold that could still buy or refresh, Freeze toggling, long Arrange runs,
overlong plans, stalled games, more moves or Freeze presses than the best, cards lost to a full
hand, Gold left at End Turn. Sample plans are kept in the promotion log for reading. First
reading: today's best and its predecessor both spend 7.8% of their self-play actions on Freeze
(the old dodge of the wasted-gold cost, closed this afternoon): the audit holds it from growing.

## Genres

The 19 comps are a starting point, not the list: the network should learn every genre and find
new ones. Switching is not a goal: it is rare, mostly from a survival warband into a high-ceiling
one when its pieces come (more aggressive at high MMR); survive first. Real starts teach that
(your midgames in real lobbies); comp starts teach each engine. `advisor.genres` scores the
network per comp (warband growth from the comp's midgame against the top 1%, core-card buys).

## Audit: what is checked, and what was found

| Check | Result | Found and fixed |
| --- | --- | --- |
| Legal actions vs the client's options (2,651 decisions) | 95.9% identical; TavernGym never allows what the client refuses | Bile Spitter playable at a full warband in one game (unexplained, left); discounted Tavern spells priced at base (fixed) |
| One action at a time (advisor.recruit_diff, 1,550 actions) | 94.5% exact | player bonuses, minion counters |
| Whole turns (advisor.turn_replay, 182 turns) | 84.6% never part from the log; the rest random draws (Dark Gift offers, Fishbait Taverns, Tea Set's random minions) | free trinket offers charged; Faelin's held minions never released; Baller improvements dropped (a Baller sold at round 14 gave +2/+2, the game +14/+14) |
| Turn transitions (advisor.transition_check, 126) | the rest: the stand-ins' trinket pick at rounds 6 and 9, combat outcomes | maximum Gold bonuses dropped (16 transitions a Gold or two short) |
| Combat replay (149 combats) | 0.88 mean probability of the logged result | first attacker, Start of Combat order, Dark Gifts |
| Live advice | — | Activate offered twice in a turn; sell-and-replay detours; no hero advice |

Most of these were in the bridge (the rebuilt state), not in TavernGym's rules: training games
are TavernGym's own, but the real starts and the live advice go through the bridge, so each fix
reaches both. Next audits: combat effects that last (warband stats after combat against the
log's, with the logged opponent's warband instead of a stand-in); opponents' trinket and hero
power counters (observation version 4); the turn replay for Tavern targets (Mind Muck) and
warband order.
