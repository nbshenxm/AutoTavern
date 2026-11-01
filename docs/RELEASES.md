# Releases

One a day at 20:00 (the schedule and targets: [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31)).
Newest first.

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
