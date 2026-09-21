fn main() {
    warn_when_backend_resources_are_unstaged();
    tauri_build::build();
}

/// A bundle built without a staged backend ships an unrunnable application:
/// the resource directory contains only the `.gitkeep` placeholder, so the
/// packaged app can never start a real backend session. Staging is a release
/// step (`scripts/stage_tauri_backend.py`, wired in `release-tauri.yml`);
/// local `--no-bundle` smoke builds legitimately skip it, so this stays a
/// loud warning rather than a hard error.
fn warn_when_backend_resources_are_unstaged() {
    let manifest_dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let backend = manifest_dir.join("resources/backend");
    let staged =
        backend.join("manifest.json").is_file() && backend.join("runtime/__main__.py").is_file();
    if !staged {
        println!(
            "cargo:warning=Tauri backend resources are unstaged: {} lacks the staged manifest; bundles built from this tree cannot run backend sessions (run scripts/stage_tauri_backend.py first)",
            backend.display()
        );
    }
}
