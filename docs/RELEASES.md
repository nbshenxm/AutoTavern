# Releases

Only when a network passes the gate against the champion (from Nov 4; before, one a day at 20:00:
[ROADMAP.md](ROADMAP.md#releases-from-2026-10-31)).
Newest first.

## R6, Nov 6: main1 it 1400 (gate pass) + the Tavern-buff guardrail

**The network:** main1 at iteration 1400, the mainline (R3's setup trained continuously since
Nov 4 19:54). Against R3 (big3 it 510) in advisor.gate: **-0.182 ± 0.020 places** (10,530 pairs,
3 seeds, each round passing); from your own logged positions about -0.09 ± 0.03. Most of its gain
is in rounds 1-5; its mid-game exams (mid_exam, engine_exam) are level with R3's, so don't expect
better scaling in the late game yet (that is spec1's job, docs/TRAINING_PLAN.md). Checked in the
live advisor on a recorded game: 60 decisions, median 133 ms an advice. Released with your OK
(Nov 6, 21:30) ahead of the "major breakthrough" rule: strictly better than what you had.

**The advice:** a plan no longer buffs a minion in the Tavern that it then neither buys nor keeps
with Freeze (your report: Suspicious Prisonguard on a Mechagnome Interpreter at 1 gold). Takes
effect at the advisor's next start (the network itself reloads by itself).

**Kept apart from training:** the advisor's network is now data/models/advisor.pt on the office
(synced home as data/models/best.pt); the office's and the cluster's data/models/best.pt stay R3,
the opponent main1 and spec1 train against (their setup unchanged). For a few minutes tonight the
promotion had replaced that too: main1 trained 8 iterations (2829-2836) and spec1 about 1 against
R6 before R3 was restored.

**Known faults:** the mid-game scaling gap (your boards grow ~2x a round in rounds 8-12, the
network's ~1.4x); other wasted plays like tonight's are being counted across your logged games
(the mistake audit) and get guardrails next.

## Nov 4: no release (no gate pass)

**From Nov 4 a release is a network that passes the gate against the champion; nothing else is
called one.** R4 and R5 would have shipped R3's network again: they changed the simulator, not the
strength. Since R3 (Nov 2) 8 candidates went through the gate: none better. What changed today, as a
changelog:

**The gate since R4** (paired, negative = better):

| Candidate vs R3 | Gain in places | Verdict |
| --- | --- | --- |
| p37 10 h (fine-tuned on the 37.0.2 rules) | -0.046 ± 0.036 | inconclusive |
| act1 4 h (forced Activates in exploration) | -0.053 ± 0.035 | even |
| late1 4 h (your late turns as a teacher) | +0.191 ± 0.052 | worse, though it agreed with your held-out turns 4x more |

late1's result changed the training plan (TRAINING_PLAN.md, Nov 4 14:30): one continuous
mainline on the office from tonight (R3's setup on the rebuilt simulator), one experiment at a time
on the cluster (mid1: your round 5-8 turns), each with its bar set first. The progress page shows
the champion ladder (docs/ladder.json).

**The simulator: what the advice sees is closer to your game.** Found by the new checks, fixed
since R4 (docs/AUDIT.md):
- From your logs: after a reconnect a game's earlier combats were lost (the player's id changes):
  459 decisions in 4 games rebuilt with no combat history, the live advisor too. Rebuilt Volumizers
  lost 3 Attack at the next re-sync. Winner's Bread's and Overconfidence's waiting part, Warcry
  Totem's spent free buys, Incubation's turns, the turn's play counters (Elementals, spells...),
  next-combat spells cast earlier in the turn (Brood of Nozdormu, Upper Hand), Battlecruiser
  Upgrades, the lobby's Deity: now read.
- Rules: Arcane Absorption rounds the half up; a dying Rally attacker triggers every Deathstrider;
  Sharing is Caring hits the enemy across from it (centred boards); Brood of Nozdormu sets Attack;
  "whenever you summon" before "after you summon"; library seats fight with their hero, Hero Powers
  and trinkets.
- From your Nov 4 games: Drek'Thar's / Vanndar's copy comes in just right of the minion it copies
  (it was summoned at the end); the game's Tavern spells cast are read from Faceless Converter (an
  opponent's C'Thun fought at 1823/913 where the log had 2303/1153).
- The overlay says when the lineup's stats are after the plan (a planned Prisonguard Activate showed
  your Roaring Recruiter 5/11 while it was 2/8 on your board).
- The live advisor's plans no longer count Warcry Totem's free buys you already spent this turn;
  the legality check no longer counts a capped hand card's second client option as a play (both
  games with gaps now match the client on every decision).

**Against your logs** (5,144 decisions, 258 combats; advisor.fidelity): the legal actions identical
to the client's in 100.0% of decisions (97.6% this morning); single actions 90.8%, whole turns 85.3%
(what's left: random targets, Discovers and pre-patch games on 37.0.2 rules); warband growth over
combat and the turn change 0.87x / 1.07x / 1.00x by round band (rounds 1-6: 0.69x this morning);
Bob's Buddy 0.040 on random warbands.

**New checks:** the attack-by-attack replay (each logged combat with the logged targets forced:
57.7% of combats exact, the rest random recipients so far), the effect audit (480 full
games, every off-text stat change explained), Bob's Buddy on the current build (0.019 mean
difference on random warbands; its card data predates 37.0.2), 113 card tests for the pool cards no
audit reached, and the exams from your positions (mid-game, late-game, value probe).

**Targets:** late >= 0.50: not met (same network). Your games: 5+ played with it, measured: 2 games
since R4 (not enough to measure).

**Known faults:** as R3 (the opening Freezes and never levels; late, it over-refreshes and buys
off-type). The case study puts the late gap in the mid-game (R3 0.28x you three rounds on from
rounds 6-9): that is what main1 and mid1 train on.

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
