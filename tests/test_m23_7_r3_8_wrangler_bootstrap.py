from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("scripts/m23_7_r3_8_wrangler_bootstrap.sh")


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(
    tmp_path: Path,
    *,
    path_entries: list[Path],
    override: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = (
        f'source "{SCRIPT.resolve()}"; '
        "m23_r3_8_resolve_wrangler || exit $?; "
        "printf 'SOURCE=%s\\n' \"$M23_R3_8_WRANGLER_SOURCE\"; "
        "printf 'CMD=%s\\n' \"${M23_R3_8_WRANGLER_CMD[*]}\""
    )
    env = {
        "PATH": os.pathsep.join(str(path) for path in path_entries),
        "HOME": str(tmp_path),
    }
    if override is not None:
        env["WRANGLER_BIN"] = override
    return subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", "-c", command],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_resolver_uses_only_bash32_compatible_array_features() -> None:
    shell = SCRIPT.read_text(encoding="utf-8")

    assert "declare -a M23_R3_8_WRANGLER_CMD=()" in shell
    for forbidden in (
        "declare -g",
        "declare -A",
        "local -n",
        "mapfile",
        "readarray",
        "${!M23_R3_8_WRANGLER_CMD",
    ):
        assert forbidden not in shell
    assert "eval " not in shell
    assert '"${M23_R3_8_WRANGLER_CMD[@]}" --version' in shell


def test_global_wrangler_is_preferred_over_npx(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "wrangler",
        "#!/bin/sh\nprintf 'wrangler 4.111.0\\n'\n",
    )
    _write_executable(
        bin_dir / "npx",
        "#!/bin/sh\nprintf 'unexpected npx use\\n' >&2\nexit 88\n",
    )

    result = _run(tmp_path, path_entries=[bin_dir])

    assert result.returncode == 0, result.stderr
    assert "SOURCE=global" in result.stdout
    assert f"CMD={bin_dir / 'wrangler'}" in result.stdout


def test_npx_fallback_uses_exact_pinned_package(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "npx",
        """#!/bin/sh
if [ "$1" != "--yes" ] || [ "$2" != "wrangler@4.111.0" ] || [ "$3" != "--version" ]; then
  exit 77
fi
printf 'wrangler 4.111.0\n'
""",
    )

    result = _run(tmp_path, path_entries=[bin_dir])

    assert result.returncode == 0, result.stderr
    assert "SOURCE=npx-pinned" in result.stdout
    assert f"CMD={bin_dir / 'npx'} --yes wrangler@4.111.0" in result.stdout


def test_explicit_single_token_override_is_supported(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    custom = bin_dir / "pinned-wrangler"
    _write_executable(custom, "#!/bin/sh\nprintf 'wrangler 4.111.0\\n'\n")

    result = _run(
        tmp_path,
        path_entries=[bin_dir],
        override=str(custom),
    )

    assert result.returncode == 0, result.stderr
    assert "SOURCE=explicit" in result.stdout
    assert f"CMD={custom}" in result.stdout


def test_wrong_version_is_rejected(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "wrangler",
        "#!/bin/sh\nprintf 'wrangler 4.112.0\\n'\n",
    )

    result = _run(tmp_path, path_entries=[bin_dir])

    assert result.returncode != 0
    assert "version drifted" in result.stderr


@pytest.mark.parametrize(
    "override",
    (
        "wrangler --unsafe",
        "wrangler;touch-pwned",
        "$(touch-pwned)",
        "wrangler|cat",
    ),
)
def test_shell_syntax_shaped_override_is_rejected(
    tmp_path: Path,
    override: str,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "touch-pwned"

    result = _run(
        tmp_path,
        path_entries=[bin_dir],
        override=override,
    )

    assert result.returncode != 0
    assert "one executable token" in result.stderr
    assert not marker.exists()


def test_missing_wrangler_and_npx_is_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    result = _run(tmp_path, path_entries=[empty])

    assert result.returncode != 0
    assert "neither wrangler nor npx" in result.stderr
