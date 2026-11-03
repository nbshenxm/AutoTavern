# Now

Short and current: the progress page shows the "Next up" items at the top. The goal is 14k+
MMR (master play); release targets in [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31), the
simulator audit in [AUDIT.md](AUDIT.md).

## Running

- [ ] Office: big3hero, random hero deals + Hero Power exploration (until Nov 3 16:00; the network never picked 48 of 116 heroes)
- [ ] Office: the gate on the past releases, R2 vs R1, R3 vs R2, big3hero vs R3: did we improve, and by how much?

## Next up

- [ ] Review ([REVIEW_20261103.md](REVIEW_20261103.md)): our check couldn't see a gain (±0.1 places); the gate (advisor.gate, paired) decides from now on
- [ ] What the past releases were worth, by the gate; then the next lever chosen by it (longer fixed runs, learning rate, play-time search: each a gate)
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
