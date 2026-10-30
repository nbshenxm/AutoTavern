//! The teacher bot (`RulesConfig::teacher`) against the plain bot: bot-only games, four seats
//! each (which four rotates with the seed), mean placement of each side.
//! Usage: cargo run --release -p taverngym --example teacher_eval -- config.json [games]

use taverngym::RulesConfig;
use taverngym::bot::run_bot_game;

fn main() {
    let mut args = std::env::args().skip(1);
    let path = args.next().expect("a RulesConfig JSON with a teacher");
    let games: u64 = args.next().and_then(|s| s.parse().ok()).unwrap_or(1000);
    let base: RulesConfig =
        serde_json::from_str(&std::fs::read_to_string(&path).expect("config")).expect("json");
    let (mut teacher, mut plain) = (vec![], vec![]);
    for seed in 0..games {
        let mut cfg = base.clone();
        let seats: Vec<usize> = (0..4).map(|k| (seed as usize + 2 * k) % 8).collect();
        cfg.teacher.as_mut().expect("teacher").seats = seats.clone();
        let g = run_bot_game(2_000_000 + seed, cfg);
        for p in &g.players {
            let side = if seats.contains(&p.id) { &mut teacher } else { &mut plain };
            side.push(p.placement as f64);
        }
    }
    for (name, v) in [("teacher", &teacher), ("plain", &plain)] {
        let n = v.len() as f64;
        let m = v.iter().sum::<f64>() / n;
        let sd = (v.iter().map(|x| (x - m).powi(2)).sum::<f64>() / n).sqrt();
        println!("{name:8}: mean place {m:.3} ± {:.3} (n {})", sd / n.sqrt(), v.len());
    }
}
