use std::path::PathBuf;
use std::sync::Mutex;

use serde_json::{json, Value};
use tauri::Emitter;

use crate::{control::RuntimeController, telemetry};

fn with_controller<T>(
    app: &tauri::AppHandle,
    state: &tauri::State<'_, Mutex<RuntimeController>>,
    operation: impl FnOnce(&mut RuntimeController) -> Result<T, String>,
) -> Result<T, String> {
    let mut controller = state
        .lock()
        .map_err(|_| "runtime controller lock poisoned".to_owned())?;
    let result = operation(&mut controller);
    for event in controller.drain_events() {
        emit_runtime_event(app, event);
    }
    result
}

fn emit_runtime_event(app: &tauri::AppHandle, event: crate::supervisor::RuntimeEvent) {
    match telemetry::event_payload(event.metadata, event.payload) {
        Ok((channel, payload)) => {
            let _ = app.emit(channel.name(), payload);
        }
        Err(error) => {
            let _ = app.emit(
                "veyra://event",
                json!({
                    "type": "diagnostics",
                    "schema_version": 1,
                    "error": {"code": "INVALID_RUNTIME_EVENT", "message": error}
                }),
            );
        }
    }
}

#[tauri::command]
pub fn runtime_status(
    app: tauri::AppHandle,
    state: tauri::State<'_, Mutex<RuntimeController>>,
) -> Result<Value, String> {
    with_controller(&app, &state, RuntimeController::refresh_status)
}

#[tauri::command]
pub fn runtime_command(
    app: tauri::AppHandle,
    command: String,
    args: Value,
    state: tauri::State<'_, Mutex<RuntimeController>>,
) -> Result<Value, String> {
    if !args.is_object() {
        return Err("command arguments must be a JSON object".to_owned());
    }
    with_controller(&app, &state, |controller| {
        controller.command(&command, args)
    })
}

#[tauri::command]
pub fn runtime_configure(
    app: tauri::AppHandle,
    config: Value,
    state: tauri::State<'_, Mutex<RuntimeController>>,
) -> Result<Value, String> {
    if !config.is_object() {
        return Err("configuration must be a JSON object".to_owned());
    }
    with_controller(&app, &state, |controller| controller.configure(config))
}

#[tauri::command]
pub fn runtime_validate_config(
    app: tauri::AppHandle,
    config: Value,
    state: tauri::State<'_, Mutex<RuntimeController>>,
) -> Result<Value, String> {
    if !config.is_object() {
        return Err("configuration must be a JSON object".to_owned());
    }
    with_controller(&app, &state, |controller| {
        controller.validate_config(config)
    })
}

#[tauri::command]
pub fn choose_dataset(
    app: tauri::AppHandle,
    dataset: String,
    root: String,
    state: tauri::State<'_, Mutex<RuntimeController>>,
) -> Result<Value, String> {
    if dataset.is_empty() || root.is_empty() {
        return Err("dataset format and directory are required".to_owned());
    }
    with_controller(&app, &state, |controller| {
        controller.datasets(&dataset, &PathBuf::from(root))
    })
}

#[tauri::command]
pub fn export_diagnostics(
    app: tauri::AppHandle,
    state: tauri::State<'_, Mutex<RuntimeController>>,
) -> Result<Value, String> {
    with_controller(&app, &state, |controller| Ok(controller.diagnostics()))
}

#[tauri::command]
pub fn runtime_shutdown(
    app: tauri::AppHandle,
    state: tauri::State<'_, Mutex<RuntimeController>>,
) -> Result<Value, String> {
    with_controller(&app, &state, |controller| {
        controller.stop()?;
        Ok(json!({"status": controller.status()}))
    })
}
