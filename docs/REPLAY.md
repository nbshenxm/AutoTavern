# Client diff and combat replay

Two checks of TavernGym against the live game: the client's card data (`tools/client_diff.py`)
and combats from Battlegrounds Power.logs replayed in the simulator (`advisor/logs.py`,
`advisor/replay.py`, `tests/test_combat_replay.py`). Inputs and outputs live in the ignored
`data/` folder: client exports are downloaded, and logs carry player names.

## Client diff

```bash
python -X utf8 tools/client_diff.py --base data/client/253932 --new <client dir> --out docs/patches/<patch>
```

Each directory holds HearthstoneJSON's `enUS.json`, `zhCN.json` and `CardDefs.xml` for one build
(`https://api.hearthstonejson.com/v1/<build>/...`); 253932 is TavernGym's own build. Client pool
flags are not the pool (the server rotates types and bans cards), so the expected pool is
TavernGym's pool plus the flag changes between the two builds. Stat and text changes are split
into patch changes and values in which TavernGym already differed from its own build. Some pool
changes are server-side only (36.6.3 added three heroes with no client flag change), so the
logged shops are the second check: `data/replay/offers.jsonl`.

## Combat replay

```bash
python -X utf8 -m advisor.logs <logs dir or Power.log>... --cards <client dir> --out data/replay
python -X utf8 -m advisor.replay data/replay/combats.jsonl -n 500
pytest tests/test_combat_replay.py      # skips when there are no extracted combats
```

`advisor.logs` splits each log at `CREATE_GAME` (a reconnect starts a new segment of the same game)
and records, for every combat: both warbands and hands before Start of Combat, again just before
the first attack with the side that attacks first, heroes, Hero Powers, trinkets, enchantments,
the players left, and the result: the winner, and the damage the winner's hero dealt (`PREDAMAGE`,
after the cap, before armor).

`advisor.replay` rebuilds each combat with the debug commands and runs `combat_preview`. Mode
`start` simulates Start of Combat too. Mode `attack` starts from the first attack with the logged
first attacker, so it tests the attack phase alone. Logged stats and keywords are set directly.
Dark Gifts and magnetized minions are attached from their enchantments. "This game" counters are
set with `set_stats` before the warband is created, so minions summoned in combat get them: the
Undead Attack bonus, Eternal Knight deaths and the Beetle bonus come from the `<card>pe`
enchantments on the player entity (Bob's dummy player carries the opponent's copy), and the
Tasty Lobster bonus comes from the buff a logged Lobster shows. A logged winner that TavernGym
gives under 2% counts as a surprise.

Baseline (TavernGym 36.6.3 data, 10 games on builds 254477 and 255790 = 37.0, 106 combats):

| Build | Mode | Combats | Mean P(logged winner) | Surprises |
| --- | --- | ---: | ---: | ---: |
| 254477 | start | 51 | 0.91 | 0 |
| 254477 | attack | 50 | 0.93 | 0 |
| 255790 | start | 55 | 0.89 | 0 |
| 255790 | attack | 54 | 0.90 | 1 |

Over both builds, the most likely simulated result is the logged one in 92.5% (start) and 95%
(attack) of combats, and the Brier score for the friendly win is 0.045 / 0.038. Before the
counters were set it was 90% / 91% and 0.073 / 0.069: Tasty Lobster builds were the main
misses. Still not carried: Hero Power and trinket counters, Blood Gem bonuses, and other
player tags with no public names (the counters are numbered player tags such as 4639).

## Recruit rules

```bash
python -X utf8 -m advisor.decisions <logs>... --cards <client dir> --out data/replay
python -X utf8 -m advisor.recruit_checks data/replay/decisions.jsonl
```

`advisor.decisions` records every recruit decision: the state (as for combats, plus Gold, the
upgrade and refresh costs, the Tavern with frozen flags, the leaderboard), the options the client
offered with their targets and errors, and the option or choice the player sent.
`advisor.recruit_checks` compares the turn starts with TavernGym's rules.

On the 10 logged games (110 recruit turns, 2,031 decisions), against TavernGym's defaults:

| Rule | Logged |
| --- | --- |
| Max Gold 3, +1 a turn, up to 10 | 96 of 110 exact; the rest are above, from effects (Goblin Wallet...) except one turn-1 reading |
| Upgrade cost: base `[5,7,8,11,11,10]` minus 1 a turn | 100 of 101 exact |
| Refresh cost 1 | 100 of 110; the others free refreshes |
| Fresh Tavern `[3,4,4,5,5,6,6]` minions + 1 spell | all, except Sindragosa (one fewer) and Innkeeper's Stein (one more, a Tier higher), both as in TavernGym; one unexplained 5 instead of 6 |
| Tier mix of the minions offered at each Tavern Tier | within 2-3 points of TavernGym's own Taverns at every Tier |
| Trinkets: Lesser at turn 6, Greater at turn 9, 4 options | all; extra 2-option offers come from effects |
| Hero options | 4 (the player's season-pass offer); TavernGym's default `hero_choices` is 2 |

## Live bridge

```bash
python -X utf8 -m advisor.bridge data/replay/decisions.jsonl
pytest tests/test_bridge.py      # skips when there are no extracted decisions
```

`advisor.bridge.build` turns a logged recruit decision into a TavernGym game with the player on
seat 0: hero, Hero Powers (used this turn, or a spent once-per-game one), trinkets, counters,
Tier, health, armor, Gold, upgrade cost, free refreshes, warband, hand in logged order (a
Lockbox's locked card stays locked) and the Tavern with its frozen flags. Seats 1-7 are the
other players from the leaderboard (hero, health, armor, Tier, eliminated with their place),
each with the warband the player last saw in combat, which is also the player's scouting
of them in the observation; the last and next opponents are marked. `parity` compares
TavernGym's legal actions there with the options the client offered, by kind and slot.

On the 10 logged games (1,870 recruit decisions), the legal sets are identical in 89%. End
Turn, Freeze, Upgrade, Sell, Buy, Dark Gift and targeted Activates agree everywhere except
one game's purchases. An Activate without a target can't be checked: the log shows it like a
move. Left over:

| Where | Count | What |
| --- | ---: | --- |
| Bile Spitter in hand, full warband | 103 | the client offers it with no target, in one game; unexplained |
| Methodical Madness | 32 | TavernGym offers it where the client doesn't |
| Spirit Swap (Hero Power) | 18 | the client offers it where TavernGym doesn't |
| One game's buys and refreshes (Malchezaar on the warband) | 87 | TavernGym allows them with 0-1 Gold, paying Health |

The live advisor only suggests actions that both TavernGym and the client allow.

## Live advisor

```bash
python -X utf8 -m advisor.live                         # follow the newest Power.log
python -X utf8 -m advisor.live --replay PATH --limit 40  # a recorded log, timed
pytest tests/test_live.py                              # skips without a recorded log
```

`advisor.live` parses the log incrementally (a parser per `CREATE_GAME` segment, finished
top-level packets exported as they arrive, combats kept across reconnects). At each recruit
Options packet it builds the lobby (`advisor.bridge`), plays the policy's turn on a copy, and
writes `advice.json` to `%LOCALAPPDATA%\TavernAdvisor`: the first step, the turn's plan, combat
odds against the next opponent's last seen warband now and after the plan (with the turn it
was seen), and warnings (setup gaps, a first step the client does not offer). On two recorded
37.0 logs it advised at all 370 recruit decisions, 42-92 ms median, 153 ms at most. The policy
is still TavernGym's scripted bot (v0): the plumbing is real, the advice is weak until M5.
