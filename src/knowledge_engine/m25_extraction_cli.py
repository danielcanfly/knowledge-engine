from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .m25_extraction_provider import RecordedResponseProvider, validate_model_policy
from .m25_extraction_worker import execute_extraction, prepare_extraction_request
from .storage import FileObjectStore


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write(output_dir: Path | None, name: str, value: dict[str, Any]) -> None:
    if output_dir is None:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / name).write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _contracts(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return _load(args.prompt_contract), _load(args.model_policy), _load(args.candidate_policy)


def _prepare(args: argparse.Namespace) -> int:
    store = FileObjectStore(args.store_root)
    prompt, model, candidate = _contracts(args)
    result = prepare_extraction_request(
        store,
        args.plan_id,
        prompt_contract=prompt,
        model_policy=model,
        candidate_policy=candidate,
    )
    _write(args.output_dir, "provider-request.json", result["request"])
    summary = {"request": result["request"], "request_key": result["request_key"]}
    print(json.dumps(summary, indent=2))
    return 0


def _replay(args: argparse.Namespace) -> int:
    store = FileObjectStore(args.store_root)
    prompt, model, candidate = _contracts(args)
    response_set = _load(args.recorded_responses)
    policy = validate_model_policy(model)
    providers = {
        route["provider_id"]: RecordedResponseProvider(
            provider_id=route["provider_id"],
            model_id=route["model_id"],
            model_revision=route["model_revision"],
            response_set=response_set,
        )
        for route in policy["routes"]
    }
    result = execute_extraction(
        store,
        args.plan_id,
        prompt_contract=prompt,
        model_policy=model,
        candidate_policy=candidate,
        providers=providers,
    )
    _write(args.output_dir, "provider-request.json", result["request"])
    _write(args.output_dir, "provider-response.json", result["response"])
    _write(args.output_dir, "candidate-packet.json", result["candidate_packet"])
    _write(args.output_dir, "extraction-receipt.json", result["receipt"])
    summary = {"receipt": result["receipt"], "receipt_key": result["receipt_key"]}
    print(json.dumps(summary, indent=2))
    return 0


def _status(args: argparse.Namespace) -> int:
    store = FileObjectStore(args.store_root)
    value = json.loads(store.get(args.receipt_key))
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="knowledge-m25-extraction")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("prepare", "replay"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--plan-id", required=True)
        sub.add_argument("--store-root", type=Path, required=True)
        sub.add_argument("--prompt-contract", type=Path, required=True)
        sub.add_argument("--model-policy", type=Path, required=True)
        sub.add_argument("--candidate-policy", type=Path, required=True)
        sub.add_argument("--output-dir", type=Path)
        if command == "replay":
            sub.add_argument("--recorded-responses", type=Path, required=True)
        sub.set_defaults(handler=_prepare if command == "prepare" else _replay)

    status = subparsers.add_parser("status")
    status.add_argument("--store-root", type=Path, required=True)
    status.add_argument("--receipt-key", required=True)
    status.set_defaults(handler=_status)

    args = parser.parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
