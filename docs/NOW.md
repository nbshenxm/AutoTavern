# Now

What's being worked on, kept current (the progress page shows it under "Where we are"). The
release targets are in [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31).

## Running

- [ ] Office: big3 (10x larger network) training on alone against 7 library seats, until Nov 2 16:00
- [ ] Cluster: big3ad (big3 it 302 in an adaptive lobby: late strength 1.25x its own, rising with it; + forced Upgrades with self-imitation)

## Next up

- [x] Cards lost to a full hand: a cost in training (card_lost_penalty, tested); big3 restarted with it 17:49
- [ ] Your games with big3: does the advice feel right late (refreshes, Gold spent)? Ctrl+Shift+B marks what doesn't
- [ ] R3 (Nov 2 20:00): late >= 0.30x, from your positions < 2.45, Gold left <= 6 (big3: 0.19x, 2.36, 1.85)
- [x] The late-game curve in the top-1% lobby (study --lobby library): big3 0.18x, the old best 0.17x; early 2.06x, mid 1.21x (old 1.87, 1.05)
- [x] Levelling: big3 is tier 2.8 at round 10 in that lobby (your lobbies 5.3). Made to level on a curve it placed 0.14 +- 0.07 worse; the teacher bot too (fast curve +0.39 worse, tier 3 the same as standard)
- [x] Why: every network gives Upgrade ~0.000 in your round 4-9 positions (inherited from the first self-play; forced exploration trained only the value). Self-imitation of forced Upgrades that pay (--explore-sil) added and tested
- [x] Why: the simulator's rules are right (prices exact, your turns replay 86% exactly); its lobby isn't: real late warbands no simulated player approaches, so the late game is lost whatever one does. Adaptive library added (--library-adaptive), big3sil stopped for it
- [ ] big3ad vs big3: P(Upgrade) in your positions, tier at round 10 and the late game in the top-1% lobby, from your positions
- [ ] big3's entropy rose 0.85 -> 1.3, back to 0.96 at it 240; from your positions 2.20 (best 2.30): watching

## Tomorrow morning (Nov 2)

- [ ] big3ad's probes (cluster, 01:45 and 05:45): does it level in your positions now (was 0% in rounds 4-9)? Its tier at round 10 in the top-1% lobby (big3 2.8)
- [ ] big3ad vs big3 (office, the control): head to head, from your positions, the top-1% lobby
- [ ] Promote whichever is better for R3 (Nov 2 20:00); if big3ad levels and holds its strength, it goes first

## Later

- [ ] R4 (Nov 3): late >= 0.40x, on-type buys >= 50% (big3: 48.5%)
- [ ] R5 (Nov 4): late >= 0.50x; 5 of your games measured
- [ ] Opponents' trinket counters in the observation (the bridge's live values)
- [ ] The full 18M network AutoTavern used (big3 is d384 x 8 layers)

## Done today (Nov 1)

- [x] R2 shipped (tag bg-r2): big3 iteration 180, the first network to beat the 18:21 one
- [x] The Cancel reward hack found and fixed (solo1, emb1); solo2 restarted from before it
- [x] Teacher test: no search plays better than the network; the advice runs without it (0.3 s)
- [x] A 10x larger network distilled and trained (big3); the play audit made fair
