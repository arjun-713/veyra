use serde_json::Value;

use crate::control::{ControlClient, ControlClientError};

#[derive(Debug, PartialEq)]
pub(crate) struct DesktopControlRequest {
    pub(crate) command: &'static str,
    pub(crate) args: Value,
}

pub(crate) struct DesktopControlService {
    client: Option<ControlClient>,
    unavailable: Option<String>,
}

impl DesktopControlService {
    pub(crate) fn from_env() -> Self {
        match ControlClient::from_env() {
            Ok(client) => Self {
                client: Some(client),
                unavailable: None,
            },
            Err(error) => Self {
                client: None,
                unavailable: Some(control_error_message(error)),
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
}

pub(crate) fn request_for(command: &str, args: Value) -> DesktopControlRequest {
    let command = match command {
        "status" => "status",
        "command" => "command",
        "configure" => "configure",
        "config_validate" => "config_validate",
        "datasets" => "datasets",
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
        };
        assert_eq!(
            service.startup_diagnostic(),
            Some("missing control endpoint")
        );
    }
}
