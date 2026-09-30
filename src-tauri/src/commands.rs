use std::path::PathBuf;
use std::sync::Mutex;

use serde_json::{json, Value};

use crate::desktop_control::{request_for, request_from_state, DesktopControlService};

async fn request(
    app: tauri::AppHandle,
    command: &'static str,
    args: Value,
) -> Result<Value, String> {
    // Runtime commands can take seconds. Never block the native UI thread.
    tauri::async_runtime::spawn_blocking(move || {
        use tauri::Manager;
        let state = app.state::<Mutex<DesktopControlService>>();
        let request = request_for(command, args);
        request_from_state(&state, request.command, request.args)
    })
    .await
    .map_err(|error| format!("runtime command worker failed: {error}"))?
}

#[tauri::command]
pub async fn runtime_status(app: tauri::AppHandle) -> Result<Value, String> {
    request(app, "status", json!({})).await
}

#[tauri::command]
pub async fn runtime_command(
    command: String,
    args: Value,
    app: tauri::AppHandle,
) -> Result<Value, String> {
    if !args.is_object() {
        return Err("command arguments must be a JSON object".to_owned());
    }
    request(app, "command", json!({"name": command, "args": args})).await
}

#[tauri::command]
pub async fn runtime_stop(app: tauri::AppHandle) -> Result<Value, String> {
    request(app, "stop", json!({})).await
}

#[tauri::command]
pub async fn runtime_configure(config: Value, app: tauri::AppHandle) -> Result<Value, String> {
    if !config.is_object() {
        return Err("configuration must be a JSON object".to_owned());
    }
    request(app, "configure", json!({"config": config})).await
}

#[tauri::command]
pub async fn runtime_validate_config(
    config: Value,
    app: tauri::AppHandle,
) -> Result<Value, String> {
    if !config.is_object() {
        return Err("configuration must be a JSON object".to_owned());
    }
    request(app, "config_validate", json!({"config": config})).await
}

#[tauri::command]
pub async fn choose_dataset(
    dataset: String,
    root: String,
    app: tauri::AppHandle,
) -> Result<Value, String> {
    if dataset.is_empty() {
        return Err("dataset format is required".to_owned());
    }
    choose_dataset_allowlist_check(&dataset)?;
    let root = validated_dataset_root(&root)?;
    request(
        app,
        "datasets",
        json!({"dataset": dataset, "root": root.to_string_lossy()}),
    )
    .await
}

#[tauri::command]
pub async fn open_dataset(
    dataset: String,
    root: String,
    sequence: Option<String>,
    app: tauri::AppHandle,
) -> Result<Value, String> {
    if dataset.is_empty() {
        return Err("dataset format is required".to_owned());
    }
    choose_dataset_allowlist_check(&dataset)?;
    let root = validated_dataset_root(&root)?;
    let mut args = serde_json::Map::new();
    args.insert("dataset".to_owned(), Value::String(dataset));
    args.insert(
        "root".to_owned(),
        Value::String(root.to_string_lossy().into_owned()),
    );
    if let Some(sequence) = sequence.filter(|value| !value.is_empty()) {
        args.insert("sequence".to_owned(), Value::String(sequence));
    }
    request(app, "open_dataset", Value::Object(args)).await
}

#[tauri::command]
pub async fn export_diagnostics(app: tauri::AppHandle) -> Result<Value, String> {
    request(app, "diagnostics", json!({})).await
}

/// Returns the complete report of the benchmark the runtime last announced.
#[tauri::command]
pub async fn read_benchmark_artifact(path: String, app: tauri::AppHandle) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        use tauri::Manager;
        app.state::<crate::benchmark_artifact::BenchmarkArtifacts>()
            .read(&path)
    })
    .await
    .map_err(|error| format!("benchmark artifact worker failed: {error}"))?
}

#[tauri::command]
pub async fn runtime_shutdown(app: tauri::AppHandle) -> Result<Value, String> {
    request(app, "shutdown", json!({})).await
}

/// Opt in to lightweight ready events and the bounded raw visualization mailbox.
#[tauri::command]
pub async fn runtime_visualization_transport(
    raw: bool,
    app: tauri::AppHandle,
) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        use tauri::{Emitter, Manager};
        let announce = app
            .state::<crate::visualization_transport::VisualizationTransport>()
            .set_raw(raw)?;
        if announce {
            app.emit("veyra://visualization-ready", json!({"available": true}))
                .map_err(|error| format!("visualization ready event failed: {error}"))?;
        }
        Ok(())
    })
    .await
    .map_err(|error| format!("visualization transport worker failed: {error}"))?
}

/// Return the latest frame as a raw, aligned VYRA packet; empty means no frame.
#[tauri::command]
pub async fn take_visualization(app: tauri::AppHandle) -> Result<tauri::ipc::Response, String> {
    tauri::async_runtime::spawn_blocking(move || {
        use tauri::Manager;
        app.state::<crate::visualization_transport::VisualizationTransport>()
            .take()
    })
    .await
    .map_err(|error| format!("visualization payload worker failed: {error}"))?
}

fn choose_dataset_allowlist_check(dataset: &str) -> Result<(), String> {
    if matches!(
        dataset,
        "rellis3d" | "semanticposs" | "semantickitti" | "generic"
    ) {
        Ok(())
    } else {
        Err("unsupported dataset format".to_owned())
    }
}

fn validated_dataset_root(root: &str) -> Result<PathBuf, String> {
    if root.is_empty() {
        return Err("dataset directory is required".to_owned());
    }
    let path = PathBuf::from(root);
    let metadata = std::fs::metadata(&path)
        .map_err(|error| format!("cannot inspect dataset directory: {error}"))?;
    if !metadata.is_dir() {
        return Err("dataset root must be an existing directory".to_owned());
    }
    path.canonicalize()
        .map_err(|error| format!("cannot resolve dataset directory: {error}"))
}

#[cfg(test)]
mod tests {
    use super::choose_dataset_allowlist_check;
    use super::validated_dataset_root;

    #[test]
    fn dataset_format_is_allowlisted_before_filesystem_access() {
        assert!(choose_dataset_allowlist_check("unsafe-format").is_err());
        assert!(choose_dataset_allowlist_check("semanticposs").is_ok());
    }

    #[test]
    fn dataset_root_rejects_a_file() {
        let root =
            std::env::temp_dir().join(format!("veyra-desktop-control-file-{}", std::process::id()));
        std::fs::write(&root, b"not a directory").unwrap();

        let error = validated_dataset_root(root.to_str().unwrap()).unwrap_err();
        assert_eq!(error, "dataset root must be an existing directory");

        std::fs::remove_file(root).unwrap();
    }

    #[test]
    fn dataset_root_is_canonicalized_before_control_request() {
        let root = std::env::temp_dir().join(format!(
            "veyra-desktop-control-directory-{}",
            std::process::id()
        ));
        std::fs::create_dir_all(&root).unwrap();

        let resolved = validated_dataset_root(root.to_str().unwrap()).unwrap();
        assert!(resolved.is_absolute());
        assert!(resolved.is_dir());

        std::fs::remove_dir(root).unwrap();
    }
}
