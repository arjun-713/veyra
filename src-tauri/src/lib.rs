mod benchmark_artifact;
mod commands;
pub mod control;
mod control_host;
mod desktop_control;
#[cfg(test)]
mod packaged_e2e;
pub mod supervisor;
mod telemetry;
mod visualization_transport;

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use tauri::{Emitter, Manager};

use benchmark_artifact::BenchmarkArtifacts;
use desktop_control::DesktopControlService;

#[derive(Clone)]
struct EventPump {
    running: Arc<AtomicBool>,
}

impl EventPump {
    fn new() -> Self {
        Self {
            running: Arc::new(AtomicBool::new(true)),
        }
    }

    fn stop(&self) {
        self.running.store(false, Ordering::Release);
    }
}

pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .setup(|app| {
            let config_dir = app.path().app_config_dir().map_err(|error| {
                format!("cannot resolve protected control storage directory: {error}")
            })?;
            let resource_dir = app
                .path()
                .resource_dir()
                .unwrap_or_else(|_| std::env::current_dir().unwrap_or_default());
            let development_repo = development_runtime_root();
            let control = DesktopControlService::bootstrap(
                application_runtime_root(&resource_dir, development_repo.as_deref()),
                &config_dir,
            );
            let startup_diagnostic = control.startup_diagnostic().map(str::to_owned);
            app.manage(Mutex::new(control));
            app.manage(BenchmarkArtifacts::default());
            app.manage(visualization_transport::VisualizationTransport::default());
            let event_pump = EventPump::new();
            spawn_event_pump(app.handle().clone(), Arc::clone(&event_pump.running));
            app.manage(event_pump);
            if let Some(message) = startup_diagnostic {
                let _ = app.emit(
                    "veyra://event",
                    serde_json::json!({
                        "type": "diagnostics",
                        "schema_version": 1,
                        "diagnostic": {
                            "code": "CONTROL_UNAVAILABLE",
                            "message": message
                        }
                    }),
                );
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::runtime_status,
            commands::runtime_command,
            commands::runtime_stop,
            commands::runtime_configure,
            commands::runtime_validate_config,
            commands::choose_dataset,
            commands::open_dataset,
            commands::export_diagnostics,
            commands::read_benchmark_artifact,
            commands::runtime_shutdown,
            commands::runtime_visualization_transport,
            commands::take_visualization,
        ]);
    let app = builder
        .build(tauri::generate_context!())
        .expect("error while building Veyra");
    app.run(|app_handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            if let Some(pump) = app_handle.try_state::<EventPump>() {
                pump.stop();
            }
            if let Some(state) = app_handle.try_state::<Mutex<DesktopControlService>>() {
                match state.lock() {
                    Ok(mut service) => {
                        if let Err(error) = service.shutdown() {
                            eprintln!("control daemon shutdown unavailable: {error}");
                        }
                    }
                    Err(_) => {
                        eprintln!("control daemon shutdown unavailable: client lock poisoned")
                    }
                }
            }
        }
    });
}

fn spawn_event_pump(app_handle: tauri::AppHandle, running: Arc<AtomicBool>) {
    thread::Builder::new()
        .name("veyra-desktop-event-pump".to_owned())
        .spawn(move || {
            while running.load(Ordering::Acquire) {
                let events = app_handle
                    .try_state::<Mutex<DesktopControlService>>()
                    .and_then(|service| service.lock().ok().map(|service| service.drain_events()))
                    .unwrap_or_default();
                for event in events {
                    match app_handle
                        .state::<visualization_transport::VisualizationTransport>()
                        .prepare(event)
                    {
                        Ok(Some((channel, payload))) => {
                            if let Some(artifacts) = app_handle.try_state::<BenchmarkArtifacts>() {
                                artifacts.observe(&payload);
                            }
                            let _ = app_handle.emit(channel, payload);
                        }
                        Ok(None) => {}
                        Err(error) => {
                            let _ = app_handle.emit(
                                "veyra://event",
                                serde_json::json!({
                                    "type": "diagnostics",
                                    "schema_version": 1,
                                    "diagnostic": {
                                        "code": "RUNTIME_EVENT_REJECTED",
                                        "message": error,
                                    }
                                }),
                            );
                        }
                    }
                }
                thread::sleep(Duration::from_millis(16));
            }
        })
        .expect("failed to spawn desktop event pump");
}

fn forwardable_runtime_event(
    event: supervisor::RuntimeEvent,
) -> Result<(&'static str, serde_json::Value), String> {
    let (channel, payload) = telemetry::event_payload(event.metadata, event.payload)?;
    Ok((channel.name(), payload))
}

/// Tauri places configured resources beneath the application resource
/// directory. Development fallback remains the repository root, whereas a
/// packaged application must supervise the staged `backend` directory.
///
/// The staged marker (`manifest.json`, always written by
/// `scripts/stage_tauri_backend.py`) is required: an unstaged `backend`
/// directory (for example a bare `.gitkeep` placeholder shipped by a build
/// that skipped staging) must never masquerade as a runnable backend.
fn runtime_root(resource_dir: &Path) -> PathBuf {
    runtime_root_with_executable_dir(resource_dir, resource_dir)
}

fn runtime_root_with_executable_dir(resource_dir: &Path, executable_dir: &Path) -> PathBuf {
    for staged_backend in [
        resource_dir.join("backend"),
        resource_dir.join("resources/backend"),
        executable_dir.join("backend"),
        executable_dir.join("resources/backend"),
    ] {
        if staged_backend.join("manifest.json").is_file()
            && staged_backend.join("runtime/__main__.py").is_file()
        {
            return staged_backend;
        }
    }
    resource_dir.to_path_buf()
}

fn application_runtime_root(resource_dir: &Path, development_repo: Option<&Path>) -> PathBuf {
    if let Some(repo) = development_repo.filter(|repo| repo.join("runtime/__main__.py").is_file()) {
        return repo.to_path_buf();
    }
    let executable_dir = std::env::current_exe()
        .ok()
        .and_then(|executable| executable.parent().map(Path::to_path_buf));
    executable_dir.as_deref().map_or_else(
        || runtime_root(resource_dir),
        |executable_dir| runtime_root_with_executable_dir(resource_dir, executable_dir),
    )
}

fn development_runtime_root() -> Option<PathBuf> {
    if !cfg!(debug_assertions) {
        return None;
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(Path::to_path_buf)
}

#[cfg(test)]
mod tests {
    use super::control::state::{AppState, RuntimeState, StateError};
    use super::forwardable_runtime_event;
    use super::supervisor::RuntimeEvent;
    use serde_json::json;
    use std::fs;

    #[test]
    fn a_new_application_starts_booting_and_cannot_play_without_a_dataset() {
        let mut state = AppState::new();

        assert_eq!(state.status().state, RuntimeState::Booting);
        assert_eq!(state.play().unwrap_err(), StateError::DatasetRequired);
    }

    #[test]
    fn renderer_filesystem_capability_scopes_writes_to_user_chosen_paths() {
        let capability = include_str!("../capabilities/default.json");

        // Writes are only reachable through dialog-picked paths
        // (openJsonFile/saveJsonFile/screenshot in tauri-api.ts), so the
        // scope must cover user directories — but nothing broader. In
        // particular no filesystem root, no recursive-everything glob, and
        // no shell/process plugin may appear.
        for allowed in [
            "$HOME/**",
            "$DOCUMENT/**",
            "$DOWNLOAD/**",
            "$DESKTOP/**",
            "$APPDATA/**",
            "$APPCONFIG/**",
        ] {
            assert!(
                capability.contains(allowed),
                "renderer capability must scope writes to user directories ({allowed})"
            );
        }
        for forbidden in [
            "\"/**\"",
            "\"/\"",
            "\"/tmp/**\"",
            "shell:",
            "\"process",
            "http:",
        ] {
            assert!(
                !capability.contains(forbidden),
                "renderer capability must not grant {forbidden}"
            );
        }
        assert!(capability.contains("dialog:default"));
        assert!(capability.contains("fs:allow-read-text-file"));
        assert!(capability.contains("fs:allow-write-text-file"));
        assert!(capability.contains("fs:allow-write-file"));
    }

    #[test]
    fn packaged_resource_directory_resolves_the_staged_backend_root() {
        let root =
            std::env::temp_dir().join(format!("veyra-resource-root-test-{}", std::process::id()));
        let backend = root.join("backend");
        fs::create_dir_all(backend.join("runtime")).unwrap();
        fs::write(backend.join("manifest.json"), "{\"schema_version\":1}").unwrap();
        fs::write(backend.join("runtime/__main__.py"), "# staged").unwrap();

        assert_eq!(super::runtime_root(&root), backend);

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn development_resource_directory_resolves_tauri_resources_backend() {
        let root = std::env::temp_dir().join(format!(
            "veyra-development-resource-root-test-{}",
            std::process::id()
        ));
        let backend = root.join("resources/backend");
        fs::create_dir_all(backend.join("runtime")).unwrap();
        fs::write(backend.join("manifest.json"), "{\"schema_version\":1}").unwrap();
        fs::write(backend.join("runtime/__main__.py"), "# staged").unwrap();

        assert_eq!(super::runtime_root(&root), backend);

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn per_user_install_resolves_backend_beside_the_executable() {
        let root = std::env::temp_dir().join(format!(
            "veyra-user-install-resource-root-test-{}",
            std::process::id()
        ));
        let tauri_resource_dir = root.join("usr/lib/veyra");
        let executable_dir = root.join("home/user/.local/opt/veyra");
        let backend = executable_dir.join("resources/backend");
        fs::create_dir_all(backend.join("runtime")).unwrap();
        fs::create_dir_all(backend.join("python/bin")).unwrap();
        fs::write(backend.join("manifest.json"), "{\"schema_version\":1}").unwrap();
        fs::write(backend.join("runtime/__main__.py"), "# staged").unwrap();
        fs::write(backend.join("python/bin/python3"), "python").unwrap();

        assert_eq!(
            super::runtime_root_with_executable_dir(&tauri_resource_dir, &executable_dir),
            backend
        );

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn development_app_prefers_current_source_runtime_over_stale_staged_resources() {
        let root = std::env::temp_dir().join(format!(
            "veyra-development-source-root-test-{}",
            std::process::id()
        ));
        let source = root.join("source");
        let resources = root.join("target/debug");
        fs::create_dir_all(source.join("runtime")).unwrap();
        fs::write(source.join("runtime/__main__.py"), "# current source").unwrap();
        fs::create_dir_all(resources.join("resources/backend/runtime")).unwrap();
        fs::write(
            resources.join("resources/backend/manifest.json"),
            "{\"schema_version\":1}",
        )
        .unwrap();
        fs::write(
            resources.join("resources/backend/runtime/__main__.py"),
            "# stale staged runtime",
        )
        .unwrap();

        assert_eq!(
            super::application_runtime_root(&resources, Some(&source)),
            source
        );

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn unstaged_backend_placeholder_never_masquerades_as_a_runnable_backend() {
        let root = std::env::temp_dir().join(format!(
            "veyra-resource-root-unstaged-test-{}",
            std::process::id()
        ));
        let backend = root.join("backend");
        fs::create_dir_all(&backend).unwrap();
        fs::write(backend.join(".gitkeep"), "").unwrap();

        assert_eq!(super::runtime_root(&root), root);

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn runtime_visualization_event_uses_the_renderer_binary_channel() {
        let (channel, payload) = forwardable_runtime_event(RuntimeEvent {
            metadata: json!({
                "type": "visualization",
                "schema_version": 2,
                "generation": 7
            }),
            payload: vec![9, 8, 7],
        })
        .unwrap();

        assert_eq!(channel, "veyra://visualization");
        assert_eq!(payload["metadata"]["generation"], 7);
        assert_eq!(payload["payload"], json!([9, 8, 7]));
    }
}
