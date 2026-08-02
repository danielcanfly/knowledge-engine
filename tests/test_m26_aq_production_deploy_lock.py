from pathlib import Path


def test_production_deploy_is_serialized_and_release_scoped() -> None:
    deploy = Path("deploy/deploy.sh").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "/tmp/knowledge-engine-production-oracle.lock" in deploy
    assert "flock -x 9" in deploy
    assert "KNOWLEDGE_ENGINE_DEPLOY_LOCK_HELD" in deploy
    assert "git rev-parse HEAD" in deploy
    assert "M26_RUNTIME_ENV_FILE" in deploy
    assert ".env.runtime.${RELEASE_SHA}." in deploy
    assert "DEPLOYMENT_RUNTIME_SHA_MISMATCH" in deploy
    assert '${M26_RUNTIME_ENV_FILE:-.env}' in compose


def test_final_closure_holds_host_lock_through_live_collection() -> None:
    workflow = Path(
        ".github/workflows/m26-aq-final-production-closure.yml"
    ).read_text(encoding="utf-8")

    assert "group: m26-owner-production-oracle" in workflow
    assert "cancel-in-progress: false" in workflow
    assert 'lock_file="/tmp/knowledge-engine-production-oracle.lock"' in workflow
    assert "flock -x 9" in workflow
    assert "KNOWLEDGE_ENGINE_DEPLOY_LOCK_HELD=1" in workflow
    assert "container_runtime_sha" in workflow
    assert "local_health_sha" in workflow

    deploy_position = workflow.index("KNOWLEDGE_ENGINE_DEPLOY_LOCK_HELD=1")
    collect_position = workflow.index("scripts/m26_aq_final_closure.py collect")
    remote_end_position = workflow.index("          REMOTE", collect_position)
    assert deploy_position < collect_position < remote_end_position


def test_final_closure_does_not_mutate_shared_build_sha_before_deploy() -> None:
    workflow = Path(
        ".github/workflows/m26-aq-final-production-closure.yml"
    ).read_text(encoding="utf-8")

    assert "env_path = deploy_path / '.env'" not in workflow
    assert "out.append(f'M26_QUERY_BUILD_SHA={release_sha}')" not in workflow
