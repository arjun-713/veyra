//! Loads the complete benchmark report the runtime announced.
//!
//! Runtime events are capped at 1 MiB, so a finished benchmark announces its
//! schema-v2 artifact (path and byte count) instead of shipping a truncated
//! summary. The renderer may read back exactly that announced file and
//! nothing else: this is not a general file-read capability.

use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde_json::Value;

pub(crate) const MAX_ARTIFACT_BYTES: u64 = 32 * 1024 * 1024;
const REPORT_SCHEMA_VERSION: u64 = 2;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct AnnouncedArtifact {
    path: PathBuf,
    bytes: u64,
}

#[derive(Default)]
pub(crate) struct BenchmarkArtifacts(Mutex<Option<AnnouncedArtifact>>);

impl BenchmarkArtifacts {
    /// Remember the artifact of a completed benchmark event; other events are ignored.
    pub(crate) fn observe(&self, payload: &Value) {
        if let Some(announced) = announced_artifact(payload) {
            if let Ok(mut current) = self.0.lock() {
                *current = Some(announced);
            }
        }
    }

    pub(crate) fn read(&self, requested: &str) -> Result<Value, String> {
        let announced = self
            .0
            .lock()
            .map_err(|_| "benchmark artifact registry lock poisoned".to_owned())?
            .clone();
        read_announced(announced.as_ref(), requested)
    }
}

pub(crate) fn announced_artifact(payload: &Value) -> Option<AnnouncedArtifact> {
    if payload.get("type").and_then(Value::as_str) != Some("benchmark")
        || payload.get("state").and_then(Value::as_str) != Some("complete")
    {
        return None;
    }
    let path = payload.get("artifact").and_then(Value::as_str)?;
    let bytes = payload.get("artifact_bytes").and_then(Value::as_u64)?;
    if path.is_empty() || bytes == 0 || bytes > MAX_ARTIFACT_BYTES {
        return None;
    }
    Some(AnnouncedArtifact {
        path: PathBuf::from(path),
        bytes,
    })
}

pub(crate) fn read_announced(
    announced: Option<&AnnouncedArtifact>,
    requested: &str,
) -> Result<Value, String> {
    let announced = announced.ok_or_else(|| {
        "no completed benchmark artifact has been announced by the runtime".to_owned()
    })?;
    if Path::new(requested) != announced.path {
        return Err(
            "requested benchmark artifact is not the one announced by the runtime".to_owned(),
        );
    }
    let file = std::fs::File::open(&announced.path).map_err(|error| {
        format!("benchmark artifact is no longer available (runtime stopped?): {error}")
    })?;
    let mut raw = Vec::new();
    file.take(MAX_ARTIFACT_BYTES + 1)
        .read_to_end(&mut raw)
        .map_err(|error| format!("cannot read benchmark artifact: {error}"))?;
    if raw.len() as u64 != announced.bytes {
        return Err(format!(
            "benchmark artifact changed after completion: expected {} bytes, found {}",
            announced.bytes,
            raw.len()
        ));
    }
    let report: Value = serde_json::from_slice(&raw)
        .map_err(|error| format!("benchmark artifact is not valid JSON: {error}"))?;
    if report.get("schema_version").and_then(Value::as_u64) != Some(REPORT_SCHEMA_VERSION) {
        return Err("benchmark artifact does not declare schema_version 2".to_owned());
    }
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::{announced_artifact, read_announced, BenchmarkArtifacts, MAX_ARTIFACT_BYTES};
    use serde_json::json;

    fn write(dir: &std::path::Path, text: &str) -> std::path::PathBuf {
        let path = dir.join("benchmark.json");
        std::fs::write(&path, text).unwrap();
        path
    }

    fn scratch(name: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "veyra-benchmark-artifact-{name}-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn only_completed_benchmark_events_announce_an_artifact() {
        assert!(announced_artifact(&json!({"type": "benchmark", "state": "error"})).is_none());
        assert!(announced_artifact(&json!({"type": "status", "artifact": "/x"})).is_none());
        assert!(announced_artifact(&json!({
            "type": "benchmark", "state": "complete", "artifact": "/x",
            "artifact_bytes": MAX_ARTIFACT_BYTES + 1
        }))
        .is_none());
        assert!(announced_artifact(&json!({
            "type": "benchmark", "state": "complete", "artifact": "/x", "artifact_bytes": 10
        }))
        .is_some());
    }

    #[test]
    fn the_announced_report_loads_intact() {
        let dir = scratch("intact");
        let text = r#"{"schema_version":2,"provenance":{"git_sha":"abc"},"policies":{}}"#;
        let path = write(&dir, text);
        let registry = BenchmarkArtifacts::default();
        registry.observe(&json!({
            "type": "benchmark", "state": "complete",
            "artifact": path.to_string_lossy(), "artifact_bytes": text.len()
        }));
        let report = registry.read(&path.to_string_lossy()).unwrap();
        assert_eq!(report["provenance"]["git_sha"], "abc");
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn unannounced_changed_or_foreign_files_are_refused() {
        let dir = scratch("refused");
        let text = r#"{"schema_version":2}"#;
        let path = write(&dir, text);
        let requested = path.to_string_lossy().into_owned();
        assert!(read_announced(None, &requested)
            .unwrap_err()
            .contains("no completed benchmark"));

        let announced = announced_artifact(&json!({
            "type": "benchmark", "state": "complete",
            "artifact": requested, "artifact_bytes": text.len()
        }))
        .unwrap();
        assert!(read_announced(Some(&announced), "/etc/passwd")
            .unwrap_err()
            .contains("not the one announced"));

        std::fs::write(&path, r#"{"schema_version":2,"extra":true}"#).unwrap();
        assert!(read_announced(Some(&announced), &requested)
            .unwrap_err()
            .contains("changed after completion"));

        let legacy = r#"{"schema_version":1}"#;
        std::fs::write(&path, legacy).unwrap();
        let announced = announced_artifact(&json!({
            "type": "benchmark", "state": "complete",
            "artifact": requested, "artifact_bytes": legacy.len()
        }))
        .unwrap();
        assert!(read_announced(Some(&announced), &requested)
            .unwrap_err()
            .contains("schema_version 2"));

        std::fs::remove_file(&path).unwrap();
        assert!(read_announced(Some(&announced), &requested)
            .unwrap_err()
            .contains("no longer available"));
        let _ = std::fs::remove_dir_all(dir);
    }
}
