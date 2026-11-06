# Now

Short and current: the progress page shows the first three "Next up" items at the top. Goal: 14k+
MMR (master play). Releases: [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31); training:
[TRAINING_PLAN.md](TRAINING_PLAN.md); simulator: [AUDIT.md](AUDIT.md).

## Running

- [ ] Office: main1, the mainline (the model; experiments branch from it); at 12 h **better than R3 by 0.097 ± 0.020** places (3 seeds, z 4.8)
- [ ] Cluster GPU: spec1, the mid/late specialist (every game from your rounds 6+ positions, 13 training games), days; judged on your 8 held-out games; 72 s an iteration since 12:00 (155 before: faster loading of your positions)

## Next up

- [ ] spec1 at it 2601 (queued on the cluster from 19:15; the audit by about 21:00, the gate overnight): held-out games only, vs main1 at the same iteration (mid and engine exams, scaling share, real suite)

## Later

- [ ] Type commitment (on-type buys 35%, you 62-69%)
- [ ] Training speed: observe only the slots that act (about 4 s of a 72 s iteration); Freeze toggles are 6% of mid/late decisions (15-20% of turns hit the cap of 10; the advice has had none since Oct 31)
- [ ] Bob's Buddy disagreements: 8 combat Hero Powers and 2 trinkets (none in your logs)
- [ ] A Hero Power exam; a rating ladder and league

## Done (Nov 6)

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
