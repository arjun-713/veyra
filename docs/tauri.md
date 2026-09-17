# Veyra Tauri desktop

The desktop shell is being migrated from Electron to Tauri 2 while the
existing Svelte, Python, and C++ layers remain the product implementation.
Electron is retained only as a behavioral reference until the parity matrix in
`docs/desktop-electron-audit.md` is complete.

## Local development

From `apps/desktop/`:

```bash
NPM_CONFIG_CACHE=/tmp/veyra-npm-cache npm ci
npm run tauri:dev
```

The Rust shell starts the Python runtime through the versioned Veyra protocol.
For a repository checkout it discovers the mapper in
`build/apps/runtime/veyra_runtime` and Python in `.venv` (or `VEYRA_PYTHON`).
The frontend receives only named Tauri commands and events; it does not get
shell or process APIs.

## Release staging

Release jobs build the C++ mapper and stage a relocatable backend before
building the Tauri bundle:

```bash
python scripts/stage_tauri_backend.py \
  --mapper build/apps/runtime/veyra_runtime \
  --python-runtime /path/to/release-venv \
  --platform linux --arch x64
```

The staged directory is ignored by Git and contains a checksum manifest. It is
copied into the Tauri resource bundle as `resources/backend`; the Rust shell
resolves that layout and sets `PYTHONHOME`/`PYTHONPATH` for the bundled
interpreter. Dataset files and model weights are never packaged.

Linux packages can be built locally with:

```bash
CARGO_HOME=/tmp/veyra-cargo-home npm run tauri:build -- --bundles deb
```

The release workflow additionally targets RPM/AppImage, Windows NSIS, and
macOS DMG. Those artifacts require their target operating system for genuine
runtime and installer validation; Linux success is not evidence of Windows or
macOS parity.

## Control surface

`src-tauri/src/control` is the native controller used by Tauri and the JSON
CLI. The safe MCP adapter exposes the same named product commands through the
Python runtime contract. Runtime events are version-checked, size-bounded, and
marked stale when their timestamp is more than 30 seconds old. Malformed
events become diagnostics instead of being emitted as trusted telemetry.
