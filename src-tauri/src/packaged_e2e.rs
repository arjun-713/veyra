//! Packaged-session E2E for the Tauri backend path (real data, no mocks).
//!
//! These tests drive the exact stack the packaged Tauri application boots:
//! `DesktopControlService` = `ControlHost` (in-process control daemon) plus a
//! loopback `ControlClient`, and `RuntimeController` → `RuntimeSupervisor` →
//! the real Python product runtime → the real C++ mapper.
//!
//! The real-data session test requires a SemanticPOSS checkout and a working
//! Python runtime. Both are absent on packaging-only CI runners, so the tests
//! skip (never fail) when the prerequisites are unavailable. Override the
//! repository root (packaged-layout proof) and dataset location with:
//! `VEYRA_E2E_REPO`, `VEYRA_E2E_DATASET_ROOT`, `VEYRA_E2E_PYTHON`.

use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use crate::control::ControlClient;
use crate::control::RuntimeController;
use crate::control_host::ControlHost;

const DATASET_FORMAT: &str = "semanticposs";
const DATASET_SUBDIR: &str = "data/raw/semanticposs/dataset";

fn e2e_repo() -> PathBuf {
    if let Ok(value) = std::env::var("VEYRA_E2E_REPO") {
        return PathBuf::from(value);
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("src-tauri must live inside the repository")
        .to_path_buf()
}

fn e2e_dataset_root(repo: &Path) -> PathBuf {
    if let Ok(value) = std::env::var("VEYRA_E2E_DATASET_ROOT") {
        return PathBuf::from(value);
    }
    repo.join(DATASET_SUBDIR)
}

fn e2e_python(repo: &Path) -> Option<PathBuf> {
    if let Ok(value) = std::env::var("VEYRA_E2E_PYTHON") {
        return Some(PathBuf::from(value));
    }
    if let Ok(value) = std::env::var("VEYRA_PYTHON") {
        return Some(PathBuf::from(value));
    }
    [
        repo.join(".venv/bin/python"),
        repo.join("python/bin/python3"),
    ]
    .into_iter()
    .find(|candidate| candidate.is_file())
}

fn e2e_mapper(repo: &Path) -> Option<PathBuf> {
    if let Ok(value) = std::env::var("VEYRA_MAPPER") {
        let path = PathBuf::from(value);
        if path.is_file() {
            return Some(path);
        }
        return None;
    }
    [
        repo.join("bin/veyra_runtime"),
        repo.join("build/apps/runtime/veyra_runtime"),
    ]
    .into_iter()
    .find(|candidate| candidate.is_file())
}

/// Returns `None` when the real-data prerequisites are unavailable; the caller
/// must skip (not fail) in that case so packaging-only runners stay green.
fn e2e_prerequisites() -> Option<(PathBuf, PathBuf)> {
    let repo = e2e_repo();
    let dataset_root = e2e_dataset_root(&repo);
    if !dataset_root.is_dir() {
        eprintln!("E2E SKIP: SemanticPOSS dataset is unavailable at {dataset_root:?}");
        return None;
    }
    if dataset_root.join("sequences").is_dir()
        && !dataset_root.join("sequences").join("00").is_dir()
    {
        eprintln!("E2E SKIP: SemanticPOSS sequences are unavailable at {dataset_root:?}");
        return None;
    }
    let Some(mapper) = e2e_mapper(&repo) else {
        eprintln!("E2E SKIP: C++ mapper binary is unavailable under {repo:?}");
        return None;
    };
    let Some(python) = e2e_python(&repo) else {
        eprintln!("E2E SKIP: no Python runtime resolves for {repo:?}");
        return None;
    };
    let probe = Command::new(&python)
        .arg("-c")
        .arg("import runtime.service, viewer.runtime")
        .current_dir(&repo)
        .output();
    match probe {
        Ok(output) if output.status.success() => {
            eprintln!("E2E prerequisites: repo={repo:?} mapper={mapper:?} python={python:?}");
            Some((repo, dataset_root))
        }
        _ => {
            eprintln!("E2E SKIP: {python:?} cannot import the product runtime");
            None
        }
    }
}

fn timed<T>(label: &str, operation: impl FnOnce() -> T) -> T {
    let started = Instant::now();
    let value = operation();
    eprintln!(
        "E2E {label} completed in {:.1}s",
        started.elapsed().as_secs_f64()
    );
    value
}

fn ok_response(label: &str, result: Result<Value, String>) -> Value {
    match result {
        Ok(value) => {
            eprintln!("E2E {label}: ok");
            value
        }
        Err(error) => panic!("E2E {label} failed: {error}"),
    }
}

/// Diagnostic only: reports whether the daemon's loopback port is still in
/// LISTEN state at the moment of a control failure (via /proc/net/tcp).
fn listener_state(endpoint: std::net::SocketAddr) -> String {
    let std::net::IpAddr::V4(ipv4) = endpoint.ip() else {
        return format!("{endpoint} NON-V4");
    };
    let wanted = format!(
        "{:08X}:{:04X}",
        u32::from_ne_bytes(ipv4.octets()),
        endpoint.port()
    );
    let mut found = false;
    for table in ["net/tcp", "net/tcp6"] {
        let path = format!("/proc/{table}");
        if let Ok(contents) = std::fs::read_to_string(&path) {
            for line in contents.lines().skip(1) {
                let fields: Vec<&str> = line.split_whitespace().collect();
                if fields.len() > 3 && fields[1].eq_ignore_ascii_case(&wanted) && fields[3] == "0A"
                {
                    found = true;
                }
            }
        }
    }
    if found {
        format!("{endpoint} LISTENING")
    } else {
        format!("{endpoint} NOT-LISTENING")
    }
}

fn drain_summary(host: &ControlHost) -> (usize, usize, Vec<String>) {
    let events = host.drain_events();
    let mut kinds = Vec::new();
    let mut visualization_bytes = 0;
    for event in &events {
        let kind = event
            .metadata
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or("?")
            .to_owned();
        if kind == "visualization" {
            visualization_bytes = visualization_bytes.max(event.payload.len());
        }
        if !kinds.contains(&kind) {
            kinds.push(kind);
        }
    }
    (events.len(), visualization_bytes, kinds)
}

/// Full acceptance flow with a real SemanticPOSS session, mirroring exactly
/// what the packaged Tauri UI invokes: dataset catalog → configure → step →
/// seek → policy → layer → start/pause → diagnostics → clean stop. Telemetry
/// and visualization evidence is asserted from the live backend.
#[test]
fn packaged_tauri_session_runs_a_real_semanticposs_flow() {
    let Some((repo, dataset_root)) = e2e_prerequisites() else {
        return;
    };
    let root = dataset_root.to_string_lossy().into_owned();

    let mut controller = RuntimeController::new(&repo);

    // 1. Dataset select: catalog the real SemanticPOSS root.
    let catalog_response = timed("datasets", || {
        ok_response(
            "datasets",
            controller.datasets(DATASET_FORMAT, Path::new(&root)),
        )
    });
    let catalog = &catalog_response["result"];
    let sequence = catalog["sequences"]
        .as_array()
        .and_then(|sequences| {
            sequences.iter().find_map(|entry| {
                let id = entry.get("id")?.as_str()?;
                let frames = entry.get("frames")?.as_u64()?;
                (frames > 0).then(|| id.to_owned())
            })
        })
        .expect("catalog must offer a non-empty sequence");
    eprintln!("E2E catalog sequence={sequence}");

    // 2. Runtime start: configure mirrors the production session defaults the
    // packaged UI sends (ground-truth semantics, ground + terrain evidence).
    let config = json!({
        "dataset": DATASET_FORMAT,
        "dataset_root": root,
        "sequence": sequence,
        "pipeline": {
            "semantic": {"mode": "ground_truth"},
            "ground": {
                "enabled": true,
                "parameter_overrides": {"min_range": 0.0, "max_range": 100.0}
            },
            "terrain": {"enabled": true},
            "temporal": {"enabled": false}
        }
    });
    let configured = timed("configure", || {
        ok_response("configure", controller.configure(config))
    });
    let frames = configured["status"]["frames"]
        .as_u64()
        .expect("configured session reports frame count");
    assert!(frames > 0, "SemanticPOSS session must expose frames");
    eprintln!("E2E configured frames={frames}");

    let status = ok_response("status", controller.refresh_status());
    // refresh_status reports live runtime truth (plus pid/mapper); the local
    // controller snapshot carries the dataset_open flag instead.
    assert_eq!(status["dataset"], "semanticposs");
    assert_eq!(status["sequence"], sequence);
    assert_eq!(status["frames"], frames);
    let local = controller.status();
    assert_eq!(local["dataset_open"], true);
    assert_eq!(local["runtime_running"], true);
    assert!(local["runtime_pid"].as_u64().is_some());

    // 3. Real processing: one frame end to end.
    timed("step", || {
        ok_response("step", controller.command("step", json!({})))
    });
    let status = ok_response("status-after-step", controller.refresh_status());
    assert_eq!(status["index"], 0);
    eprintln!(
        "E2E after step: index={} policy={}",
        status["index"], status["policy"]
    );

    // 4. Map display evidence: the supervisor must have delivered telemetry
    // with live map statistics plus a binary visualization frame.
    let (telemetry_cells, visual_bytes, perception, health) = timed("drain", || {
        let events = controller.drain_events();
        let mut cells = 0_u64;
        let mut visual = 0_usize;
        let mut perception = Value::Null;
        let mut health = Value::Null;
        for event in &events {
            match event.metadata.get("type").and_then(Value::as_str) {
                Some("telemetry") => {
                    cells = cells.max(
                        event
                            .metadata
                            .pointer("/map/active_cells")
                            .and_then(Value::as_u64)
                            .unwrap_or(0),
                    );
                    perception = event
                        .metadata
                        .get("perception")
                        .cloned()
                        .unwrap_or(Value::Null);
                    health = event.metadata.get("health").cloned().unwrap_or(Value::Null);
                }
                Some("visualization") => {
                    visual = visual.max(event.payload.len());
                }
                _ => {}
            }
        }
        eprintln!("E2E drained {} events", events.len());
        (cells, visual, perception, health)
    });
    assert!(
        telemetry_cells > 0,
        "telemetry must report live map cells after real processing"
    );
    assert!(
        visual_bytes > 0,
        "a binary visualization frame must reach the renderer channel"
    );
    assert_eq!(perception["provider"], "Ground Truth");
    assert!(perception["points"].as_u64().unwrap_or(0) > 0);
    assert!(health["runtime"].as_str().is_some());
    assert_eq!(health["telemetry"], "fresh");
    eprintln!("E2E map evidence: active_cells={telemetry_cells} visual_bytes={visual_bytes}");

    // 5. Seek back to the first frame (reprocesses deterministically).
    timed("seek", || {
        ok_response("seek", controller.command("seek", json!({"index": 0})))
    });
    let status = ok_response("status-after-seek", controller.refresh_status());
    assert_eq!(status["index"], 0);

    // 6. Policy switch reconfigures the live session.
    timed("policy", || {
        ok_response(
            "policy",
            controller.command("policy", json!({"policy": "uniform40"})),
        )
    });
    let status = ok_response("status-after-policy", controller.refresh_status());
    assert_eq!(status["policy"], "uniform40");
    assert!(status["frames"].as_u64().unwrap_or(0) > 0);

    // 7. Layer switch is local and instant.
    let layered = ok_response(
        "layer",
        controller.command("layer", json!({"layer": "lod"})),
    );
    assert_eq!(layered["status"]["layer"], "lod");

    // 8. Playback state machine: play then pause.
    timed("start", || {
        ok_response("start", controller.command("start", json!({})))
    });
    timed("pause", || {
        ok_response("pause", controller.command("pause", json!({})))
    });
    let status = ok_response("status-after-pause", controller.refresh_status());
    assert_eq!(status["state"], "paused");

    // 9. Inspect: diagnostics carry the runtime + supervisor truth.
    let diagnostics = controller.diagnostics();
    assert_eq!(
        diagnostics["supervisor"]["running"].as_bool(),
        Some(true),
        "supervisor must still run before clean stop"
    );
    assert!(
        diagnostics.get("runtime").is_some(),
        "diagnostics must carry the runtime report"
    );

    // 10. Clean stop. The runtime idles on its command stream, so shutdown
    // resolves via the supervisor's stop escalation; poll briefly for reap.
    timed("stop", || {
        controller
            .stop()
            .unwrap_or_else(|error| panic!("E2E stop failed: {error}"))
    });
    let stopped = std::time::Instant::now();
    loop {
        if controller.status()["runtime_running"] == json!(false) {
            break;
        }
        assert!(
            stopped.elapsed() < Duration::from_secs(5),
            "runtime process was not reaped after clean stop"
        );
        std::thread::sleep(Duration::from_millis(50));
    }
    eprintln!("E2E real-data flow complete: sequence={sequence} frames={frames}");
}

/// The packaged boot path over loopback TCP: daemon start, authenticated fast
/// commands, event drain, clean shutdown. Slow session commands are covered by
/// the controller-level flow above; this test proves the Tauri control plane
/// wiring (discovery, auth, framing) end to end.
#[test]
fn packaged_control_plane_serves_authenticated_fast_commands() {
    let Some((_repo, dataset_root)) = e2e_prerequisites() else {
        return;
    };
    let config_dir = std::env::temp_dir().join(format!(
        "veyra-packaged-e2e-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock before epoch")
            .as_nanos()
    ));
    std::fs::create_dir_all(&config_dir).expect("e2e config dir");

    let repo = e2e_repo();
    let mut host =
        Some(ControlHost::start(repo, &config_dir).expect("packaged control daemon boots"));
    let endpoint = host.as_ref().expect("host").config().endpoint;
    let token_file = host.as_ref().expect("host").config().token_file.clone();
    let mut client = ControlClient::from_endpoint_and_token_file(endpoint, &token_file)
        .expect("packaged client authenticates from the discovery record");

    let mut call = |command: &str, args: Value, host: &mut Option<ControlHost>| {
        // Bounded tolerance for load-marginal timing only: the first command
        // after a cold boot (~1.8 s) and the stop escalation both straddle
        // ControlClient's fixed 2 s IO budget, so a transient timeout is
        // retried. Every retry redoes the idempotent command and the final
        // shutdown + join still assert a live, cleanly stopped daemon, so a
        // genuinely dead backend cannot pass.
        let mut attempts = 0;
        loop {
            attempts += 1;
            match client.request(command, args.clone()) {
                Ok(value) => return value,
                Err(error)
                    if attempts < 5
                        && (error.to_string().contains("cannot read")
                            || error.to_string().contains("cannot connect")) =>
                {
                    eprintln!("E2E retrying {command} after transient control error: {error}");
                    if let Some(host) = host.as_ref() {
                        eprintln!(
                            "E2E listener state: {}",
                            listener_state(host.config().endpoint)
                        );
                    }
                    std::thread::sleep(Duration::from_millis(500));
                }
                Err(error) => {
                    // Failure diagnostics: if the daemon thread already
                    // exited, joining it reveals serve's error instead of
                    // hanging; guarded by a timeout for a live daemon.
                    // The test panics right after, so taking host is fine.
                    if let Some(mut taken) = host.take() {
                        let (sender, receiver) = std::sync::mpsc::channel();
                        std::thread::spawn(move || {
                            let result = taken.join_after_shutdown();
                            let _ = sender.send(format!("{result:?}"));
                        });
                        match receiver.recv_timeout(Duration::from_secs(3)) {
                            Ok(joined) => eprintln!("E2E daemon thread outcome: {joined}"),
                            Err(_) => eprintln!("E2E daemon thread still alive (join timed out)"),
                        }
                    }
                    panic!("E2E {command} failed: {error}")
                }
            }
        }
    };

    let catalog_response = call(
        "datasets",
        json!({"dataset": DATASET_FORMAT, "root": dataset_root.to_string_lossy()}),
        &mut host,
    );
    // The daemon returns the supervisor envelope; the catalog is its result.
    let catalog = &catalog_response["result"];
    assert!(
        catalog["sequences"]
            .as_array()
            .is_some_and(|sequences| !sequences.is_empty()),
        "packaged daemon must list real SemanticPOSS sequences"
    );
    eprintln!(
        "E2E catalog sequences={}",
        catalog["sequences"].as_array().map(Vec::len).unwrap_or(0)
    );

    let status = call("status", json!({}), &mut host);
    assert!(status.get("state").is_some());

    let layered = call(
        "command",
        json!({"name": "layer", "args": {"layer": "traversability"}}),
        &mut host,
    );
    assert_eq!(layered["status"]["layer"], "traversability");

    let (events, _visual_bytes, _kinds) = drain_summary(host.as_ref().expect("host"));
    eprintln!("E2E drained {events} control-plane events");

    call("stop", json!({}), &mut host);
    call("shutdown", json!({}), &mut host);
    host.take()
        .expect("host")
        .join_after_shutdown()
        .unwrap_or_else(|error| panic!("E2E daemon join failed: {error}"));
    let _ = std::fs::remove_dir_all(&config_dir);
    eprintln!("E2E packaged control-plane proof complete");
}
