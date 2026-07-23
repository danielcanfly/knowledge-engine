from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
DOC = ROOT / "docs" / "architecture" / "m26" / "m26-2-retrieval-envelope.md"


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def bind_self(value: dict[str, Any]) -> dict[str, Any]:
    unsigned = dict(value)
    unsigned.pop("self_sha256", None)
    return {**unsigned, "self_sha256": digest(unsigned)}


def repair_corpus() -> None:
    path = PILOT / "m26-2-synthetic-corpus.json"
    corpus = load(path)
    source_digests: dict[str, str] = {}
    for source in corpus["source_documents"]:
        text = source["text"]
        content_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        source["content_sha256"] = content_sha
        source["snapshot_sha256"] = hashlib.sha256(
            ("snapshot:" + text).encode("utf-8")
        ).hexdigest()
        source_digests[source["source_id"]] = content_sha
    for record in corpus["provenance"]["records"]:
        for source in record["sources"]:
            source_id = source["source_id"]
            source["content_sha256"] = source_digests[source_id]
    write(path, bind_self(corpus))


def repair_self_bound_artifact(name: str) -> None:
    path = PILOT / name
    write(path, bind_self(load(path)))


def repair_registry() -> None:
    path = PILOT / "m26-2-contract-registry.json"
    registry = load(path)
    for contract in registry["contracts"]:
        contract_path = ROOT / contract["path"]
        contract["sha256"] = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    write(path, bind_self(registry))


def repair_doc() -> None:
    text = DOC.read_text(encoding="utf-8")
    text = text.replace("- required facets;\n", "- required facet coverage;\n")
    if "facet coverage" not in text.casefold():
        raise AssertionError("facet coverage wording is still absent")
    DOC.write_text(text, encoding="utf-8")


def verify() -> None:
    for name in (
        "m26-2-retrieval-policy.json",
        "m26-2-synthetic-corpus.json",
        "m26-2-benchmark-cases.json",
        "m26-2-contract-registry.json",
        "m26-2-entry-contract.json",
    ):
        value = load(PILOT / name)
        claimed = value.pop("self_sha256")
        if claimed != digest(value):
            raise AssertionError(f"self digest mismatch after repair: {name}")
    registry = load(PILOT / "m26-2-contract-registry.json")
    for contract in registry["contracts"]:
        actual = hashlib.sha256((ROOT / contract["path"]).read_bytes()).hexdigest()
        if contract["sha256"] != actual:
            raise AssertionError(f"registry mismatch: {contract['path']}")


def main() -> None:
    repair_corpus()
    for name in (
        "m26-2-retrieval-policy.json",
        "m26-2-benchmark-cases.json",
        "m26-2-entry-contract.json",
    ):
        repair_self_bound_artifact(name)
    repair_registry()
    repair_doc()
    verify()


if __name__ == "__main__":
    main()
