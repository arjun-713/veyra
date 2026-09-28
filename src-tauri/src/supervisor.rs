use std::collections::{HashMap, VecDeque};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStderr, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use thiserror::Error;

const HEADER_SIZE: usize = 16;
const MAX_METADATA: usize = 1024 * 1024;
const MAX_PAYLOAD: usize = 32 * 1024 * 1024;
const MAX_REQUEST: usize = 64 * 1024;
const MAX_PENDING: usize = 8;
const MAX_EVENTS: usize = 128;

#[derive(Debug, Error, Clone)]
pub enum SupervisorError {
    #[error("runtime is not running")]
    NotRunning,
    #[error("runtime command queue is full")]
    QueueFull,
    #[error("runtime command timed out: {0}")]
    Timeout(String),
    #[error("runtime protocol error: {0}")]
    Protocol(String),
    #[error("runtime process error: {0}")]
    Process(String),
    #[error("runtime response error: {0}")]
    Response(String),
}

#[derive(Debug, Clone)]
pub struct RuntimeEvent {
    pub metadata: Value,
    pub payload: Vec<u8>,
}

struct Shared {
    stdin: Option<ChildStdin>,
    child: Option<Child>,
    pending: HashMap<String, mpsc::Sender<Result<Value, SupervisorError>>>,
    events: VecDeque<RuntimeEvent>,
    stderr: String,
    last_error: Option<String>,
    sequence: u64,
    stopping: bool,
}

pub struct RuntimeSupervisor {
    repo: PathBuf,
    shared: Arc<Mutex<Shared>>,
}

impl RuntimeSupervisor {
    pub fn new(repo: impl Into<PathBuf>) -> Self {
        Self {
            repo: repo.into(),
            shared: Arc::new(Mutex::new(Shared {
                stdin: None,
                child: None,
                pending: HashMap::new(),
                events: VecDeque::new(),
                stderr: String::new(),
                last_error: None,
                sequence: 0,
                stopping: false,
            })),
        }
    }

    pub fn is_running(&self) -> bool {
        self.shared
            .lock()
            .map(|shared| shared.child.is_some())
            .unwrap_or(false)
    }

    pub fn pid(&self) -> Option<u32> {
        self.shared
            .lock()
            .ok()
            .and_then(|shared| shared.child.as_ref().map(Child::id))
    }

    pub fn start(&self) -> Result<(), SupervisorError> {
        let mut shared = self
            .shared
            .lock()
            .map_err(|_| SupervisorError::Process("supervisor lock poisoned".into()))?;
        if shared.child.is_some() {
            return Ok(());
        }

        let python = python_executable(&self.repo);
        let mut command = Command::new(&python);
        command
            .arg("-u")
            .arg("-m")
            .arg("runtime")
            .arg("--repo")
            .arg(&self.repo)
            .current_dir(&self.repo)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        if self.repo.join("python").is_dir() {
            command.env("PYTHONHOME", self.repo.join("python"));
            command.env("PYTHONPATH", &self.repo);
            command.env("PYTHONDONTWRITEBYTECODE", "1");
        }
        let mut child = command.spawn().map_err(|error| {
            SupervisorError::Process(format!("failed to start {}: {error}", python.display()))
        })?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| SupervisorError::Process("runtime stdin was not piped".into()))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| SupervisorError::Process("runtime stdout was not piped".into()))?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| SupervisorError::Process("runtime stderr was not piped".into()))?;

        let shared_arc = Arc::clone(&self.shared);
        shared.stdin = Some(stdin);
        shared.child = Some(child);
        shared.stopping = false;
        shared.last_error = None;
        drop(shared);

        spawn_stdout_reader(shared_arc.clone(), stdout);
        spawn_stderr_reader(shared_arc.clone(), stderr);
        spawn_process_monitor(shared_arc);
        Ok(())
    }

    pub fn request(&self, command: &str, args: Value) -> Result<Value, SupervisorError> {
        self.start()?;
        let (id, receiver) = {
            let mut shared = self
                .shared
                .lock()
                .map_err(|_| SupervisorError::Process("supervisor lock poisoned".into()))?;
            if shared.pending.len() >= MAX_PENDING {
                return Err(SupervisorError::QueueFull);
            }
            if shared.stdin.is_none() {
                return Err(SupervisorError::NotRunning);
            }
            shared.sequence = shared.sequence.saturating_add(1);
            let id = shared.sequence.to_string();
            let request = serde_json::to_vec(&json!({
                "id": id,
                "command": command,
                "args": args,
            }))
            .map_err(|error| SupervisorError::Process(error.to_string()))?;
            if request.len() + 1 > MAX_REQUEST {
                return Err(SupervisorError::Process(
                    "runtime request exceeds 64 KiB".into(),
                ));
            }
            let (sender, receiver) = mpsc::channel();
            shared.pending.insert(id.clone(), sender);
            let stdin = shared.stdin.as_mut().ok_or(SupervisorError::NotRunning)?;
            if let Err(error) = stdin
                .write_all(&[request.as_slice(), b"\n"].concat())
                .and_then(|_| stdin.flush())
            {
                shared.pending.remove(&id);
                return Err(SupervisorError::Process(error.to_string()));
            }
            (id, receiver)
        };

        let timeout = if command == "benchmark" {
            Duration::from_secs(3600)
        } else {
            Duration::from_secs(120)
        };
        match receiver.recv_timeout(timeout) {
            Ok(result) => result,
            Err(mpsc::RecvTimeoutError::Timeout) => {
                if let Ok(mut shared) = self.shared.lock() {
                    shared.pending.remove(&id);
                }
                Err(SupervisorError::Timeout(command.to_owned()))
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => Err(SupervisorError::NotRunning),
        }
    }

    pub fn drain_events(&self) -> Vec<RuntimeEvent> {
        self.shared
            .lock()
            .map(|mut shared| shared.events.drain(..).collect())
            .unwrap_or_default()
    }

    pub fn diagnostics(&self) -> Value {
        self.shared
            .lock()
            .map(|shared| {
                json!({
                    "running": shared.child.is_some(),
                    "pid": shared.child.as_ref().map(Child::id),
                    "pending": shared.pending.len(),
                    "queued_events": shared.events.len(),
                    "stderr": shared.stderr,
                    "last_error": shared.last_error,
                })
            })
            .unwrap_or_else(|_| json!({"error":"supervisor lock poisoned"}))
    }

    pub fn stop(&self) -> Result<(), SupervisorError> {
        if !self.is_running() {
            return Ok(());
        }
        if let Err(error) = self.request("shutdown", Value::Object(Default::default())) {
            if !matches!(error, SupervisorError::NotRunning) {
                self.record_error(error.to_string());
            }
        }
        // Close stdin once the shutdown round-trip is done: the runtime
        // acknowledges shutdown but its main thread stays blocked reading
        // stdin, so without EOF it lingers until the SIGKILL escalation
        // below (every stop took the full 2 s deadline). EOF lets it exit
        // promptly and run its session teardown instead of being killed.
        if let Ok(mut shared) = self.shared.lock() {
            shared.stdin.take();
        }
        let deadline = Instant::now() + Duration::from_secs(2);
        while Instant::now() < deadline && self.is_running() {
            thread::sleep(Duration::from_millis(25));
        }
        if self.is_running() {
            if let Ok(mut shared) = self.shared.lock() {
                shared.stopping = true;
                if let Some(child) = shared.child.as_mut() {
                    let _ = child.kill();
                }
            }
            // Reap synchronously so a subsequent start() can never observe
            // the killed child: without this, start() sees child.is_some(),
            // returns Ok, and the next request is written into a dead stdin
            // pipe (hanging up to the 120 s supervisor budget while the
            // monitor has not reaped yet). The monitor reaps identically;
            // whichever reaps first wins and the outcome is the same.
            let reap = Instant::now() + Duration::from_secs(2);
            while self.is_running() && Instant::now() < reap {
                if let Ok(mut shared) = self.shared.lock() {
                    let reaped = shared
                        .child
                        .as_mut()
                        .and_then(|child| child.try_wait().ok().flatten())
                        .is_some();
                    if reaped {
                        shared.child = None;
                        shared.stdin = None;
                    }
                }
                thread::sleep(Duration::from_millis(10));
            }
        }
        Ok(())
    }

    fn record_error(&self, message: String) {
        if let Ok(mut shared) = self.shared.lock() {
            shared.last_error = Some(message.clone());
            fail_pending(&mut shared, SupervisorError::Process(message));
        }
    }
}

fn python_executable(repo: &Path) -> PathBuf {
    if let Ok(value) = std::env::var("VEYRA_PYTHON") {
        return PathBuf::from(value);
    }
    let candidates = if cfg!(windows) {
        vec![
            repo.join("python/python.exe"),
            repo.join(".venv/Scripts/python.exe"),
            PathBuf::from("python"),
        ]
    } else {
        vec![
            repo.join("python/bin/python3"),
            repo.join("python/bin/python"),
            repo.join(".venv/bin/python"),
            PathBuf::from("python3"),
            PathBuf::from("python"),
        ]
    };
    candidates
        .into_iter()
        .find(|candidate| candidate.is_absolute() && candidate.is_file())
        .unwrap_or_else(|| {
            if cfg!(windows) {
                PathBuf::from("python")
            } else {
                PathBuf::from("python3")
            }
        })
}

fn spawn_stdout_reader(shared: Arc<Mutex<Shared>>, mut stdout: ChildStdout) {
    thread::Builder::new()
        .name("veyra-runtime-stdout".into())
        .spawn(move || loop {
            match read_packet(&mut stdout) {
                Ok((metadata, payload)) => dispatch_packet(&shared, metadata, payload),
                Err(error) if error.kind() == io::ErrorKind::UnexpectedEof => break,
                Err(error) => {
                    if let Ok(mut state) = shared.lock() {
                        state.last_error = Some(error.to_string());
                        fail_pending(&mut state, SupervisorError::Protocol(error.to_string()));
                    }
                    break;
                }
            }
        })
        .expect("failed to spawn runtime stdout reader");
}

fn spawn_stderr_reader(shared: Arc<Mutex<Shared>>, mut stderr: ChildStderr) {
    thread::Builder::new()
        .name("veyra-runtime-stderr".into())
        .spawn(move || {
            let mut buffer = [0_u8; 4096];
            loop {
                match stderr.read(&mut buffer) {
                    Ok(0) => break,
                    Ok(size) => {
                        if let Ok(mut state) = shared.lock() {
                            state
                                .stderr
                                .push_str(&String::from_utf8_lossy(&buffer[..size]));
                            let excess = state.stderr.len().saturating_sub(65536);
                            if excess > 0 {
                                state.stderr.drain(..excess);
                            }
                        }
                    }
                    Err(_) => break,
                }
            }
        })
        .expect("failed to spawn runtime stderr reader");
}

fn spawn_process_monitor(shared: Arc<Mutex<Shared>>) {
    thread::Builder::new()
        .name("veyra-runtime-monitor".into())
        .spawn(move || loop {
            thread::sleep(Duration::from_millis(50));
            let exited = match shared.lock() {
                Ok(mut state) => match state.child.as_mut() {
                    Some(child) => match child.try_wait() {
                        Ok(Some(status)) => {
                            state.child = None;
                            state.stdin = None;
                            if !state.stopping {
                                let message =
                                    runtime_exit_error(&status.to_string(), &state.stderr);
                                state.last_error = Some(message.clone());
                                fail_pending(&mut state, SupervisorError::Process(message));
                            }
                            true
                        }
                        Ok(None) => false,
                        Err(error) => {
                            state.last_error = Some(error.to_string());
                            fail_pending(&mut state, SupervisorError::Process(error.to_string()));
                            state.child = None;
                            state.stdin = None;
                            true
                        }
                    },
                    None => true,
                },
                Err(_) => true,
            };
            if exited {
                break;
            }
        })
        .expect("failed to spawn runtime monitor");
}

fn runtime_exit_error(status: &str, stderr: &str) -> String {
    const STDERR_LIMIT: usize = 4096;
    let compact = stderr.split_whitespace().collect::<Vec<_>>().join(" ");
    if compact.is_empty() {
        return format!("runtime exited: {status}");
    }
    let detail = if compact.chars().count() > STDERR_LIMIT {
        compact
            .chars()
            .rev()
            .take(STDERR_LIMIT)
            .collect::<String>()
            .chars()
            .rev()
            .collect::<String>()
    } else {
        compact
    };
    format!("runtime exited: {status}: {detail}")
}

fn fail_pending(shared: &mut Shared, error: SupervisorError) {
    for (_, sender) in shared.pending.drain() {
        let _ = sender.send(Err(error.clone()));
    }
}

fn dispatch_packet(shared: &Arc<Mutex<Shared>>, metadata: Value, payload: Vec<u8>) {
    let kind = metadata.get("type").and_then(Value::as_str);
    if let Ok(mut state) = shared.lock() {
        if kind == Some("response") {
            if let Some(id) = metadata.get("id").and_then(Value::as_str) {
                if let Some(sender) = state.pending.remove(id) {
                    if metadata.get("ok").and_then(Value::as_bool).unwrap_or(false) {
                        let _ = sender.send(Ok(metadata));
                    } else {
                        let message = metadata
                            .get("error")
                            .and_then(|value| value.get("message"))
                            .and_then(Value::as_str)
                            .unwrap_or("runtime request failed");
                        let _ = sender.send(Err(SupervisorError::Response(message.to_owned())));
                    }
                    return;
                }
            }
        }
        if state.events.len() >= MAX_EVENTS {
            state.events.pop_front();
        }
        state.events.push_back(RuntimeEvent { metadata, payload });
    }
}

fn read_packet(reader: &mut impl Read) -> io::Result<(Value, Vec<u8>)> {
    let mut header = [0_u8; HEADER_SIZE];
    reader.read_exact(&mut header)?;
    if &header[0..4] != b"VYRA" || u16::from_le_bytes([header[4], header[5]]) != 1 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "invalid protocol magic/version",
        ));
    }
    let kind = u16::from_le_bytes([header[6], header[7]]);
    let metadata_size = u32::from_le_bytes([header[8], header[9], header[10], header[11]]) as usize;
    let payload_size =
        u32::from_le_bytes([header[12], header[13], header[14], header[15]]) as usize;
    if !(kind == 1 || kind == 2)
        || metadata_size > MAX_METADATA
        || payload_size > MAX_PAYLOAD
        || (kind == 1 && payload_size != 0)
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "protocol length/kind limit exceeded",
        ));
    }
    let mut metadata = vec![0_u8; metadata_size];
    reader.read_exact(&mut metadata)?;
    let metadata: Value = serde_json::from_slice(&metadata)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error.to_string()))?;
    if !metadata.is_object() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "metadata must be an object",
        ));
    }
    let mut payload = vec![0_u8; payload_size];
    reader.read_exact(&mut payload)?;
    Ok((metadata, payload))
}

#[cfg(test)]
fn decode_packet(packet: &[u8]) -> Result<(Value, Vec<u8>), SupervisorError> {
    read_packet(&mut &packet[..]).map_err(|error| SupervisorError::Protocol(error.to_string()))
}

#[cfg(test)]
mod tests {
    use super::{
        decode_packet, dispatch_packet, fail_pending, python_executable, read_packet,
        RuntimeSupervisor, Shared, SupervisorError, HEADER_SIZE,
    };
    use serde_json::json;
    use std::collections::{HashMap, VecDeque};
    use std::io::Cursor;
    use std::sync::{Arc, Mutex};
    use std::time::{Duration, Instant};

    #[test]
    fn rejects_truncated_header() {
        assert!(decode_packet(&[0; HEADER_SIZE]).is_err());
    }

    #[test]
    fn decodes_a_response_packet() {
        let metadata = serde_json::to_vec(&json!({"type":"response","id":"1","ok":true})).unwrap();
        let mut packet = Vec::new();
        packet.extend_from_slice(b"VYRA");
        packet.extend_from_slice(&1_u16.to_le_bytes());
        packet.extend_from_slice(&1_u16.to_le_bytes());
        packet.extend_from_slice(&(metadata.len() as u32).to_le_bytes());
        packet.extend_from_slice(&0_u32.to_le_bytes());
        packet.extend_from_slice(&metadata);
        let (value, payload) = read_packet(&mut Cursor::new(packet)).unwrap();
        assert_eq!(value["id"], "1");
        assert!(payload.is_empty());
    }

    #[test]
    fn supervises_the_real_python_runtime_status_path() {
        let repo = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .to_path_buf();
        let supervisor = RuntimeSupervisor::new(repo);
        let response = supervisor
            .request("status", json!({}))
            .expect("runtime status response");
        assert_eq!(response["type"], "response");
        assert_eq!(response["ok"], true);
        supervisor.stop().unwrap();
    }

    #[test]
    fn prefers_the_packaged_python_runtime() {
        let root =
            std::env::temp_dir().join(format!("veyra-supervisor-test-{}", std::process::id()));
        let executable = root.join("python/bin/python3");
        std::fs::create_dir_all(executable.parent().unwrap()).unwrap();
        std::fs::write(&executable, b"python").unwrap();

        assert_eq!(python_executable(&root), executable);
        std::fs::remove_dir_all(root).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn packaged_python_cannot_write_bytecode_into_signed_bundle() {
        use std::os::unix::fs::PermissionsExt;

        let root =
            std::env::temp_dir().join(format!("veyra-python-bytecode-test-{}", std::process::id()));
        let executable = root.join("python/bin/python3");
        std::fs::create_dir_all(executable.parent().unwrap()).unwrap();
        std::fs::write(
            &executable,
            // Write then rename so the marker only appears once complete: a
            // reader polling for the file must never observe it half-written.
            b"#!/bin/sh\nprintf '%s' \"$PYTHONDONTWRITEBYTECODE\" > bytecode-env.tmp\n\
              mv bytecode-env.tmp bytecode-env.txt\nexec sleep 10\n",
        )
        .unwrap();
        std::fs::set_permissions(&executable, std::fs::Permissions::from_mode(0o755)).unwrap();

        let supervisor = RuntimeSupervisor::new(&root);
        supervisor.start().unwrap();
        let marker = root.join("bytecode-env.txt");
        // The first exec of a freshly written script can take well over a
        // second on macOS (the system policy scan of a new executable), and
        // longer under a loaded parallel test run; a 1 s budget was flaky.
        let deadline = std::time::Instant::now() + Duration::from_secs(20);
        while !marker.is_file() && std::time::Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(10));
        }
        let actual = std::fs::read_to_string(&marker).unwrap_or_default();
        {
            let mut shared = supervisor.shared.lock().unwrap();
            shared.stdin.take();
            if let Some(mut child) = shared.child.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
        std::fs::remove_dir_all(root).unwrap();
        assert_eq!(actual, "1");
    }

    fn test_repo() -> std::path::PathBuf {
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .to_path_buf()
    }

    fn wait_while_running(supervisor: &RuntimeSupervisor, timeout: Duration) -> bool {
        let deadline = Instant::now() + timeout;
        while supervisor.is_running() && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(25));
        }
        !supervisor.is_running()
    }

    /// Portable across Linux and macOS: `ps -p` also lists unreaped zombies,
    /// so a stopped child must be both terminated and reaped to count as gone.
    #[cfg(unix)]
    fn pid_alive(pid: u32) -> bool {
        std::process::Command::new("ps")
            .args(["-p", &pid.to_string()])
            .stdout(std::process::Stdio::null())
            .status()
            .is_ok_and(|status| status.success())
    }

    #[test]
    fn duplicate_start_keeps_a_single_child() {
        let supervisor = RuntimeSupervisor::new(test_repo());
        supervisor.start().expect("first start");
        let first = supervisor.pid().expect("child pid after start");
        supervisor.start().expect("duplicate start is idempotent");
        assert_eq!(supervisor.pid(), Some(first));
        assert!(supervisor.is_running());
        let status = supervisor
            .request("status", json!({}))
            .expect("status through the single child");
        assert_eq!(status["ok"], true);
        supervisor.stop().unwrap();
    }

    #[test]
    fn stop_is_idempotent_and_releases_the_child() {
        let supervisor = RuntimeSupervisor::new(test_repo());
        supervisor.stop().expect("stop before start is a no-op");
        assert!(!supervisor.is_running());
        supervisor.start().expect("start");
        assert!(supervisor.is_running());
        supervisor.stop().expect("stop");
        supervisor.stop().expect("stop after stop is a no-op");
        assert!(!supervisor.is_running());
        assert_eq!(supervisor.pid(), None);
    }

    #[test]
    #[cfg(unix)]
    fn stop_leaves_no_orphan_and_supervisor_restarts() {
        let supervisor = RuntimeSupervisor::new(test_repo());
        supervisor.start().expect("start");
        let pid = supervisor.pid().expect("child pid");
        assert!(pid_alive(pid));
        supervisor.stop().expect("stop");
        assert!(
            !pid_alive(pid),
            "stopped runtime pid {pid} must be reaped, not orphaned"
        );
        assert!(!supervisor.is_running());
        // The supervisor itself survives stop: a fresh session starts cleanly.
        supervisor.start().expect("restart after stop");
        let status = supervisor
            .request("status", json!({}))
            .expect("status after restart");
        assert_eq!(status["ok"], true);
        supervisor.stop().unwrap();
    }

    #[test]
    #[cfg(unix)]
    fn external_crash_is_reaped_and_recovered() {
        let supervisor = RuntimeSupervisor::new(test_repo());
        supervisor.start().expect("start");
        let pid = supervisor.pid().expect("child pid");
        std::process::Command::new("kill")
            .arg("-9")
            .arg(pid.to_string())
            .status()
            .expect("SIGKILL the runtime");
        assert!(
            wait_while_running(&supervisor, Duration::from_secs(5)),
            "monitor must reap the crashed child"
        );
        assert_eq!(supervisor.pid(), None);
        // Next request auto-starts a fresh runtime (crash recovery path).
        let status = supervisor
            .request("status", json!({}))
            .expect("status after crash recovery");
        assert_eq!(status["ok"], true);
        supervisor.stop().unwrap();
    }

    fn test_shared() -> Arc<Mutex<Shared>> {
        Arc::new(Mutex::new(Shared {
            stdin: None,
            child: None,
            pending: HashMap::new(),
            events: VecDeque::new(),
            stderr: String::new(),
            last_error: None,
            sequence: 0,
            stopping: false,
        }))
    }

    #[test]
    fn response_packets_resolve_their_pending_sender() {
        let shared = test_shared();
        let (sender, receiver) = std::sync::mpsc::channel();
        shared
            .lock()
            .unwrap()
            .pending
            .insert("7".to_owned(), sender);
        dispatch_packet(
            &shared,
            json!({"type": "response", "id": "7", "ok": true}),
            Vec::new(),
        );
        assert!(receiver
            .recv_timeout(Duration::from_secs(1))
            .unwrap()
            .is_ok());
        assert!(shared.lock().unwrap().pending.is_empty());
    }

    #[test]
    fn error_responses_and_crashes_fail_pending_with_context() {
        let shared = test_shared();
        let (sender, receiver) = std::sync::mpsc::channel();
        shared
            .lock()
            .unwrap()
            .pending
            .insert("9".to_owned(), sender);
        dispatch_packet(
            &shared,
            json!({"type": "response", "id": "9", "ok": false,
                   "error": {"message": "boom"}}),
            Vec::new(),
        );
        let error = receiver
            .recv_timeout(Duration::from_secs(1))
            .unwrap()
            .unwrap_err();
        assert!(matches!(error, SupervisorError::Response(message) if message == "boom"));

        // Crash path: every waiter still blocked on the dead child is failed.
        let (sender, receiver) = std::sync::mpsc::channel();
        shared
            .lock()
            .unwrap()
            .pending
            .insert("10".to_owned(), sender);
        fail_pending(
            &mut shared.lock().unwrap(),
            SupervisorError::Process("runtime exited: signal".to_owned()),
        );
        let error = receiver
            .recv_timeout(Duration::from_secs(1))
            .unwrap()
            .unwrap_err();
        assert!(matches!(error, SupervisorError::Process(_)));

        // Non-response packets never resolve a waiter; they queue as events.
        dispatch_packet(&shared, json!({"type": "telemetry", "tick": 3}), Vec::new());
        assert_eq!(shared.lock().unwrap().events.len(), 1);
    }

    #[test]
    fn runtime_exit_error_includes_bounded_stderr_context() {
        let message =
            super::runtime_exit_error("exit status: 1", "Traceback: No module named runtime\n");
        assert!(message.contains("exit status: 1"));
        assert!(message.contains("No module named runtime"));
        assert!(!message.contains('\n'));

        let bounded = super::runtime_exit_error("exit status: 1", &"x".repeat(10_000));
        assert!(bounded.len() < 4_200);
    }

    #[test]
    fn oversize_protocol_lengths_are_rejected() {
        let metadata = serde_json::to_vec(&json!({"type":"response","id":"1","ok":true})).unwrap();
        let mut packet = Vec::new();
        packet.extend_from_slice(b"VYRA");
        packet.extend_from_slice(&1_u16.to_le_bytes());
        packet.extend_from_slice(&1_u16.to_le_bytes());
        packet.extend_from_slice(&((1024 * 1024 + 1) as u32).to_le_bytes());
        packet.extend_from_slice(&0_u32.to_le_bytes());
        packet.extend_from_slice(&metadata);
        assert!(decode_packet(&packet).is_err());
    }
}
