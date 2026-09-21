use serde_json::Value;

use crate::control::{ControlClient, ControlClientError};
use crate::control_host::{ClientConfig, ControlHost, ControlHostError};

#[derive(Debug, PartialEq)]
pub(crate) struct DesktopControlRequest {
    pub(crate) command: &'static str,
    pub(crate) args: Value,
}

pub(crate) struct DesktopControlService {
    client: Option<ControlClient>,
    unavailable: Option<String>,
    host: Option<ControlHost>,
}

impl DesktopControlService {
    pub(crate) fn bootstrap(repo: std::path::PathBuf, config_dir: &std::path::Path) -> Self {
        // CLI connection overrides do not carry the desktop's event stream.
        // The GUI must own a host with an event relay; CLI/MCP can attach to
        // its published discovery record instead.
        match ControlHost::start(repo, config_dir)
            .and_then(|host| client_from_config(host.config()).map(|client| (host, client)))
        {
            Ok((host, client)) => Self {
                client: Some(client),
                unavailable: None,
                host: Some(host),
            },
            Err(error) => Self {
                client: None,
                unavailable: Some(control_host_error_message(error)),
                host: None,
            },
        }
    }

    pub(crate) fn startup_diagnostic(&self) -> Option<&str> {
        self.unavailable.as_deref()
    }

    pub(crate) fn request(&mut self, command: &'static str, args: Value) -> Result<Value, String> {
        let client = self.client.as_mut().ok_or_else(|| {
            format!(
                "CONTROL_UNAVAILABLE: {}",
                self.unavailable
                    .as_deref()
                    .unwrap_or("local control daemon is unavailable")
            )
        })?;
        client.request(command, args).map_err(control_error_message)
    }

    pub(crate) fn shutdown(&mut self) -> Result<(), String> {
        if let Some(client) = self.client.as_mut() {
            client
                .request("shutdown", serde_json::json!({}))
                .map_err(control_error_message)?;
        }
        if let Some(host) = self.host.as_mut() {
            host.join_after_shutdown()?;
        }
        Ok(())
    }

    pub(crate) fn drain_events(&self) -> Vec<crate::supervisor::RuntimeEvent> {
        self.host
            .as_ref()
            .map(ControlHost::drain_events)
            .unwrap_or_default()
    }
}

fn client_from_config(config: &ClientConfig) -> Result<ControlClient, ControlHostError> {
    ControlClient::from_endpoint_and_token_file(config.endpoint, &config.token_file)
        .map_err(|error| ControlHostError::Start(error.to_string()))
}

fn control_host_error_message(error: ControlHostError) -> String {
    error.to_string()
}

pub(crate) fn request_for(command: &str, args: Value) -> DesktopControlRequest {
    let command = match command {
        "status" => "status",
        "command" => "command",
        "stop" => "stop",
        "configure" => "configure",
        "config_validate" => "config_validate",
        "datasets" => "datasets",
        "open_dataset" => "open_dataset",
        "diagnostics" => "diagnostics",
        "shutdown" => "shutdown",
        _ => panic!("unsupported desktop control command"),
    };
    DesktopControlRequest { command, args }
}

fn control_error_message(error: ControlClientError) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{control_error_message, request_for, DesktopControlRequest};
    use crate::control::ControlClientError;

    #[test]
    fn desktop_requests_map_to_the_daemon_protocol() {
        assert_eq!(
            request_for("status", json!({})),
            DesktopControlRequest {
                command: "status",
                args: json!({}),
            }
        );
        assert_eq!(
            request_for("command", json!({"name": "pause", "args": {}})),
            DesktopControlRequest {
                command: "command",
                args: json!({"name": "pause", "args": {}}),
            }
        );
        assert_eq!(
            request_for("configure", json!({"config": {"dataset": "kitti"}})),
            DesktopControlRequest {
                command: "configure",
                args: json!({"config": {"dataset": "kitti"}}),
            }
        );
        assert_eq!(
            request_for("config_validate", json!({"config": {}})),
            DesktopControlRequest {
                command: "config_validate",
                args: json!({"config": {}}),
            }
        );
        assert_eq!(
            request_for("datasets", json!({"dataset": "generic", "root": "/data"})),
            DesktopControlRequest {
                command: "datasets",
                args: json!({"dataset": "generic", "root": "/data"}),
            }
        );
        assert_eq!(
            request_for(
                "open_dataset",
                json!({"dataset": "semanticposs", "root": "/data", "sequence": "00"}),
            ),
            DesktopControlRequest {
                command: "open_dataset",
                args: json!({"dataset": "semanticposs", "root": "/data", "sequence": "00"}),
            }
        );
        assert_eq!(
            request_for("diagnostics", json!({})),
            DesktopControlRequest {
                command: "diagnostics",
                args: json!({}),
            }
        );
        assert_eq!(
            request_for("shutdown", json!({})),
            DesktopControlRequest {
                command: "shutdown",
                args: json!({}),
            }
        );
    }

    #[test]
    fn daemon_failures_reach_tauri_with_code_and_message() {
        let error = ControlClientError::Daemon {
            code: "CONTROLLER_ERROR".to_owned(),
            message: "dataset is not configured".to_owned(),
        };

        assert_eq!(
            control_error_message(error),
            "CONTROLLER_ERROR: dataset is not configured"
        );
    }

    #[test]
    fn unavailable_control_plane_fails_closed_without_preventing_desktop_boot() {
        let service = super::DesktopControlService {
            client: None,
            unavailable: Some("missing control endpoint".to_owned()),
            host: None,
        };
        assert_eq!(
            service.startup_diagnostic(),
            Some("missing control endpoint")
        );
    }
}
