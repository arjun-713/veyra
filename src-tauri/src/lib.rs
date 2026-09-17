mod commands;
pub mod control;
mod control_host;
mod desktop_control;
pub mod supervisor;

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use tauri::{Emitter, Manager};

use desktop_control::DesktopControlService;

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
            let control =
                DesktopControlService::bootstrap(runtime_root(&resource_dir), &config_dir);
            let startup_diagnostic = control.startup_diagnostic().map(str::to_owned);
            app.manage(Mutex::new(control));
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
            commands::runtime_configure,
            commands::runtime_validate_config,
            commands::choose_dataset,
            commands::export_diagnostics,
            commands::runtime_shutdown,
        ]);
    let app = builder
        .build(tauri::generate_context!())
        .expect("error while building Veyra");
    app.run(|app_handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
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

/// Tauri places configured resources beneath the application resource
/// directory. Development fallback remains the repository root, whereas a
/// packaged application must supervise the staged `backend` directory.
fn runtime_root(resource_dir: &Path) -> PathBuf {
    let staged_backend = resource_dir.join("backend");
    if staged_backend.is_dir() {
        staged_backend
    } else {
        resource_dir.to_path_buf()
    }
}

#[cfg(test)]
mod tests {
    use super::control::state::{AppState, RuntimeState, StateError};
    use std::fs;

    #[test]
    fn a_new_application_starts_booting_and_cannot_play_without_a_dataset() {
        let mut state = AppState::new();

        assert_eq!(state.status().state, RuntimeState::Booting);
        assert_eq!(state.play().unwrap_err(), StateError::DatasetRequired);
    }

    #[test]
    fn renderer_filesystem_capability_has_no_broad_user_directory_scope() {
        let capability = include_str!("../capabilities/default.json");

        for broad_scope in [
            "$HOME/**",
            "$DOCUMENT/**",
            "$DOWNLOAD/**",
            "$DESKTOP/**",
            "$APPDATA/**",
            "$APPCONFIG/**",
        ] {
            assert!(
                !capability.contains(broad_scope),
                "renderer capability must not grant recursive access to {broad_scope}"
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
        fs::create_dir_all(backend.join("bin")).unwrap();

        assert_eq!(super::runtime_root(&root), backend);

        fs::remove_dir_all(root).unwrap();
    }
}
