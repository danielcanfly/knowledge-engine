from scripts import m23_7_r3_8_remote_recovery_probe as base
from scripts import m23_7_r3_8_remote_recovery_probe_296367 as adapter


def test_adapter_adds_only_exact_authorized_identity() -> None:
    assert adapter.AUTHORIZED_RUN_ID == "29636761264"
    assert adapter.AUTHORIZED_ENGINE_SHA == (
        "fc1dca7186fa66db153489a90a7b369ca053db61"
    )
    assert adapter.AUTHORIZED_WORKER_NAME == "knowledge-engine-r3-8-29636761264"
    assert base.AUTHORIZED_RUNS[adapter.AUTHORIZED_RUN_ID] == {
        "engine_sha": adapter.AUTHORIZED_ENGINE_SHA,
        "worker_name": adapter.AUTHORIZED_WORKER_NAME,
    }
    assert adapter.main is not base.main


def test_adapter_preserves_read_only_probe_contract() -> None:
    assert base.CONFIRMATION_SUFFIX == "_SCHEMA_V2"
    assert base.SCHEMA_VERSION == "knowledge-engine-m23-7-r3-8-9-recovery-probe/v2"
