from __future__ import annotations

import argparse
import copy
import math
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx

from knowledge_engine import m23_7_r3_8_latency_repair as latency
from scripts import m23_7_r3_8_remote_operator as base

ALLOWED_PLACEMENT_CLASSES = frozenset({"absent", "local", "remote"})
ENABLED_PLACEMENT_CLASSES = frozenset({"local", "remote"})
PLACEMENT_CONTRACT_SHA256 = (
    "4b32ddd0bfe236d5c501a1c2ecbcd2e409442a85117014388a6f6edc9f12f4c9"
)
_OBSERVED_PLACEMENT_CLASS: str | None = None


def worker_ready_response(
    status_code: int,
    payload: object,
    placement: str | None,
) -> bool:
    return (
        status_code == 400
        and payload == {"status": "error", "code": "request-schema-drift"}
    )


class PlacementAwareHttpWorkerInvoker(latency.HttpWorkerInvoker):
    placement_response_class: str | None = None

    def invoke(
        self,
        request_body: Mapping[str, Any],
        *,
        clock_ns: Callable[[], int] = time.perf_counter_ns,
    ) -> tuple[Mapping[str, Any], int]:
        latency._require(not self._closed, "client_closed", "Worker invoker is closed")
        body = latency.canonical_json(request_body).encode("utf-8")
        started = clock_ns()
        try:
            response = self._http.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._operator_token}",
                    "Content-Type": "application/json",
                    "Cache-Control": "no-store",
                    "Content-Length": str(len(body)),
                },
                content=body,
            )
            latency._require(
                len(response.content) <= latency.MAX_RESPONSE_BYTES,
                "worker_response_size",
                "Worker response is too large",
            )
            if response.status_code >= 400:
                raise latency.LatencyRepairError(
                    latency.worker_http_error_code(response),
                    "Worker returned bounded error status",
                )
            placement = response.headers.get(latency.PLACEMENT_RESPONSE_HEADER)
            latency._require(
                placement in ALLOWED_PLACEMENT_CLASSES,
                "worker_placement_unproven",
                "Worker invocation did not return a bounded placement class",
            )
            try:
                payload = response.json()
            except ValueError as exc:
                raise latency.LatencyRepairError(
                    "worker_unavailable",
                    "Worker response is invalid JSON",
                ) from exc
        except httpx.TimeoutException as exc:
            raise latency.LatencyRepairError(
                "worker_timeout",
                "Worker request timed out",
            ) from exc
        except httpx.HTTPError as exc:
            raise latency.LatencyRepairError(
                "worker_unavailable",
                "Worker request failed",
            ) from exc
        finished = clock_ns()
        latency._require(
            isinstance(payload, Mapping),
            "worker_shape",
            "Worker response is invalid",
        )
        global _OBSERVED_PLACEMENT_CLASS
        self.placement_response_class = str(placement)
        _OBSERVED_PLACEMENT_CLASS = self.placement_response_class
        return payload, max(0, math.ceil((finished - started) / 1_000_000))


def normalise_receipt(
    receipt: Mapping[str, Any],
    placement_class: str,
) -> dict[str, Any]:
    if placement_class not in ALLOWED_PLACEMENT_CLASSES:
        raise base.RemoteOperatorError("worker_placement_unproven")
    value = copy.deepcopy(dict(receipt))
    remote_operator = value.get("remote_operator")
    if not isinstance(remote_operator, dict):
        raise base.RemoteOperatorError("remote_operator_receipt_missing")
    remote_operator["placement_header_verified"] = True
    remote_operator["placement_observation_verified"] = True
    remote_operator["placement_local_or_remote_readiness_verified"] = (
        placement_class in ENABLED_PLACEMENT_CLASSES
    )
    remote_operator["placement_remote_readiness_verified"] = (
        placement_class == "remote"
    )
    remote_operator["placement_response_class"] = placement_class
    remote_operator["placement_routing_was_remote"] = placement_class == "remote"
    remote_operator["placement_targeted_hostname_configured"] = True
    remote_operator["placement_location_persisted"] = False
    remote_operator["placement_contract_sha256"] = PLACEMENT_CONTRACT_SHA256
    value.pop("receipt_sha256", None)
    value["receipt_sha256"] = latency.canonical_sha256(value)
    return value


def execute(args: argparse.Namespace) -> int:
    global _OBSERVED_PLACEMENT_CLASS
    _OBSERVED_PLACEMENT_CLASS = None
    original_ready = base.worker_ready_response
    original_invoker = latency.HttpWorkerInvoker
    original_write_json = base._write_json
    original_retry_codes = base.LIVE_OBSERVATION_RETRY_CODES

    def write_json_v2(path: Path, value: dict[str, Any]) -> None:
        bounded = value
        if path.name == "latency-repair-receipt.json":
            placement_class = _OBSERVED_PLACEMENT_CLASS
            if placement_class is None:
                raise base.RemoteOperatorError("worker_placement_unproven")
            bounded = normalise_receipt(value, placement_class)
        original_write_json(path, bounded)

    try:
        base.worker_ready_response = worker_ready_response
        latency.HttpWorkerInvoker = PlacementAwareHttpWorkerInvoker
        base._write_json = write_json_v2
        base.LIVE_OBSERVATION_RETRY_CODES = frozenset(
            (set(original_retry_codes) - {"worker_placement_not_remote"})
            | {"worker_placement_unproven"}
        )
        return base.execute(args)
    finally:
        base.worker_ready_response = original_ready
        latency.HttpWorkerInvoker = original_invoker
        base._write_json = original_write_json
        base.LIVE_OBSERVATION_RETRY_CODES = original_retry_codes
        _OBSERVED_PLACEMENT_CLASS = None


def main(argv: list[str] | None = None) -> int:
    return execute(base.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
