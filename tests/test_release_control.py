from knowledge_engine import promotion, release_control


def test_release_control_exports_the_canonical_controller() -> None:
    assert release_control.PromotionRequest is promotion.PromotionRequest
    assert release_control.PromotionResult is promotion.PromotionResult
    assert release_control.RollbackResult is promotion.RollbackResult
    assert release_control.promote_release is promotion.promote_release
    assert release_control.rollback_release is promotion.rollback_release
