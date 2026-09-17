use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::supervisor::{RuntimeSupervisor, SupervisorError};

use super::AppState;

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
                "semantic" | "elevation" | "traversability" | "motion" | "lod" | "utility"
            ) {
                return Err(format!("unsupported layer: {layer}"));
            }
            self.layer = layer.to_owned();
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
        })
    }

    pub fn drain_events(&self) -> Vec<crate::supervisor::RuntimeEvent> {
        self.supervisor.drain_events()
    }

    pub fn stop(&mut self) -> Result<(), String> {
        self.supervisor.stop().map_err(|error| error.to_string())?;
        if self.state.status().dataset_open {
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
            self.state.fail();
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

fn supervisor_error(error: SupervisorError) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use super::RuntimeController;
    use serde_json::json;

    #[test]
    fn controller_starts_booting_without_starting_the_backend() {
        let controller = RuntimeController::new("/tmp/veyra-test-repo");
        let status = controller.status();
        assert_eq!(status["state"], "booting");
        assert_eq!(status["runtime_running"], false);
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
}
