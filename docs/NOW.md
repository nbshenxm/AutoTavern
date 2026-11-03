# Now

Short and current: the progress page shows the "Next up" items at the top. The goal is 14k+
MMR (master play); release targets in [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31), the
simulator audit in [AUDIT.md](AUDIT.md).

## Running

- [ ] Office: lr3, R3 at 3x the learning rate (one change, old rules); the gate against R3 at 15:12 and 19:00 decides
- [ ] Office, after lr3's gates (~19:40): rebuild for 37.0.2, then p37 (the gate's pick fine-tuned on the new rules, to Nov 4 14:00), gated against R3 at 4 h and 10 h (data/gate/after_lr3.sh)

## Next up

- [ ] Patch 37.0.2 is in the simulator ([patches/37.0.2_simulator.md](patches/37.0.2_simulator.md)); rebuild the home advisor (close it first) and check the readings against your first games on the patch
- [ ] Review ([REVIEW_20261103.md](REVIEW_20261103.md)): our check couldn't see a gain (±0.1 places); the gate (advisor.gate, paired) decides from now on
- [ ] By the gate: R2 beat R1 by 0.14, R3 beat R2 by 0.12; since R3 nothing (big3 786 +0.01, big3hero +0.04, both inconclusive). The plateau is R3's
- [ ] The search on the gate works but costs ~16 CPU-minutes a pair at k=2: a precise verdict needs a cheaper search or late positions only
- [ ] Commit to a type and hold cards: on-type buys 35% (you 62-69%), plays 11 a turn (you 7-8)

## Later

- [ ] A Hero Power exam: per hero, use rate against yours and whether using it more pays

- [ ] R4 (Nov 3): late >= 0.40x, on-type buys >= 50%
- [ ] A rating ladder and a league of strong networks (the bar beyond Firestone's top 1%)
- [ ] Your winning games as a training signal (a milestone, not the ceiling)
- [ ] The full 18M network AutoTavern used (big3 is d384 x 8 layers)

## Done (Nov 2)

- [x] R3 shipped: big3 iteration 510 and the audited rebuild of your positions
- [x] Simulator audit: rules faithful; 15+ rebuild bugs fixed; a standing check after every game
- [x] Positioning exam: the network is even with you (0.048 below the best order, you 0.046)
- [x] Live plan: stops at the Discover a Hero Power opens (it showed its own pick, "Deadly Spore", as if it misread your Gryphon)
