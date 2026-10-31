# Now

What's being worked on, kept current (the progress page shows it under "Where we are"). The
release targets are in [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31).

## While the PC is off (Oct 31 18:45 to Nov 1 afternoon)

Everything runs on the office and the cluster without the home PC:

- [ ] Cluster: solo1, AutoTavern's setup (job 96998, hourly tasks, about 40 iterations each; ~20 by tomorrow afternoon)
- [ ] Cluster: the teacher test (job 97021, 64 CPUs, results saved case by case)
- [ ] Office: emb1 vs sig1 (the new information vs the blind control) until Nov 1 16:00
- [ ] Office: the hourly promotion check with the play audit (a network that passes reaches best.pt; the overlay gets it at the next home sync)

## Next up (tomorrow afternoon, when the PC is back)

- [ ] Teacher test result: keep search data only if a search clearly beats the network
- [ ] emb1 vs sig1: keep the new information or not (your positions, top-1% lobbies)
- [ ] solo1 against the office runs on the same measures; its best.pt to the office for the promotion check
- [ ] R2 at 20:00 (late game >= 0.25x or from your positions < 2.50): ship whatever is best, say plainly if it misses
- [ ] If neither solo1 nor emb1 moved: the next approach for R3 (larger network on the cluster, or opponents' trinket counters)

## Later

- [ ] R3 (Nov 2): late >= 0.30x, from your positions < 2.45, Gold left <= 6
- [ ] R4 (Nov 3): late >= 0.40x, on-type buys >= 50%
- [ ] R5 (Nov 4): late >= 0.50x; 5 of your games measured
- [ ] A larger network (AutoTavern used 18M parameters; ours 0.9M) once a setup clearly learns
- [ ] Opponents' trinket counters in the observation (the bridge's live values)
- [ ] Shrink the office runs' memory at their next restart (room for tests there)

## Done today

- [x] R1 shipped (tag bg-r1): next-step advice, trinket offers and picks, checks fixed; strength unchanged
- [x] Audit: Gold-left check fixed, play audit with the review's rules, fidelity check repaired
- [x] Observation v4 and card text; the cluster set up (its own folder) and solo1 started
- [x] solo1 measured like every run (head to head, your positions, top-1% lobby)
- [x] Progress page: "Where we are" with every running job and these checklists
