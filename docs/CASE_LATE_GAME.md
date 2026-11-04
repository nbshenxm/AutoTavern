# Case study: your late game against R3 (Nov 3)

Asked for after R1-R3 stalled in the late game: learn the late game from your own play first.
Material: your 18 logged Battlegrounds games (16 reach round 9, 11 reach round 13), the 37.0.2
build, R3 (big3 iteration 510). Two parts: what your late games do (the logs alone), and R3 playing
from your exact positions.

## A. How your late games scale

**One engine carries every deep run.** By round 10, one or two minions hold most of your warband
and grow 2-3x every round; the whole warband follows (4,505 → 11,400 → 20,016 → 32,260 → 48,464 in
the Glambot game, rounds 10-14).

| Game | Engine | Growth by round |
| --- | --- | --- |
| Oct 31 10:18 (Y'Shaarj) | Glambot + golden Utility Drones: spells cast on Mechs | Glambot 185 (r9) → 2,272 → 4,428 → 7,293 → 11,041 → 14,713 |
| Oct 24 17:51 (Faelin) | Devilish Distractor: spells cast on it | 393 (r10) → 907 → 3,716 → 6,725 |
| Oct 29 11:09 (Vol'jin) | Ashen Corruptor, then Dark Paradox | Paradox 669 (r12) → 6,875 → 12,955 → 30,862 |
| Oct 30 18:43 (Sindragosa) | Resourceful Robot + Polarizing Beatboxer: Magnetic | Beatboxer 302 (r10) → 1,529 → 3,615 → 11,512 |
| Oct 29 19:05 (Morchie) | Unbound Tempest + Living Prison: Elementals | Tempest 837 (r11) → 1,413 → 2,904 → 6,066 → 10,086 |
| Oct 31 15:04 (Baz'hial) | golden Tarecgosa + Training Certificate, a two-minion warband | x3 a round: 612 (r9) → 746,000 (r15) |
| Oct 29 09:51 (Reno), Nov 2 12:23 | Beasts: Lionfish, Deathstrider, Lobster, Gryphon, Titus | 767 (r11) → 4,417 → 9,584 → 11,775 |

- **You commit by rounds 9-10**: 5-7 minions of one type. A pivot comes at rounds 8-10, when an
  engine appears (Pirates → Demons, Mechs → Elementals, Pirates/Dragons → Beasts), then no more.
- **Tier isn't the driver**: Tier 5 by rounds 8-9 usually, 6 when it's convenient; the Tarecgosa
  game stayed at Tier 4 to round 12, the Vol'jin Demons at Tier 5 to the end.
- **You play from low health** (3-16 for several rounds) while the engine scales.

## B. R3 from your positions

The continuation test (advisor.continue_test, greedy, 2 trials): R3 plays every seat on from your
position at the start of a round. Its warband at the end of that same turn against yours:

| From | R3 / you, same turn (median) |
| --- | --- |
| round 9 | 0.98 (n 38) |
| round 10 | 0.75 (n 26) |
| round 11 | 0.63 (n 24) |

From your positions, one turn of R3 already falls behind, more so the later; where you feed an engine,
far behind. Your turn and R3's turn, action by action, from the same six positions:

| Position | You | R3 | Next |
| --- | --- | --- | --- |
| Oct 31 10:18, r9, Glambot | buy 2 Utility Drones, Goldenize them, sell the non-Mechs, every spell (Fortify, 2 Bananas, Lost Staff, Forest's Bounty, the Goldenizers) **on a Mech** | Goldenizers on whatever, untargeted spells, ~10 Refreshes, a second Glambot, Charging Czarina | Glambot 2,272 (you) vs 411 (R3) |
| Oct 31 15:04, r10, golden Tarecgosa + Training Certificate | buy a Tarecgosa, Might of Stormwind and Overconfidence; **end with two minions**, so the Certificate always doubles a Tarecgosa | adds two Hopebringers (they become the two lowest-Attack: the Certificate doubles them), 7 moves back and forth, Freeze | 5,520 vs 1,840 |
| Nov 2 12:23, r11, Beasts | Ophidian Staff on Deathstrider; **play each Beast for its Battlecry/trigger, then sell it** (a dozen times), Lionfish onto the right targets | cycles the hand too, ~15 Refreshes, Pointy Arrows, Shiny Ring | Deathstriders 1,513 / 2,167 vs 369 |
| Nov 2 23:10, r9, Beasts | sell the filler, Hyena and Lobster in, Triple Reward → Tyrael on Gryphon | **sells the Beasts** (Wolf Pup, Lionfish, Goldrinn), buys Rescue Bot, Auto Reveille, Champion of Sargeras | a Beast warband vs a mixed one |
| Oct 29 09:51, r11, Beasts | play-and-sell the hand's Beasts, Eyes of the Earth Mother on a Lionfish | sells **Titus Rivendare**, Goldrinn and both Hyenas | Lionfish 1,970 vs 106 |

## What R3 does wrong, and what it would have to learn

1. **Buffs aren't funnelled into the engine.** Spells go anywhere; yours go onto the minion that
   multiplies them (Glambot, Utility Drone, Distractor, Deathstrider).
2. **The board isn't shaped for the engine.** It fills slots that break a condition (the two
   lowest-Attack minions, a Mech-only warband).
3. **It doesn't cycle cards through the engine's trigger** ("whenever you play a Beast"): you
   play-and-sell a dozen cheap Beasts a turn.
4. **It dismantles a working comp** for unrelated minions, and sells the multipliers (Titus).

These are about *which* target and *which* minion, not how much Gold: the late Refresh and Gold
habits are already close to yours.

## Next

- **An engine exam** from these positions (your rounds 9-12): R3's warband after its turn and two
  rounds on, per engine, against yours. Cheap (one turn to a few rounds from each start),
  interpretable, and aimed at the weakness; a candidate must not fall behind R3 on it.
- **Where the targets go**: at every targeted spell and Battlecry in these positions, the share
  R3 puts on the engine minion against yours (the first diagnosis: is it the choice head, or does
  it not see the engine?).
- Then one change at a time, judged by the engine exam and the gate.
