use std::sync::Mutex;

use serde_json::{json, Value};

use crate::supervisor::RuntimeEvent;
use crate::telemetry::{normalize_event, EventChannel};

const MAX_PAYLOAD_BYTES: usize = 32 * 1024 * 1024;

#[derive(Default)]
struct Mailbox {
    raw: bool,
    latest: Option<RuntimeEvent>,
}

#[derive(Default)]
pub(crate) struct VisualizationTransport {
    mailbox: Mutex<Mailbox>,
}

impl VisualizationTransport {
    pub(crate) fn set_raw(&self, raw: bool) -> Result<bool, String> {
        let mut mailbox = self
            .mailbox
            .lock()
            .map_err(|_| "visualization mailbox lock poisoned")?;
        let announce = raw && !mailbox.raw && mailbox.latest.is_some();
        if mailbox.raw != raw {
            mailbox.raw = raw;
            if !raw {
                mailbox.latest = None;
            }
        }
        Ok(announce)
    }

    pub(crate) fn prepare(
        &self,
        event: RuntimeEvent,
    ) -> Result<Option<(&'static str, Value)>, String> {
        let normalized = normalize_event(event.metadata)?;
        let event = RuntimeEvent {
            metadata: normalized.payload,
            payload: event.payload,
        };
        if normalized.channel == EventChannel::Visualization {
            if event.payload.len() > MAX_PAYLOAD_BYTES {
                return Err("visualization payload exceeds the 32 MiB protocol limit".to_owned());
            }
            let mut mailbox = self
                .mailbox
                .lock()
                .map_err(|_| "visualization mailbox lock poisoned")?;
            if mailbox.raw {
                // Signal only the empty-to-full transition. A slow renderer
                // gets the newest frame without an unbounded notification queue.
                let announce = mailbox.latest.replace(event).is_none();
                return Ok(
                    announce.then(|| ("veyra://visualization-ready", json!({"available": true})))
                );
            }
            // Keep one paused preview through listener/transport startup.
            // Legacy delivery still needs its own bytes for the number array.
            mailbox.latest = Some(event.clone());
        }
        crate::forwardable_runtime_event(event).map(Some)
    }

    pub(crate) fn take(&self) -> Result<tauri::ipc::Response, String> {
        let event = {
            let mut mailbox = self
                .mailbox
                .lock()
                .map_err(|_| "visualization mailbox lock poisoned")?;
            if mailbox.raw {
                mailbox.latest.take()
            } else {
                None
            }
        };
        let Some(event) = event else {
            return Ok(tauri::ipc::Response::new(Vec::<u8>::new()));
        };
        // Detach before encoding or IPC delivery: neither calls back into
        // Tauri while holding the mailbox or desktop command locks.
        let mut metadata =
            serde_json::to_vec(&event.metadata).map_err(|error| error.to_string())?;
        metadata.resize((metadata.len() + 3) & !3, b' ');
        let mut packet = Vec::with_capacity(16 + metadata.len() + event.payload.len());
        packet.extend_from_slice(b"VYRA");
        packet.extend_from_slice(&1_u16.to_le_bytes());
        packet.extend_from_slice(&2_u16.to_le_bytes());
        packet.extend_from_slice(&(metadata.len() as u32).to_le_bytes());
        packet.extend_from_slice(&(event.payload.len() as u32).to_le_bytes());
        packet.extend_from_slice(&metadata);
        packet.extend_from_slice(&event.payload);
        Ok(tauri::ipc::Response::new(packet))
    }
}

#[cfg(test)]
mod tests {
    use super::VisualizationTransport;
    use crate::supervisor::RuntimeEvent;
    use serde_json::json;
    use tauri::ipc::{InvokeResponseBody, IpcResponse};

    fn frame(id: u64, payload: Vec<u8>) -> RuntimeEvent {
        RuntimeEvent {
            metadata: json!({"type": "visualization", "schema_version": 3, "frame_id": id, "generation": 7}),
            payload,
        }
    }

    fn take_bytes(transport: &VisualizationTransport) -> Vec<u8> {
        match transport.take().unwrap().body().unwrap() {
            InvokeResponseBody::Raw(bytes) => bytes,
            InvokeResponseBody::Json(_) => panic!("visualization must return raw IPC bytes"),
        }
    }

    #[test]
    fn raw_mailbox_announces_once_and_consumes_latest_aligned_packet() {
        let transport = VisualizationTransport::default();
        transport.set_raw(true).unwrap();
        let ready = transport.prepare(frame(1, vec![1; 68])).unwrap().unwrap();
        assert_eq!(
            ready,
            ("veyra://visualization-ready", json!({"available": true}))
        );
        for id in 2..100 {
            assert!(transport
                .prepare(frame(id, vec![id as u8; 68]))
                .unwrap()
                .is_none());
        }
        let bytes = take_bytes(&transport);
        assert_eq!(&bytes[..8], b"VYRA\x01\x00\x02\x00");
        let metadata_len = u32::from_le_bytes(bytes[8..12].try_into().unwrap()) as usize;
        let payload_len = u32::from_le_bytes(bytes[12..16].try_into().unwrap()) as usize;
        assert_eq!((16 + metadata_len) % 4, 0, "float payload must be aligned");
        assert_eq!(payload_len, 68);
        assert_eq!(bytes.len(), 16 + metadata_len + payload_len);
        let metadata: serde_json::Value =
            serde_json::from_slice(&bytes[16..16 + metadata_len]).unwrap();
        assert_eq!(metadata["frame_id"], 99);
        assert_eq!(metadata["generation"], 7);
        assert_eq!(&bytes[16 + metadata_len..], &[99; 68]);
        assert!(take_bytes(&transport).is_empty());
        assert!(transport
            .prepare(frame(100, vec![0; 68]))
            .unwrap()
            .is_some());
    }

    #[test]
    fn raw_mailbox_validates_before_replacing_pending_frame() {
        let transport = VisualizationTransport::default();
        transport.set_raw(true).unwrap();
        transport.prepare(frame(1, vec![9])).unwrap();
        let invalid = RuntimeEvent {
            metadata: json!({"type": "visualization", "schema_version": 99}),
            payload: vec![0],
        };
        assert!(transport.prepare(invalid).is_err());
        let bytes = take_bytes(&transport);
        assert_eq!(bytes.last(), Some(&9));
    }

    #[test]
    fn enabling_raw_keeps_preview_that_arrived_before_listener_registration() {
        let transport = VisualizationTransport::default();
        transport.prepare(frame(1, vec![7])).unwrap();
        transport.set_raw(true).unwrap();
        let bytes = take_bytes(&transport);
        assert_eq!(
            bytes.last(),
            Some(&7),
            "paused preview must survive raw transport startup"
        );
        assert!(take_bytes(&transport).is_empty());
    }

    #[test]
    fn repeated_enable_does_not_discard_pending_frame() {
        let transport = VisualizationTransport::default();
        transport.set_raw(true).unwrap();
        transport.prepare(frame(1, vec![7])).unwrap();
        transport.set_raw(true).unwrap();
        assert_eq!(take_bytes(&transport).last(), Some(&7));
    }

    #[test]
    fn raw_mailbox_rejects_oversized_binary_frames() {
        let transport = VisualizationTransport::default();
        transport.set_raw(true).unwrap();
        assert!(transport
            .prepare(frame(1, vec![0; 32 * 1024 * 1024 + 1]))
            .is_err());
        assert!(take_bytes(&transport).is_empty());
    }

    #[test]
    fn transport_switch_clears_mailbox_and_preserves_legacy_event_contract() {
        let transport = VisualizationTransport::default();
        let legacy = transport.prepare(frame(1, vec![9, 8])).unwrap().unwrap();
        assert_eq!(legacy.0, "veyra://visualization");
        assert_eq!(legacy.1["payload"], json!([9, 8]));
        transport.set_raw(true).unwrap();
        transport.prepare(frame(2, vec![7])).unwrap();
        transport.set_raw(false).unwrap();
        assert!(take_bytes(&transport).is_empty());
        let legacy = transport.prepare(frame(3, vec![6])).unwrap().unwrap();
        assert_eq!(legacy.1["metadata"]["frame_id"], 3);
        assert_eq!(legacy.1["payload"], json!([6]));
    }

    #[test]
    fn raw_mode_keeps_control_events_on_existing_channel() {
        let transport = VisualizationTransport::default();
        transport.set_raw(true).unwrap();
        let event = transport
            .prepare(RuntimeEvent {
                metadata: json!({"type": "status", "state": "paused"}),
                payload: vec![],
            })
            .unwrap()
            .unwrap();
        assert_eq!(
            event,
            (
                "veyra://event",
                json!({"type": "status", "state": "paused"})
            )
        );
        assert!(take_bytes(&transport).is_empty());
    }
}
