mod commands;
pub mod control;
pub mod supervisor;
mod telemetry;

use tauri::Manager;

fn packaged_repo(resource_dir: &std::path::Path) -> Option<std::path::PathBuf> {
    [
        resource_dir.to_path_buf(),
        resource_dir.join("backend"),
        resource_dir.join("resources/backend"),
    ]
    .into_iter()
    .find(|path| path.join("runtime").is_dir())
}

fn emit_runtime_event(app: &tauri::AppHandle, event: supervisor::RuntimeEvent) {
    match telemetry::event_payload(event.metadata, event.payload) {
        Ok((channel, payload)) => {
            use tauri::Emitter;
            let _ = app.emit(channel.name(), payload);
        }
        Err(error) => {
            use tauri::Emitter;
            let _ = app.emit(
                "veyra://event",
                serde_json::json!({
                    "type": "diagnostics",
                    "schema_version": 1,
                    "error": {"code": "INVALID_RUNTIME_EVENT", "message": error}
                }),
            );
        }
    }
}

pub fn run() {
    let stop_signal = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let pump_stop_signal = std::sync::Arc::clone(&stop_signal);
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .setup(move |app| {
            let packaged_backend = app
                .path()
                .resource_dir()
                .ok()
                .and_then(|path| packaged_repo(&path));
            let repo = std::env::var_os("VEYRA_REPO")
                .map(std::path::PathBuf::from)
                .or(packaged_backend)
                .or_else(|| std::env::current_dir().ok())
                .unwrap_or_else(|| std::path::PathBuf::from("."));
            app.manage(std::sync::Mutex::new(control::RuntimeController::new(repo)));
            let handle = app.handle().clone();
            let stop_signal = std::sync::Arc::clone(&pump_stop_signal);
            std::thread::Builder::new()
                .name("veyra-event-pump".into())
                .spawn(move || {
                    while !stop_signal.load(std::sync::atomic::Ordering::Acquire) {
                        std::thread::sleep(std::time::Duration::from_millis(25));
                        let state = handle.state::<std::sync::Mutex<control::RuntimeController>>();
                        let events = state
                            .lock()
                            .map(|controller| controller.drain_events())
                            .unwrap_or_default();
                        for event in events {
                            emit_runtime_event(&handle, event);
                        }
                    }
                })
                .map_err(|error| format!("failed to start event pump: {error}"))?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::runtime_status,
            commands::runtime_command,
            commands::runtime_configure,
            commands::runtime_validate_config,
            commands::choose_dataset,
            commands::export_diagnostics,
            commands::runtime_shutdown,
        ]);
    let app = builder
        .build(tauri::generate_context!())
        .expect("error while building Veyra");
    app.run(move |app_handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            stop_signal.store(true, std::sync::atomic::Ordering::Release);
            if let Some(state) =
                app_handle.try_state::<std::sync::Mutex<control::RuntimeController>>()
            {
                if let Ok(mut controller) = state.lock() {
                    let _ = controller.stop();
                }
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::{
        control::{
            state::{RuntimeState, StateError},
            AppState,
        },
        packaged_repo,
    };

    #[test]
    fn a_new_application_starts_booting_and_cannot_play_without_a_dataset() {
        let mut state = AppState::new();

        assert_eq!(state.status().state, RuntimeState::Booting);
        assert_eq!(state.play().unwrap_err(), StateError::DatasetRequired);
    }

    #[test]
    fn packaged_repo_resolves_the_backend_resource_directory() {
        let root = std::env::temp_dir().join(format!("veyra-resource-test-{}", std::process::id()));
        std::fs::create_dir_all(root.join("backend/runtime")).unwrap();
        assert_eq!(packaged_repo(&root), Some(root.join("backend")));
        std::fs::remove_dir_all(root).unwrap();
    }
}
