use std::fmt;
use std::io::{BufRead, BufReader, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::Duration;

use serde_json::{json, Value};

const MAX_FRAME_BYTES: usize = 64 * 1024;
const MAX_ID_BYTES: usize = 128;
const MAX_COMMAND_BYTES: usize = 64;
const CONNECT_TIMEOUT: Duration = Duration::from_secs(2);
const IO_TIMEOUT: Duration = Duration::from_secs(2);

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
        stream
            .set_read_timeout(Some(IO_TIMEOUT))
            .and_then(|_| stream.set_write_timeout(Some(IO_TIMEOUT)))
            .map_err(|error| {
                ControlClientError::Transport(format!("cannot configure control timeouts: {error}"))
            })?;
        stream.write_all(&frame).map_err(|error| {
            ControlClientError::Transport(format!("cannot write control request: {error}"))
        })?;
        stream.flush().map_err(|error| {
            ControlClientError::Transport(format!("cannot flush control request: {error}"))
        })?;

        let mut reader = BufReader::new(stream);
        let response = read_response(&mut reader)?;
        validate_response(&response, &id)
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

fn read_response(reader: &mut impl BufRead) -> Result<Value, ControlClientError> {
    let mut line = Vec::new();
    loop {
        let available = reader.fill_buf().map_err(|error| {
            ControlClientError::Transport(format!("cannot read control response: {error}"))
        })?;
        if available.is_empty() {
            if line.is_empty() {
                return Err(ControlClientError::Protocol(
                    "control response was empty".to_owned(),
                ));
            }
            break;
        }
        let newline = available.iter().position(|byte| *byte == b'\n');
        let amount = newline.map_or(available.len(), |index| index + 1);
        if line.len().saturating_add(amount) > MAX_FRAME_BYTES {
            return Err(ControlClientError::Protocol(
                "control response exceeds 64 KiB".to_owned(),
            ));
        }
        line.extend_from_slice(&available[..amount]);
        reader.consume(amount);
        if newline.is_some() {
            break;
        }
    }
    serde_json::from_slice::<Value>(&line).map_err(|error| {
        ControlClientError::Protocol(format!("malformed control response: {error}"))
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
        parse_endpoint, read_response, validate_response, validate_token, ControlClient,
        ControlClientError, MAX_FRAME_BYTES,
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

    #[test]
    fn oversized_response_is_rejected_before_json_parsing() {
        let response = vec![b'x'; MAX_FRAME_BYTES + 1];
        let error = read_response(&mut Cursor::new(response)).unwrap_err();
        assert!(
            matches!(error, ControlClientError::Protocol(message) if message.contains("exceeds 64 KiB"))
        );
    }
}
