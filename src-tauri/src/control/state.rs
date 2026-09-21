use serde::Serialize;
use thiserror::Error;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum RuntimeState {
    Booting,
    Ready,
    Loading,
    Running,
    Paused,
    Stopping,
    Error,
}

impl RuntimeState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Booting => "BOOTING",
            Self::Ready => "READY",
            Self::Loading => "LOADING",
            Self::Running => "RUNNING",
            Self::Paused => "PAUSED",
            Self::Stopping => "STOPPING",
            Self::Error => "ERROR",
        }
    }
}

#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum StateError {
    #[error("a dataset is required before playback")]
    DatasetRequired,
    #[error("the requested transition is not valid from {0}")]
    InvalidTransition(&'static str),
}

#[derive(Debug, Clone, Serialize)]
pub struct RuntimeStatus {
    pub state: RuntimeState,
    pub dataset_open: bool,
}

#[derive(Debug, Clone)]
pub struct AppState {
    state: RuntimeState,
    dataset_open: bool,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            state: RuntimeState::Booting,
            dataset_open: false,
        }
    }

    pub fn status(&self) -> RuntimeStatus {
        RuntimeStatus {
            state: self.state,
            dataset_open: self.dataset_open,
        }
    }

    pub fn mark_ready(&mut self) {
        self.state = RuntimeState::Ready;
    }

    pub fn open_dataset(&mut self) -> Result<(), StateError> {
        if self.state == RuntimeState::Stopping {
            return Err(StateError::InvalidTransition(self.state.as_str()));
        }
        // A previous failure must not wedge the controller: opening again
        // retries from a clean slate.
        self.state = RuntimeState::Loading;
        self.dataset_open = true;
        self.state = RuntimeState::Ready;
        Ok(())
    }

    pub fn play(&mut self) -> Result<(), StateError> {
        if !self.dataset_open {
            return Err(StateError::DatasetRequired);
        }
        match self.state {
            RuntimeState::Ready | RuntimeState::Paused => {
                self.state = RuntimeState::Running;
                Ok(())
            }
            RuntimeState::Running => Ok(()),
            _ => Err(StateError::InvalidTransition(self.state.as_str())),
        }
    }

    pub fn pause(&mut self) -> Result<(), StateError> {
        match self.state {
            RuntimeState::Running => {
                self.state = RuntimeState::Paused;
                Ok(())
            }
            RuntimeState::Paused => Ok(()),
            _ => Err(StateError::InvalidTransition(self.state.as_str())),
        }
    }

    pub fn stop(&mut self) -> Result<(), StateError> {
        match self.state {
            RuntimeState::Ready | RuntimeState::Paused | RuntimeState::Running => {
                self.state = RuntimeState::Stopping;
                self.dataset_open = false;
                self.state = RuntimeState::Ready;
                Ok(())
            }
            // Stopping after a failure resets to Ready so the next open or
            // command starts clean instead of latching ERROR forever.
            RuntimeState::Error => {
                self.dataset_open = false;
                self.state = RuntimeState::Ready;
                Ok(())
            }
            RuntimeState::Stopping => Ok(()),
            _ => Err(StateError::InvalidTransition(self.state.as_str())),
        }
    }

    pub fn fail(&mut self) {
        self.state = RuntimeState::Error;
    }
}

impl Default for AppState {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::{AppState, RuntimeState, StateError};

    #[test]
    fn opening_a_dataset_makes_playback_ready() {
        let mut state = AppState::new();
        state.open_dataset().unwrap();

        assert_eq!(state.status().state, RuntimeState::Ready);
        state.play().unwrap();
        assert_eq!(state.status().state, RuntimeState::Running);
    }

    #[test]
    fn failed_runtime_cannot_be_played() {
        let mut state = AppState::new();
        state.fail();
        assert_eq!(state.play(), Err(StateError::DatasetRequired));
    }

    #[test]
    fn running_playback_can_pause_and_stop_cleanly() {
        let mut state = AppState::new();
        state.open_dataset().unwrap();
        state.play().unwrap();
        state.pause().unwrap();
        assert_eq!(state.status().state, RuntimeState::Paused);
        state.stop().unwrap();
        assert_eq!(state.status().state, RuntimeState::Ready);
        assert!(!state.status().dataset_open);
    }

    #[test]
    fn error_state_rejects_playback_but_allows_recovery() {
        let mut state = AppState::new();
        state.fail();
        assert_eq!(state.pause(), Err(StateError::InvalidTransition("ERROR")));
        assert_eq!(state.play(), Err(StateError::DatasetRequired));
        // Recovery paths: stopping resets to Ready, opening retries cleanly.
        state.stop().unwrap();
        assert_eq!(state.status().state, RuntimeState::Ready);
        state.fail();
        state.open_dataset().unwrap();
        assert_eq!(state.status().state, RuntimeState::Ready);
        state.play().unwrap();
        assert_eq!(state.status().state, RuntimeState::Running);
    }
}
