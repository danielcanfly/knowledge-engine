from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .m14_public_contracts import Audience

FeedbackType = Literal[
    "helpful",
    "unhelpful",
    "factual_correction",
    "citation_issue",
    "missing_coverage",
    "unsafe_or_inappropriate",
    "other",
]
FeedbackReceiptStatus = Literal["accepted", "duplicate"]

FEEDBACK_TYPES: tuple[FeedbackType, ...] = (
    "helpful",
    "unhelpful",
    "factual_correction",
    "citation_issue",
    "missing_coverage",
    "unsafe_or_inappropriate",
    "other",
)


class PublicFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    feedback_type: FeedbackType
    request_id: str = Field(pattern=r"^req_[0-9a-f]{32}$")
    release_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    audience: Audience = "public"
    message: str | None = Field(default=None, max_length=2000)
    citation_id: str | None = Field(
        default=None,
        pattern=r"^cite_[0-9a-f]{32}$",
    )
    source_card_id: str | None = Field(
        default=None,
        pattern=r"^card_[0-9a-f]{32}$",
    )
    concept_id: str | None = Field(default=None, min_length=1, max_length=512)
    section_id: str | None = Field(default=None, min_length=1, max_length=512)
    reference_uri: str | None = Field(default=None, min_length=1, max_length=2048)
    locale: Literal["en", "zh-TW"] = "en"

    @model_validator(mode="after")
    def validate_feedback_shape(self) -> PublicFeedbackRequest:
        requires_message = {
            "factual_correction",
            "citation_issue",
            "missing_coverage",
            "unsafe_or_inappropriate",
            "other",
        }
        if self.feedback_type in requires_message and not self.message:
            raise ValueError(f"message is required for {self.feedback_type}")
        if self.feedback_type == "citation_issue" and not (
            self.citation_id or self.source_card_id
        ):
            raise ValueError(
                "citation_issue requires citation_id or source_card_id"
            )
        if self.feedback_type == "factual_correction" and not (
            self.concept_id or self.section_id
        ):
            raise ValueError(
                "factual_correction requires concept_id or section_id"
            )
        if self.section_id and not self.concept_id:
            prefix = self.section_id.split("#", 1)[0]
            if not prefix:
                raise ValueError("section_id must include a concept identity")
        if (
            self.section_id
            and self.concept_id
            and not self.section_id.startswith(f"{self.concept_id}#")
        ):
            raise ValueError("section_id must belong to concept_id")
        return self


class PublicFeedbackReceipt(BaseModel):
    schema_version: str = "knowledge-engine-public-feedback-receipt/v1"
    feedback_id: str
    status: FeedbackReceiptStatus
    feedback_type: FeedbackType
    request_id: str
    release_id: str
    audience: Audience
    received_at: str
    curation_status: Literal["pending_review"] = "pending_review"
    privacy_redactions_applied: bool
    source_write_performed: bool = False
    production_write_performed: bool = False
