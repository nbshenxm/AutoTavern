# Now

Short and current: the progress page shows the "Next up" items at the top. The goal is 14k+
MMR (master play); release targets in [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31), the
simulator audit in [AUDIT.md](AUDIT.md).

## Running

- [ ] Office: act1, R3 + forced Activates (option A), to 19:40; its 4 h gate running. Cluster: late1, R3 + your better late turns (option B), to 20:00; its 4 h gate queued on the cluster CPUs. Bar for both: engine exam >= 1.05x R3, gate not worse
- [ ] late1 agrees with your held-out late turns 32-34% (R3 7.6%; your refreshes 24-32%, R3 0%): it learns your late play, not only the 933 training decisions (95% on those), though held-out slips a little as training goes on
- [ ] Queued: mid1 (office, after act1 at 19:40): R3 + your round 5-8 turns, the root-cause lever ([CASE_LATE_GAME.md](CASE_LATE_GAME.md#the-root-cause-r3s-own-training-games-nov-4))
- [ ] Effect audit on the cluster (cards in action, 2,400 full games): now saves per chunk and resumes

## Next up

- [ ] From Nov 5: the training plan ([TRAINING_PLAN.md](TRAINING_PLAN.md)): the mainline from tonight's best verdict, the next experiment library seats with players; the champion ladder on the progress page
- [ ] R5 tonight at 20:00: R3 unless a candidate passes the gate and the recheck; the simulator fixes and the exams ship either way
- [ ] Late-game case study ([CASE_LATE_GAME.md](CASE_LATE_GAME.md)): the late gap is made in rounds 5-9, where R3's value head can't tell your turns from its own (55%); search on top of it finds nothing, so the network has to learn engines' worth
- [ ] Commit to a type and hold cards: on-type buys 35% (you 62-69%), plays 11 a turn (you 7-8)

## Later

- [ ] Coverage: every pool card checked or tested (978 tests); left: 8 combat Hero Powers and 2 trinkets Bob's Buddy disagrees with (none in your logs), Bob's Buddy runs when you're not playing; the library-with-players boards for the next run

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
