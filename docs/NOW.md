# Now

What's being worked on, kept current (the progress page shows it under "Where we are"). The
release targets are in [ROADMAP.md](ROADMAP.md#releases-from-2026-10-31).

## Running

- [ ] Office: big3 (10x larger network) training on alone against 7 library seats, until Nov 2 16:00
- [ ] Cluster: big3sil (big3 + forced Upgrades and self-imitation of the ones that paid), from big3's it 250; solo2 stopped (behind big3, 4.8 head to head)

## Next up

- [x] Cards lost to a full hand: a cost in training (card_lost_penalty, tested); big3 restarted with it 17:49
- [ ] Your games with big3: does the advice feel right late (refreshes, Gold spent)? Ctrl+Shift+B marks what doesn't
- [ ] R3 (Nov 2 20:00): late >= 0.30x, from your positions < 2.45, Gold left <= 6 (big3: 0.19x, 2.36, 1.85)
- [x] The late-game curve in the top-1% lobby (study --lobby library): big3 0.18x, the old best 0.17x; early 2.06x, mid 1.21x (old 1.87, 1.05)
- [ ] Levelling: big3 is tier 2.8 at round 10 in that lobby (your lobbies 5.3, the old best 3.9). Level test running (office): made to Upgrade on a curve, does it place better?
- [x] Why: every network gives Upgrade ~0.000 in your round 4-9 positions (inherited from the first self-play; forced exploration trained only the value). Self-imitation of forced Upgrades that pay (--explore-sil) added and tested
- [ ] big3sil vs big3: P(Upgrade) in your positions, tier at round 10 in the top-1% lobby, from your positions
- [ ] big3's entropy rose 0.85 -> 1.3, back to 0.96 at it 240; from your positions 2.20 (best 2.30): watching

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
