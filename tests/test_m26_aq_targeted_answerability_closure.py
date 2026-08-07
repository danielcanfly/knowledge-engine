from __future__ import annotations

from scripts.m26_aq_targeted_answerability_closure import (
    _is_non_blocking_group_a_telemetry_failure,
)


def test_missing_group_a_telemetry_is_non_blocking_only_after_product_passes() -> None:
    assert _is_non_blocking_group_a_telemetry_failure(
        group="A_original_reproduction",
        product_failures=[],
        telemetry_failures=["recovery:missing_group_a_telemetry"],
    )
    assert not _is_non_blocking_group_a_telemetry_failure(
        group="A_original_reproduction",
        product_failures=["answerable:empty_answer"],
        telemetry_failures=["recovery:missing_group_a_telemetry"],
    )
    assert not _is_non_blocking_group_a_telemetry_failure(
        group="B_new_variant",
        product_failures=[],
        telemetry_failures=["recovery:missing_group_a_telemetry"],
    )
    assert not _is_non_blocking_group_a_telemetry_failure(
        group="A_original_reproduction",
        product_failures=[],
        telemetry_failures=[
            "recovery:missing_group_a_telemetry",
            "recovery:question_alignment_not_checked",
        ],
    )
