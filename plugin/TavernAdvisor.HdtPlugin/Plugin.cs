using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.CompilerServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Hearthstone_Deck_Tracker.API;
using Hearthstone_Deck_Tracker.Plugins;
using Newtonsoft.Json.Linq;

namespace TavernAdvisor.HdtPlugin
{
    /// <summary>
    /// Shows the Battlegrounds advisor's advice on HDT's overlay during the recruit phase. The advice
    /// comes from `python -m advisor.live` (the AutoTavern fork), which this plugin starts and stops;
    /// the plugin itself only reads advice.json in %LOCALAPPDATA%\TavernAdvisor. It never acts in the
    /// game.
    /// </summary>
    public class Plugin : IPlugin
    {
        Settings _settings;
        Process _advisor;
        Border _box;
        StackPanel _panel;
        DateTime _lastRead = DateTime.MinValue;
        DateTime _lastPoll = DateTime.MinValue;
        DateTime _lastStart = DateTime.MinValue;
        DateTime _flaggedAt = DateTime.MinValue;
        bool _loaded;      // HDT keeps a registered hotkey after unloading: its action checks this
        bool _hidden;      // the advice says combat is on

        public string Name => "Tavern Advisor (Battlegrounds)";
        public string Description => "Recruit-phase suggestions for Battlegrounds from a local TavernGym simulator. Reads Power.log only; never plays for you.";
        public string ButtonText => "Open advice folder";
        public string Author => "Xiangmin Shen";
        public Version Version => new Version(0, 1, 0);
        public MenuItem MenuItem => null;

        static readonly FontFamily Font = new FontFamily("Segoe UI, Microsoft YaHei UI");

        public void OnLoad()
        {
            _settings = Settings.Load(Path.GetDirectoryName(typeof(Plugin).Assembly.Location));
            CreateOverlay();
            if (_settings.StartAdvisor)
                StartAdvisor();
            _loaded = true;
            try
            {
                RegisterFlagHotkey(FlagAdvice);
            }
            catch (Exception)
            {
                // HDT without this hotkey API: no flagging
            }
        }

        /// <summary>Ctrl+Shift+B: "this advice is wrong" (Ctrl+Shift+F is the constructed advisor's).
        /// Kept apart so a missing HDT type fails here.</summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        static void RegisterFlagHotkey(Action action)
        {
            var key = new Hearthstone_Deck_Tracker.Utility.HotKeys.HotKey(
                Hearthstone_Deck_Tracker.Utility.HotKeys.ModifierKeys.Control | Hearthstone_Deck_Tracker.Utility.HotKeys.ModifierKeys.Shift,
                System.Windows.Forms.Keys.B);
            Hearthstone_Deck_Tracker.Utility.HotKeys.HotKeyManager.RegisterHotkey(key, action, "Tavern Advisor: mark this advice as wrong");
        }

        /// <summary>The advice on screen, appended to flagged.jsonl as you saw it.</summary>
        void FlagAdvice()
        {
            if (!_loaded || _settings == null || !File.Exists(_settings.AdviceFile))
                return;
            try
            {
                JObject advice = JObject.Parse(File.ReadAllText(_settings.AdviceFile));
                var line = new JObject { ["flagged_at"] = DateTime.Now.ToString("s"), ["advice"] = advice };
                File.AppendAllText(Path.Combine(_settings.LiveDir, "flagged.jsonl"),
                    line.ToString(Newtonsoft.Json.Formatting.None) + Environment.NewLine);
                _flaggedAt = DateTime.Now;
                _lastRead = DateTime.MinValue;   // redraw, with the note
            }
            catch (Exception)
            {
                // Being written as we read: press again
            }
        }

        public void OnUnload()
        {
            _loaded = false;
            StopAdvisor();
            if (_box != null)
                Core.OverlayCanvas.Children.Remove(_box);
            _box = null;
        }

        public void OnButtonPress()
        {
            string dir = _settings?.LiveDir;
            if (dir != null && Directory.Exists(dir))
                Process.Start("explorer.exe", dir);
        }

        /// <summary>Called by HDT about every 100 ms on the UI thread.</summary>
        public void OnUpdate()
        {
            if (_box == null || (DateTime.Now - _lastPoll).TotalMilliseconds < 250)
                return;
            _lastPoll = DateTime.Now;
            PositionOverlay();
            KeepAdvisorRunning();

            string path = _settings.AdviceFile;
            bool inBattlegrounds = Core.Game != null && !Core.Game.IsInMenu && Core.Game.IsBattlegroundsMatch;
            if (!inBattlegrounds || !File.Exists(path))
            {
                _box.Visibility = Visibility.Collapsed;
                return;
            }
            DateTime written = File.GetLastWriteTime(path);
            if ((DateTime.Now - written).TotalSeconds > _settings.StaleSeconds)
            {
                _box.Visibility = Visibility.Collapsed;
                return;
            }
            if (written != _lastRead)
            {
                _lastRead = written;
                ShowAdvice(path);
            }
            _box.Visibility = _hidden ? Visibility.Collapsed : Visibility.Visible;
        }

        void ShowAdvice(string path)
        {
            try
            {
                JObject a = JObject.Parse(File.ReadAllText(path));
                _hidden = a.Value<string>("phase") == "combat";
                if (_hidden)
                    return;
                _panel.Children.Clear();
                _panel.Children.Add(Text($"Turn {a.Value<int>("turn")} · {a.Value<string>("policy")}", 11,
                    color: Color.FromRgb(170, 170, 170)));
                _panel.Children.Add(Text(a.Value<string>("action") ?? "(no suggestion)", 16, FontWeights.SemiBold));
                if (a["plan"] is JArray plan)
                {
                    int shown = 0;
                    for (int i = 1; i < plan.Count && shown < _settings.MaxSteps; i++, shown++)
                        _panel.Children.Add(Text($"{i + 1}. {(string)plan[i]}", 13));
                    if (plan.Count - 1 > shown)
                        _panel.Children.Add(Text($"… {plan.Count - 1 - shown} more", 12, color: Color.FromRgb(190, 190, 190)));
                }
                AddOdds("Now", a["odds_now"] as JObject);
                AddOdds("After the plan", a["odds_after_plan"] as JObject);
                if (a["warnings"] is JArray warnings)
                    foreach (JToken w in warnings)
                        _panel.Children.Add(Text("⚠ " + (string)w, 11, color: Color.FromRgb(240, 190, 90)));
                if ((DateTime.Now - _flaggedAt).TotalSeconds < 30 && File.GetLastWriteTime(path) < _flaggedAt)
                    _panel.Children.Add(Text("Marked as wrong (saved)", 12, color: Colors.Orange));
            }
            catch (IOException)
            {
                // Being written as we read; picked up on the next poll
                _lastRead = DateTime.MinValue;
            }
            catch (Exception e)
            {
                _panel.Children.Clear();
                _panel.Children.Add(Text("Tavern Advisor: unreadable advice (" + e.Message + ")", 12));
            }
        }

        /// <summary>"After the plan: win 62% · tie 8% · lose 30% (their warband from turn 7)".</summary>
        void AddOdds(string label, JObject odds)
        {
            if (odds == null)
                return;
            int age = odds.Value<int?>("seen_turn") ?? 0;
            string text = $"{label}: win {odds.Value<double>("win"):P0} · tie {odds.Value<double>("tie"):P0} · lose {odds.Value<double>("loss"):P0}"
                          + (age > 0 ? $" (their warband from turn {age})" : "");
            var t = Text(text, 12, color: Color.FromRgb(160, 210, 255));
            t.Margin = new Thickness(0, 4, 0, 0);
            _panel.Children.Add(t);
        }

        static TextBlock Text(string text, double size, FontWeight? weight = null, Color? color = null) => new TextBlock
        {
            Text = text,
            Foreground = new SolidColorBrush(color ?? Colors.White),
            FontSize = size,
            FontWeight = weight ?? FontWeights.Normal,
            // Chinese card names fall back to Microsoft YaHei UI
            FontFamily = Font,
            TextWrapping = TextWrapping.Wrap,
            MaxWidth = 420,
        };

        void CreateOverlay()
        {
            _panel = new StackPanel();
            _box = new Border
            {
                Child = _panel,
                Padding = new Thickness(8, 5, 8, 6),
                CornerRadius = new CornerRadius(4),
                Background = new SolidColorBrush(Color.FromArgb(195, 25, 25, 28)),
                Visibility = Visibility.Collapsed,
                IsHitTestVisible = false,
                LayoutTransform = new ScaleTransform(_settings.Scale, _settings.Scale),
            };
            Core.OverlayCanvas.Children.Add(_box);
            PositionOverlay();
        }

        void PositionOverlay()
        {
            Canvas canvas = Core.OverlayCanvas;
            Canvas.SetLeft(_box, canvas.ActualWidth * _settings.OverlayLeft);
            Canvas.SetTop(_box, canvas.ActualHeight * _settings.OverlayTop);
        }

        void StartAdvisor()
        {
            _lastStart = DateTime.Now;
            if (!File.Exists(_settings.Python) || !Directory.Exists(_settings.Repo))
                return;
            try
            {
                Directory.CreateDirectory(_settings.LiveDir);
                string logFile = Path.Combine(_settings.LiveDir, "live.log");
                _advisor = Process.Start(new ProcessStartInfo
                {
                    FileName = _settings.Python,
                    Arguments = $"-X utf8 -m advisor.live --locale {_settings.Locale} --live-dir \"{_settings.LiveDir}\" --log-file \"{logFile}\"",
                    WorkingDirectory = _settings.Repo,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                });
            }
            catch (Exception)
            {
                _advisor = null;
            }
        }

        /// <summary>Restart the advisor if it exited (at most once a minute, so a crash can't loop).</summary>
        void KeepAdvisorRunning()
        {
            if (!_settings.StartAdvisor || (DateTime.Now - _lastStart).TotalSeconds < 60)
                return;
            bool running;
            try
            {
                running = _advisor != null && !_advisor.HasExited;
            }
            catch (InvalidOperationException)
            {
                running = false;
            }
            if (!running)
                StartAdvisor();
        }

        void StopAdvisor()
        {
            try
            {
                if (_advisor != null && !_advisor.HasExited)
                    _advisor.Kill();
            }
            catch (InvalidOperationException)
            {
                // already exited
            }
            _advisor = null;
        }
    }

    /// <summary>taverngym.plugin.json next to the plugin DLL.</summary>
    class Settings
    {
        public string Repo = @"D:\GitHub\AutoTavern";
        public string Python = @"%USERPROFILE%\anaconda3\envs\taverngym\pythonw.exe";
        public bool StartAdvisor = true;
        public string Locale = "enUS";
        public double OverlayLeft = 0.02;
        public double OverlayTop = 0.12;
        public double StaleSeconds = 90;
        public int MaxSteps = 6;
        public double Scale = 1.0;

        public string LiveDir => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "TavernAdvisor");
        public string AdviceFile => Path.Combine(LiveDir, "advice.json");

        public static Settings Load(string dir)
        {
            var s = new Settings();
            string path = Path.Combine(dir ?? "", "taverngym.plugin.json");
            if (File.Exists(path))
            {
                try
                {
                    JObject j = JObject.Parse(File.ReadAllText(path));
                    s.Repo = (string)j["repo"] ?? s.Repo;
                    s.Python = (string)j["python"] ?? s.Python;
                    s.StartAdvisor = (bool?)j["start_advisor"] ?? s.StartAdvisor;
                    s.Locale = (string)j["locale"] ?? s.Locale;
                    s.OverlayLeft = (double?)j["overlay_left"] ?? s.OverlayLeft;
                    s.OverlayTop = (double?)j["overlay_top"] ?? s.OverlayTop;
                    s.StaleSeconds = (double?)j["stale_seconds"] ?? s.StaleSeconds;
                    s.MaxSteps = (int?)j["max_steps"] ?? s.MaxSteps;
                    s.Scale = (double?)j["scale"] ?? s.Scale;
                }
                catch (Exception)
                {
                    // keep defaults
                }
            }
            s.Repo = Environment.ExpandEnvironmentVariables(s.Repo);
            s.Python = Environment.ExpandEnvironmentVariables(s.Python);
            return s;
        }
    }
}
