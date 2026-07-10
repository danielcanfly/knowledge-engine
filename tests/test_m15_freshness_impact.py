import pytest

from knowledge_engine.m15_freshness_impact import (
    Audience,
    EdgeKind,
    FreshnessAuthority,
    ImpactEdge,
    ImpactGraph,
    ImpactNode,
    ImpactReason,
    ImpactState,
    NodeKind,
    evaluate_freshness_impact,
    finalize_freshness_report,
)

ENGINE = "34f8f14f6fa9d756a1767b1daecef9bb4757ad55"


def node(node_id: str, kind: NodeKind, audience: Audience = Audience.PUBLIC, **overrides: object) -> ImpactNode:
    values: dict[str, object] = {
        "node_id": node_id,
        "kind": kind,
        "audience": audience,
        "engine_sha": ENGINE,
        "expected_engine_sha": ENGINE,
    }
    values.update(overrides)
    return ImpactNode(**values)


def graph() -> ImpactGraph:
    return ImpactGraph(
        nodes=[
            node("fact:1", NodeKind.SOURCE_FACT),
            node("concept:1", NodeKind.CONCEPT),
            node("page:1", NodeKind.PAGE),
        ],
        edges=[
            ImpactEdge(source_id="fact:1", target_id="concept:1", kind=EdgeKind.DERIVES),
            ImpactEdge(source_id="concept:1", target_id="page:1", kind=EdgeKind.REFERENCES),
        ],
    )


def test_direct_and_transitive_propagation_is_deterministic() -> None:
    first = evaluate_freshness_impact(graph(), changed_node_ids=["fact:1"])
    second = evaluate_freshness_impact(graph(), changed_node_ids=["fact:1"])
    assert first.artifact_sha256 == second.artifact_sha256
    assert [(item.node_id, item.state) for item in first.impacts] == [
        ("concept:1", ImpactState.TRANSITIVE),
        ("fact:1", ImpactState.DIRECT),
        ("page:1", ImpactState.TRANSITIVE),
    ]


def test_audience_cannot_broaden_during_propagation() -> None:
    restricted = ImpactGraph(
        nodes=[
            node("fact:private", NodeKind.SOURCE_FACT, Audience.PRIVATE),
            node("page:public", NodeKind.PAGE, Audience.PUBLIC),
        ],
        edges=[ImpactEdge(source_id="fact:private", target_id="page:public", kind=EdgeKind.PUBLISHES)],
    )
    report = evaluate_freshness_impact(restricted, changed_node_ids=["fact:private"])
    blocked = [item for item in report.impacts if item.node_id == "page:public"]
    assert blocked[0].state == ImpactState.BLOCKED
    assert blocked[0].reason == ImpactReason.AUDIENCE_BOUNDARY


def test_cycle_is_explicit_and_fails_closed() -> None:
    cyclic = ImpactGraph(
        nodes=[node("fact:1", NodeKind.SOURCE_FACT), node("concept:1", NodeKind.CONCEPT)],
        edges=[
            ImpactEdge(source_id="fact:1", target_id="concept:1", kind=EdgeKind.DERIVES),
            ImpactEdge(source_id="concept:1", target_id="fact:1", kind=EdgeKind.REFERENCES),
        ],
    )
    report = evaluate_freshness_impact(cyclic, changed_node_ids=["fact:1"])
    assert report.cycle_detected is True
    assert any(item.reason == ImpactReason.CYCLE for item in report.impacts)


def test_depth_limit_is_visible_not_silently_dropped() -> None:
    report = evaluate_freshness_impact(graph(), changed_node_ids=["fact:1"], max_depth=1)
    assert report.truncated is True
    assert any(item.reason == ImpactReason.DEPTH_LIMIT for item in report.impacts)


def test_identity_drift_is_unknown() -> None:
    drifted = ImpactGraph(
        nodes=[node("fact:1", NodeKind.SOURCE_FACT, engine_sha="0" * 40)],
        edges=[],
    )
    report = evaluate_freshness_impact(drifted, changed_node_ids=["fact:1"])
    assert report.impacts[0].state == ImpactState.UNKNOWN
    assert report.impacts[0].reason == ImpactReason.IDENTITY_DRIFT


def test_duplicate_nodes_and_orphan_edges_are_rejected() -> None:
    with pytest.raises(ValueError):
        ImpactGraph(nodes=[node("fact:1", NodeKind.SOURCE_FACT), node("fact:1", NodeKind.CONCEPT)], edges=[])
    with pytest.raises(ValueError):
        ImpactGraph(
            nodes=[node("fact:1", NodeKind.SOURCE_FACT)],
            edges=[ImpactEdge(source_id="fact:1", target_id="missing", kind=EdgeKind.DERIVES)],
        )


def test_private_payload_fields_are_not_part_of_contract() -> None:
    with pytest.raises(ValueError):
        ImpactNode(
            node_id="fact:1",
            kind=NodeKind.SOURCE_FACT,
            audience=Audience.PRIVATE,
            engine_sha=ENGINE,
            expected_engine_sha=ENGINE,
            raw_text="private excerpt",
        )


def test_unknown_changed_node_and_unbounded_depth_are_rejected() -> None:
    with pytest.raises(ValueError):
        evaluate_freshness_impact(graph(), changed_node_ids=["missing"])
    with pytest.raises(ValueError):
        evaluate_freshness_impact(graph(), changed_node_ids=["fact:1"], max_depth=65)


def test_mutation_authority_is_rejected() -> None:
    with pytest.raises(ValueError):
        FreshnessAuthority(source_write_allowed=True)
    with pytest.raises(ValueError):
        FreshnessAuthority(candidate_creation_allowed=True)
    with pytest.raises(ValueError):
        FreshnessAuthority(production_write_allowed=True)


def test_report_is_tamper_evident() -> None:
    report = evaluate_freshness_impact(graph(), changed_node_ids=["fact:1"])
    tampered = report.model_copy(update={"truncated": True})
    with pytest.raises(ValueError):
        finalize_freshness_report(tampered)
