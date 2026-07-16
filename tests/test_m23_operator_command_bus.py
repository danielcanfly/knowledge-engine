from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import m23_operator_command_bus as subject


def _auth(nonce: str) -> dict:
    value = {
        "schema_version": subject.AUTH_SCHEMA,
        "authorization_id": "m23-r3-8-post-delete-recovery-29521901629",
        "command_type": "r3_8_post_delete_recovery",
        "nonce": nonce,
        "bus_issue_number": subject.BUS_ISSUE_NUMBER,
        "actor_login": subject.OWNER_LOGIN,
        "source_run_id": "29521901629",
        "source_engine_sha": "542907fa0cfae47addd6d777c1708ae62155aea4",
        "worker_name": "knowledge-engine-r3-8-29506217284",
        "previous_deletion_authorization_path": (
            "deletion_authorizations/m23-7/r3-8/"
            "knowledge-engine-r3-8-29506217284.json"
        ),
        "authority": dict(subject._EXPECTED_AUTHORITY),
    }
    value["authorization_sha256"] = subject.canonical_sha256(value)
    return value


def _event(body: str) -> dict:
    return {
        "action": "created",
        "issue": {"number": subject.BUS_ISSUE_NUMBER},
        "comment": {
            "body": body,
            "author_association": "OWNER",
            "user": {"login": subject.OWNER_LOGIN},
        },
    }


def test_parse_command_requires_canonical_single_line() -> None:
    payload = {
        "authorization_path": (
            "operator_authorizations/m23/r3-8/"
            "post-delete-recovery-29521901629.json"
        ),
        "expected_head": "a" * 40,
        "nonce": "b" * 64,
    }
    body = subject.COMMAND_PREFIX + subject.canonical_json(payload)
    assert subject.parse_command_body(body) == payload
    with pytest.raises(subject.OperatorCommandError):
        subject.parse_command_body(subject.COMMAND_PREFIX + json.dumps(payload, indent=2))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("action", "edited"),
        ("issue", {"number": 999}),
        (
            "comment",
            {
                "body": "x",
                "author_association": "OWNER",
                "user": {"login": "attacker"},
            },
        ),
    ],
)
def test_event_rejects_wrong_surface(field: str, value: object) -> None:
    event = _event("x")
    event[field] = value
    with pytest.raises(subject.OperatorCommandError):
        subject.validate_event(event)


def test_validate_authorization_binds_nonce_and_denies_mutation(tmp_path: Path) -> None:
    nonce = "c" * 64
    auth = _auth(nonce)
    path = tmp_path / "auth.json"
    path.write_text(subject.canonical_json(auth) + "\n", encoding="utf-8")
    assert subject.validate_authorization(path, expected_nonce=nonce)["command_type"] == (
        "r3_8_post_delete_recovery"
    )

    auth["authority"]["worker_delete_authorized"] = True
    unsigned = dict(auth)
    unsigned.pop("authorization_sha256")
    auth["authorization_sha256"] = subject.canonical_sha256(unsigned)
    path.write_text(subject.canonical_json(auth) + "\n", encoding="utf-8")
    with pytest.raises(subject.OperatorCommandError, match="authorization_boundary"):
        subject.validate_authorization(path, expected_nonce=nonce)


def test_validate_command_requires_exact_head_and_repo_bound_path(tmp_path: Path) -> None:
    nonce = "d" * 64
    rel = (
        "operator_authorizations/m23/r3-8/"
        "post-delete-recovery-29521901629.json"
    )
    auth_path = tmp_path / rel
    auth_path.parent.mkdir(parents=True)
    auth = _auth(nonce)
    auth_path.write_text(subject.canonical_json(auth) + "\n", encoding="utf-8")
    payload = {
        "authorization_path": rel,
        "expected_head": "e" * 40,
        "nonce": nonce,
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(
        subject.canonical_json(
            _event(subject.COMMAND_PREFIX + subject.canonical_json(payload))
        ),
        encoding="utf-8",
    )
    command, validated = subject.validate_command(
        event_path=event_path,
        repo_root=tmp_path,
        actual_head="e" * 40,
    )
    assert command["nonce"] == nonce
    assert validated["authorization_sha256"] == auth["authorization_sha256"]
    with pytest.raises(subject.OperatorCommandError, match="command_exact_head_mismatch"):
        subject.validate_command(
            event_path=event_path,
            repo_root=tmp_path,
            actual_head="f" * 40,
        )
