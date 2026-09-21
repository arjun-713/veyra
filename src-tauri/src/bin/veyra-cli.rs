use std::fs;

use serde_json::{json, Value};
use veyra_lib::control::{ControlClient, ControlClientError};

fn main() {
    let output = match run(std::env::args().skip(1).collect()) {
        Ok(value) => json!({"ok": true, "result": value}),
        Err(error) => error_json(&error),
    };
    println!("{output}");
    if output["ok"] == false {
        std::process::exit(1);
    }
}

#[derive(Debug, PartialEq)]
enum CliOperation {
    Request { command: &'static str, args: Value },
}

fn run(args: Vec<String>) -> Result<Value, ControlClientError> {
    // Output is always the JSON envelope printed by `main`; accept a trailing
    // `--json` on every command so scripts can request machine output uniformly.
    let args = strip_json_flag(args);
    let operation = parse_args(&args)?;
    let mut client = ControlClient::from_env()?;
    execute(&mut client, operation)
}

fn strip_json_flag(args: Vec<String>) -> Vec<String> {
    if matches!(args.last(), Some(flag) if flag == "--json") {
        args[..args.len() - 1].to_vec()
    } else {
        args
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

fn execute(
    client: &mut ControlClient,
    operation: CliOperation,
) -> Result<Value, ControlClientError> {
    match operation {
        CliOperation::Request { command, args } => client.request(command, args),
    }
}

fn parse_args(args: &[String]) -> Result<CliOperation, ControlClientError> {
    match args {
        [command] if command == "status" || command == "metrics" => {
            Ok(request("status", json!({})))
        }
        [command, flag] if command == "metrics" && flag == "--json" => {
            Ok(request("status", json!({})))
        }
        [command, action] if command == "runtime" && action == "start" => {
            Ok(command_request("start", json!({})))
        }
        [command, action] if command == "runtime" && action == "stop" => {
            Ok(request("stop", json!({})))
        }
        [command, action] if command == "runtime" && action == "restart" => {
            Ok(command_request("restart", json!({})))
        }
        [command, path] if command == "configure" => {
            let config = read_json(path)?;
            Ok(request("configure", json!({"config": config})))
        }
        [command, action, dataset, root] if command == "dataset" && action == "info" => {
            validate_dataset(dataset, root)?;
            Ok(request(
                "datasets",
                json!({"dataset": dataset, "root": root}),
            ))
        }
        [command, action, dataset, root] if command == "dataset" && action == "open" => {
            validate_dataset(dataset, root)?;
            Ok(request(
                "open_dataset",
                json!({"dataset": dataset, "root": root}),
            ))
        }
        [command, action, dataset, root, sequence] if command == "dataset" && action == "open" => {
            validate_dataset(dataset, root)?;
            if sequence.is_empty() || sequence.len() > 64 {
                return Err(invalid_argument(
                    "dataset sequence must be a bounded non-empty string",
                ));
            }
            Ok(request(
                "open_dataset",
                json!({
                    "dataset": dataset,
                    "root": root,
                    "sequence": sequence
                }),
            ))
        }
        [command, action] if command == "playback" && action == "play" => {
            Ok(command_request("start", json!({})))
        }
        [command, action] if command == "playback" && action == "pause" => {
            Ok(command_request("pause", json!({})))
        }
        [command, action, index] if command == "playback" && action == "seek" => {
            let index = index
                .parse::<u64>()
                .map_err(|_| invalid_argument("seek index must be a non-negative integer"))?;
            Ok(command_request("seek", json!({"index": index})))
        }
        [command, action, policy] if command == "policy" && action == "set" => {
            validate_policy(policy)?;
            Ok(command_request("policy", json!({"policy": policy})))
        }
        [command, action, layer] if command == "layer" && action == "set" => {
            validate_layer(layer)?;
            Ok(command_request("layer", json!({"layer": layer})))
        }
        [command] if command == "diagnostics" => Ok(request("diagnostics", json!({}))),
        [command, action] if command == "benchmark" && action == "run" => {
            Ok(command_request("benchmark", json!({})))
        }
        [command, action] if command == "validation" && action == "run" => {
            Ok(command_request("validation", json!({})))
        }
        [command, action, path] if command == "config" && action == "validate" => {
            let config = read_json(path)?;
            Ok(request("config_validate", json!({"config": config})))
        }
        _ => Err(ControlClientError::Configuration(
            concat!(
                "usage: veyra-cli status | metrics [--json] | runtime start|stop|restart | ",
                "configure <json> | config validate <json> | dataset info <format> <root> | ",
                "dataset open <format> <root> [sequence] | ",
                "playback play|pause|seek <frame> | policy set <policy> | ",
                "layer set <layer> | diagnostics | benchmark run | validation run"
            )
            .to_owned(),
        )),
    }
}

fn request(command: &'static str, args: Value) -> CliOperation {
    CliOperation::Request { command, args }
}

fn command_request(name: &'static str, args: Value) -> CliOperation {
    request("command", json!({"name": name, "args": args}))
}

fn invalid_argument(message: &str) -> ControlClientError {
    ControlClientError::Daemon {
        code: "INVALID_ARGUMENT".to_owned(),
        message: message.to_owned(),
    }
}

fn validate_dataset(dataset: &str, root: &str) -> Result<(), ControlClientError> {
    if !matches!(
        dataset,
        "rellis3d" | "semanticposs" | "semantickitti" | "generic"
    ) {
        return Err(invalid_argument("unsupported dataset format"));
    }
    if root.is_empty() {
        return Err(invalid_argument("dataset root must be a non-empty path"));
    }
    Ok(())
}

fn validate_policy(policy: &str) -> Result<(), ControlClientError> {
    if matches!(
        policy,
        "uniform5" | "uniform40" | "distance_lod" | "utility_lod"
    ) {
        Ok(())
    } else {
        Err(invalid_argument("unsupported map policy"))
    }
}

fn validate_layer(layer: &str) -> Result<(), ControlClientError> {
    if matches!(
        layer,
        "semantic"
            | "elevation"
            | "ground"
            | "terrain"
            | "traversability"
            | "motion"
            | "lod"
            | "utility"
    ) {
        Ok(())
    } else {
        Err(invalid_argument("unsupported layer"))
    }
}

fn read_json(path: &str) -> Result<Value, ControlClientError> {
    const MAX_CONFIG_FILE_BYTES: u64 = 1024 * 1024;
    let size = fs::metadata(path)
        .map_err(|error| ControlClientError::Configuration(format!("cannot read {path}: {error}")))?
        .len();
    if size > MAX_CONFIG_FILE_BYTES {
        return Err(ControlClientError::Configuration(format!(
            "configuration file {path} exceeds 1 MiB"
        )));
    }
    let text = fs::read_to_string(path).map_err(|error| {
        ControlClientError::Configuration(format!("cannot read {path}: {error}"))
    })?;
    serde_json::from_str(&text).map_err(|error| {
        ControlClientError::Configuration(format!("invalid JSON configuration: {error}"))
    })
}

#[cfg(test)]
mod tests {
    use super::{error_json, parse_args, CliOperation};
    use serde_json::json;
    use veyra_lib::control::ControlClientError;

    #[test]
    fn trailing_json_flag_is_stripped_from_every_command() {
        assert_eq!(
            super::strip_json_flag(vec!["status".to_owned(), "--json".to_owned()]),
            vec!["status".to_owned()]
        );
        assert_eq!(
            super::strip_json_flag(vec!["status".to_owned()]),
            vec!["status".to_owned()]
        );
        assert!(super::strip_json_flag(vec![]).is_empty());
        // parse_args then accepts the stripped form as the plain command.
        let stripped = super::strip_json_flag(vec!["diagnostics".to_owned(), "--json".to_owned()]);
        assert_eq!(
            parse_args(&stripped),
            Ok(CliOperation::Request {
                command: "diagnostics",
                args: json!({}),
            })
        );
    }

    #[test]
    fn parses_metrics_json_as_the_same_status_alias() {
        assert_eq!(
            parse_args(&["metrics".to_owned()]),
            Ok(CliOperation::Request {
                command: "status",
                args: json!({}),
            })
        );
        assert_eq!(
            parse_args(&["metrics".to_owned(), "--json".to_owned()]),
            Ok(CliOperation::Request {
                command: "status",
                args: json!({}),
            })
        );
    }

    #[test]
    fn runtime_stop_requests_a_runtime_stop_without_shutting_down_the_daemon() {
        assert_eq!(
            parse_args(&["runtime".to_owned(), "stop".to_owned()]),
            Ok(CliOperation::Request {
                command: "stop",
                args: json!({}),
            })
        );
    }

    #[test]
    fn dataset_info_requests_metadata_without_opening_a_runtime_session() {
        assert_eq!(
            parse_args(&[
                "dataset".to_owned(),
                "info".to_owned(),
                "generic".to_owned(),
                "/data/example".to_owned(),
            ]),
            Ok(CliOperation::Request {
                command: "datasets",
                args: json!({"dataset": "generic", "root": "/data/example"}),
            })
        );
    }

    #[test]
    fn dataset_open_uses_the_shared_controller_operation() {
        assert_eq!(
            parse_args(&[
                "dataset".to_owned(),
                "open".to_owned(),
                "semanticposs".to_owned(),
                "/data/example".to_owned(),
            ]),
            Ok(CliOperation::Request {
                command: "open_dataset",
                args: json!({"dataset": "semanticposs", "root": "/data/example"}),
            })
        );
    }

    #[test]
    fn benchmark_run_uses_the_shared_runtime_benchmark_operation() {
        assert_eq!(
            parse_args(&["benchmark".to_owned(), "run".to_owned()]),
            Ok(CliOperation::Request {
                command: "command",
                args: json!({"name": "benchmark", "args": {}}),
            })
        );
    }

    #[test]
    fn validates_seek_policy_and_layer_before_network_use() {
        assert!(parse_args(&[
            "playback".to_owned(),
            "seek".to_owned(),
            "not-an-integer".to_owned(),
        ])
        .is_err());
        assert!(
            parse_args(&["policy".to_owned(), "set".to_owned(), "unknown".to_owned(),]).is_err()
        );
        assert!(
            parse_args(&["layer".to_owned(), "set".to_owned(), "unknown".to_owned(),]).is_err()
        );
    }

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

    #[test]
    fn oversized_config_file_is_rejected_before_parsing() {
        let path = std::env::temp_dir().join(format!("veyra-cli-config-{}", std::process::id()));
        std::fs::write(&path, vec![b'{'; 1024 * 1024 + 1]).unwrap();
        let error = super::read_json(path.to_str().unwrap()).unwrap_err();
        assert!(error.to_string().contains("exceeds 1 MiB"));
        std::fs::remove_file(path).unwrap();
    }
}
