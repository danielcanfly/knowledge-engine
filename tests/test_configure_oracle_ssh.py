from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "configure_oracle_ssh.sh"
PRIVATE_KEY = (
    "-----BEGIN TEST PRIVATE KEY-----\n"
    "never-print-this-key\n"
    "-----END TEST PRIVATE KEY-----"
)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o700)


def _read_count(path: Path) -> int:
    return int(path.read_text(encoding="utf-8"))


def _run_helper(
    tmp_path: Path,
    *,
    keyscan_succeed_at: int = 1,
    ssh_succeed_at: int = 1,
) -> subprocess.CompletedProcess[str]:
    state = tmp_path / "state"
    fake_bin = tmp_path / "fake-bin"
    home = tmp_path / "home"
    state.mkdir()
    fake_bin.mkdir()
    home.mkdir()
    _write_executable(
        fake_bin / "ssh-keyscan",
        """#!/usr/bin/env bash
set -euo pipefail
state=\"${ORACLE_FAKE_STATE_DIR:?}\"
count_file=\"$state/keyscan_count\"
count=0
if [ -f \"$count_file\" ]; then
  count=\"$(cat \"$count_file\")\"
fi
count=$((count + 1))
printf '%s' \"$count\" > \"$count_file\"
printf '%s\\n' \"$*\" >> \"$state/keyscan_args\"
if [ \"$count\" -ge \"${ORACLE_FAKE_KEYSCAN_SUCCEED_AT:?}\" ]; then
  printf '%s ssh-ed25519 AAAATESTKEY\\n' \"${ORACLE_VM_HOST:?}\"
  exit 0
fi
exit 1
""",
    )
    _write_executable(
        fake_bin / "ssh",
        """#!/usr/bin/env bash
set -euo pipefail
state=\"${ORACLE_FAKE_STATE_DIR:?}\"
count_file=\"$state/ssh_count\"
count=0
if [ -f \"$count_file\" ]; then
  count=\"$(cat \"$count_file\")\"
fi
count=$((count + 1))
printf '%s' \"$count\" > \"$count_file\"
printf '%s\\n' \"$*\" >> \"$state/ssh_args\"
if [ \"$count\" -ge \"${ORACLE_FAKE_SSH_SUCCEED_AT:?}\" ]; then
  exit 0
fi
exit 255
""",
    )
    _write_executable(
        fake_bin / "sleep",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' \"$*\" >> \"${ORACLE_FAKE_STATE_DIR:?}/sleep_args\"
""",
    )
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "ORACLE_FAKE_STATE_DIR": str(state),
        "ORACLE_FAKE_KEYSCAN_SUCCEED_AT": str(keyscan_succeed_at),
        "ORACLE_FAKE_SSH_SUCCEED_AT": str(ssh_succeed_at),
        "ORACLE_VM_HOST": "oracle.example.invalid",
        "ORACLE_VM_USER": "ubuntu",
        "ORACLE_VM_SSH_PRIVATE_KEY": PRIVATE_KEY,
    }
    return subprocess.run(
        ["bash", str(SCRIPT)],
        check=False,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )


def test_keyscan_transient_recovery(tmp_path: Path) -> None:
    result = _run_helper(tmp_path, keyscan_succeed_at=3)

    assert result.returncode == 0
    assert _read_count(tmp_path / "state" / "keyscan_count") == 3
    assert "ORACLE_SSH_STAGE=keyscan_attempt_3" in result.stderr
    keyscan_args = (tmp_path / "state" / "keyscan_args").read_text(encoding="utf-8")
    assert "-4 -T 10 -H oracle.example.invalid" in keyscan_args
    assert "ORACLE_SSH_STAGE=ready" in result.stderr


def test_keyscan_exhaustion_fails_without_preflight(tmp_path: Path) -> None:
    result = _run_helper(tmp_path, keyscan_succeed_at=99)

    assert result.returncode != 0
    assert _read_count(tmp_path / "state" / "keyscan_count") == 5
    assert not (tmp_path / "state" / "ssh_count").exists()
    assert "ORACLE_SSH_STAGE=ready" not in result.stderr


def test_config_policy_and_permissions(tmp_path: Path) -> None:
    result = _run_helper(tmp_path)

    assert result.returncode == 0
    ssh_dir = tmp_path / "home" / ".ssh"
    config = (ssh_dir / "config").read_text(encoding="utf-8")
    for expected in (
        "BatchMode yes",
        "IdentitiesOnly yes",
        "AddressFamily inet",
        "ConnectTimeout 15",
        "ConnectionAttempts 3",
        "ServerAliveInterval 30",
        "ServerAliveCountMax 6",
        "TCPKeepAlive yes",
        "StrictHostKeyChecking yes",
        "ControlMaster auto",
        "ControlPersist 10m",
        f"ControlPath {ssh_dir}/oracle-%r@%h:%p",
    ):
        assert expected in config
    assert stat.S_IMODE(ssh_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((ssh_dir / "id_oracle").stat().st_mode) == 0o600
    assert stat.S_IMODE((ssh_dir / "config").stat().st_mode) == 0o600


def test_auth_preflight_transient_recovery(tmp_path: Path) -> None:
    result = _run_helper(tmp_path, ssh_succeed_at=2)

    assert result.returncode == 0
    assert _read_count(tmp_path / "state" / "ssh_count") == 2
    assert "ORACLE_SSH_STAGE=auth_preflight_attempt_2" in result.stderr
    assert "ORACLE_SSH_STAGE=ready" in result.stderr


def test_auth_preflight_exhaustion_fails_without_ready(tmp_path: Path) -> None:
    result = _run_helper(tmp_path, ssh_succeed_at=99)

    assert result.returncode != 0
    assert _read_count(tmp_path / "state" / "ssh_count") == 3
    assert "ORACLE_SSH_ERROR=auth_preflight_failed" in result.stderr
    assert "ORACLE_SSH_STAGE=ready" not in result.stderr


def test_secret_cleanliness(tmp_path: Path) -> None:
    result = _run_helper(tmp_path, keyscan_succeed_at=99)

    assert PRIVATE_KEY not in result.stdout
    assert PRIVATE_KEY not in result.stderr
    assert (tmp_path / "home" / ".ssh" / "id_oracle").read_text(
        encoding="utf-8"
    ).strip() == PRIVATE_KEY
