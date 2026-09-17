use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpListener};
use std::path::{Path, PathBuf};
use std::thread::{self, JoinHandle};

use crate::control::{serve_listener, RuntimeController};

const TOKEN_BYTES: usize = 32;
const TOKEN_FILE: &str = "control.token";
const DISCOVERY_FILE: &str = "control.json";

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ClientConfig {
    pub(crate) endpoint: SocketAddr,
    pub(crate) token_file: PathBuf,
}

#[derive(Debug, thiserror::Error)]
pub(crate) enum ControlHostError {
    #[error("control endpoint configuration must provide both VEYRA_CONTROL_ENDPOINT and VEYRA_CONTROL_TOKEN_FILE")]
    PartialEnvironment,
    #[error("control endpoint is invalid: {0}")]
    InvalidEndpoint(String),
    #[error("control token file is invalid: {0}")]
    InvalidTokenFile(String),
    #[error("cannot create protected control storage: {0}")]
    Storage(#[source] io::Error),
    #[error("cannot generate a cryptographically strong control secret: {0}")]
    Entropy(#[source] io::Error),
    #[error("cannot bind the local control daemon: {0}")]
    Bind(#[source] io::Error),
    #[error("control daemon stopped during startup: {0}")]
    Start(String),
}

pub(crate) struct ControlHost {
    config: ClientConfig,
    thread: Option<JoinHandle<Result<(), String>>>,
    secret: Option<String>,
    owns_daemon: bool,
    persisted: bool,
}

impl ControlHost {
    pub(crate) fn start(repo: PathBuf, config_dir: &Path) -> Result<Self, ControlHostError> {
        match (
            std::env::var_os("VEYRA_CONTROL_ENDPOINT"),
            std::env::var_os("VEYRA_CONTROL_TOKEN_FILE"),
        ) {
            (Some(endpoint), Some(token_file)) => {
                let config =
                    validate_external_config(&endpoint.to_string_lossy(), Path::new(&token_file))?;
                Ok(Self {
                    config,
                    thread: None,
                    secret: None,
                    owns_daemon: false,
                    persisted: false,
                })
            }
            (None, None) => Self::launch_owned(repo, config_dir),
            _ => Err(ControlHostError::PartialEnvironment),
        }
    }

    pub(crate) fn config(&self) -> &ClientConfig {
        &self.config
    }

    pub(crate) fn join_after_shutdown(&mut self) -> Result<(), String> {
        if let Some(thread) = self.thread.take() {
            match thread.join() {
                Ok(result) => result,
                Err(_) => Err("control daemon thread panicked".to_owned()),
            }
        } else {
            Ok(())
        }
    }

    fn stop_and_join(&mut self) -> Result<(), String> {
        if let Some(secret) = self.secret.as_deref() {
            let mut client = crate::control::ControlClient::from_endpoint_and_token(
                self.config.endpoint,
                secret,
            )
            .map_err(|error| error.to_string())?;
            let _ = client.request("shutdown", serde_json::json!({}));
        }
        self.join_after_shutdown()
    }

    fn launch_owned(repo: PathBuf, config_dir: &Path) -> Result<Self, ControlHostError> {
        let secret = generate_secret()?;
        let listener = TcpListener::bind(SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 0))
            .map_err(ControlHostError::Bind)?;
        let endpoint = listener.local_addr().map_err(ControlHostError::Bind)?;
        let token_file = config_dir.join(TOKEN_FILE);
        let discovery_file = config_dir.join(DISCOVERY_FILE);

        persist_credentials(&token_file, &discovery_file, endpoint, &secret)?;
        let daemon_secret = secret.clone();
        let thread = thread::Builder::new()
            .name("veyra-control-daemon".to_owned())
            .spawn(move || {
                serve_listener(listener, RuntimeController::new(repo), daemon_secret)
                    .map_err(|error| error.to_string())
            })
            .map_err(|error| ControlHostError::Start(error.to_string()))?;

        Ok(Self {
            config: ClientConfig {
                endpoint,
                token_file,
            },
            thread: Some(thread),
            secret: Some(secret),
            owns_daemon: true,
            persisted: true,
        })
    }
}

impl Drop for ControlHost {
    fn drop(&mut self) {
        if self.owns_daemon {
            let _ = self.stop_and_join();
        }
        if self.persisted {
            let _ = fs::remove_file(&self.config.token_file);
            let _ = fs::remove_file(self.config.token_file.with_file_name(DISCOVERY_FILE));
        }
    }
}

pub(crate) fn validate_external_config(
    endpoint: &str,
    token_file: &Path,
) -> Result<ClientConfig, ControlHostError> {
    let endpoint = endpoint
        .parse::<SocketAddr>()
        .map_err(|error| ControlHostError::InvalidEndpoint(error.to_string()))?;
    if !endpoint.ip().is_loopback() || endpoint.ip().is_unspecified() {
        return Err(ControlHostError::InvalidEndpoint(
            "endpoint must be a loopback address".to_owned(),
        ));
    }
    validate_token_file(token_file)?;
    Ok(ClientConfig {
        endpoint,
        token_file: token_file.to_path_buf(),
    })
}

fn persist_credentials(
    token_file: &Path,
    discovery_file: &Path,
    endpoint: SocketAddr,
    secret: &str,
) -> Result<(), ControlHostError> {
    fs::create_dir_all(token_file.parent().unwrap_or_else(|| Path::new(".")))
        .map_err(ControlHostError::Storage)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(
            token_file.parent().unwrap_or_else(|| Path::new(".")),
            fs::Permissions::from_mode(0o700),
        )
        .map_err(ControlHostError::Storage)?;
        write_protected_file(token_file, secret.as_bytes())?;
        let discovery = format!(
            "{{\"schema_version\":1,\"endpoint\":\"{endpoint}\",\"token_file\":{}}}\n",
            serde_json::to_string(token_file.to_string_lossy().as_ref()).expect("path string")
        );
        write_protected_file(discovery_file, discovery.as_bytes())?;
        Ok(())
    }
    #[cfg(not(unix))]
    {
        let _ = (token_file, discovery_file, endpoint, secret);
        Err(ControlHostError::Storage(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "protected discovery storage is not implemented on this platform",
        )))
    }
}

#[cfg(unix)]
fn write_protected_file(path: &Path, contents: &[u8]) -> Result<(), ControlHostError> {
    use std::os::unix::fs::OpenOptionsExt;
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .mode(0o600)
        .open(path)
        .map_err(ControlHostError::Storage)?;
    file.write_all(contents)
        .map_err(ControlHostError::Storage)?;
    file.sync_all().map_err(ControlHostError::Storage)
}

fn validate_token_file(path: &Path) -> Result<(), ControlHostError> {
    if !path.is_absolute() {
        return Err(ControlHostError::InvalidTokenFile(
            "path must be absolute".to_owned(),
        ));
    }
    let metadata = fs::metadata(path)
        .map_err(|error| ControlHostError::InvalidTokenFile(error.to_string()))?;
    if !metadata.is_file() {
        return Err(ControlHostError::InvalidTokenFile(
            "path must refer to a regular file".to_owned(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(ControlHostError::InvalidTokenFile(
                "file permissions must deny group and other access".to_owned(),
            ));
        }
    }
    let mut token = String::new();
    File::open(path)
        .and_then(|mut file| file.read_to_string(&mut token))
        .map_err(|error| ControlHostError::InvalidTokenFile(error.to_string()))?;
    while token.ends_with(['\r', '\n']) {
        token.pop();
    }
    if !(32..=256).contains(&token.len()) || !token.bytes().all(|byte| byte.is_ascii_graphic()) {
        return Err(ControlHostError::InvalidTokenFile(
            "token must contain 32-256 printable ASCII bytes".to_owned(),
        ));
    }
    Ok(())
}

fn generate_secret() -> Result<String, ControlHostError> {
    let mut bytes = [0u8; TOKEN_BYTES];
    #[cfg(unix)]
    {
        File::open("/dev/urandom")
            .and_then(|mut file| file.read_exact(&mut bytes))
            .map_err(ControlHostError::Entropy)?;
    }
    #[cfg(windows)]
    unsafe {
        #[link(name = "advapi32")]
        extern "system" {
            fn SystemFunction036(buffer: *mut u8, length: u32) -> u8;
        }
        if SystemFunction036(bytes.as_mut_ptr(), bytes.len() as u32) == 0 {
            return Err(ControlHostError::Entropy(io::Error::last_os_error()));
        }
    }
    #[cfg(not(any(unix, windows)))]
    return Err(ControlHostError::Entropy(io::Error::new(
        io::ErrorKind::Unsupported,
        "secure operating-system randomness is unavailable",
    )));

    let mut secret = String::with_capacity(TOKEN_BYTES * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        write!(&mut secret, "{byte:02x}").expect("writing to String cannot fail");
    }
    Ok(secret)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_file(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!("veyra-control-host-{name}-{}", std::process::id()))
    }

    #[test]
    fn external_config_rejects_non_loopback_and_relative_tokens() {
        let error = validate_external_config("0.0.0.0:1234", Path::new("token"))
            .expect_err("unspecified endpoint must be rejected first");
        assert!(matches!(error, ControlHostError::InvalidEndpoint(_)));
    }

    #[cfg(unix)]
    #[test]
    fn external_config_requires_private_token_file() {
        use std::os::unix::fs::PermissionsExt;
        let path = temp_file("permissions");
        fs::write(&path, "a".repeat(32)).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
        let error = validate_external_config("127.0.0.1:1234", &path).unwrap_err();
        assert!(matches!(error, ControlHostError::InvalidTokenFile(_)));
        let _ = fs::remove_file(path);
    }

    #[test]
    fn generated_secret_is_printable_and_bounded() {
        let secret = generate_secret().unwrap();
        assert_eq!(secret.len(), TOKEN_BYTES * 2);
        assert!(secret.bytes().all(|byte| byte.is_ascii_graphic()));
    }

    #[test]
    fn launch_storage_contains_no_secret_in_discovery_record() {
        let root = temp_file(&format!(
            "storage-{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&root).unwrap();
        let token = root.join(TOKEN_FILE);
        let discovery = root.join(DISCOVERY_FILE);
        persist_credentials(
            &token,
            &discovery,
            "127.0.0.1:1234".parse().unwrap(),
            &"a".repeat(64),
        )
        .unwrap();
        let record = fs::read_to_string(discovery).unwrap();
        assert!(!record.contains(&"a".repeat(64)));
        validate_token_file(&token).unwrap();
        let _ = fs::remove_dir_all(root);
    }
}
