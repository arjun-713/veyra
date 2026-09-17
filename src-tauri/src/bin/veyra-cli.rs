use std::fs;

use serde_json::{json, Value};
use veyra_lib::control::{ControlClient, ControlClientError};

fn main() {
    let output = match ControlClient::from_env()
        .and_then(|mut client| execute(&mut client, std::env::args().skip(1).collect()))
    {
        Ok(value) => json!({"ok": true, "result": value}),
        Err(error) => error_json(&error),
    };
    println!("{output}");
    if output["ok"] == false {
        std::process::exit(1);
    }
}

fn error_json(error: &ControlClientError) -> Value {
    match error {
        ControlClientError::Daemon { code, message } => {
            json!({"ok": false, "error": {"code": code, "message": message}})
        }
        _ => json!({"ok": false, "error": {"code": "CLI_ERROR", "message": error.to_string()}}),
    }
}

fn execute(client: &mut ControlClient, args: Vec<String>) -> Result<Value, ControlClientError> {
    match args.as_slice() {
        [command] if command == "status" || command == "metrics" => {
            client.request("status", json!({}))
        }
        [command, action] if command == "runtime" && action == "start" => {
            command_request(client, "start", json!({}))
        }
        [command, action] if command == "runtime" && action == "stop" => {
            client.request("shutdown", json!({}))
        }
        [command, action] if command == "runtime" && action == "restart" => {
            command_request(client, "restart", json!({}))
        }
        [command, path] if command == "configure" => {
            let config = read_json(path)?;
            client.request("configure", json!({"config": config}))
        }
        [command, action, dataset, root] if command == "dataset" && action == "open" => {
            client.request("datasets", json!({"dataset": dataset, "root": root}))
        }
        [command, action] if command == "playback" && action == "play" => {
            command_request(client, "start", json!({}))
        }
        [command, action] if command == "playback" && action == "pause" => {
            command_request(client, "pause", json!({}))
        }
        [command, action, index] if command == "playback" && action == "seek" => {
            let index = index.parse::<u64>().map_err(|_| {
                ControlClientError::Configuration("seek index must be an integer".to_owned())
            })?;
            command_request(client, "seek", json!({"index": index}))
        }
        [command, action, policy] if command == "policy" && action == "set" => {
            command_request(client, "policy", json!({"policy": policy}))
        }
        [command, action, layer] if command == "layer" && action == "set" => {
            command_request(client, "layer", json!({"layer": layer}))
        }
        [command] if command == "diagnostics" => client.request("diagnostics", json!({})),
        _ => Err(ControlClientError::Configuration(
            concat!(
                "usage: veyra-cli status | runtime start|stop|restart | ",
                "configure <json> | dataset open <format> <root> | ",
                "playback play|pause|seek <frame> | policy set <policy> | ",
                "metrics | diagnostics"
            )
            .to_owned(),
        )),
    }
}

fn command_request(
    client: &mut ControlClient,
    name: &str,
    args: Value,
) -> Result<Value, ControlClientError> {
    client.request("command", json!({"name": name, "args": args}))
}

fn read_json(path: &str) -> Result<Value, ControlClientError> {
    let text = fs::read_to_string(path).map_err(|error| {
        ControlClientError::Configuration(format!("cannot read {path}: {error}"))
    })?;
    serde_json::from_str(&text).map_err(|error| {
        ControlClientError::Configuration(format!("invalid JSON configuration: {error}"))
    })
}

#[cfg(test)]
mod tests {
    use super::error_json;
    use veyra_lib::control::ControlClientError;

    #[test]
    fn cli_wrapper_preserves_structured_daemon_error_information() {
        let output = error_json(&ControlClientError::Daemon {
            code: "CONTROLLER_ERROR".to_owned(),
            message: "runtime is not ready".to_owned(),
        });
        assert_eq!(output["ok"], false);
        assert_eq!(output["error"]["code"], "CONTROLLER_ERROR");
        assert_eq!(output["error"]["message"], "runtime is not ready");
    }
}
