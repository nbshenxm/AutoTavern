# Now

Short and current: the progress page shows the first three "Next up" items at the top. Goal: 14k+
MMR (master play). Releases: [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31); training:
[TRAINING_PLAN.md](TRAINING_PLAN.md); simulator: [AUDIT.md](AUDIT.md).

## Running

- [ ] Office: main1, the mainline (the model; experiments branch from it); at 12 h **better than R3 by 0.097 ± 0.020** places (3 seeds, z 4.8)
- [ ] Cluster GPU: comp2, main1 + twice the comps' midgame starts (the late gap is made in rounds 5-9), 12 h to about 00:30
- [ ] Cluster CPUs: does one Upgrade pay for main1 where you could afford one? (it gives Upgrade a probability of 1e-6 or less there)

## Next up

- [ ] main1 at 24 h (about Nov 5 20:00): still climbing past -0.097? Three seeds on the cluster's CPUs
- [ ] comp2 at 4 h (about 16:00) and at its end, against main1 at the same iteration
- [ ] The next method after comp2: a search teacher or a bigger network, chosen on comp2's result

## Later

- [ ] Type commitment (on-type buys 35%, you 62-69%)
- [ ] Training speed: observe only the slots that act (about 4 s of a 72 s iteration); Freeze toggles are 6% of mid/late decisions (15-20% of turns hit the cap of 10; the advice has had none since Oct 31)
- [ ] Bob's Buddy disagreements: 8 combat Hero Powers and 2 trinkets (none in your logs)
- [ ] A Hero Power exam; a rating ladder and league; the full 18M network

## Done (Nov 5)

- [x] Audit, main1 vs R3: its gain is efficiency in R3's own style; levelling, tribe commitment and the engine unchanged (Upgrade probability 1e-6..1e-13 at your positions)

- [x] main1 12 h: -0.097 ± 0.020 against R3 on every suite (your positions -0.10, library -0.10, fresh -0.09)
- [x] Opening rules in realistic lobbies: still worse (+0.18, +0.19); forcing tempo onto R3 is off the queue
- [x] main1 4 h: the first gate pass since R3; act1 at 4 seeds: -0.051 ± 0.017, also better than R3
- [x] main1 faster: bfloat16 collection, 81 → 68 s an iteration (chunk 512 was slower on the office's GPU); `--overlap` dropped (unstable)

## Done (Nov 4)

- [x] Simulator: legality 100% of your decisions, early carry 0.69x -> 0.87x, combats attack by attack 54.9% -> 57.7% (AUDIT.md: about 15 fixes)
- [x] act1 end: even with R3 (-0.05 ± 0.03), late1: worse (+0.19); neither ships
- [x] Training plan: one mainline plus one experiment, the champion ladder on the progress page
