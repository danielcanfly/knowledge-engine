from pathlib import Path

from knowledge_engine.m26_production_answer_bundle import FULL_PRODUCTION_QDRANT_COLLECTION

BACKEND_REDEPLOY_WORKFLOW = Path(
    ".github/workflows/m26-pa7-explicit-backend-redeploy.yml"
)
PROMOTION_WORKFLOW = Path(
    ".github/workflows/m26-pa-7-production-promotion-closure.yml"
)


def test_production_deploy_is_serialized_and_release_scoped() -> None:
    deploy = Path("deploy/deploy.sh").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "/tmp/knowledge-engine-production-oracle.lock" in deploy
    assert "flock -x 9" in deploy
    assert "KNOWLEDGE_ENGINE_DEPLOY_LOCK_HELD" in deploy
    assert "git rev-parse HEAD" in deploy
    assert "M26_RUNTIME_ENV_FILE" in deploy
    assert ".env.runtime." in deploy
    assert "DEPLOYMENT_RUNTIME_SHA_MISMATCH" in deploy
    assert "docker compose run --rm --no-deps" in deploy
    assert "</dev/null" in deploy
    assert "M26_RUNTIME_ENV_FILE:-.env" in compose


def test_production_deploy_discards_tracked_checkout_residue_before_exact_head() -> None:
    deploy = Path("deploy/deploy.sh").read_text(encoding="utf-8")

    reset_position = deploy.index("git reset --hard HEAD")
    checkout_position = deploy.index('git checkout --detach "$RELEASE_SHA"')
    assert reset_position < checkout_position
    assert "git clean" not in deploy


def test_backend_redeploy_binds_exact_checked_out_sha_to_deploy_script() -> None:
    workflow = BACKEND_REDEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert "EXPECTED_DEPLOY_SHA:" in workflow
    assert "github.event.pull_request.head.sha || github.sha" in workflow
    assert 'test "$(git rev-parse HEAD)" = "$EXPECTED_DEPLOY_SHA"' in workflow
    assert "scripts/configure_oracle_ssh.sh" in workflow
    assert "RELEASE_SHA='$EXPECTED_DEPLOY_SHA'" in workflow
    assert 'scp deploy/deploy.sh "oracle-knowledge:$remote_runner"' in workflow
    assert 'bash "$REMOTE_RUNNER"' in workflow
    assert "bash '$ORACLE_VM_DEPLOY_PATH/deploy/deploy.sh'" not in workflow


def test_production_deploy_binds_accepted_qdrant_collection() -> None:
    deploy = Path("deploy/deploy.sh").read_text(encoding="utf-8")

    assert (
        f'CANONICAL_M26_QDRANT_COLLECTION="{FULL_PRODUCTION_QDRANT_COLLECTION}"'
        in deploy
    )
    assert 'out.append(f"M26_PA7_DENSE_COLLECTION={canonical_collection}")' in deploy
    assert 'stripped.startswith("M26_PA7_DENSE_COLLECTION=")' in deploy


def test_pa7_promotion_defaults_to_accepted_qdrant_collection() -> None:
    promotion = PROMOTION_WORKFLOW.read_text(encoding="utf-8")

    assert "M26_PA7_DENSE_COLLECTION:" in promotion
    assert FULL_PRODUCTION_QDRANT_COLLECTION in promotion


def test_backend_redeploy_serializes_runner_and_host_deployment() -> None:
    workflow = BACKEND_REDEPLOY_WORKFLOW.read_text(encoding="utf-8")
    deploy = Path("deploy/deploy.sh").read_text(encoding="utf-8")

    assert "group: m26-pa7-oracle-backend-production-" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "needs: verify" in workflow
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in workflow
    assert "/tmp/knowledge-engine-production-oracle.lock" in deploy
    assert 'exec 9>"$DEPLOY_LOCK_FILE"' in deploy
    assert "flock -x 9" in deploy
    assert "deploy_locked" in deploy


def test_backend_redeploy_smoke_evidence_is_sanitized_and_fail_closed() -> None:
    workflow = BACKEND_REDEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert '"protected_knowledge_mutations": 0' in workflow
    assert '"raw_answer_text_recorded": False' in workflow
    assert '"raw_token_recorded": False' in workflow
    assert '"raw_r2_endpoint_recorded": False' in workflow
    assert "backend-owner-smoke.json" in workflow
    assert "Fail if backend smoke failed" in workflow
    assert "if smoke.get('status') != 'pass':" in workflow


def test_backend_redeploy_does_not_mutate_shared_build_sha_before_deploy() -> None:
    workflow = BACKEND_REDEPLOY_WORKFLOW.read_text(encoding="utf-8")
    deploy = Path("deploy/deploy.sh").read_text(encoding="utf-8")

    assert "env_path = deploy_path / '.env'" not in workflow
    assert "tmp.replace(env_path)" not in workflow
    assert "output.append(f'M26_QUERY_BUILD_SHA={release_sha}')" not in workflow

    assert 'BASE_ENV="$DEPLOY_PATH/.env"' in deploy
    assert 'RUNTIME_ENV="$runtime_env"' in deploy
    assert 'out.append(f"M26_QUERY_BUILD_SHA={release_sha}")' in deploy
    assert 'out.append(f"M26_PA7_DENSE_COLLECTION={canonical_collection}")' in deploy
