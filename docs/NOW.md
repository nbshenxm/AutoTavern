# Now

Short and current: the progress page shows the "Next up" items at the top. The goal is 14k+
MMR (master play); release targets in [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31), the
simulator audit in [AUDIT.md](AUDIT.md).

## Running

- [ ] Office: p37, R3 fine-tuned on the 37.0.2 rules (from 21:17 to Nov 4 14:00), gated against R3 at 01:20 and 07:20

## Next up

- [ ] Late-game case study ([CASE_LATE_GAME.md](CASE_LATE_GAME.md)): you scale one engine 2-3x a round from round 10; R3's turn from your positions ends at 0.76x yours (engine exam), Beasts 0.55x (Lionfish activations 0.6 a turn vs your 3.1)
- [ ] R3's value head prefers your late End Turns in 71% of 62 (value probe), but search scored by it finds nothing (plan search 1.00x, full-turn lookahead 0.98x); forcing Lionfish's Activate: Beasts 1.18x. The network has to learn what engines are worth: choose the training lever (morning)
- [ ] p37 4 h: not better than R3 (+0.06 ± 0.04), engine exam 0.95x; its 10 h gate and exam at ~07:20
- [ ] Patch 37.0.2 is in the simulator ([patches/37.0.2_simulator.md](patches/37.0.2_simulator.md)), home advisor rebuilt (R3 on the new rules); check the readings against your first games on the patch
- [ ] Review ([REVIEW_20261103.md](REVIEW_20261103.md)): our check couldn't see a gain (±0.1 places); the gate (advisor.gate, paired) decides from now on
- [ ] By the gate: R2 beat R1 by 0.14, R3 beat R2 by 0.12; since R3 nothing (big3 786, big3hero, lr3 at 3x the learning rate: all within ±0.05). The plateau is R3's, and not the learning rate
- [ ] The search on the gate works but costs ~16 CPU-minutes a pair at k=2: a precise verdict needs a cheaper search or late positions only
- [ ] Commit to a type and hold cards: on-type buys 35% (you 62-69%), plays 11 a turn (you 7-8)

## Later

- [ ] The fidelity baseline for 37.0.2: your pre-patch logs replay at 88.8% exact on the new rules (93.6% before: Glambot 5/5, Tea Set +3/+3...); reset it on the first post-patch games

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
