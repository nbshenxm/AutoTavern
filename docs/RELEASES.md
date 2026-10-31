# Releases

One a day at 20:00 (the schedule and targets: [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31)).
Newest first.

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
