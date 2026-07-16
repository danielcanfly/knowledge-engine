from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path("scripts/m23_7_r3_8_worker_absence_probe.sh")
WORKER_NAME = "knowledge-engine-m23-7-r3-8-latency"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(
    tmp_path: Path,
    *,
    shim_body: str,
    worker_name: str = WORKER_NAME,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "wrangler-shim"
    _write_executable(shim, shim_body)
    config = tmp_path / "wrangler.local.jsonc"
    config.write_text("{}\n", encoding="utf-8")
    command = (
        f'source "{SCRIPT.resolve()}"; '
        f'M23_R3_8_WRANGLER_CMD=("{shim}"); '
        f'M23_R3_8_PYTHON_BIN="{sys.executable}"; '
        f'm23_r3_8_probe_worker_absence "{worker_name}" "{config}"'
    )
    return subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", "-c", command],
        cwd=Path.cwd(),
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )


def _checking_shim(body: str, *, exit_code: int) -> str:
    return f"""#!/bin/sh
if [ "$1" != "versions" ] || [ "$2" != "list" ] || [ "$3" != "--name" ]; then
  exit 71
fi
if [ "$4" != "{WORKER_NAME}" ] || [ "$5" != "--config" ] || [ "$7" != "--json" ]; then
  exit 72
fi
{body}
exit {exit_code}
"""


def test_absent_only_on_exact_worker_not_found_code(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        shim_body=_checking_shim(
            "printf 'Cloudflare API error [code: 10007]\\n' >&2",
            exit_code=1,
        ),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "absent\n"


def test_present_only_on_nonempty_json_versions_array(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        shim_body=_checking_shim(
            "printf '[{\"id\":\"version-1\"}]\\n'",
            exit_code=0,
        ),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "present\n"


@pytest.mark.parametrize(
    ("body", "exit_code"),
    (
        ("printf 'HTTP 403 secret-sentinel\\n' >&2", 1),
        ("printf 'Cloudflare API error [code: 10008]\\n' >&2", 1),
        ("printf 'not-json\\n'", 0),
        ("printf '{}\\n'", 0),
        ("printf '[]\\n'", 0),
    ),
)
def test_ambiguous_or_invalid_probe_fails_closed_without_raw_output(
    tmp_path: Path,
    body: str,
    exit_code: int,
) -> None:
    result = _run(
        tmp_path,
        shim_body=_checking_shim(body, exit_code=exit_code),
    )

    assert result.returncode != 0
    assert "secret-sentinel" not in result.stdout
    assert "secret-sentinel" not in result.stderr
    assert result.stdout == ""
    assert "absence probe ERROR" in result.stderr


def test_oversized_output_is_rejected(tmp_path: Path) -> None:
    body = (
        f"{sys.executable} - <<'PY'\n"
        "print('x' * 70000)\n"
        "PY"
    )
    result = _run(
        tmp_path,
        shim_body=_checking_shim(body, exit_code=1),
    )

    assert result.returncode != 0
    assert "exceeded the bounded limit" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    "worker_name",
    (
        "worker;touch-pwned",
        "$(touch-pwned)",
        "Worker With Spaces",
        "../worker",
    ),
)
def test_shell_injection_shaped_worker_name_is_rejected(
    tmp_path: Path,
    worker_name: str,
) -> None:
    marker = tmp_path / "touch-pwned"
    result = _run(
        tmp_path,
        shim_body="#!/bin/sh\nexit 99\n",
        worker_name=worker_name,
    )

    assert result.returncode != 0
    assert "bounded lowercase token" in result.stderr
    assert not marker.exists()


def test_probe_source_uses_bash32_arrays_and_never_eval() -> None:
    shell = SCRIPT.read_text(encoding="utf-8")

    assert '"${M23_R3_8_WRANGLER_CMD[@]}"' in shell
    assert "versions list" in shell
    assert "--json" in shell
    assert "10007" in shell
    assert "eval " not in shell
    for forbidden in ("declare -g", "declare -A", "local -n", "mapfile", "readarray"):
        assert forbidden not in shell
