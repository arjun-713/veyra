"""Create a verified, unstyled DMG from a signed Tauri application bundle.

The hosted-runner path avoids mounting an editable image and asking Disk
Arbitration to detach it, which can time out after a successful app build.
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path


def package_dmg(app: Path, output: Path) -> Path:
    app = app.absolute()
    output = output.absolute()
    if app.suffix != ".app" or not (app / "Contents" / "Info.plist").is_file():
        raise ValueError(f"not an application bundle: {app}")
    if output.suffix != ".dmg":
        raise ValueError("output must be a .dmg file")
    if output.exists():
        raise FileExistsError(output)
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(app)],
        check=True,
        timeout=120,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="veyra-dmg-") as temporary:
            folder = Path(temporary)
            # ditto preserves macOS metadata and the already-sealed signature.
            subprocess.run(
                ["ditto", str(app), str(folder / app.name)], check=True, timeout=600
            )
            (folder / "Applications").symlink_to("/Applications")
            subprocess.run(
                [
                    "hdiutil",
                    "create",
                    "-volname",
                    "Veyra",
                    "-srcfolder",
                    str(folder),
                    "-format",
                    "UDZO",
                    "-fs",
                    "HFS+",
                    str(output),
                ],
                check=True,
                timeout=900,
            )
            if not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError("hdiutil did not produce a nonempty disk image")
            subprocess.run(["hdiutil", "verify", str(output)], check=True, timeout=120)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(package_dmg(args.app, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
