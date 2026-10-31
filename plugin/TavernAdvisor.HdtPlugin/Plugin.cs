using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Effects;
using System.Windows.Media.Imaging;
using Hearthstone_Deck_Tracker.API;
using Hearthstone_Deck_Tracker.Plugins;
using Hearthstone_Deck_Tracker.Utility.Assets;
using Newtonsoft.Json.Linq;
using HdtDatabase = Hearthstone_Deck_Tracker.Hearthstone.Database;

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
        Border _lineupBox;      // below the advice: the recommended warband order, top to bottom
        StackPanel _lineupPanel;
        bool _hasLineup;
        Border _genreBox;       // below the lineup: a few genres, a share each, the cards they need
        StackPanel _genrePanel;
        bool _hasGenres;
        DateTime _lastRead = DateTime.MinValue;
        DateTime _lastPoll = DateTime.MinValue;
        DateTime _lastStart = DateTime.MinValue;
        DateTime _flaggedAt = DateTime.MinValue;
        DateTime _settingsRead = DateTime.MinValue;
        bool _loaded;      // HDT keeps a registered hotkey after unloading: its action checks this
        bool _hidden;      // the advice says combat is on
        bool _artBroken;   // HDT's asset API isn't what this was built against: names only

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
            _settingsRead = SettingsWritten();
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
            if (_lineupBox != null)
                Core.OverlayCanvas.Children.Remove(_lineupBox);
            if (_genreBox != null)
                Core.OverlayCanvas.Children.Remove(_genreBox);
            _box = null;
            _lineupBox = null;
            _genreBox = null;
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
            ReloadSettingsIfChanged();
            PositionOverlay();
            KeepAdvisorRunning();

            string path = _settings.AdviceFile;
            bool inBattlegrounds = Core.Game != null && !Core.Game.IsInMenu && Core.Game.IsBattlegroundsMatch;
            if (!inBattlegrounds || !File.Exists(path))
            {
                _box.Visibility = _lineupBox.Visibility = _genreBox.Visibility = Visibility.Collapsed;
                return;
            }
            DateTime written = File.GetLastWriteTime(path);
            if ((DateTime.Now - written).TotalSeconds > _settings.StaleSeconds)
            {
                _box.Visibility = _lineupBox.Visibility = _genreBox.Visibility = Visibility.Collapsed;
                return;
            }
            if (written != _lastRead)
            {
                _lastRead = written;
                ShowAdvice(path);
            }
            _box.Visibility = _hidden ? Visibility.Collapsed : Visibility.Visible;
            _lineupBox.Visibility = _hidden || !_hasLineup ? Visibility.Collapsed : Visibility.Visible;
            _genreBox.Visibility = _hidden || !_hasGenres ? Visibility.Collapsed : Visibility.Visible;
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
                _lineupPanel.Children.Clear();
                _hasLineup = false;
                _genrePanel.Children.Clear();
                _hasGenres = false;
                if (a["display"] is JObject d)
                    ShowDisplay(d);
                else
                    _panel.Children.Add(Text(a.Value<string>("action") ?? "(no suggestion)", 16, FontWeights.SemiBold));
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

        /// <summary>The constructed advisor's layout: a title, one row per step, notes (combat odds),
        /// warnings; an Arrange step's warband order goes to the lineup panel below.</summary>
        void ShowDisplay(JObject d)
        {
            _panel.Children.Add(Text(d.Value<string>("title") ?? "", 15, FontWeights.SemiBold));
            if (d["lineup"] is JArray lineup)   // the warband as the plan leaves it (Arrange included)
                ShowLineup(lineup);
            if (d["genres"] is JArray genres)
                ShowGenres(genres);
            if (d["rows"] is JArray rows)
            {
                int shown = 0;
                foreach (JObject row in rows)
                {
                    if (row["cards"] is JArray order && !(d["lineup"] is JArray))   // older advice
                        ShowLineup(order);
                    if (shown++ >= _settings.MaxSteps)
                        break;
                    _panel.Children.Add(Row(row));
                }
                if (rows.Count > _settings.MaxSteps)
                    _panel.Children.Add(Text($"… +{rows.Count - _settings.MaxSteps}", 12, color: Color.FromRgb(190, 190, 190)));
            }
            if (d["notes"] is JArray notes)
                foreach (JToken note in notes)
                {
                    var t = Text((string)note, 12, color: Color.FromRgb(160, 210, 255));
                    t.Margin = new Thickness(0, 3, 0, 0);
                    _panel.Children.Add(t);
                }
            if (d["warnings"] is JArray warnings)
                foreach (JToken w in warnings)
                    _panel.Children.Add(Text("⚠ " + (string)w, 11, color: Color.FromRgb(240, 190, 90)));
        }

        /// <summary>One step: "3. Play [H2] [tile: name] → [B4]", "1. Buy [T3] [tile]",
        /// "2. Magnetize [H1] [tile] → [B2] [tile]", "5. Arrange [tile] [tile] ...".</summary>
        FrameworkElement Row(JObject row)
        {
            var line = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 2, 0, 0) };
            line.Children.Add(Text(row.Value<int>("n") + ".", 13, margin: new Thickness(0, 0, 4, 0), width: 18));
            line.Children.Add(Text(row.Value<string>("verb") ?? "", 13, FontWeights.SemiBold,
                margin: new Thickness(0, 0, 6, 0)));
            AddBadge(line, row.Value<string>("badge"), row.Value<string>("badge_kind"));
            if (row["card_id"] != null && row["card_id"].Type != JTokenType.Null)
                line.Children.Add(Tile(row.Value<string>("card_id"), row.Value<string>("name"), 150, 30));
            if (row["target_card_id"] != null && row["target_card_id"].Type != JTokenType.Null)
            {
                if (row["card_id"] != null && row["card_id"].Type != JTokenType.Null)
                    line.Children.Add(Glyph("→"));
                AddBadge(line, row.Value<string>("target_badge"), row.Value<string>("target_badge_kind"));
                line.Children.Add(Tile(row.Value<string>("target_card_id"), row.Value<string>("target_name"), 118, 30));
            }
            if (!string.IsNullOrEmpty(row.Value<string>("place")))
            {
                line.Children.Add(Glyph("→"));
                AddBadge(line, row.Value<string>("place"), "board");
            }
            if (row["cards"] is JArray)   // Arrange: the order is in the lineup panel below
                line.Children.Add(Glyph("↓"));
            return line;
        }

        /// <summary>A few genres, one line each: its key card's tile with the genre's name, its share, and
        /// the one or two cards it needs most.</summary>
        void ShowGenres(JArray genres)
        {
            _genrePanel.Children.Clear();
            _hasGenres = genres.Count > 0;
            bool zh = (_settings.Locale ?? "").StartsWith("zh");
            foreach (JObject g in genres)
            {
                var line = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 2, 0, 0) };
                line.Children.Add(Tile(g.Value<string>("card_id"), g.Value<string>("name"), 190, 26));
                line.Children.Add(Text($"{g.Value<int>("pct")}%", 14, FontWeights.Bold, margin: new Thickness(8, 0, 8, 0),
                    width: 40));
                if (g["need"] is JArray need && need.Count > 0)
                {
                    line.Children.Add(Text(zh ? "缺" : "needs", 12, color: Color.FromRgb(190, 190, 190),
                        margin: new Thickness(0, 0, 4, 0)));
                    foreach (JObject c in need)
                        line.Children.Add(Tile(c.Value<string>("card_id"), c.Value<string>("name"), 120, 22, 3));
                }
                _genrePanel.Children.Add(line);
            }
        }

        /// <summary>The recommended warband order, one card per line, position 1 (left) first.</summary>
        void ShowLineup(JArray cards)
        {
            _lineupPanel.Children.Clear();
            _hasLineup = cards.Count > 0;
            bool zh = (_settings.Locale ?? "").StartsWith("zh");
            _lineupPanel.Children.Add(Text(zh ? "推荐站位（从左到右）" : "Recommended lineup (left to right)", 14,
                FontWeights.SemiBold, margin: new Thickness(0, 0, 0, 3)));
            int i = 0;
            foreach (JObject c in cards)
            {
                var line = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 2, 0, 0) };
                AddBadge(line, (++i).ToString(), "board");
                // Copies of a card told apart: golden, Attack/Health, keywords
                string name = (c.Value<bool?>("golden") == true ? "★ " : "") + c.Value<string>("name");
                line.Children.Add(Tile(c.Value<string>("card_id"), name, 190, 28));
                if (c["atk"] != null && c["atk"].Type != JTokenType.Null)
                    line.Children.Add(Text($"{c.Value<int>("atk")}/{c.Value<int>("hp")}", 14, FontWeights.Bold,
                        margin: new Thickness(8, 0, 4, 0)));
                if (c["keywords"] is JArray kws)
                    foreach (JToken k in kws)
                        line.Children.Add(new Border
                        {
                            Background = new SolidColorBrush(Color.FromRgb(70, 70, 78)),
                            CornerRadius = new CornerRadius(3),
                            Padding = new Thickness(4, 0, 4, 0),
                            Margin = new Thickness(0, 0, 3, 0),
                            Height = 20,
                            VerticalAlignment = VerticalAlignment.Center,
                            Child = new TextBlock
                            {
                                Text = (string)k, Foreground = Brushes.White, FontFamily = Font, FontSize = 12,
                                VerticalAlignment = VerticalAlignment.Center,
                            },
                        });
                _lineupPanel.Children.Add(line);
            }
        }

        static void AddBadge(Panel line, string text, string kind)
        {
            if (string.IsNullOrEmpty(text))
                return;
            Color c;
            switch (kind)
            {
                case "hand": c = Color.FromRgb(45, 105, 190); break;
                case "board": c = Color.FromRgb(40, 140, 80); break;
                case "tavern": c = Color.FromRgb(175, 120, 30); break;
                case "power": c = Color.FromRgb(125, 70, 170); break;
                case "choose": c = Color.FromRgb(90, 90, 90); break;
                default: c = Color.FromRgb(90, 90, 90); break;
            }
            line.Children.Add(new Border
            {
                Background = new SolidColorBrush(c),
                CornerRadius = new CornerRadius(3),
                Padding = new Thickness(5, 0, 5, 0),
                Margin = new Thickness(0, 0, 4, 0),
                MinWidth = 34,
                Height = 24,
                VerticalAlignment = VerticalAlignment.Center,
                Child = new TextBlock
                {
                    Text = text, Foreground = Brushes.White, FontFamily = Font, FontWeight = FontWeights.Bold,
                    FontSize = 14, HorizontalAlignment = HorizontalAlignment.Center,
                    VerticalAlignment = VerticalAlignment.Center,
                },
            });
        }

        static TextBlock Glyph(string glyph) => new TextBlock
        {
            Text = glyph, Foreground = Brushes.White, FontSize = 16, FontFamily = new FontFamily("Segoe UI Symbol, Segoe UI"),
            Margin = new Thickness(4, 0, 4, 0), VerticalAlignment = VerticalAlignment.Center,
        };

        /// <summary>The card's tile art (as in HDT's deck list) with its name over it.</summary>
        FrameworkElement Tile(string cardId, string name, double width, double height, double gap = 0)
        {
            var grid = new Grid
            {
                Width = width, Height = height, ClipToBounds = true, VerticalAlignment = VerticalAlignment.Center,
                Background = new SolidColorBrush(Color.FromRgb(45, 45, 50)), Margin = new Thickness(0, 0, gap, 0),
            };
            if (_settings.CardArt && !_artBroken && !string.IsNullOrEmpty(cardId))
            {
                var image = new Image { Stretch = Stretch.UniformToFill, HorizontalAlignment = HorizontalAlignment.Right };
                try
                {
                    LoadTile(cardId, image);
                    grid.Children.Add(image);
                }
                catch (Exception e) when (e is MissingMemberException || e is TypeLoadException || e is FileNotFoundException)
                {
                    _artBroken = true;   // a newer HDT changed the API: show names only from now on
                }
                catch (Exception)
                {
                    // this card's art isn't available: its name alone
                }
            }
            // Darker on the left, where the name is
            grid.Children.Add(new Border
            {
                Background = new LinearGradientBrush(Color.FromArgb(235, 20, 20, 22), Color.FromArgb(20, 20, 20, 22), 0),
            });
            grid.Children.Add(new TextBlock
            {
                Text = name ?? cardId ?? "?", Foreground = Brushes.White, FontFamily = Font, FontWeight = FontWeights.SemiBold,
                FontSize = 13 * height / 30, Margin = new Thickness(6, 0, 4, 0), VerticalAlignment = VerticalAlignment.Center,
                TextTrimming = TextTrimming.CharacterEllipsis,
                Effect = new DropShadowEffect { ShadowDepth = 1, BlurRadius = 3, Opacity = 1, Color = Colors.Black },
            });
            return grid;
        }

        /// <summary>HDT's own tile cache and downloader; a tile not cached yet appears when it arrives.
        /// Kept apart so a missing HDT type fails here (when this method is compiled), not in Tile.</summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        static void LoadTile(string cardId, Image image)
        {
            var card = HdtDatabase.GetCardFromId(cardId);
            if (card == null)
                return;
            var downloader = AssetDownloaders.cardTileDownloader;
            if (downloader == null)
                return;
            BitmapImage cached = downloader.TryGetAssetData(card, false);
            if (cached != null && cached != downloader.PlaceholderAsset)
            {
                image.Source = cached;
                return;
            }
            downloader.GetAssetData(card, false).ContinueWith(t =>
            {
                if (t.Status == TaskStatus.RanToCompletion && t.Result != null)
                    image.Dispatcher.BeginInvoke(new Action(() => image.Source = t.Result));
            });
        }

        static TextBlock Text(string text, double size, FontWeight? weight = null, Color? color = null,
            Thickness? margin = null, double width = double.NaN) => new TextBlock
        {
            Text = text,
            Foreground = new SolidColorBrush(color ?? Colors.White),
            FontSize = size,
            FontWeight = weight ?? FontWeights.Normal,
            // Chinese card names fall back to Microsoft YaHei UI
            FontFamily = Font,
            TextWrapping = TextWrapping.Wrap,
            MaxWidth = 520,
            Width = width,
            Margin = margin ?? new Thickness(0),
            VerticalAlignment = VerticalAlignment.Center,
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
            _lineupPanel = new StackPanel();
            _lineupBox = new Border
            {
                Child = _lineupPanel,
                Padding = new Thickness(8, 5, 8, 6),
                CornerRadius = new CornerRadius(4),
                Background = new SolidColorBrush(Color.FromArgb(195, 25, 25, 28)),
                Visibility = Visibility.Collapsed,
                IsHitTestVisible = false,
                LayoutTransform = new ScaleTransform(_settings.Scale, _settings.Scale),
            };
            Core.OverlayCanvas.Children.Add(_lineupBox);
            _genrePanel = new StackPanel();
            _genreBox = new Border
            {
                Child = _genrePanel,
                Padding = new Thickness(8, 5, 8, 6),
                CornerRadius = new CornerRadius(4),
                Background = new SolidColorBrush(Color.FromArgb(195, 25, 25, 28)),
                Visibility = Visibility.Collapsed,
                IsHitTestVisible = false,
                LayoutTransform = new ScaleTransform(_settings.Scale, _settings.Scale),
            };
            Core.OverlayCanvas.Children.Add(_genreBox);
            PositionOverlay();
        }

        static string SettingsPath => Path.Combine(Path.GetDirectoryName(typeof(Plugin).Assembly.Location) ?? "",
            "taverngym.plugin.json");

        static DateTime SettingsWritten() => File.Exists(SettingsPath) ? File.GetLastWriteTime(SettingsPath) : DateTime.MinValue;

        /// <summary>Overlay position, scale and the rest follow taverngym.plugin.json while HDT runs
        /// (the advisor's own options apply at its next start).</summary>
        void ReloadSettingsIfChanged()
        {
            DateTime written = SettingsWritten();
            if (written == _settingsRead)
                return;
            _settingsRead = written;
            _settings = Settings.Load(Path.GetDirectoryName(typeof(Plugin).Assembly.Location));
            _box.LayoutTransform = new ScaleTransform(_settings.Scale, _settings.Scale);
            _lineupBox.LayoutTransform = new ScaleTransform(_settings.Scale, _settings.Scale);
            _genreBox.LayoutTransform = new ScaleTransform(_settings.Scale, _settings.Scale);
            _lastRead = DateTime.MinValue;   // redraw with the new settings
        }

        void PositionOverlay()
        {
            Canvas canvas = Core.OverlayCanvas;
            double left = canvas.ActualWidth * _settings.OverlayLeft, top = canvas.ActualHeight * _settings.OverlayTop;
            Canvas.SetLeft(_box, left);
            Canvas.SetTop(_box, top);
            if (_lineupBox != null)   // right below the advice (its rendered height, scale included)
            {
                double below = top + (_box.Visibility == Visibility.Visible ? _box.ActualHeight : 0) + 6;
                Canvas.SetLeft(_lineupBox, left);
                Canvas.SetTop(_lineupBox, below);
                if (_lineupBox.Visibility == Visibility.Visible)
                    below += _lineupBox.ActualHeight + 6;
                if (_genreBox != null)   // and the genre panel under the lineup
                {
                    Canvas.SetLeft(_genreBox, left);
                    Canvas.SetTop(_genreBox, below);
                }
            }
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
        public double OverlayTop = 0.42;
        public double StaleSeconds = 90;
        public int MaxSteps = 6;
        public double Scale = 1.0;
        public bool CardArt = true;

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
                    s.CardArt = (bool?)j["card_art"] ?? s.CardArt;
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
