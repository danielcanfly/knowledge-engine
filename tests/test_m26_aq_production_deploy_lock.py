from pathlib import Path

from knowledge_engine.m26_production_answer_bundle import FULL_PRODUCTION_QDRANT_COLLECTION


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
    assert "docker compose run --rm --no-deps" in deploy
    assert "</dev/null" in deploy
    assert '${M26_RUNTIME_ENV_FILE:-.env}' in compose


def test_production_deploy_discards_tracked_checkout_residue_before_exact_head() -> None:
    deploy = Path("deploy/deploy.sh").read_text(encoding="utf-8")

    reset_position = deploy.index("git reset --hard HEAD")
    checkout_position = deploy.index('git checkout --detach "$RELEASE_SHA"')
    assert reset_position < checkout_position
    # Do not use git clean here: server-side ignored/untracked configuration
    # such as .env must survive deployment.
    assert "git clean" not in deploy


def test_aq_deploy_bootstrap_comes_from_exact_head_not_shared_checkout() -> None:
    final_workflow = Path(
        ".github/workflows/m26-aq-final-production-closure.yml"
    ).read_text(encoding="utf-8")
    diagnostic_workflow = Path(
        ".github/workflows/m26-aq-query-runtime-diagnostic.yml"
    ).read_text(encoding="utf-8")
    remote = Path("scripts/m26_aq_remote_production_closure.sh").read_text(
        encoding="utf-8"
    )

    exact_head_path = "/tmp/m26-aq-exact-head-deploy.sh"
    assert f"oracle-knowledge:{exact_head_path}" in final_workflow
    assert f"oracle-knowledge:{exact_head_path}" in diagnostic_workflow
    assert "bash \"$AQ_EXACT_HEAD_DEPLOY_SCRIPT\"" in diagnostic_workflow
    assert (
        "AQ_EXACT_HEAD_DEPLOY_SCRIPT='/tmp/m26-aq-exact-head-deploy.sh'"
        in diagnostic_workflow
    )
    assert (
        "AQ_EXACT_HEAD_DEPLOY_SCRIPT='/tmp/m26-aq-exact-head-deploy.sh'"
        in final_workflow
    )
    expected_remote_binding = (
        'exact_head_deploy_script="${AQ_EXACT_HEAD_DEPLOY_SCRIPT:'
        '-/tmp/m26-aq-exact-head-deploy.sh}"'
    )
    assert expected_remote_binding in remote
    assert 'bash "$exact_head_deploy_script"' in remote
    assert 'bash "$DEPLOY_PATH/deploy/deploy.sh"' not in remote


def test_production_deploy_binds_accepted_qdrant_collection() -> None:
    deploy = Path("deploy/deploy.sh").read_text(encoding="utf-8")

    assert f'CANONICAL_M26_QDRANT_COLLECTION="{FULL_PRODUCTION_QDRANT_COLLECTION}"' in deploy
    assert 'out.append(f"M26_PA7_DENSE_COLLECTION={canonical_collection}")' in deploy
    assert 'stripped.startswith("M26_PA7_DENSE_COLLECTION=")' in deploy


def test_final_closure_holds_host_lock_through_live_collection() -> None:
    workflow = Path(
        ".github/workflows/m26-aq-final-production-closure.yml"
    ).read_text(encoding="utf-8")
    remote = Path("scripts/m26_aq_remote_production_closure.sh").read_text(
        encoding="utf-8"
    )

    # Workflow owns runner-level serialization and delegates the atomic remote
    # deploy/live-collection critical section to the canonical remote script.
    assert "group: m26-owner-production-oracle" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "scripts/m26_aq_remote_production_closure.sh" in workflow

    # The remote script owns the host lock and must retain it while both deploy
    # and live collection execute in the same shell process.
    assert 'lock_file="/tmp/knowledge-engine-production-oracle.lock"' in remote
    assert "flock -x 9" in remote
    assert "KNOWLEDGE_ENGINE_DEPLOY_LOCK_HELD=1" in remote
    assert "container_runtime_sha" in remote
    assert "local_health_sha" in remote

    lock_position = remote.index("flock -x 9")
    deploy_position = remote.index("KNOWLEDGE_ENGINE_DEPLOY_LOCK_HELD=1")
    collect_position = remote.index("scripts/m26_aq_final_closure.py collect")
    assert lock_position < deploy_position < collect_position


def test_final_closure_uses_canonical_named_tunnel_without_recording_it() -> None:
    workflow = Path(
        ".github/workflows/m26-aq-final-production-closure.yml"
    ).read_text(encoding="utf-8")
    remote = Path("scripts/m26_aq_remote_production_closure.sh").read_text(
        encoding="utf-8"
    )

    # Workflow owns credential/environment binding; the remote script owns
    # routed-origin construction and sanitized production identity evidence.
    assert "M26_QUERY_BACKEND_TUNNEL_HOSTNAME" in workflow
    assert "ROUTED_BACKEND_HOSTNAME='$M26_QUERY_BACKEND_TUNNEL_HOSTNAME'" in workflow
    assert 'routed_origin="https://${ROUTED_BACKEND_HOSTNAME}"' in remote
    assert "container_env M26_QUERY_BACKEND_ORIGIN" not in remote
    assert '"raw_routed_origin_recorded": False' in remote


def test_final_closure_does_not_mutate_shared_build_sha_before_deploy() -> None:
    workflow = Path(
        ".github/workflows/m26-aq-final-production-closure.yml"
    ).read_text(encoding="utf-8")

    assert "env_path = deploy_path / '.env'" not in workflow
    assert "out.append(f'M26_QUERY_BUILD_SHA={release_sha}')" not in workflow
