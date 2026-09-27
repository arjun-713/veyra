use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::supervisor::{RuntimeSupervisor, SupervisorError};

use super::state::RuntimeState;
use super::AppState;

/// Build profile of this shell binary. The frontend displays it so
/// cross-hardware screenshots cannot silently compare Debug against Release.
fn build_mode() -> &'static str {
    if cfg!(debug_assertions) {
        "debug"
    } else {
        "release"
    }
}

pub struct RuntimeController {
    pub state: AppState,
    supervisor: RuntimeSupervisor,
    repo: PathBuf,
    mapper: PathBuf,
    last_config: Option<Value>,
    layer: String,
}

impl RuntimeController {
    pub fn new(repo: impl Into<PathBuf>) -> Self {
        let repo = repo.into();
        let mapper = mapper_path(&repo);
        let state = AppState::new();
        Self {
            supervisor: RuntimeSupervisor::new(&repo),
            state,
            repo,
            mapper,
            last_config: None,
            layer: "semantic".to_owned(),
        }
    }

    pub fn status(&self) -> Value {
        let local = self.state.status();
        json!({
            "state": local.state.as_str().to_ascii_lowercase(),
            "dataset_open": local.dataset_open,
            "runtime_running": self.supervisor.is_running(),
            "runtime_pid": self.supervisor.pid(),
            "repo": self.repo,
            "mapper": self.mapper,
            "layer": self.layer,
            "build_mode": build_mode(),
        })
    }

    pub fn refresh_status(&mut self) -> Result<Value, String> {
        let response = self.request("status", Value::Object(Default::default()))?;
        self.state.mark_ready();
        let mut status = response
            .get("status")
            .cloned()
            .unwrap_or_else(|| self.status());
        if let Some(object) = status.as_object_mut() {
            object.insert("runtime_pid".to_owned(), json!(self.supervisor.pid()));
            object.insert("mapper".to_owned(), json!(self.mapper));
        }
        Ok(status)
    }

    pub fn configure(&mut self, mut config: Value) -> Result<Value, String> {
        inject_mapper(&mut config, &self.mapper)?;
        let response = self.request("configure", json!({"config": config.clone()}))?;
        self.state
            .open_dataset()
            .map_err(|error| error.to_string())?;
        self.last_config = Some(config);
        Ok(response)
    }

    pub fn validate_config(&mut self, mut config: Value) -> Result<Value, String> {
        inject_mapper(&mut config, &self.mapper)?;
        self.request("config_validate", json!({"config": config}))
    }

    pub fn datasets(&mut self, dataset: &str, root: &Path) -> Result<Value, String> {
        self.request(
            "datasets",
            json!({"dataset": dataset, "root": root.to_string_lossy()}),
        )
    }

    /// Inspect and open a supported dataset using the product's explicit safe
    /// defaults.  Dataset discovery stays in Python so the Rust control layer
    /// never learns dataset-specific file layouts.
    pub fn open_dataset(
        &mut self,
        dataset: &str,
        root: &Path,
        requested_sequence: Option<&str>,
    ) -> Result<Value, String> {
        let catalog = self.datasets(dataset, root)?;
        let normalized_catalog = unwrap_runtime_result(catalog.clone());
        let sequence = select_openable_sequence(&normalized_catalog, requested_sequence)?;
        let configured = self.configure(dataset_open_configuration(dataset, root, &sequence))?;
        Ok(json!({
            "catalog": catalog,
            "selected_sequence": sequence,
            "configured": configured,
        }))
    }

    pub fn command(&mut self, command: &str, args: Value) -> Result<Value, String> {
        if command == "status" {
            return self.refresh_status();
        }
        if command == "layer" {
            let layer = args
                .get("layer")
                .and_then(Value::as_str)
                .ok_or_else(|| "layer must be a string".to_owned())?;
            if !matches!(
                layer,
                "semantic"
                    | "elevation"
                    | "ground"
                    | "terrain"
                    | "traversability"
                    | "motion"
                    | "lod"
                    | "utility"
            ) {
                return Err(format!("unsupported layer: {layer}"));
            }
            self.layer = layer.to_owned();
            return Ok(json!({"status": self.status()}));
        }
        if command == "stop" {
            self.stop()?;
            return Ok(json!({"status": self.status()}));
        }
        let response = if command == "restart" {
            self.restart()?
        } else {
            let response = self.request(command, args)?;
            match command {
                "start" => self.state.play().map_err(|error| error.to_string())?,
                "pause" => self.state.pause().map_err(|error| error.to_string())?,
                "reset" | "sequence" | "policy" if self.state.status().dataset_open => {
                    self.state
                        .open_dataset()
                        .map_err(|error| error.to_string())?;
                }
                _ => {}
            }
            response
        };
        Ok(response)
    }

    pub fn diagnostics(&mut self) -> Value {
        let runtime = self
            .request("diagnostics", Value::Object(Default::default()))
            .unwrap_or_else(|error| json!({"error": error}));
        json!({
            "schema_version": 1,
            "application": "veyra",
            "repo": self.repo,
            "mapper": self.mapper,
            "state": self.status(),
            "runtime": runtime,
            "supervisor": self.supervisor.diagnostics(),
            "build_mode": build_mode(),
        })
    }

    pub fn drain_events(&self) -> Vec<crate::supervisor::RuntimeEvent> {
        self.supervisor.drain_events()
    }

    pub fn stop(&mut self) -> Result<(), String> {
        self.supervisor.stop().map_err(|error| error.to_string())?;
        let status = self.state.status();
        if status.dataset_open || status.state == RuntimeState::Error {
            self.state.stop().map_err(|error| error.to_string())?;
        }
        Ok(())
    }

    fn restart(&mut self) -> Result<Value, String> {
        self.stop()?;
        let config = self.last_config.clone();
        if let Some(config) = config {
            self.configure(config)
        } else {
            Ok(json!({"status": self.status()}))
        }
    }

    fn request(&mut self, command: &str, args: Value) -> Result<Value, String> {
        let response = self.supervisor.request(command, args).map_err(|error| {
            if marks_runtime_failed(&error) {
                self.state.fail();
            }
            supervisor_error(error)
        })?;
        Ok(response)
    }
}

fn mapper_path(repo: &Path) -> PathBuf {
    if let Some(value) = std::env::var_os("VEYRA_MAPPER") {
        return PathBuf::from(value);
    }
    let packaged = repo.join(if cfg!(windows) {
        "bin/veyra_runtime.exe"
    } else {
        "bin/veyra_runtime"
    });
    if packaged.is_file() {
        packaged
    } else {
        repo.join(if cfg!(windows) {
            "build/apps/runtime/veyra_runtime.exe"
        } else {
            "build/apps/runtime/veyra_runtime"
        })
    }
}

fn inject_mapper(config: &mut Value, mapper: &Path) -> Result<(), String> {
    let object = config
        .as_object_mut()
        .ok_or_else(|| "configuration must be a JSON object".to_owned())?;
    let map = object
        .entry("map")
        .or_insert_with(|| Value::Object(Default::default()))
        .as_object_mut()
        .ok_or_else(|| "configuration map must be an object".to_owned())?;
    map.insert(
        "executable".to_owned(),
        Value::String(mapper.to_string_lossy().into_owned()),
    );
    Ok(())
}

fn dataset_open_configuration(dataset: &str, root: &Path, sequence: &str) -> Value {
    json!({
        "dataset": dataset,
        "dataset_root": root.to_string_lossy(),
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
    })
}

fn unwrap_runtime_result(response: Value) -> Value {
    if response.get("type").and_then(Value::as_str) == Some("response") {
        response.get("result").cloned().unwrap_or(response)
    } else {
        response
    }
}

fn select_openable_sequence(
    catalog: &Value,
    requested_sequence: Option<&str>,
) -> Result<String, String> {
    if catalog.get("status").and_then(Value::as_str) == Some("invalid") {
        let diagnostic = catalog
            .get("diagnostics")
            .and_then(Value::as_array)
            .and_then(|values| values.first())
            .and_then(Value::as_str)
            .unwrap_or("dataset adapter rejected the selected root");
        return Err(format!("dataset is invalid: {diagnostic}"));
    }
    let sequences = catalog
        .get("sequences")
        .and_then(Value::as_array)
        .ok_or_else(|| "dataset catalog has no sequences".to_owned())?;
    let matches_requested = |entry: &&Value| match requested_sequence {
        None => true,
        Some(requested) => entry.get("id").and_then(Value::as_str) == Some(requested),
    };
    sequences
        .iter()
        .filter(matches_requested)
        .find_map(|entry| {
            let id = entry.get("id").and_then(Value::as_str)?;
            let frames = entry.get("frames").and_then(Value::as_u64)?;
            (frames > 0).then(|| id.to_owned())
        })
        .ok_or_else(|| match requested_sequence {
            Some(sequence) => format!("sequence {sequence} is unavailable or has no frames"),
            None => "dataset has no openable sequence".to_owned(),
        })
}

/// A rejected request (bad dataset path, invalid argument) leaves the runtime
/// healthy and must not latch ERROR; only a lost or broken process does.
fn marks_runtime_failed(error: &SupervisorError) -> bool {
    !matches!(
        error,
        SupervisorError::Response(_) | SupervisorError::QueueFull
    )
}

fn supervisor_error(error: SupervisorError) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use super::RuntimeController;
    use serde_json::json;

    #[test]
    fn rejected_requests_do_not_latch_error_but_process_failures_do() {
        use super::marks_runtime_failed;
        use crate::supervisor::SupervisorError;
        assert!(!marks_runtime_failed(&SupervisorError::Response(
            "dataset is invalid".into()
        )));
        assert!(!marks_runtime_failed(&SupervisorError::QueueFull));
        for error in [
            SupervisorError::NotRunning,
            SupervisorError::Timeout("benchmark".into()),
            SupervisorError::Protocol("bad packet".into()),
            SupervisorError::Process("exit status: 1".into()),
        ] {
            assert!(marks_runtime_failed(&error), "{error}");
        }
    }

    #[test]
    fn stop_and_restart_recover_from_error_without_an_open_dataset() {
        let mut controller = RuntimeController::new("/tmp/veyra-test-error-recovery");
        controller.state.fail();
        assert_eq!(controller.status()["state"], "error");
        controller.stop().unwrap();
        assert_eq!(controller.status()["state"], "ready");
    }

    #[test]
    fn controller_starts_booting_without_starting_the_backend() {
        let controller = RuntimeController::new("/tmp/veyra-test-repo");
        let status = controller.status();
        assert_eq!(status["state"], "booting");
        assert_eq!(status["runtime_running"], false);
        // Build profile travels with status so screenshots cannot silently
        // compare Debug against Release across machines.
        let mode = status["build_mode"].as_str().unwrap();
        assert!(mode == "debug" || mode == "release");
    }

    #[test]
    fn mapper_path_is_injected_without_mutating_other_config() {
        let controller = RuntimeController::new("/tmp/veyra-test-repo");
        let mut config = json!({"dataset":"generic","map":{"policy":"distance_lod"}});
        super::inject_mapper(&mut config, &controller.mapper).unwrap();
        assert!(config["map"]["executable"]
            .as_str()
            .unwrap()
            .ends_with("veyra_runtime"));
        assert_eq!(config["dataset"], "generic");
    }

    #[test]
    fn layer_selection_is_local_and_reported_in_status() {
        let mut controller = RuntimeController::new("/tmp/veyra-test-repo");
        controller
            .command("layer", json!({"layer": "lod"}))
            .unwrap();

        assert_eq!(controller.status()["layer"], "lod");
        assert!(controller
            .command("layer", json!({"layer": "not-a-layer"}))
            .is_err());
    }

    #[test]
    fn packaged_controller_uses_the_staged_mapper() {
        let root =
            std::env::temp_dir().join(format!("veyra-controller-test-{}", std::process::id()));
        std::fs::create_dir_all(root.join("bin")).unwrap();
        let mapper = root.join("bin/veyra_runtime");
        std::fs::write(&mapper, b"mapper").unwrap();

        let controller = RuntimeController::new(&root);
        assert_eq!(controller.mapper, mapper);
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn dataset_open_configuration_uses_explicit_production_defaults() {
        let config = super::dataset_open_configuration(
            "semanticposs",
            std::path::Path::new("/data/semanticposs"),
            "00",
        );

        assert_eq!(config["dataset"], "semanticposs");
        assert_eq!(config["dataset_root"], "/data/semanticposs");
        assert_eq!(config["sequence"], "00");
        assert_eq!(config["pipeline"]["semantic"]["mode"], "ground_truth");
        assert_eq!(config["pipeline"]["ground"]["enabled"], true);
        assert_eq!(config["pipeline"]["terrain"]["enabled"], true);
        assert_eq!(config["pipeline"]["temporal"]["enabled"], false);
    }

    #[test]
    fn selects_only_nonempty_dataset_sequences_without_accepting_invalid_catalogs() {
        let catalog = json!({
            "status": "partial",
            "sequences": [
                {"id": "00", "frames": 0},
                {"id": "01", "frames": 4}
            ]
        });
        assert_eq!(
            super::select_openable_sequence(&catalog, None),
            Ok("01".to_owned())
        );
        assert_eq!(
            super::select_openable_sequence(&catalog, Some("00")).unwrap_err(),
            "sequence 00 is unavailable or has no frames"
        );
        assert!(
            super::select_openable_sequence(&json!({"status": "invalid"}), None)
                .unwrap_err()
                .starts_with("dataset is invalid:")
        );
    }

    #[test]
    fn unwraps_runtime_response_envelope_before_reading_dataset_catalog() {
        let catalog = json!({
            "type": "response",
            "id": "1",
            "ok": true,
            "result": {
                "status": "partial",
                "sequences": [{"id": "00", "frames": 488}]
            }
        });
        let normalized = super::unwrap_runtime_result(catalog);
        assert_eq!(
            super::select_openable_sequence(&normalized, Some("00")),
            Ok("00".to_owned())
        );
    }
}
