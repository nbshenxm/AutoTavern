# Now

Short and current: the progress page shows the first three "Next up" items at the top. Goal: 14k+
MMR (master play). Releases: [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31); training:
[TRAINING_PLAN.md](TRAINING_PLAN.md); simulator: [AUDIT.md](AUDIT.md).

## Running

- [ ] Office: **plan2**, plan-conditioned training with the plan marked on its tribe's cards (moved from the cluster at it 4498): at it 4450 **the plans became real** (planned seats build their tribe: 2.06 vs 1.47 minions at round 8, and place no worse)
- [ ] Office: the rest of the R7 audit (habits, buys, value probe), after **the clean gate passed: main1 it 5200 vs R6 -0.194 ± 0.033** and the audit -0.200 ± 0.076 (gain in rounds 6-9)
- [ ] main1 paused at it 5833 (your OK): its snapshots cover plan2's comparisons

## Next up

- [ ] R7 (main1 it 5200) to the advisor, with your OK, once the audit's last steps are in
- [ ] plan2 vs main1 at the same iteration: gate and audit with the picker (office)

## Later

- [ ] Type commitment (on-type buys 35%, you 62-69%)
- [ ] Training speed: observe only the slots that act (about 4 s of a 72 s iteration); Freeze toggles are 6% of mid/late decisions (15-20% of turns hit the cap of 10; the advice has had none since Oct 31)
- [ ] Bob's Buddy disagreements: 8 combat Hero Powers and 2 trinkets (none in your logs)
- [ ] A Hero Power exam; a rating ladder and league

## Done (Nov 9)

- [x] Data bug found and fixed: since Nov 8 20:20 the office's top-1% hero stats had no warband curve (a bad Firestone download), so the library opponents weren't scaled and there were no comp starts (training place 4.5 -> 3.2). The download now keeps the last good copy; training and gates refuse to run without the curve. main1's last 633 iterations (5200-5833) were trained on it
- [x] plan2 at 850 iterations: **the plans became real** (planned seats build their tribe: 2.06 vs 1.47 minions at round 8, place no worse); moved to the office (main1 paused, your OK)

## Done (Nov 8)

- [x] The Freeze test (partial, 387 frozen turns): R6's Freeze habit neither pays nor costs (+0.10 ± 0.09 places): no Freeze guardrail
- [x] plan1 at 1,000 iterations: **the plans weren't followed** (11.8% vs 12.8% unplanned), level with main1 on your positions (audit -0.18 ± 0.12, gate -0.00 ± 0.08), worse on the library (+0.19 ± 0.07): stopped for plan2 (your OK)
- [x] Plan picker fix: it compares each plan's value plus its potential (the shaping makes the learned value the return less it); advisor.plan_check written

## Done (Nov 7)

- [x] spec1 stopped (no gain at 8 h and 24 h); the disagreement audit: one decision at a time R6 is as good as you under its own follow-through: the gap is a local optimum (your committed style), so plan1

- [x] Advice guardrails (live.Waste), from the mistake audit and your logs: no buff on a Tavern minion it then refreshes away or leaves (3-4% of turns), no buff on a minion it then sells (up to 2.4%), no Freeze undone by a Refresh; 1% of plans change, each as intended (from the advisor's next start)

## Done (Nov 6)

- [x] **R6 released (your OK): main1 it 1400 is the advisor's network** (-0.182 ± 0.020 vs R3); the runs keep R3 as their opponent (the advisor's file is now apart: data/models/advisor.pt on the office)

- [x] Your report: the advice buffed a Tavern minion it couldn't buy (Suspicious Prisonguard on a Mechagnome Interpreter at 1 gold). The client allows Tavern targets, but the network weighs them like warband ones (41% vs 40%; main1 29%) and you never use them (0 of 11). The plan now re-plans a buff on a Tavern minion it neither buys nor freezes (from the next advisor start)

- [x] wide1 (twice the feed-forward width) vs main1 at the same iteration: **a tie** (audit -0.008 ± 0.075; gate +0.048 ± 0.035), scaling and the exams the same: capacity isn't the limit; spec1 stays narrow
- [x] spec1 3x faster loading of your positions: 155 -> 72 s an iteration

## Done (Nov 5)

- [x] main1 at 22 h: -0.189 ± 0.024 vs R3 (still climbing); keeping the tribe forced on it: worse in every lobby (+0.30..+0.45); the lessons of every run written into the plan (no more variants of failed ideas)
- [x] Buy audit: offered an on-tribe minion in rounds 7-9, main1 takes it 35% of the time (you 72%, R3 44%) and sells on-tribe ones more: it doesn't value the synergy
- [x] comp2 (twice the comps' midgame starts): worse than main1 (+0.133 ± 0.043), scaling unchanged; stopped for wide1
- [x] Why main1 doesn't move toward your play: one Upgrade pays it in no lobby (+0.05..+0.14), and its value head is right about it (your mid-game End Turn ends no better under its play-on). The gap is its own mid-game play: what it buys and keeps in rounds 5-9
- [x] Audit, main1 vs R3: its gain is efficiency in R3's own style; levelling, tribe commitment and the engine unchanged (Upgrade probability 1e-6..1e-13 at your positions)

- [x] main1 12 h: -0.097 ± 0.020 against R3 on every suite (your positions -0.10, library -0.10, fresh -0.09)
- [x] Opening rules in realistic lobbies: still worse (+0.18, +0.19); forcing tempo onto R3 is off the queue
- [x] main1 4 h: the first gate pass since R3; act1 at 4 seeds: -0.051 ± 0.017, also better than R3
- [x] main1 faster: bfloat16 collection, 81 → 68 s an iteration (chunk 512 was slower on the office's GPU); `--overlap` dropped (unstable)

## Done (Nov 4)

- [x] Simulator: legality 100% of your decisions, early carry 0.69x -> 0.87x, combats attack by attack 54.9% -> 57.7% (AUDIT.md: about 15 fixes)
- [x] act1 end: even with R3 (-0.05 ± 0.03), late1: worse (+0.19); neither ships
- [x] Training plan: one mainline plus one experiment, the champion ladder on the progress page
