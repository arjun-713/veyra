use std::fs;
use std::path::PathBuf;

use serde_json::{json, Value};
use veyra_lib::control::RuntimeController;

fn main() {
    let result = execute(std::env::args().skip(1).collect());
    match result {
        Ok(value) => println!("{}", json!({"ok": true, "result": value})),
        Err(error) => {
            println!("{}", json!({"ok": false, "error": {"message": error}}));
            std::process::exit(1);
        }
    }
}

fn execute(args: Vec<String>) -> Result<Value, String> {
    let repo = std::env::var_os("VEYRA_REPO")
        .map(PathBuf::from)
        .or_else(|| std::env::current_dir().ok())
        .ok_or_else(|| "cannot determine repository directory".to_owned())?;
    let mut controller = RuntimeController::new(repo);
    match args.as_slice() {
        [command] if command == "status" => controller.refresh_status(),
        [command, action] if command == "runtime" && action == "start" => {
            controller.command("start", json!({}))
        }
        [command, action] if command == "runtime" && action == "stop" => {
            controller.stop().map(|_| controller.status())
        }
        [command, action] if command == "runtime" && action == "restart" => {
            controller.command("restart", json!({}))
        }
        [command, path] if command == "configure" => {
            let config = read_json(path)?;
            controller.configure(config)
        }
        [command, action, dataset, root] if command == "dataset" && action == "open" => {
            controller.datasets(dataset, &PathBuf::from(root))
        }
        [command, action] if command == "playback" && action == "play" => {
            controller.command("start", json!({}))
        }
        [command, action] if command == "playback" && action == "pause" => {
            controller.command("pause", json!({}))
        }
        [command, action, index] if command == "playback" && action == "seek" => {
            let index = index
                .parse::<u64>()
                .map_err(|_| "seek index must be an integer".to_owned())?;
            controller.command("seek", json!({"index": index}))
        }
        [command, action, policy] if command == "policy" && action == "set" => {
            controller.command("policy", json!({"policy": policy}))
        }
        [command, action, layer] if command == "layer" && action == "set" => {
            controller.command("layer", json!({"layer": layer}))
        }
        [command] if command == "metrics" => controller.refresh_status(),
        [command] if command == "diagnostics" => Ok(controller.diagnostics()),
        _ => Err(concat!(
            "usage: veyra-cli status | runtime start|stop|restart | ",
            "configure <json> | dataset open <format> <root> | ",
            "playback play|pause|seek <frame> | policy set <policy> | ",
            "metrics | diagnostics"
        )
        .to_owned()),
    }
}

fn read_json(path: &str) -> Result<Value, String> {
    let text = fs::read_to_string(path).map_err(|error| format!("cannot read {path}: {error}"))?;
    serde_json::from_str(&text).map_err(|error| format!("invalid JSON configuration: {error}"))
}
