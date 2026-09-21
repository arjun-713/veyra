use std::net::SocketAddr;
use std::path::PathBuf;

use veyra_lib::control::serve;

fn main() {
    match parse_args(std::env::args().skip(1).collect())
        .and_then(|(repo, bind, token_file)| {
            read_secret(&token_file).map(|secret| (repo, bind, secret))
        })
        .and_then(|(repo, bind, secret)| serve(repo, bind, secret))
    {
        Ok(()) => {}
        Err(error) => {
            eprintln!("veyra-control: {error}");
            std::process::exit(1);
        }
    }
}

fn parse_args(args: Vec<String>) -> Result<(PathBuf, SocketAddr, PathBuf), String> {
    let mut repo = None;
    let mut bind = None;
    let mut token_file = None;
    let mut args = args.into_iter();
    while let Some(argument) = args.next() {
        match argument.as_str() {
            "--repo" => repo = Some(PathBuf::from(next_value(&mut args, "--repo")?)),
            "--bind" => {
                bind = Some(
                    next_value(&mut args, "--bind")?
                        .parse::<SocketAddr>()
                        .map_err(|error| format!("invalid --bind address: {error}"))?,
                )
            }
            "--token-file" => {
                token_file = Some(PathBuf::from(next_value(&mut args, "--token-file")?))
            }
            "--help" | "-h" => return Err(
                "usage: veyra-control --repo <path> --bind 127.0.0.1:<port> --token-file <path>"
                    .to_owned(),
            ),
            _ => return Err(format!("unknown argument: {argument}")),
        }
    }

    let repo = repo.ok_or_else(|| "missing --repo".to_owned())?;
    let bind = bind.ok_or_else(|| "missing --bind".to_owned())?;
    let token_file = token_file.ok_or_else(|| "missing --token-file".to_owned())?;
    Ok((repo, bind, token_file))
}

fn read_secret(path: &PathBuf) -> Result<String, String> {
    let metadata = std::fs::metadata(path)
        .map_err(|error| format!("cannot read control token file {}: {error}", path.display()))?;
    if !metadata.is_file() {
        return Err(format!(
            "control token path {} must be a regular file",
            path.display()
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(format!(
                "control token file {} permissions must deny group and other access",
                path.display()
            ));
        }
    }
    if metadata.len() > 257 {
        return Err("control token file exceeds 257 bytes".to_owned());
    }
    let secret = std::fs::read_to_string(path)
        .map_err(|error| format!("cannot read control token file {}: {error}", path.display()))?;
    let secret = secret.trim_end_matches(['\r', '\n']).to_owned();
    if secret.is_empty() {
        return Err("control token file is empty".to_owned());
    }
    Ok(secret)
}

fn next_value(args: &mut impl Iterator<Item = String>, option: &str) -> Result<String, String> {
    args.next()
        .filter(|value| !value.starts_with('-'))
        .ok_or_else(|| format!("missing value for {option}"))
}

#[cfg(test)]
mod tests {
    use super::read_secret;

    #[test]
    fn control_secret_is_rejected_without_a_bounded_token() {
        let missing =
            std::env::temp_dir().join(format!("veyra-control-missing-{}", std::process::id()));
        let _ = std::fs::remove_file(&missing);
        assert!(read_secret(&missing).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn control_secret_rejects_group_or_world_readable_token_files() {
        use std::os::unix::fs::PermissionsExt;

        let path = std::env::temp_dir().join(format!("veyra-control-token-{}", std::process::id()));
        std::fs::write(&path, "12345678901234567890123456789012").unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
        assert!(read_secret(&path).is_ok());
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
        let error = read_secret(&path).unwrap_err();
        assert!(error.contains("permissions"));
        std::fs::remove_file(path).unwrap();
    }
}
