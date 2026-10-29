# Client diff and combat replay

Two checks of TavernGym against the live game: the client's card data (`tools/client_diff.py`)
and combats from Battlegrounds Power.logs replayed in the simulator (`tools/bg_logs.py`,
`tools/combat_replay.py`, `tests/test_combat_replay.py`). Inputs and outputs live in the ignored
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
python -X utf8 tools/bg_logs.py <logs dir or Power.log>... --cards <client dir> --out data/replay
python -X utf8 tools/combat_replay.py data/replay/combats.jsonl -n 500
pytest tests/test_combat_replay.py      # skips when there are no extracted combats
```

`bg_logs.py` splits each log at `CREATE_GAME` (a reconnect starts a new segment of the same game)
and records, for every combat: both warbands and hands before Start of Combat, again just before
the first attack with the side that attacks first, heroes, Hero Powers, trinkets, enchantments,
the players left, and the result: the winner, and the damage the winner's hero dealt (`PREDAMAGE`,
after the cap, before armor).

`combat_replay.py` rebuilds each combat with the debug commands and runs `combat_preview`. Mode
`start` simulates Start of Combat too. Mode `attack` starts from the first attack with the logged
first attacker, so it tests the attack phase alone. Logged stats and keywords are set directly.
Dark Gifts and magnetized minions are attached from their enchantments. A logged winner that
TavernGym gives under 2% counts as a surprise.

Baseline (TavernGym 36.6.3 data, 10 games on builds 254477 and 255790 = 37.0, 106 combats):

| Build | Mode | Combats | Mean P(logged winner) | Surprises |
| --- | --- | ---: | ---: | ---: |
| 254477 | start | 51 | 0.89 | 1 |
| 254477 | attack | 50 | 0.91 | 0 |
| 255790 | start | 55 | 0.85 | 1 |
| 255790 | attack | 54 | 0.86 | 1 |

Over both builds, the most likely simulated result is the logged one in 90% (start) and 91%
(attack) of combats, and the Brier score for the friendly win is 0.07 in both modes. The known gap is player-level state
the setup can't carry yet: "this game" buffs and counters (Tasty Lobster improvements,
Beetle and Undead bonuses, the `<card>pe` player enchantments) and Hero Power counters. It
shows as a lean against the friendly side: logged wins that TavernGym gave 10-40%.
