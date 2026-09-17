mod commands;
pub mod control;
mod desktop_control;
pub mod supervisor;

use std::sync::Mutex;

use tauri::{Emitter, Manager};

use desktop_control::DesktopControlService;

pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .setup(|app| {
            let control = DesktopControlService::from_env();
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
                        if let Err(error) = service.request("shutdown", serde_json::json!({})) {
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

#[cfg(test)]
mod tests {
    use super::control::state::{AppState, RuntimeState, StateError};

    #[test]
    fn a_new_application_starts_booting_and_cannot_play_without_a_dataset() {
        let mut state = AppState::new();

        assert_eq!(state.status().state, RuntimeState::Booting);
        assert_eq!(state.play().unwrap_err(), StateError::DatasetRequired);
    }
}
