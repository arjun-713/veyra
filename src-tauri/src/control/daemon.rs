use std::io::{self, BufRead, BufReader, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::path::PathBuf;
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use serde_json::{json, Map, Value};

use super::RuntimeController;
use crate::supervisor::RuntimeEvent;

pub const PROTOCOL_VERSION: u64 = 1;
const MAX_FRAME_BYTES: usize = 64 * 1024;
const MAX_ID_BYTES: usize = 128;
const MAX_COMMAND_BYTES: usize = 64;
const CONNECTION_IO_TIMEOUT: Duration = Duration::from_millis(100);

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
    controller: RuntimeController,
    secret: String,
) -> io::Result<()> {
    serve_listener_with_event_sink(listener, controller, secret, None)
}

pub type RuntimeEventSink = Arc<dyn Fn(RuntimeEvent) + Send + Sync>;

pub fn serve_listener_with_event_sink(
    listener: TcpListener,
    mut controller: RuntimeController,
    secret: String,
    event_sink: Option<RuntimeEventSink>,
) -> io::Result<()> {
    listener.set_nonblocking(true)?;
    loop {
        match listener.accept() {
            Ok((stream, _)) => {
                if handle_connection(stream, &mut controller, &secret)? {
                    return Ok(());
                }
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {}
            Err(error) => eprintln!("veyra-control connection failed: {error}"),
        }
        if let Some(sink) = event_sink.as_ref() {
            for event in controller.drain_events() {
                sink(event);
            }
        }
        thread::sleep(Duration::from_millis(10));
    }
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
    stream.set_read_timeout(Some(CONNECTION_IO_TIMEOUT))?;
    stream.set_write_timeout(Some(CONNECTION_IO_TIMEOUT))?;
    let mut reader = BufReader::new(stream.try_clone()?);
    let mut writer = stream;
    let mut line = Vec::new();

    loop {
        line.clear();
        let frame = match read_frame(&mut reader, &mut line) {
            Ok(frame) => frame,
            Err(error) if client_connection_error(&error) => return Ok(false),
            Err(error) => return Err(error),
        };
        match frame {
            Frame::Eof => return Ok(false),
            Frame::TooLarge => {
                match write_response(
                    &mut writer,
                    &error_response(Value::Null, "FRAME_TOO_LARGE", "request exceeds 64 KiB"),
                ) {
                    Ok(()) => {}
                    Err(error) if client_connection_error(&error) => {
                        eprintln!(
                            "veyra-control client went away before FRAME_TOO_LARGE reply: {error}"
                        );
                        return Ok(false);
                    }
                    Err(error) => return Err(error),
                }
                continue;
            }
            Frame::Line => {
                let response = dispatch_line(&line, controller, secret);
                let shutdown = response.shutdown;
                match write_response(&mut writer, &response.value) {
                    Ok(()) => {}
                    Err(error) if client_connection_error(&error) => {
                        eprintln!(
                            "veyra-control client went away mid-response; closing connection: {error}"
                        );
                        return Ok(false);
                    }
                    Err(error) => return Err(error),
                }
                if shutdown {
                    return Ok(true);
                }
            }
        }
    }
}

fn client_connection_error(error: &io::Error) -> bool {
    matches!(
        error.kind(),
        io::ErrorKind::TimedOut
            | io::ErrorKind::WouldBlock
            | io::ErrorKind::BrokenPipe
            | io::ErrorKind::ConnectionAborted
            | io::ErrorKind::ConnectionReset
            | io::ErrorKind::NotConnected
    )
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
            | "open_dataset"
            | "command"
            | "diagnostics"
            | "stop"
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

    if command == "stop" {
        return match controller.stop() {
            Ok(()) => DispatchResponse {
                value: success_response(id, json!({"status": controller.status()})),
                shutdown: false,
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
        "open_dataset" => required_string(args, "dataset").and_then(|dataset| {
            required_string(args, "root").and_then(|root| {
                let sequence = optional_string(args, "sequence")?;
                controller.open_dataset(dataset, &PathBuf::from(root), sequence)
            })
        }),
        "command" => dispatch_controller_command(args, controller),
        "diagnostics" => Ok(controller.diagnostics()),
        "stop" => unreachable!(),
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
    if !is_supported_controller_command(command) {
        return Err("unsupported controller command".to_owned());
    }
    let command_args = args
        .get("args")
        .filter(|value| value.is_object())
        .cloned()
        .ok_or_else(|| "command args must be an object".to_owned())?;
    controller.command(command, command_args)
}

fn is_supported_controller_command(command: &str) -> bool {
    matches!(
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
            | "step"
            | "speed"
            | "governor"
            | "benchmark"
    )
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

fn optional_string<'a>(
    args: &'a Map<String, Value>,
    name: &str,
) -> Result<Option<&'a str>, String> {
    match args.get(name) {
        None => Ok(None),
        Some(Value::String(value)) if !value.is_empty() && value.len() <= MAX_COMMAND_BYTES => {
            Ok(Some(value))
        }
        _ => Err(format!("{name} must be an optional bounded string")),
    }
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
    write_response_to(&mut *writer, response)
}

fn write_response_to(writer: &mut impl Write, response: &Value) -> io::Result<()> {
    // Serialize before touching the socket so a dead (client-abandoned)
    // peer surfaces as its native transport error (BrokenPipe /
    // ConnectionReset / TimedOut) instead of being rewrapped as
    // InvalidData inside serde_json::to_writer. That rewrapping escaped
    // `client_connection_error`, so any slow command abandoned by the 2 s
    // ControlClient budget killed the whole daemon (serve loop exited,
    // listener closed, later commands got Connection refused).
    let mut encoded = serde_json::to_vec(response)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    encoded.push(b'\n');
    writer.write_all(&encoded)?;
    writer.flush()
}

#[cfg(test)]
mod tests {
    use std::io::{self, BufRead, Write};
    use std::net::{TcpListener, TcpStream};
    use std::thread;
    use std::time::{Duration, Instant};

    use serde_json::json;

    use super::super::RuntimeController;
    use super::{
        client_connection_error, dispatch_line, handle_connection, is_supported_controller_command,
        serve_listener, validate_bind_address, write_response_to,
    };

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

    #[test]
    fn runtime_stop_keeps_the_control_daemon_available() {
        let request = json!({
            "schema_version": 1,
            "id": "runtime-stop",
            "authorization": TEST_SECRET,
            "command": "stop",
            "args": {}
        });
        let mut controller = RuntimeController::new("/tmp/veyra-daemon-stop-test");
        let response = dispatch_line(
            &serde_json::to_vec(&request).unwrap(),
            &mut controller,
            TEST_SECRET,
        );

        assert_eq!(response.value["ok"], true);
        assert_eq!(response.value["result"]["status"]["runtime_running"], false);
        assert!(!response.shutdown);
    }

    #[test]
    fn daemon_accepts_every_runtime_command_exposed_by_the_tauri_frontend() {
        for command in [
            "start",
            "pause",
            "reset",
            "sequence",
            "policy",
            "seek",
            "layer",
            "restart",
            "status",
            "step",
            "speed",
            "governor",
            "benchmark",
        ] {
            assert!(
                is_supported_controller_command(command),
                "Tauri runtime command must not be rejected by the daemon: {command}"
            );
        }
    }

    #[test]
    fn idle_connection_cannot_stall_the_control_loop() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let client = thread::spawn(move || {
            let _stream = TcpStream::connect(address).unwrap();
            thread::sleep(Duration::from_millis(350));
        });
        let (stream, _) = listener.accept().unwrap();
        let mut controller = RuntimeController::new("/tmp/veyra-daemon-idle-test");

        let started = Instant::now();
        assert!(!handle_connection(stream, &mut controller, TEST_SECRET).unwrap());
        assert!(
            started.elapsed() < Duration::from_millis(200),
            "idle local control connection blocked the daemon for {:?}",
            started.elapsed()
        );
        client.join().unwrap();
    }

    /// A writer that is already gone, modelling a client that abandoned a
    /// slow command after its 2 s budget and closed the socket.
    struct DeadClientWriter;

    impl Write for DeadClientWriter {
        fn write(&mut self, _buf: &[u8]) -> io::Result<usize> {
            Err(io::Error::new(
                io::ErrorKind::BrokenPipe,
                "broken pipe (test dead client)",
            ))
        }

        fn flush(&mut self) -> io::Result<()> {
            Err(io::Error::new(
                io::ErrorKind::BrokenPipe,
                "broken pipe (test dead client)",
            ))
        }
    }

    #[test]
    fn write_failure_to_a_dead_client_is_a_disconnect_not_a_serve_failure() {
        let response = json!({"ok": true, "id": "abandoned", "result": {}});
        let error = write_response_to(&mut DeadClientWriter, &response)
            .expect_err("writing to a gone client must fail");
        assert_eq!(
            error.kind(),
            io::ErrorKind::BrokenPipe,
            "EPIPE must keep its transport kind (was rewrapped as InvalidData, \
             which escaped client_connection_error and killed the daemon)"
        );
        assert!(
            client_connection_error(&error),
            "EPIPE must close only that connection, never the serve loop"
        );
    }

    fn daemon_request_line(id: &str, command: &str) -> String {
        serde_json::to_string(&json!({
            "schema_version": 1,
            "id": id,
            "authorization": TEST_SECRET,
            "command": command,
            "args": {}
        }))
        .unwrap()
            + "\n"
    }

    fn daemon_round_trip(
        address: std::net::SocketAddr,
        id: &str,
        command: &str,
    ) -> serde_json::Value {
        let mut stream = TcpStream::connect(address)
            .unwrap_or_else(|error| panic!("daemon must still accept connections: {error}"));
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        stream
            .write_all(daemon_request_line(id, command).as_bytes())
            .unwrap();
        stream.flush().unwrap();
        let mut line = String::new();
        std::io::BufReader::new(stream)
            .read_line(&mut line)
            .unwrap();
        serde_json::from_str(&line).unwrap()
    }

    #[test]
    fn abandoned_command_keeps_daemon_alive_for_the_next_client() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            serve_listener(
                listener,
                RuntimeController::new("/tmp/veyra-daemon-epipe-test"),
                TEST_SECRET.to_owned(),
            )
        });

        // Abandoned slow command: send a request, then go away without
        // reading the reply (the 2 s ControlClient-budget analogue).
        let mut abandoned = TcpStream::connect(address).unwrap();
        abandoned
            .write_all(daemon_request_line("abandoned-stop", "stop").as_bytes())
            .unwrap();
        abandoned.flush().unwrap();
        drop(abandoned);
        thread::sleep(Duration::from_millis(400));

        // The next client must be served; Connection refused here means the
        // abandoned write killed the daemon (the routed EPIPE defect).
        // (`diagnostics` is infallible without an open dataset; `status`
        // needs one, so it is not a liveness probe here.)
        let response = daemon_round_trip(address, "after-abandon", "diagnostics");
        assert_eq!(response["ok"], true);
        assert_eq!(response["id"], "after-abandon");

        // stop keeps the daemon alive (existing contract, still honored).
        let response = daemon_round_trip(address, "runtime-stop", "stop");
        assert_eq!(response["ok"], true);
        let response = daemon_round_trip(address, "still-alive", "diagnostics");
        assert_eq!(response["ok"], true);

        // Clean shutdown so the serve thread can be joined.
        let response = daemon_round_trip(address, "teardown", "shutdown");
        assert_eq!(response["ok"], true);
        server
            .join()
            .expect("serve thread panicked")
            .expect("serve loop must exit cleanly on shutdown");
    }
}
