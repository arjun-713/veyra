use std::path::PathBuf;
use std::sync::Mutex;

use serde_json::{json, Value};

use crate::desktop_control::{request_for, DesktopControlService};

fn request(
    state: &tauri::State<'_, Mutex<DesktopControlService>>,
    command: &'static str,
    args: Value,
) -> Result<Value, String> {
    let request = request_for(command, args);
    state
        .lock()
        .map_err(|_| "desktop control client lock poisoned".to_owned())?
        .request(request.command, request.args)
}

#[tauri::command]
pub fn runtime_status(
    state: tauri::State<'_, Mutex<DesktopControlService>>,
) -> Result<Value, String> {
    request(&state, "status", json!({}))
}

#[tauri::command]
pub fn runtime_command(
    command: String,
    args: Value,
    state: tauri::State<'_, Mutex<DesktopControlService>>,
) -> Result<Value, String> {
    if !args.is_object() {
        return Err("command arguments must be a JSON object".to_owned());
    }
    request(&state, "command", json!({"name": command, "args": args}))
}

#[tauri::command]
pub fn runtime_configure(
    config: Value,
    state: tauri::State<'_, Mutex<DesktopControlService>>,
) -> Result<Value, String> {
    if !config.is_object() {
        return Err("configuration must be a JSON object".to_owned());
    }
    request(&state, "configure", json!({"config": config}))
}

#[tauri::command]
pub fn runtime_validate_config(
    config: Value,
    state: tauri::State<'_, Mutex<DesktopControlService>>,
) -> Result<Value, String> {
    if !config.is_object() {
        return Err("configuration must be a JSON object".to_owned());
    }
    request(&state, "config_validate", json!({"config": config}))
}

#[tauri::command]
pub fn choose_dataset(
    dataset: String,
    root: String,
    state: tauri::State<'_, Mutex<DesktopControlService>>,
) -> Result<Value, String> {
    if dataset.is_empty() {
        return Err("dataset format is required".to_owned());
    }
    choose_dataset_allowlist_check(&dataset)?;
    let root = validated_dataset_root(&root)?;
    request(
        &state,
        "datasets",
        json!({"dataset": dataset, "root": root.to_string_lossy()}),
    )
}

#[tauri::command]
pub fn export_diagnostics(
    state: tauri::State<'_, Mutex<DesktopControlService>>,
) -> Result<Value, String> {
    request(&state, "diagnostics", json!({}))
}

#[tauri::command]
pub fn runtime_shutdown(
    state: tauri::State<'_, Mutex<DesktopControlService>>,
) -> Result<Value, String> {
    request(&state, "shutdown", json!({}))
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
    use super::validated_dataset_root;
    use super::choose_dataset_allowlist_check;

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
