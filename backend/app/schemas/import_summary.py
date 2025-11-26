from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from ..services.import_summary import (
    AccuracyAssessment,
    ImportSummaryResult,
    P95Assessment,
    PerformanceSummary,
)


class ImportOperationPayload(BaseModel):
    status: str | None = Field(default=None, description="Outcome status for the import row.")
    metadata: Mapping[str, Any] | None = Field(
        default=None, description="Raw metadata captured for the imported request."
    )

    model_config = ConfigDict(populate_by_name=True)


class ImportSummaryRequest(BaseModel):
    method: str | None = Field(default=None, description="Method identifier associated with the import run.")
    operations: list[ImportOperationPayload] = Field(
        default_factory=list, description="Raw import operation data used for summarisation."
    )

    model_config = ConfigDict(populate_by_name=True)


class P95Summary(BaseModel):
    value_ms: float | None = Field(default=None, alias="valueMs")
    ci_low_ms: float | None = Field(default=None, alias="ciLowMs")
    ci_high_ms: float | None = Field(default=None, alias="ciHighMs")
    threshold_ms: float = Field(..., alias="thresholdMs")
    inference: Literal["meet-target", "above-target", "insufficient-data"]
    confidence_level: float = Field(..., alias="confidenceLevel")
    sample_size: int = Field(..., alias="sampleSize")
    considered_count: int = Field(..., alias="consideredCount")

    model_config = ConfigDict(populate_by_name=True)

    @classmethod
    def from_assessment(cls, assessment: P95Assessment) -> "P95Summary":
        return cls(
            valueMs=assessment.value_ms,
            ciLowMs=assessment.ci_low_ms,
            ciHighMs=assessment.ci_high_ms,
            thresholdMs=assessment.threshold_ms,
            inference=assessment.inference,
            confidenceLevel=assessment.confidence_level,
            sampleSize=assessment.sample_size,
            consideredCount=assessment.considered_count,
        )


class AccuracySummary(BaseModel):
    value: float | None
    threshold: float
    p_value: float | None = Field(default=None, alias="pValue")
    inference: Literal["meet-target", "below-target", "insufficient-data"]
    confidence_level: float = Field(..., alias="confidenceLevel")
    sample_size: int = Field(..., alias="sampleSize")
    success_count: int = Field(..., alias="successCount")

    model_config = ConfigDict(populate_by_name=True)

    @classmethod
    def from_assessment(cls, assessment: AccuracyAssessment) -> "AccuracySummary":
        return cls(
            value=assessment.value,
            threshold=assessment.threshold,
            pValue=assessment.p_value,
            inference=assessment.inference,
            confidenceLevel=assessment.confidence_level,
            sampleSize=assessment.sample_size,
            successCount=assessment.success_count,
        )


class PerformanceSummaryResponse(BaseModel):
    method: str | None
    request_count: int = Field(..., alias="requestCount")
    mean_response_ms: float | None = Field(default=None, alias="meanResponseMs")
    p95: P95Summary
    accuracy: AccuracySummary

    model_config = ConfigDict(populate_by_name=True)

    @classmethod
    def from_performance(cls, performance: PerformanceSummary) -> "PerformanceSummaryResponse":
        return cls(
            method=performance.method,
            requestCount=performance.request_count,
            meanResponseMs=performance.mean_response_ms,
            p95=P95Summary.from_assessment(performance.p95),
            accuracy=AccuracySummary.from_assessment(performance.accuracy),
        )


class UsageSummary(BaseModel):
    tokensIn: float | None = None
    tokensOut: float | None = None
    apiCalls: float | None = None
    cpuMs: float | None = None
    ramMbSeconds: float | None = None

    model_config = ConfigDict(populate_by_name=True)

    @classmethod
    def from_usage(cls, usage: Mapping[str, float]) -> "UsageSummary":
        return cls(**usage)


class ImportSummaryResponse(BaseModel):
    performance: PerformanceSummaryResponse
    usage: UsageSummary

    model_config = ConfigDict(populate_by_name=True)

    @classmethod
    def from_service_summary(cls, summary: ImportSummaryResult) -> "ImportSummaryResponse":
        return cls(
            performance=PerformanceSummaryResponse.from_performance(summary.performance),
            usage=UsageSummary.from_usage(summary.usage),
        )


__all__ = [
    "AccuracySummary",
    "ImportOperationPayload",
    "ImportSummaryRequest",
    "ImportSummaryResponse",
    "P95Summary",
    "PerformanceSummaryResponse",
    "UsageSummary",
]
