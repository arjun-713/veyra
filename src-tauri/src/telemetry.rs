use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{Map, Value};

const MAX_EVENT_BYTES: usize = 1_048_576;
const TELEMETRY_SCHEMA_VERSION: u64 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum EventChannel {
    Event,
    Visualization,
}

impl EventChannel {
    pub(crate) fn name(self) -> &'static str {
        match self {
            Self::Event => "veyra://event",
            Self::Visualization => "veyra://visualization",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct NormalizedEvent {
    pub(crate) channel: EventChannel,
    pub(crate) payload: Value,
}

pub(crate) fn event_channel(metadata: &Value) -> Result<EventChannel, String> {
    match metadata.get("type").and_then(Value::as_str) {
        Some("visualization") => Ok(EventChannel::Visualization),
        Some(
            "status" | "telemetry" | "response" | "benchmark" | "validation" | "governor"
            | "diagnostics",
        ) => Ok(EventChannel::Event),
        Some(event_type) => Err(format!("unsupported runtime event type: {event_type}")),
        None => Err("runtime event is missing a string type".to_owned()),
    }
}

pub(crate) fn normalize_event(mut payload: Value) -> Result<NormalizedEvent, String> {
    let channel = event_channel(&payload)?;
    let object = payload
        .as_object_mut()
        .ok_or_else(|| "runtime event must be a JSON object".to_owned())?;

    match object.get("type").and_then(Value::as_str) {
        Some("telemetry")
            if object.get("schema_version").and_then(Value::as_u64)
                != Some(TELEMETRY_SCHEMA_VERSION) =>
        {
            return Err("telemetry event must declare schema_version 1".to_owned());
        }
        Some("visualization")
            if !matches!(
                object.get("schema_version").and_then(Value::as_u64),
                Some(2 | 3)
            ) =>
        {
            return Err(
                "visualization event must declare supported schema_version 2 or 3".to_owned(),
            );
        }
        _ => {}
    }
    if let Some(timestamp) = object.get("timestamp") {
        if !timestamp.is_number() {
            return Err("runtime event timestamp must be numeric".to_owned());
        }
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| "system clock is before the Unix epoch".to_owned())?
            .as_secs_f64();
        let stale = timestamp.as_f64().is_some_and(|value| now - value > 30.0);
        object.insert("stale".to_owned(), Value::Bool(stale));
    }
    if serde_json::to_vec(&payload)
        .map_err(|error| format!("failed to encode runtime event: {error}"))?
        .len()
        > MAX_EVENT_BYTES
    {
        return Err("runtime event exceeds the 1 MiB metadata limit".to_owned());
    }

    Ok(NormalizedEvent { channel, payload })
}

pub(crate) fn event_payload(
    metadata: Value,
    payload: Vec<u8>,
) -> Result<(EventChannel, Value), String> {
    let normalized = normalize_event(metadata)?;
    if normalized.channel == EventChannel::Visualization {
        let mut object = Map::new();
        object.insert("metadata".to_owned(), normalized.payload);
        object.insert(
            "payload".to_owned(),
            Value::Array(payload.into_iter().map(Value::from).collect()),
        );
        Ok((normalized.channel, Value::Object(object)))
    } else {
        Ok((normalized.channel, normalized.payload))
    }
}

#[cfg(test)]
mod tests {
    use super::{event_payload, normalize_event, EventChannel};
    use serde_json::json;

    #[test]
    fn telemetry_events_are_versioned_and_keep_unknown_fields() {
        let event = json!({
            "type": "telemetry",
            "schema_version": 1,
            "timestamp": 1_700_000_000.0,
            "state": "running",
            "future_field": {"value": 7}
        });

        let normalized = normalize_event(event).unwrap();
        assert_eq!(normalized.channel, EventChannel::Event);
        assert_eq!(normalized.payload["schema_version"], 1);
        assert_eq!(normalized.payload["future_field"]["value"], 7);
    }

    #[test]
    fn visualization_events_use_the_binary_channel() {
        let event = json!({
            "type": "visualization",
            "schema_version": 2,
            "metadata": {"generation": 3},
            "payload": [1, 2, 3]
        });

        let normalized = normalize_event(event).unwrap();
        assert_eq!(normalized.channel, EventChannel::Visualization);
        assert_eq!(normalized.payload["metadata"]["generation"], 3);

        let (channel, payload) = event_payload(normalized.payload, vec![1, 2, 3]).unwrap();
        assert_eq!(channel, EventChannel::Visualization);
        assert_eq!(payload["payload"][2], 3);
    }

    #[test]
    fn current_visualization_schema_keeps_optional_physical_layer_metadata() {
        let event = json!({
            "type": "visualization", "schema_version": 3,
            "physical_layers": {"version": 1, "count": 1, "offset": 68, "stride": 60}
        });
        let normalized = normalize_event(event).unwrap();
        assert_eq!(normalized.payload["physical_layers"]["stride"], 60);
        assert_eq!(normalized.channel, EventChannel::Visualization);
    }

    #[test]
    fn supported_visualization_versions_forward_metadata_and_binary_unchanged() {
        for (version, cell_stride) in [(2, 36), (3, 68)] {
            let metadata = json!({
                "type": "visualization",
                "schema_version": version,
                "generation": 7,
                "points": {"count": 1, "offset": 0, "stride": 68},
                "cells": {"count": 1, "offset": 68, "stride": cell_stride},
                "layers": {"semantic": "ground_truth", "terrain": "available"}
            });
            let bytes = vec![0x7f; 68 + cell_stride];
            let (channel, forwarded) = event_payload(metadata.clone(), bytes.clone()).unwrap();
            assert_eq!(channel, EventChannel::Visualization);
            assert_eq!(forwarded["metadata"], metadata);
            assert_eq!(forwarded["payload"], json!(bytes));
        }
    }

    #[test]
    fn malformed_and_unsupported_events_are_rejected() {
        assert!(normalize_event(json!(null)).is_err());
        assert!(normalize_event(json!({"type": "unknown"})).is_err());
        assert!(normalize_event(json!({"type": "telemetry", "schema_version": 2})).is_err());
        assert!(normalize_event(json!({"type": "visualization", "schema_version": 1})).is_err());
        for version in [json!(4), json!(-1), json!(3.5), json!("3"), json!(null)] {
            assert!(normalize_event(json!({
                "type": "visualization", "schema_version": version
            }))
            .is_err());
        }
        assert!(normalize_event(json!({"type": "visualization"})).is_err());
    }

    #[test]
    fn validation_events_are_safe_bounded_event_channel_messages() {
        let normalized = normalize_event(json!({
            "type": "validation",
            "state": "complete",
            "result": {"status": "pass"}
        }))
        .unwrap();
        assert_eq!(normalized.channel, EventChannel::Event);
        assert_eq!(normalized.payload["result"]["status"], "pass");
    }
}
