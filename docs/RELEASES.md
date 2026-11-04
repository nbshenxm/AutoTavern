# Releases

One a day at 20:00 (the schedule and targets: [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31)).
Newest first.

## R4 · Nov 3 (shipped 21:05) · tag `bg-r4`

**Strength: unchanged, and now we can say so precisely.** The overlay still runs R3's network
(big3 iteration 510): nothing has beaten it on the new gate. **The rules are patch 37.0.2.**

**The gate (advisor.gate).** The old check (250 games, ±0.1 places) couldn't see a real gain
([REVIEW_20261103.md](REVIEW_20261103.md)). Now both networks play seat 0 of the same games and
seeds (your positions, top-1% lobbies, fresh games), paired, about 2,000-3,400 pairs a verdict.
What it found:

| Comparison | Gain in places (negative = better) | Verdict |
| --- | --- | --- |
| R2 vs R1 | -0.135 ± 0.049 | better |
| R3 vs R2 | -0.121 ± 0.035 | better |
| big3 it 786 vs R3 | -0.013 ± 0.034 | even |
| big3hero it 908 vs R3 | -0.041 ± 0.038 | even (worse in the top-1% lobbies) |
| lr3 4 h (3x learning rate) vs R3 | +0.053 ± 0.040 | not better |

So the releases did improve (about 0.26 places R1 → R3), and the plateau is R3's.

**Patch 37.0.2 in the simulator** ([patches/37.0.2_simulator.md](patches/37.0.2_simulator.md)):
131 cards from the client data (stats, texts, Trinket and spell prices), Murcules back (scripted)
and Expert Aviator out, four Trinkets out of the pool, Weighted Gauntlet a Greater Trinket, Wand of
Divination out of Quilboar lobbies, the new Dark Gift windows and the typed Dark Gift options from
turn 7; the scripts' numbers card by card. The network reads the new stats and texts; what the
changed effects are worth it learns in p37.

**Live fix:** a Discover a Hero Power target (Captain Hooktusk's Trash for Treasure) now ends the
shown plan, instead of going on to the simulator's own pick ("Choose Deadly Spore", which looked
like a misread Headhunter Gryphon).

**Targets:** late >= 0.40 and on-type >= 50%: not met (same network).

**Known faults:** as R3 (the opening Freezes and never levels; late, it over-refreshes and buys
off-type). The readings of the patch text listed in the patch note are to be checked against your
first games on 37.0.2.

**In training for R5:** p37 (office): the gate's pick fine-tuned on the 37.0.2 rules until Nov 4
14:00, gated against R3 at 4 h and 10 h.

## R3 · Nov 2 (shipped 21:10) · tag `bg-r3`

**Strength: a small step; the late game is unchanged.** The overlay runs **big3 iteration 510**
(promoted automatically at 06:53: head to head with R2 4.28, play audit clean). Targets: from
your positions 2.46 (target < 2.45: missed by 0.01), Gold left in rounds 13+ 0.36 (target <= 6:
met), late game 0.20x your lobbies (target 0.30: missed). It refreshes 7.2 times a turn late (you
3.8) and buys on-type 35% of the time late (you 62-69%).

**What changed in the advice: the board it reads is your real one.** A day-long audit of the
simulator (docs/AUDIT.md) found the rules faithful and the rebuild of your positions from the log
wrong in ways that changed what the advice saw:
- Magnetizations: a minion's Satellites, Volumizers and Beatboxer echoes are one enchantment in
  the log and came out as one (Utility Drone engines grew 0.42x the real amount; Robot, Beatboxer,
  Reveille now within 0-18%).
- Counters never read: the Volumizer bonus, the Deity and its size, Easterly Winds, Blood Gems,
  improve-this cards (Spark Snapper, Ultraviolet Ascendant, Wrathguard, Leviathan, Patient Scout,
  Rogers), Wax Warband's size.
- Temporary Attack (Vol'jin's swap) rebuilt as permanent; armed Hero Powers (Y'Shaarj, Rafaam),
  Lock and Load's minion and an activated Living Prison now read from the turn's earlier
  decisions.
- One simulator rule: the Sacrifice Dark Gifts could buff their own host.

**What changed in the checks:** `advisor.fidelity` runs every audit against a baseline after each
game and fails on a drop: one action 93.8%, whole turns 86.3%, transitions 99.4%, combats
calibrated within +2.8 SD (fixes took it from +3.1), over the turn change 0.70/1.06/0.88x by round,
Bob's Buddy agreement on random warbands 0.047. Bob's Buddy is the second opinion; every strong
disagreement checked against your logs so far favoured TavernGym.

**Known faults:** the opening Freezes far more than you and never levels (rounds 2-6: 0.6-0.7
Freezes a turn, you 0.1; Upgrades 0, you 0.55); late, it over-refreshes and buys off-type.

**In training for R4:** big3open (office: the early lobby at your lobbies' strength; after 4.5 h
its rounds 4-6 Freezes fell 0.71 -> 0.26 a turn, Refreshes 0.88 -> 0.55; still no early
Upgrades) and big3ad (cluster: the adaptive late lobby).

## R2 · Nov 1 (shipped 17:40) · tag `bg-r2`

**Strength: the first network to beat the 18:21 one.** The overlay now runs **big3 iteration
180**: a network 10x larger (d384, 8 layers), distilled from solo1 and trained AutoTavern's way
(alone against seven top-1% library seats, placement reward). Head to head with the old best
4.35 (confirmed 4.28 on fresh seeds; 4.5 = even); against plain bots 1.38 (old 1.42).

| | Old best (big2 it 70) | big3 it 180 | You |
| --- | --- | --- | --- |
| From your positions (mean place) | 2.44 | 2.36 | |
| Rounds 13+: Refreshes per turn | 0.5 | 4.24 | 3.79 |
| Rounds 13+: Freeze per turn | 1.5 | 0.18 | 0.09 |
| Rounds 13+: Gold left at End | 9.2 | 1.85 | 4.70 |
| Rounds 10+: on-type minion buys | 40% | 48.5% | 66% |
| Plans ending with 3+ spendable Gold (your positions) | 28% | 0% | |
| Late game (rounds 10-13, self-play warband vs your lobbies) | 0.19x | 0.19x | |

**R2 targets:** from your positions < 2.50: met (2.36). Late game >= 0.25x: missed (0.19x; this
number is from games against copies of itself).

**Advice:** without the plan search now (it plays no better than the network: the teacher test),
0.3 s an advice instead of 2 s with the larger network; the close second comes from the
network's own probabilities.

**Promoted by hand, with your approval,** over two play-audit flags in self-play: moves are 19%
of its actions (old 10%; capped at 7 a turn, no long Arrange steps in its plans) and 0.8 cards a
game lost to a full hand (old 0.1; mostly activating a card-making minion with 9-10 cards).

**Known faults:** the cards lost to a full hand (next: a cost for them in training); its own
self-play warbands still small late (the 0.19x).

**Found and fixed on the way:** solo1 and emb1 learned a reward hack (play a targeted card,
Cancel, repeat until the action cap ended the turn without its wasted-Gold cost): Cancel is now
excluded while anything else is legal; the teacher test found no search better than the network.

## R1 · Oct 31 (shipped 18:40, before the PC was shut down) · tag `bg-r1`

**Strength: unchanged.** The overlay still runs big2 iteration 70 (promoted Oct 30 18:21): late
game 0.19x your lobbies (rounds 10-13), from your positions 2.56, Gold left in rounds 13+ 9.2,
on-type minion buys 40%. Every R2 target misses today.

**What changed in the advice and overlay:**
- The next step only, and a second one after "或" when the search scores it within 0.03.
- The round-6 trinket offer reaches the advice (it never did); trinkets ranked like heroes:
  public placement 0.7, the network's estimate 0.3 (it picked the worst one alone 3 times in 4).
- Workers of home jobs pause within 15 s when you start Hearthstone (a search batch had slowed
  the advice to 17 s in one game).

**What changed in the checks:**
- The Gold-left check works (it read the state after End Turn and never fired): 228 plans in
  your games end with 3+ spendable Gold, 218 in rounds 11-15. No rule broken.
- The simulator check runs again (a broken line had stopped it after every game since Oct 30);
  a Magnetic card dropped on a Mech replays as Magnetize (whole turns 85.2 → 86.5%).
- Trinkets checked against your games one by one: all scripted, none wrong found.

**Known faults:** late turns end with Gold left and Freeze; minion buys mostly off your
warband's type; trinket counters and other card counters only reach networks trained with
observation version 4 (none in the overlay yet).

**In training for R2:** solo1 (cluster, AutoTavern's setup), emb1 vs sig1 (office), the teacher
test (cluster).
