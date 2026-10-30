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
3. **Comp starts** (next): training games where your seat starts a comp's midgame (its stage
   cards, the matching tribes in the lobby): Beatboxer magnetizing, Undead attack counts,
   triples on buffed cards practised where they matter.
4. **Pattern checks on every checkpoint** (next): the measurements above, on the progress page,
   so a checkpoint that learns (or unlearns) a pattern shows.
5. **Search where it pays**: plan search already finds better turns than the network alone
   (0.48 places); a Refresh lookahead was tried and didn't change how often plans refresh
   (15 of 30 late positions either way) while doubling latency: not used.
6. **Larger network** (running): 8.6M parameters, for the longer, order-dependent late turns.

## Audit: what is checked, and what was found

| Check | Result | Found and fixed |
| --- | --- | --- |
| Legal actions vs the client's options (2,651 decisions) | 95.9% identical; TavernGym never allows what the client refuses | Bile Spitter playable at a full warband in one game (unexplained, left); discounted Tavern spells priced at base (fix needs a rebuild) |
| One action at a time (advisor.recruit_diff, 1,550 actions) | 94.5% exact | player bonuses, minion counters |
| Whole turns (advisor.turn_replay, 182 turns) | 84.6% never part from the log | free trinket offers charged; Faelin's locked hand never unlocks (to fix) |
| Combat replay (149 combats) | 0.88 mean probability of the logged result | first attacker, Start of Combat order, Dark Gifts |
| Live advice | — | Activate offered twice in a turn; sell-and-replay detours; no hero advice |

Next audits: the turn transition (end of turn, combat and the next turn's start against the log:
gold income, end-of-turn effects, Tavern refill); the remaining warband-stat drifts in whole
turns (Air/Fire Baller, Snarky Shark, Hoarding Hyena, Misplaced Tea Set, Mind Muck); Lurking
Lionfish's Activate; opponents' trinket and hero power counters (observation version 4).
