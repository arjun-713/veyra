"""Resolve one release identity and stamp it before packaging the backend/UI."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

VERSION = re.compile(
    r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)


def validate_version(raw: str) -> str:
    version = raw.removeprefix("v")
    match = VERSION.fullmatch(version)
    if not match:
        raise ValueError(f"invalid release version: {raw!r}")
    if any(int(part) > 65535 for part in match.groups()[:3]):
        raise ValueError("version exceeds the Windows installer component limit")
    if match[4] and any(
        part.isdigit() and len(part) > 1 and part.startswith("0")
        for part in match[4].split(".")
    ):
        raise ValueError("numeric prerelease identifiers cannot have leading zeros")
    return version


def resolve_release(
    base_version: str,
    event_name: str,
    ref: str,
    run_number: int,
    requested_version: str = "",
    prerelease: bool = True,
) -> dict[str, str | bool]:
    if event_name == "workflow_dispatch" and requested_version:
        version = validate_version(requested_version)
    elif event_name == "push" and ref.startswith("refs/tags/v"):
        version = validate_version(ref.removeprefix("refs/tags/"))
        prerelease = False
    elif event_name in {"push", "workflow_dispatch"} and ref == "refs/heads/main":
        base = VERSION.fullmatch(validate_version(base_version))
        if run_number < 1:
            raise ValueError("run number must be positive")
        # The workflow run number is monotonic; retries keep the same version.
        version = validate_version(f"{base[1]}.{base[2]}.{int(base[3]) + run_number}")
        prerelease = False
    else:
        raise ValueError("automatic releases require the main branch")
    match = VERSION.fullmatch(version)
    return {
        "version": version,
        "tag": f"v{version}",
        "prerelease": bool(prerelease or match[4]),
    }


def stamp_version(repo: Path, version: str) -> None:
    version = validate_version(version)
    conf_path = repo / "src-tauri/tauri.conf.json"
    config = json.loads(conf_path.read_text(encoding="utf-8"))
    cargo_path = repo / "src-tauri/Cargo.toml"
    text = cargo_path.read_text(encoding="utf-8")
    # Limit the edit to [package], even if another table also has a version key.
    package = re.search(r"(?ms)^\[package\]\s*\n(.*?)(?=^\[|\Z)", text)
    if package is None:
        raise ValueError("Cargo manifest has no package section")
    body, count = re.subn(
        r'^version\s*=\s*"[^"]*"',
        f'version = "{version}"',
        package[1],
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError("expected exactly one package version in Cargo.toml")
    config["version"] = version
    conf_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    cargo_path.write_text(
        text[: package.start(1)] + body + text[package.end(1) :], encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--stamp", help="Stamp an already resolved version")
    args = parser.parse_args()
    if args.stamp:
        stamp_version(args.repo, args.stamp)
        print(f"stamped product/backend version {args.stamp}")
        return 0
    config = json.loads((args.repo / "src-tauri/tauri.conf.json").read_text())
    identity = resolve_release(
        config["version"],
        os.environ["GITHUB_EVENT_NAME"],
        os.environ["GITHUB_REF"],
        int(os.environ["GITHUB_RUN_NUMBER"]),
        os.environ.get("REQUESTED_VERSION", ""),
        os.environ.get("REQUESTED_PRERELEASE", "true") == "true",
    )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.writelines(
            f"{name}={str(value).lower() if isinstance(value, bool) else value}\n"
            for name, value in identity.items()
        )
    print(json.dumps(identity))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
