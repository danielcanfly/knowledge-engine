#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

SMOKE_QUESTIONS = (
    "How should I know if I need a workflow or an agent?",
    "How should teams choose an agent architecture before committing to a framework?",
    "What responsibilities belong in a complete agent harness architecture?",
)
VALID_TERMINALS = {"answer.completed", "answer.abstained"}


def _request(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 120,
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def _parse_sse(body: bytes) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in body.decode("utf-8", errors="replace").strip().split("\n\n"):
        data_lines = [line[6:] for line in block.splitlines() if line.startswith("data: ")]
        if data_lines:
            payload = json.loads("\n".join(data_lines))
            if isinstance(payload, dict):
                events.append(payload)
    return events


def _validate_health(payload: dict[str, Any], expected_sha: str) -> None:
    if payload.get("ok") is not True:
        raise ValueError("health payload does not contain boolean ok=true")
    if payload.get("status") != "ok":
        raise ValueError("health payload status is not ok")
    build_sha = str(payload.get("backend", {}).get("build_sha", ""))
    if build_sha != expected_sha:
        raise ValueError(f"health build SHA mismatch: {build_sha or '<empty>'}")


def _validate_transport(events: list[dict[str, Any]], expected_sha: str) -> dict[str, Any]:
    if not events:
        raise ValueError("answer stream has no SSE events")
    accepted = next((event for event in events if event.get("type") == "request.accepted"), None)
    if accepted is None:
        raise ValueError("answer stream has no request.accepted event")
    build_sha = str(accepted.get("runtime", {}).get("build_sha", ""))
    if build_sha != expected_sha:
        raise ValueError(f"answer stream build SHA mismatch: {build_sha or '<empty>'}")
    terminal = [event for event in events if str(event.get("type", "")).startswith("answer.")]
    if len(terminal) != 1 or terminal[0].get("type") not in VALID_TERMINALS:
        raise ValueError("answer stream did not produce exactly one valid terminal")
    if terminal[0] is not events[-1]:
        raise ValueError("answer stream contains events after its terminal")
    return terminal[0]


def _validate_usability(terminals: list[dict[str, Any]]) -> None:
    if len(terminals) < len(SMOKE_QUESTIONS):
        raise ValueError("product usability gate did not run the full fixed smoke set")
    completed = [event for event in terminals if event.get("type") == "answer.completed"]
    usable = [
        event
        for event in completed
        if str(event.get("answer", "")).strip()
        and isinstance(event.get("sources"), list)
        and event["sources"]
    ]
    if not usable:
        raise ValueError("fixed smoke set produced no completed answer with sources")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed M26 public cutover gate")
    parser.add_argument("--health-url", required=True)
    parser.add_argument("--answers-url", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--origin", default="https://danielcanfly.com")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()

    health_status, _, health_body = _request(args.health_url, timeout=args.timeout)
    if health_status != 200:
        raise ValueError(f"health HTTP status is {health_status}")
    health_payload = json.loads(health_body)
    _validate_health(health_payload, args.expected_sha)

    cors_status, cors_headers, cors_body = _request(
        args.answers_url,
        method="OPTIONS",
        headers={
            "Origin": args.origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, x-m26-owner-bypass",
        },
        timeout=args.timeout,
    )
    if cors_status != 204:
        raise ValueError(f"CORS preflight HTTP status is {cors_status}")
    allow_origin = next(
        (
            value
            for key, value in cors_headers.items()
            if key.casefold() == "access-control-allow-origin"
        ),
        "",
    )
    if allow_origin != args.origin:
        raise ValueError("CORS preflight did not return the requested production origin")
    allow_headers = next(
        (
            value.casefold()
            for key, value in cors_headers.items()
            if key.casefold() == "access-control-allow-headers"
        ),
        "",
    )
    required_headers = {"content-type", "x-m26-owner-bypass"}
    observed_headers = {item.strip() for item in allow_headers.split(",") if item.strip()}
    if not required_headers.issubset(observed_headers):
        raise ValueError("CORS preflight does not allow the live frontend request headers")

    outcomes: list[dict[str, Any]] = []
    terminals: list[dict[str, Any]] = []
    combined = health_body + b"\n" + cors_body
    for index, question in enumerate(SMOKE_QUESTIONS, start=1):
        answer_status, answer_headers, answer_body = _request(
            args.answers_url,
            method="POST",
            data=json.dumps({"question": question}).encode("utf-8"),
            headers={
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
                "Origin": args.origin,
            },
            timeout=args.timeout,
        )
        combined += b"\n" + answer_body
        if answer_status != 200:
            raise ValueError(f"smoke {index} answer HTTP status is {answer_status}")
        content_type = next(
            (
                value.casefold()
                for key, value in answer_headers.items()
                if key.casefold() == "content-type"
            ),
            "",
        )
        if not content_type.startswith("text/event-stream"):
            raise ValueError(f"smoke {index} response is not text/event-stream")
        terminal = _validate_transport(_parse_sse(answer_body), args.expected_sha)
        terminals.append(terminal)
        outcomes.append(
            {
                "answer_present": bool(str(terminal.get("answer", "")).strip()),
                "code": terminal.get("code"),
                "index": index,
                "source_count": (
                    len(terminal["sources"])
                    if isinstance(terminal.get("sources"), list)
                    else 0
                ),
                "terminal": terminal["type"],
            }
        )
    if b"m24-internal" in combined.lower():
        raise ValueError("forbidden legacy hostname is exposed by the public API")
    _validate_usability(terminals)

    print(
        json.dumps(
            {
                "answers_url": args.answers_url,
                "cors": "PASS",
                "expected_sha": args.expected_sha,
                "forbidden_hostname_absent": True,
                "health_url": args.health_url,
                "smoke_outcomes": outcomes,
                "smoke_set_size": len(SMOKE_QUESTIONS),
                "transport_gate": "PASS",
                "usability_gate": "PASS",
                "status": "PASS",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, json.JSONDecodeError, TimeoutError, urllib.error.URLError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc
