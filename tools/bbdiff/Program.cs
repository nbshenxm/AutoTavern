// One fight per input line (JSON), Bob's Buddy's result per output line:
//   in:  {"id": 1, "turn": 9, "n": 1000,
//         "player":   {"tier": 5, "health": 30, "minions": [{"card": "BG36_853", "atk": 4, "hp": 4,
//                      "golden": false, "taunt": false, "div": false, "reborn": false,
//                      "windfury": false, "poisonous": false, "venomous": false, "stealth": false}]},
//         "opponent": {...}}
//   out: {"id": 1, "win": 0.52, "tie": 0.03, "loss": 0.45, "error": null}
// Run from the HDT folder's DLLs (AppDomain probing: see App.config-free resolve below).
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using BobsBuddy;
using BobsBuddy.Simulation;
using Newtonsoft.Json.Linq;

static class Program
{
    static string HdtDir = Environment.GetEnvironmentVariable("HDT_DIR")
        ?? Path.Combine(Environment.GetEnvironmentVariable("LOCALAPPDATA"), "HearthstoneDeckTracker", "app-1.59.6");

    static int Main()
    {
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) =>
        {
            var f = Path.Combine(HdtDir, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(f) ? Assembly.LoadFrom(f) : null;
        };
        return Run();
    }

    static int Run()
    {
        string line;
        while ((line = Console.In.ReadLine()) != null)
        {
            if (line.Trim().Length == 0) continue;
            var o = new JObject();
            try
            {
                var j = JObject.Parse(line);
                o["id"] = j["id"];
                var output = Fight(j);
                o["win"] = output.winRate;
                o["tie"] = output.tieRate;
                o["loss"] = output.lossRate;
                o["error"] = null;
            }
            catch (Exception ex)
            {
                o["error"] = ex.GetType().Name + ": " + ex.Message;
            }
            Console.Out.WriteLine(o.ToString(Newtonsoft.Json.Formatting.None));
            Console.Out.Flush();
        }
        return 0;
    }

    static Output Fight(JObject j)
    {
        var input = new Input();
        var sim = new Simulator();
        var p = (JObject)j["player"];
        var q = (JObject)j["opponent"];
        input.SetTurn((int?)j["turn"] ?? 10);
        input.SetHealths((int?)p["health"] ?? 30, (int?)q["health"] ?? 30);
        input.SetTiers((int?)p["tier"] ?? 1, (int?)q["tier"] ?? 1);
        Fill(input.Player, (JArray)p["minions"], true, sim);
        Fill(input.Opponent, (JArray)q["minions"], false, sim);
        Counters(input.Player, (JObject)p["counters"]);
        Counters(input.Opponent, (JObject)q["counters"]);
        Trinkets(input.Player, (JArray)p["trinkets"], true, sim);
        Trinkets(input.Opponent, (JArray)q["trinkets"], false, sim);
        HeroPowers(input.Player, (JArray)p["hero_powers"], true);
        HeroPowers(input.Opponent, (JArray)q["hero_powers"], false);
        var n = (int?)j["n"] ?? 1000;
        return new SimulationRunner().SimulateMultiThreaded(input, n, 1, 20000).Result;
    }

    // Player-level "this game" counters by Bob's Buddy's property name (UndeadAttackBonus,
    // VolumizerAtkBuff, TastyLobsterCounter, BloodGemAtkBuff...)
    static void Counters(Player side, JObject counters)
    {
        if (counters == null) return;
        foreach (var kv in counters)
        {
            var prop = typeof(Player).GetProperty(kv.Key);
            if (prop != null && prop.CanWrite && prop.PropertyType == typeof(int))
                prop.SetValue(side, (int)kv.Value);
        }
    }

    static void Trinkets(Player side, JArray trinkets, bool friendly, Simulator sim)
    {
        if (trinkets == null) return;
        foreach (var t in trinkets)
        {
            try { side.Trinkets.Add(sim.TrinketFactory.Create((string)t, friendly)); }
            catch (Exception) { }  // a trinket Bob's Buddy doesn't model
        }
    }

    // {"card": id, "activated": bool, "data": n, "data2": n}
    static void HeroPowers(Player side, JArray powers, bool friendly)
    {
        if (powers == null) return;
        foreach (JObject h in powers)
            side.AddHeroPower((string)h["card"], friendly, (bool?)h["activated"] ?? false,
                              (int?)h["data"] ?? 0, (int?)h["data2"] ?? 0);
    }

    static void Fill(Player side, JArray minions, bool friendly, Simulator sim)
    {
        var factory = sim.MinionFactory;
        foreach (JObject m in minions)
        {
            var card = (string)m["card"];
            var minion = factory.CreateFromCardId(card, friendly);
            minion.baseAttack = (int)m["atk"];
            minion.baseHealth = (int)m["hp"];
            minion.golden = (bool?)m["golden"] ?? minion.golden;  // (the factory knows a golden card id)
            minion.taunt = (bool?)m["taunt"] ?? minion.taunt;
            if (m["div"] != null) minion.div = (bool)m["div"] ? Math.Max(1, minion.div) : 0;  // (a hit count: Dark Paradox 3)
            minion.reborn = (bool?)m["reborn"] ?? minion.reborn;
            minion.windfury = (bool?)m["windfury"] ?? minion.windfury;
            minion.poisonous = (bool?)m["poisonous"] ?? minion.poisonous;
            minion.venomous = (bool?)m["venomous"] ?? minion.venomous;
            minion.stealth = (bool?)m["stealth"] ?? minion.stealth;
            // The card's script data as the client shows it (HDT passes these: counters, a
            // Divine Shield's hits left...)
            if (m["sd1"] != null) minion.ScriptDataNum1 = (int)m["sd1"];
            if (m["sd2"] != null) minion.ScriptDataNum2 = (int)m["sd2"];
            if (Environment.GetEnvironmentVariable("BBDIFF_DEBUG") == "1")
                Console.Error.WriteLine($"{card}: golden={minion.golden} div={minion.div} taunt={minion.taunt} reborn={minion.reborn} windfury={minion.windfury} atk={minion.attack()} hp={minion.health()} name={minion.minionName}");
            side.Side.Add(minion);
        }
    }
}
