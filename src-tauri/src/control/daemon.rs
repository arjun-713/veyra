use std::io::{self, BufRead, BufReader, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::path::PathBuf;

use serde_json::{json, Map, Value};

use super::RuntimeController;

pub const PROTOCOL_VERSION: u64 = 1;
const MAX_FRAME_BYTES: usize = 64 * 1024;
const MAX_ID_BYTES: usize = 128;
const MAX_COMMAND_BYTES: usize = 64;

pub fn serve(repo: PathBuf, bind_addr: SocketAddr, secret: String) -> Result<(), String> {
    validate_bind_address(bind_addr)?;
    validate_secret(&secret)?;
    let listener = TcpListener::bind(bind_addr)
        .map_err(|error| format!("failed to bind control endpoint {bind_addr}: {error}"))?;
    eprintln!(
        "veyra-control listening on {}",
        listener.local_addr().unwrap_or(bind_addr)
    );
    serve_listener(listener, RuntimeController::new(repo), secret)
        .map_err(|error| error.to_string())
}

pub fn serve_listener(
    listener: TcpListener,
    mut controller: RuntimeController,
    secret: String,
) -> io::Result<()> {
    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                if handle_connection(stream, &mut controller, &secret)? {
                    return Ok(());
                }
            }
            Err(error) => eprintln!("veyra-control connection failed: {error}"),
        }
    }
    Ok(())
}

fn validate_bind_address(bind_addr: SocketAddr) -> Result<(), String> {
    if bind_addr.ip() != std::net::IpAddr::V4(Ipv4Addr::LOCALHOST) {
        return Err("control endpoint must bind to 127.0.0.1".to_owned());
    }
    Ok(())
}

fn validate_secret(secret: &str) -> Result<(), String> {
    if !(32..=256).contains(&secret.len()) || !secret.bytes().all(|byte| byte.is_ascii_graphic()) {
        return Err("control secret must contain 32-256 printable ASCII bytes".to_owned());
    }
    Ok(())
}

fn handle_connection(
    stream: TcpStream,
    controller: &mut RuntimeController,
    secret: &str,
) -> io::Result<bool> {
    let mut reader = BufReader::new(stream.try_clone()?);
    let mut writer = stream;
    let mut line = Vec::new();

    loop {
        line.clear();
        match read_frame(&mut reader, &mut line)? {
            Frame::Eof => return Ok(false),
            Frame::TooLarge => {
                write_response(
                    &mut writer,
                    &error_response(Value::Null, "FRAME_TOO_LARGE", "request exceeds 64 KiB"),
                )?;
                continue;
            }
            Frame::Line => {
                let response = dispatch_line(&line, controller, secret);
                let shutdown = response.shutdown;
                write_response(&mut writer, &response.value)?;
                if shutdown {
                    return Ok(true);
                }
            }
        }
    }
}

enum Frame {
    Eof,
    Line,
    TooLarge,
}

fn read_frame<R: BufRead>(reader: &mut R, line: &mut Vec<u8>) -> io::Result<Frame> {
    loop {
        let available = reader.fill_buf()?;
        if available.is_empty() {
            return Ok(if line.is_empty() {
                Frame::Eof
            } else {
                Frame::Line
            });
        }

        let newline = available.iter().position(|byte| *byte == b'\n');
        let amount = newline.map_or(available.len(), |index| index + 1);
        let next_len = line.len().saturating_add(amount);
        if next_len > MAX_FRAME_BYTES {
            reader.consume(amount);
            while newline.is_none() {
                let chunk = reader.fill_buf()?;
                if chunk.is_empty() {
                    break;
                }
                if let Some(index) = chunk.iter().position(|byte| *byte == b'\n') {
                    reader.consume(index + 1);
                    break;
                }
                let chunk_len = chunk.len();
                reader.consume(chunk_len);
            }
            return Ok(Frame::TooLarge);
        }

        line.extend_from_slice(&available[..amount]);
        reader.consume(amount);
        if newline.is_some() {
            return Ok(Frame::Line);
        }
    }
}

struct DispatchResponse {
    value: Value,
    shutdown: bool,
}

fn dispatch_line(
    line: &[u8],
    controller: &mut RuntimeController,
    secret: &str,
) -> DispatchResponse {
    let request = match serde_json::from_slice::<Value>(line) {
        Ok(value) => value,
        Err(error) => {
            return DispatchResponse {
                value: error_response(Value::Null, "MALFORMED_JSON", &error.to_string()),
                shutdown: false,
            }
        }
    };

    let object = match request.as_object() {
        Some(object) => object,
        None => {
            return DispatchResponse {
                value: error_response(Value::Null, "INVALID_REQUEST", "request must be an object"),
                shutdown: false,
            }
        }
    };
    let id = match bounded_string(object, "id", MAX_ID_BYTES) {
        Ok(id) => Value::String(id.to_owned()),
        Err(error) => {
            return DispatchResponse {
                value: error_response(Value::Null, "INVALID_REQUEST", &error),
                shutdown: false,
            }
        }
    };
    if object.get("schema_version").and_then(Value::as_u64) != Some(PROTOCOL_VERSION) {
        return DispatchResponse {
            value: error_response(id, "UNSUPPORTED_SCHEMA_VERSION", "schema_version must be 1"),
            shutdown: false,
        };
    }
    if !constant_time_equal(
        object
            .get("authorization")
            .and_then(Value::as_str)
            .unwrap_or("")
            .as_bytes(),
        secret.as_bytes(),
    ) {
        return DispatchResponse {
            value: error_response(id, "UNAUTHORIZED", "control authorization failed"),
            shutdown: false,
        };
    }
    let command = match bounded_string(object, "command", MAX_COMMAND_BYTES) {
        Ok(command) => command,
        Err(error) => {
            return DispatchResponse {
                value: error_response(id, "INVALID_REQUEST", &error),
                shutdown: false,
            }
        }
    };
    let args = match object.get("args").and_then(Value::as_object) {
        Some(args) => args,
        None => {
            return DispatchResponse {
                value: error_response(id, "INVALID_ARGS", "args must be an object"),
                shutdown: false,
            }
        }
    };

    if !matches!(
        command,
        "status"
            | "configure"
            | "config_validate"
            | "datasets"
            | "command"
            | "diagnostics"
            | "shutdown"
    ) {
        return DispatchResponse {
            value: error_response(id, "UNKNOWN_COMMAND", "unrecognized command"),
            shutdown: false,
        };
    }

    if command == "shutdown" {
        return match controller.stop() {
            Ok(()) => DispatchResponse {
                value: success_response(id, json!({"status": controller.status()})),
                shutdown: true,
            },
            Err(error) => DispatchResponse {
                value: error_response(id, "CONTROLLER_ERROR", &error),
                shutdown: false,
            },
        };
    }

    let result = match command {
        "status" => controller.refresh_status(),
        "configure" => {
            required_object(args, "config").and_then(|config| controller.configure(config))
        }
        "config_validate" => {
            required_object(args, "config").and_then(|config| controller.validate_config(config))
        }
        "datasets" => required_string(args, "dataset").and_then(|dataset| {
            required_string(args, "root")
                .and_then(|root| controller.datasets(dataset, &PathBuf::from(root)))
        }),
        "command" => dispatch_controller_command(args, controller),
        "diagnostics" => Ok(controller.diagnostics()),
        "shutdown" => unreachable!(),
        _ => unreachable!(),
    };

    DispatchResponse {
        value: match result {
            Ok(result) => success_response(id, result),
            Err(error) => error_response(id, "CONTROLLER_ERROR", &error),
        },
        shutdown: false,
    }
}

fn constant_time_equal(left: &[u8], right: &[u8]) -> bool {
    let max_len = left.len().max(right.len());
    let mut difference = left.len() ^ right.len();
    for index in 0..max_len {
        difference |= usize::from(*left.get(index).unwrap_or(&0) ^ *right.get(index).unwrap_or(&0));
    }
    difference == 0
}

fn dispatch_controller_command(
    args: &Map<String, Value>,
    controller: &mut RuntimeController,
) -> Result<Value, String> {
    let command = required_string(args, "name")?;
    if !matches!(
        command,
        "start"
            | "pause"
            | "reset"
            | "sequence"
            | "policy"
            | "seek"
            | "layer"
            | "restart"
            | "status"
    ) {
        return Err("unsupported controller command".to_owned());
    }
    let command_args = args
        .get("args")
        .filter(|value| value.is_object())
        .cloned()
        .ok_or_else(|| "command args must be an object".to_owned())?;
    controller.command(command, command_args)
}

fn required_string<'a>(args: &'a Map<String, Value>, name: &str) -> Result<&'a str, String> {
    args.get(name)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty() && value.len() <= MAX_COMMAND_BYTES)
        .ok_or_else(|| format!("{name} must be a non-empty bounded string"))
}

fn required_object(args: &Map<String, Value>, name: &str) -> Result<Value, String> {
    args.get(name)
        .filter(|value| value.is_object())
        .cloned()
        .ok_or_else(|| format!("{name} must be an object"))
}

fn bounded_string<'a>(
    object: &'a Map<String, Value>,
    name: &str,
    max_bytes: usize,
) -> Result<&'a str, String> {
    let value = object
        .get(name)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{name} must be a string"))?;
    if value.is_empty() || value.len() > max_bytes {
        return Err(format!("{name} exceeds its maximum length"));
    }
    Ok(value)
}

fn success_response(id: Value, result: Value) -> Value {
    json!({"ok": true, "id": id, "result": result})
}

fn error_response(id: Value, code: &str, message: &str) -> Value {
    json!({"ok": false, "id": id, "error": {"code": code, "message": message}})
}

fn write_response(writer: &mut TcpStream, response: &Value) -> io::Result<()> {
    serde_json::to_writer(&mut *writer, response)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    writer.write_all(b"\n")?;
    writer.flush()
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::super::RuntimeController;
    use super::{dispatch_line, validate_bind_address};

    const TEST_SECRET: &str = "test-control-secret-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ";

    #[test]
    fn rejects_a_request_with_an_unsupported_schema_version() {
        let request = json!({
            "schema_version": 99,
            "id": "bad-schema",
            "command": "status",
            "args": {}
        });
        let mut controller = RuntimeController::new("/tmp/veyra-daemon-test");
        let response = dispatch_line(
            &serde_json::to_vec(&request).unwrap(),
            &mut controller,
            TEST_SECRET,
        );

        assert_eq!(
            response.value["error"]["code"],
            "UNSUPPORTED_SCHEMA_VERSION"
        );
        assert!(!response.shutdown);
    }

    #[test]
    fn sequential_requests_share_the_daemon_controller_state() {
        let request = json!({
            "schema_version": 1,
            "id": "set-layer",
            "authorization": TEST_SECRET,
            "command": "command",
            "args": {"name": "layer", "args": {"layer": "lod"}}
        });
        let mut controller = RuntimeController::new("/tmp/veyra-daemon-state-test");
        let response = dispatch_line(
            &serde_json::to_vec(&request).unwrap(),
            &mut controller,
            TEST_SECRET,
        );
        assert_eq!(response.value["ok"], true);
        assert_eq!(controller.status()["layer"], "lod");

        assert!(validate_bind_address("127.0.0.1:0".parse().unwrap()).is_ok());
        assert!(validate_bind_address("0.0.0.0:0".parse().unwrap()).is_err());
    }

    #[test]
    fn rejects_a_request_with_the_wrong_authorization_secret() {
        let request = json!({
            "schema_version": 1,
            "id": "wrong-secret",
            "authorization": "not-the-daemon-secret",
            "command": "command",
            "args": {"name": "layer", "args": {"layer": "lod"}}
        });
        let mut controller = RuntimeController::new("/tmp/veyra-daemon-auth-test");
        let response = dispatch_line(
            &serde_json::to_vec(&request).unwrap(),
            &mut controller,
            TEST_SECRET,
        );

        assert_eq!(response.value["error"]["code"], "UNAUTHORIZED");
        assert!(!response.shutdown);
    }
}
