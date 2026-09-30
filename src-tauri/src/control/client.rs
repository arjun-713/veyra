use std::fmt;
use std::io::{self, BufRead, BufReader, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::Duration;

use serde_json::{json, Value};

const MAX_FRAME_BYTES: usize = 64 * 1024;
const MAX_ID_BYTES: usize = 128;
const MAX_COMMAND_BYTES: usize = 64;
const CONNECT_TIMEOUT: Duration = Duration::from_secs(2);
const IO_TIMEOUT: Duration = Duration::from_secs(2);
const LONG_OPERATION_TIMEOUT: Duration = Duration::from_secs(120);

#[derive(Debug, PartialEq, Eq)]
pub enum ControlClientError {
    Configuration(String),
    Transport(String),
    Protocol(String),
    Daemon { code: String, message: String },
}

impl fmt::Display for ControlClientError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Configuration(message) | Self::Transport(message) | Self::Protocol(message) => {
                formatter.write_str(message)
            }
            Self::Daemon { code, message } => write!(formatter, "{code}: {message}"),
        }
    }
}

#[derive(Clone)]
pub struct ControlClient {
    endpoint: SocketAddr,
    token: String,
    next_id: u64,
}

impl ControlClient {
    pub fn from_endpoint_and_token(
        endpoint: SocketAddr,
        token: impl Into<String>,
    ) -> Result<Self, ControlClientError> {
        if !endpoint.ip().is_loopback() || endpoint.ip().is_unspecified() {
            return Err(ControlClientError::Configuration(
                "control endpoint must use a loopback address".to_owned(),
            ));
        }
        let token = validate_token(token.into().into_bytes())?;
        Ok(Self {
            endpoint,
            token,
            next_id: 1,
        })
    }

    pub fn from_endpoint_and_token_file(
        endpoint: SocketAddr,
        token_path: &std::path::Path,
    ) -> Result<Self, ControlClientError> {
        validate_token_file(token_path)?;
        let token = std::fs::read(token_path).map_err(|error| {
            ControlClientError::Configuration(format!(
                "cannot read control token file {}: {error}",
                token_path.display()
            ))
        })?;
        Self::from_endpoint_and_token(endpoint, validate_token(token)?)
    }

    pub fn from_env() -> Result<Self, ControlClientError> {
        let endpoint = std::env::var("VEYRA_CONTROL_ENDPOINT").map_err(|_| {
            ControlClientError::Configuration(
                "VEYRA_CONTROL_ENDPOINT is required for the local control daemon".to_owned(),
            )
        })?;
        let endpoint = parse_endpoint(&endpoint)?;
        let token_path = std::env::var("VEYRA_CONTROL_TOKEN_FILE").map_err(|_| {
            ControlClientError::Configuration(
                "VEYRA_CONTROL_TOKEN_FILE is required for the local control daemon".to_owned(),
            )
        })?;
        Self::from_endpoint_and_token_file(endpoint, std::path::Path::new(&token_path))
    }

    pub fn request(&mut self, command: &str, args: Value) -> Result<Value, ControlClientError> {
        if command.is_empty() || command.len() > MAX_COMMAND_BYTES {
            return Err(ControlClientError::Protocol(
                "command must be a non-empty bounded string".to_owned(),
            ));
        }
        if !args.is_object() {
            return Err(ControlClientError::Protocol(
                "args must be an object".to_owned(),
            ));
        }

        let id = format!("cli-{}", self.next_id);
        self.next_id = self.next_id.wrapping_add(1);
        let request = json!({
            "schema_version": 1,
            "id": id,
            "authorization": self.token,
            "command": command,
            "args": args,
        });
        let mut frame = serde_json::to_vec(&request).map_err(|error| {
            ControlClientError::Protocol(format!("cannot encode control request: {error}"))
        })?;
        frame.push(b'\n');
        if frame.len() > MAX_FRAME_BYTES {
            return Err(ControlClientError::Protocol(
                "control request exceeds 64 KiB".to_owned(),
            ));
        }

        let mut stream =
            TcpStream::connect_timeout(&self.endpoint, CONNECT_TIMEOUT).map_err(|error| {
                ControlClientError::Transport(format!(
                    "cannot connect to control endpoint {}: {error}",
                    self.endpoint
                ))
            })?;
        let io_timeout = request_timeout(command);
        stream
            .set_read_timeout(Some(io_timeout))
            .and_then(|_| stream.set_write_timeout(Some(io_timeout)))
            .map_err(|error| {
                ControlClientError::Transport(format!("cannot configure control timeouts: {error}"))
            })?;
        stream.write_all(&frame).map_err(|error| {
            transport_error("write control request", command, io_timeout, &error)
        })?;
        stream.flush().map_err(|error| {
            transport_error("flush control request", command, io_timeout, &error)
        })?;

        let mut reader = BufReader::new(stream);
        let response = read_response(&mut reader).map_err(|error| match error {
            ResponseError::Io(error) => {
                transport_error("read control response", command, io_timeout, &error)
            }
            ResponseError::Client(error) => error,
        })?;
        validate_response(&response, &id)
    }
}

fn request_timeout(command: &str) -> Duration {
    // Every command below can require a runtime round trip: the daemon
    // starts the Python runtime on first use (a cold start imports Torch and
    // can take several seconds) and the runtime answers between frames (a
    // single frame can take several seconds), so even cheap reads such as
    // `config_validate` get the long budget. `stop`/`shutdown` wait for the
    // runtime to exit. Only commands the daemon rejects without touching the
    // runtime fall through to the short budget.
    match command {
        "configure" | "config_validate" | "open_dataset" | "benchmark" | "command" | "status"
        | "metrics" | "diagnostics" | "datasets" | "stop" | "shutdown" => LONG_OPERATION_TIMEOUT,
        _ => IO_TIMEOUT,
    }
}

/// Maps a socket read/write error to a transport error. An expired
/// `SO_RCVTIMEO`/`SO_SNDTIMEO` surfaces as `WouldBlock` (EAGAIN; "os error
/// 35" on macOS) on Unix and as `TimedOut` on Windows; both mean the budget
/// ran out, so say that instead of "Resource temporarily unavailable".
fn transport_error(
    operation: &str,
    command: &str,
    timeout: Duration,
    error: &io::Error,
) -> ControlClientError {
    if matches!(
        error.kind(),
        io::ErrorKind::WouldBlock | io::ErrorKind::TimedOut
    ) {
        ControlClientError::Transport(format!(
            "cannot {operation}: control daemon did not answer `{command}` within {} s",
            timeout.as_secs()
        ))
    } else {
        ControlClientError::Transport(format!("cannot {operation}: {error}"))
    }
}

fn validate_token_file(token_path: &std::path::Path) -> Result<(), ControlClientError> {
    let metadata = std::fs::metadata(token_path).map_err(|error| {
        ControlClientError::Configuration(format!(
            "cannot inspect control token file {}: {error}",
            token_path.display()
        ))
    })?;
    if !metadata.is_file() {
        return Err(ControlClientError::Configuration(
            "control token path must be a regular file".to_owned(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(ControlClientError::Configuration(
                "control token file permissions must deny group and other access".to_owned(),
            ));
        }
    }
    Ok(())
}

fn parse_endpoint(value: &str) -> Result<SocketAddr, ControlClientError> {
    let endpoint = value.parse::<SocketAddr>().map_err(|error| {
        ControlClientError::Configuration(format!(
            "VEYRA_CONTROL_ENDPOINT must be a loopback SocketAddr: {error}"
        ))
    })?;
    if !endpoint.ip().is_loopback() || endpoint.ip().is_unspecified() {
        return Err(ControlClientError::Configuration(
            "VEYRA_CONTROL_ENDPOINT must use a loopback address".to_owned(),
        ));
    }
    Ok(endpoint)
}

fn validate_token(mut token: Vec<u8>) -> Result<String, ControlClientError> {
    while matches!(token.last(), Some(b'\r' | b'\n')) {
        token.pop();
    }
    if !(32..=256).contains(&token.len()) || !token.iter().all(u8::is_ascii_graphic) {
        return Err(ControlClientError::Configuration(
            "control token must contain 32-256 printable ASCII bytes".to_owned(),
        ));
    }
    String::from_utf8(token).map_err(|_| {
        ControlClientError::Configuration(
            "control token must contain 32-256 printable ASCII bytes".to_owned(),
        )
    })
}

#[derive(Debug)]
enum ResponseError {
    Io(io::Error),
    Client(ControlClientError),
}

fn read_response(reader: &mut impl BufRead) -> Result<Value, ResponseError> {
    let mut line = Vec::new();
    loop {
        let available = reader.fill_buf().map_err(ResponseError::Io)?;
        if available.is_empty() {
            if line.is_empty() {
                return Err(ResponseError::Client(ControlClientError::Protocol(
                    "control response was empty".to_owned(),
                )));
            }
            break;
        }
        let newline = available.iter().position(|byte| *byte == b'\n');
        let amount = newline.map_or(available.len(), |index| index + 1);
        if line.len().saturating_add(amount) > MAX_FRAME_BYTES {
            return Err(ResponseError::Client(ControlClientError::Protocol(
                "control response exceeds 64 KiB".to_owned(),
            )));
        }
        line.extend_from_slice(&available[..amount]);
        reader.consume(amount);
        if newline.is_some() {
            break;
        }
    }
    serde_json::from_slice::<Value>(&line).map_err(|error| {
        ResponseError::Client(ControlClientError::Protocol(format!(
            "malformed control response: {error}"
        )))
    })
}

fn validate_response(response: &Value, expected_id: &str) -> Result<Value, ControlClientError> {
    let object = response.as_object().ok_or_else(|| {
        ControlClientError::Protocol("control response must be an object".to_owned())
    })?;
    let id = object.get("id").and_then(Value::as_str).ok_or_else(|| {
        ControlClientError::Protocol("control response id must be a string".to_owned())
    })?;
    if id.len() > MAX_ID_BYTES || id != expected_id {
        return Err(ControlClientError::Protocol(
            "control response id did not match the request".to_owned(),
        ));
    }
    let ok = object.get("ok").and_then(Value::as_bool).ok_or_else(|| {
        ControlClientError::Protocol("control response ok must be a boolean".to_owned())
    })?;
    if ok {
        return object.get("result").cloned().ok_or_else(|| {
            ControlClientError::Protocol("successful control response lacks result".to_owned())
        });
    }
    let error = object
        .get("error")
        .and_then(Value::as_object)
        .ok_or_else(|| {
            ControlClientError::Protocol("failed control response lacks error object".to_owned())
        })?;
    let code = error.get("code").and_then(Value::as_str).ok_or_else(|| {
        ControlClientError::Protocol("control error code must be a string".to_owned())
    })?;
    let message = error
        .get("message")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            ControlClientError::Protocol("control error message must be a string".to_owned())
        })?;
    if code.is_empty() || message.is_empty() {
        return Err(ControlClientError::Protocol(
            "control error code and message must be non-empty".to_owned(),
        ));
    }
    Err(ControlClientError::Daemon {
        code: code.to_owned(),
        message: message.to_owned(),
    })
}

#[cfg(test)]
mod tests {
    use std::io::Cursor;

    use super::{
        parse_endpoint, read_response, request_timeout, transport_error, validate_response,
        validate_token, ControlClient, ControlClientError, ResponseError, IO_TIMEOUT,
        LONG_OPERATION_TIMEOUT, MAX_FRAME_BYTES,
    };
    use serde_json::json;

    #[test]
    fn missing_endpoint_and_token_are_rejected_before_connecting() {
        std::env::remove_var("VEYRA_CONTROL_ENDPOINT");
        std::env::remove_var("VEYRA_CONTROL_TOKEN_FILE");

        let error = match ControlClient::from_env() {
            Ok(_) => panic!("missing control configuration was accepted"),
            Err(error) => error,
        };
        assert!(
            matches!(error, ControlClientError::Configuration(message) if message.contains("VEYRA_CONTROL_ENDPOINT"))
        );
    }

    #[test]
    fn endpoint_must_be_loopback() {
        assert!(parse_endpoint("127.0.0.1:8765").is_ok());
        assert!(parse_endpoint("0.0.0.0:8765").is_err());
        assert!(parse_endpoint("192.168.1.2:8765").is_err());
    }

    #[test]
    fn token_is_trimmed_and_bounded_without_exposing_contents_in_errors() {
        let path = std::env::temp_dir().join(format!("veyra-token-{}", std::process::id()));
        std::fs::write(&path, b"12345678901234567890123456789012\r\n").unwrap();
        assert_eq!(
            validate_token(std::fs::read(&path).unwrap()).unwrap().len(),
            32
        );
        std::fs::write(&path, b"short\n").unwrap();
        let error = validate_token(std::fs::read(&path).unwrap())
            .unwrap_err()
            .to_string();
        assert!(!error.contains("short"));
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn response_validation_preserves_daemon_code_and_message() {
        let error = validate_response(
            &json!({"ok": false, "id": "cli-1", "error": {"code": "NO_DATA", "message": "dataset is not open"}}),
            "cli-1",
        )
        .unwrap_err();
        assert_eq!(
            error,
            ControlClientError::Daemon {
                code: "NO_DATA".to_owned(),
                message: "dataset is not open".to_owned(),
            }
        );
    }

    #[test]
    fn response_id_and_shape_are_strictly_validated() {
        assert!(
            validate_response(&json!({"ok": true, "id": "wrong", "result": {}}), "cli-1").is_err()
        );
        assert!(validate_response(&json!({"ok": true, "id": "cli-1"}), "cli-1").is_err());
        assert!(validate_response(&json!([]), "cli-1").is_err());
    }

    #[test]
    fn request_rejects_non_object_args_without_connecting() {
        let mut client = ControlClient {
            endpoint: "127.0.0.1:1".parse().unwrap(),
            token: "12345678901234567890123456789012".to_owned(),
            next_id: 1,
        };
        assert!(matches!(
            client.request("status", json!([])),
            Err(ControlClientError::Protocol(message)) if message == "args must be an object"
        ));
    }

    #[test]
    fn long_running_control_operations_get_a_bounded_extended_timeout() {
        assert_eq!(request_timeout("status"), LONG_OPERATION_TIMEOUT);
        assert_eq!(request_timeout("metrics"), LONG_OPERATION_TIMEOUT);
        assert_eq!(request_timeout("diagnostics"), LONG_OPERATION_TIMEOUT);
        assert_eq!(request_timeout("datasets"), LONG_OPERATION_TIMEOUT);
        assert_eq!(request_timeout("stop"), LONG_OPERATION_TIMEOUT);
        assert_eq!(request_timeout("open_dataset"), LONG_OPERATION_TIMEOUT);
        assert_eq!(request_timeout("configure"), LONG_OPERATION_TIMEOUT);
        assert_eq!(request_timeout("benchmark"), LONG_OPERATION_TIMEOUT);
        assert_eq!(request_timeout("command"), LONG_OPERATION_TIMEOUT);
        assert_eq!(request_timeout("config_validate"), LONG_OPERATION_TIMEOUT);
        assert_eq!(request_timeout("shutdown"), LONG_OPERATION_TIMEOUT);
        assert_eq!(request_timeout("not_a_daemon_command"), IO_TIMEOUT);
    }

    #[test]
    fn expired_socket_timeouts_report_a_timeout_on_every_platform() {
        // Unix reports an expired SO_RCVTIMEO as EAGAIN (WouldBlock; "os
        // error 35" on macOS); Windows reports TimedOut.
        for kind in [std::io::ErrorKind::WouldBlock, std::io::ErrorKind::TimedOut] {
            let error = transport_error(
                "read control response",
                "config_validate",
                LONG_OPERATION_TIMEOUT,
                &std::io::Error::from(kind),
            );
            assert_eq!(
                error,
                ControlClientError::Transport(
                    "cannot read control response: control daemon did not answer \
                     `config_validate` within 120 s"
                        .to_owned()
                )
            );
        }
        let reset = transport_error(
            "read control response",
            "status",
            LONG_OPERATION_TIMEOUT,
            &std::io::Error::from(std::io::ErrorKind::ConnectionReset),
        );
        assert!(
            matches!(reset, ControlClientError::Transport(message) if message.starts_with("cannot read control response: ") && !message.contains("within"))
        );
    }

    #[test]
    fn explicit_client_construction_requires_loopback_without_environment_changes() {
        let client = ControlClient::from_endpoint_and_token(
            "127.0.0.1:8765".parse().unwrap(),
            "12345678901234567890123456789012",
        )
        .unwrap();
        assert_eq!(client.endpoint, "127.0.0.1:8765".parse().unwrap());
        assert!(ControlClient::from_endpoint_and_token(
            "0.0.0.0:8765".parse().unwrap(),
            "12345678901234567890123456789012",
        )
        .is_err());
    }

    #[cfg(unix)]
    #[test]
    fn token_file_client_rejects_group_or_world_readable_secret() {
        use std::os::unix::fs::PermissionsExt;

        let path = std::env::temp_dir().join(format!("veyra-client-token-{}", std::process::id()));
        std::fs::write(&path, b"12345678901234567890123456789012").unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
        let result =
            ControlClient::from_endpoint_and_token_file("127.0.0.1:8765".parse().unwrap(), &path);
        let error = match result {
            Ok(_) => panic!("insecure token file was accepted"),
            Err(error) => error,
        };
        assert!(error.to_string().contains("permissions"));
        std::fs::remove_file(path).unwrap();
    }

    /// Regression: on a fresh desktop launch "Open dataset & preview" first
    /// sends `config_validate`, which makes the daemon spawn the Python
    /// runtime and wait for its reply. That round trip routinely outlives
    /// the 2 s short-IO budget, and on macOS an expired `SO_RCVTIMEO`
    /// surfaces as `WouldBlock` ("os error 35"). The client must wait the
    /// runtime-round-trip budget for every command the daemon forwards.
    #[test]
    fn config_validate_waits_for_a_cold_runtime_response() {
        use std::io::{BufRead, BufReader, Write};
        use std::net::TcpListener;

        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let endpoint = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            let mut line = String::new();
            reader.read_line(&mut line).unwrap();
            let request: serde_json::Value = serde_json::from_str(&line).unwrap();
            assert_eq!(request["command"], "config_validate");
            // Longer than the 2 s short-IO budget: a cold runtime start.
            std::thread::sleep(std::time::Duration::from_millis(2_600));
            let mut writer = stream;
            let response = json!({"ok": true, "id": request["id"], "result": {"valid": true}});
            writer
                .write_all(format!("{response}\n").as_bytes())
                .unwrap();
        });

        let mut client =
            ControlClient::from_endpoint_and_token(endpoint, "12345678901234567890123456789012")
                .unwrap();
        let result = client.request("config_validate", json!({"config": {}}));
        server.join().unwrap();
        assert_eq!(result, Ok(json!({"valid": true})));
    }

    #[test]
    fn oversized_response_is_rejected_before_json_parsing() {
        let response = vec![b'x'; MAX_FRAME_BYTES + 1];
        let error = read_response(&mut Cursor::new(response)).unwrap_err();
        assert!(
            matches!(error, ResponseError::Client(ControlClientError::Protocol(message)) if message.contains("exceeds 64 KiB"))
        );
    }
}
