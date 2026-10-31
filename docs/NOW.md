# Now

What's being worked on, kept current (the progress page shows it under "Where we are"). The
release targets are in [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31).

## Next up

- [ ] Teacher test result: keep search data only if a search clearly beats the network
- [ ] R1 at 20:00 today: tag bg-r1, note in RELEASES.md (advice fixes; strength unchanged)
- [ ] 22:00: decide emb1 vs sig1 (new information or not) on your positions and top-1% lobbies
- [ ] solo1's first evaluations against the office runs; stop it early if it falls clearly behind
- [ ] Shrink the office runs' memory at their next restart (room for tests there, not at home)
- [ ] solo1's best.pt to the office's data/train/solo1/ when it beats the best there, so advisor.promote (and its play audit) judges it

## Later

- [ ] R2 (Nov 1): late game >= 0.25x, from your positions < 2.50
- [ ] R3 (Nov 2): late >= 0.30x, from your positions < 2.45, Gold left <= 6
- [ ] R4 (Nov 3): late >= 0.40x, on-type buys >= 50%
- [ ] R5 (Nov 4): late >= 0.50x; 5 of your games measured
- [ ] A larger network (AutoTavern used 18M parameters; ours 0.9M) once a setup clearly learns
- [ ] Opponents' trinket counters in the observation (the bridge's live values)

## Done today

- [x] Advice: next step only, a close second after "or"; trinket offers advised and ranked
- [x] Audit: Gold-left check fixed, play audit with the review's rules, fidelity check repaired
- [x] Observation v4 and card text; the cluster set up (its own folder) and solo1 started
- [x] solo1 measured like every run (head to head, your positions, top-1% lobby), from its next hourly task
- [x] Progress page: "Where we are" with every running job and these checklists
