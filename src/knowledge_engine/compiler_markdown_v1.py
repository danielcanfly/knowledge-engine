from __future__ import annotations

import re
from typing import Any

from .compiler_contract_v1 import CompilerFailure
from .intake_v1 import canonical_json_bytes
from .storage import sha256_bytes

HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
LIST_RE = re.compile(r"^[ \t]*(?:[-+*]|\d+[.)])[ \t]+(.+?)$")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
DATE_RE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
DEF_RE = re.compile(r"^([^:\n—]{1,100})\s*(?::|—)\s+(.+)$")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})([^\n]*)$")


def _lines(text: str) -> list[tuple[str, int, int]]:
    values = []
    offset = 0
    for line in text.splitlines(keepends=True):
        values.append((line, offset, offset + len(line)))
        offset += len(line)
    return values


def raw_blocks(text: str, limit: int) -> list[dict[str, Any]]:
    lines = _lines(text)
    blocks: list[dict[str, Any]] = []
    index = 0

    def add(
        kind: str,
        start: int,
        end: int,
        value: str,
        level: int | None = None,
        parent: int | None = None,
    ) -> int:
        if len(blocks) >= limit:
            raise CompilerFailure(
                "BLOCK_LIMIT_EXCEEDED", "structure", "block limit exceeded"
            )
        blocks.append(
            {
                "ordinal": len(blocks),
                "kind": kind,
                "start": start,
                "end": end,
                "text": value,
                "level": level,
                "parent": parent,
            }
        )
        return len(blocks) - 1

    if lines and lines[0][0].rstrip("\n") == "---":
        close = next(
            (i for i in range(1, len(lines)) if lines[i][0].rstrip("\n") == "---"),
            None,
        )
        if close is not None:
            add(
                "metadata",
                lines[0][1],
                lines[close][2],
                text[lines[0][1] : lines[close][2]],
            )
            index = close + 1

    while index < len(lines):
        line, start, end = lines[index]
        stripped = line.rstrip("\n")
        if not stripped.strip():
            index += 1
            continue
        fence = FENCE_RE.match(stripped)
        if fence:
            marker = fence.group(1)
            finish = index + 1
            while finish < len(lines) and not lines[finish][0].lstrip().startswith(marker):
                finish += 1
            if finish < len(lines):
                finish += 1
            stop = lines[finish - 1][2]
            add("code", start, stop, text[start:stop])
            index = finish
            continue
        heading = HEADING_RE.match(stripped)
        if heading:
            add("heading", start, end, heading.group(2), len(heading.group(1)))
            index += 1
            continue
        item = LIST_RE.match(stripped)
        if item:
            parent = add("list", start, end, text[start:end])
            while index < len(lines):
                current = LIST_RE.match(lines[index][0].rstrip("\n"))
                if not current:
                    break
                add(
                    "list_item",
                    lines[index][1],
                    lines[index][2],
                    current.group(1),
                    parent=parent,
                )
                blocks[parent]["end"] = lines[index][2]
                blocks[parent]["text"] = text[blocks[parent]["start"] : lines[index][2]]
                index += 1
            continue
        if stripped.lstrip().startswith(">"):
            finish = index + 1
            while finish < len(lines) and lines[finish][0].lstrip().startswith(">"):
                finish += 1
            stop = lines[finish - 1][2]
            value = "\n".join(
                part[0].lstrip()[1:].lstrip().rstrip("\n")
                for part in lines[index:finish]
            )
            add("quote", start, stop, value)
            index = finish
            continue
        finish = index + 1
        while finish < len(lines):
            probe = lines[finish][0].rstrip("\n")
            if not probe.strip() or HEADING_RE.match(probe) or LIST_RE.match(probe):
                break
            if FENCE_RE.match(probe) or probe.lstrip().startswith(">"):
                break
            finish += 1
        stop = lines[finish - 1][2]
        add("paragraph", start, stop, text[start:stop].strip())
        index = finish
    return blocks


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def materialize(
    run_id: str,
    text: str,
    raw: list[dict[str, Any]],
    snapshot_id: str,
    derivative_id: str,
    normalized_hash: str,
    audience: str,
):
    block_ids: dict[int, str] = {}
    maps = []
    blocks = []
    for value in raw:
        quote = text[value["start"] : value["end"]]
        segment = {
            "segment_ordinal": 0,
            "normalized_start_char": value["start"],
            "normalized_end_char": value["end"],
            "normalized_start_line": _line_number(text, value["start"]),
            "normalized_end_line": _line_number(
                text, max(value["start"], value["end"] - 1)
            ),
            "source_start_byte": None,
            "source_end_byte": None,
            "quote": quote,
            "quote_sha256": sha256_bytes(quote.encode()),
        }
        map_payload = {
            "compiler_run_id": run_id,
            "snapshot_id": snapshot_id,
            "derivative_id": derivative_id,
            "normalized_sha256": normalized_hash,
            "segments": [segment],
        }
        map_id = "smap_" + sha256_bytes(canonical_json_bytes(map_payload))
        maps.append(
            {
                "schema_version": "knowledge-compiler-source-map/v1",
                "source_map_id": map_id,
                **map_payload,
            }
        )
        block_payload = {
            "compiler_run_id": run_id,
            "ordinal": value["ordinal"],
            "kind": value["kind"],
            "level": value["level"],
            "text": value["text"],
            "source_map_ids": [map_id],
            "effective_audience": audience,
            "canonical_write_permitted": False,
        }
        block_id = "block_" + sha256_bytes(canonical_json_bytes(block_payload))
        block_ids[value["ordinal"]] = block_id
        blocks.append(
            {
                "schema_version": "knowledge-compiler-structured-block/v1",
                "block_id": block_id,
                **block_payload,
                "parent_block_id": None,
            }
        )
    for value, block in zip(raw, blocks, strict=True):
        if value["parent"] is not None:
            block["parent_block_id"] = block_ids[value["parent"]]
    return blocks, maps


def candidates(
    run_id: str,
    blocks: list[dict[str, Any]],
    maps: list[dict[str, Any]],
    audience: str,
    limit: int,
) -> list[dict[str, Any]]:
    map_by_id = {item["source_map_id"]: item for item in maps}
    output: list[dict[str, Any]] = []

    def add(
        kind: str,
        value: str,
        block: dict[str, Any],
        method: str,
        confidence: float,
    ) -> None:
        if len(output) >= limit:
            raise CompilerFailure(
                "CANDIDATE_LIMIT_EXCEEDED", "extract", "candidate limit exceeded"
            )
        map_id = block["source_map_ids"][0]
        evidence = [
            {
                "block_id": block["block_id"],
                "source_map_id": map_id,
                "quote_sha256": map_by_id[map_id]["segments"][0]["quote_sha256"],
            }
        ]
        payload = {
            "compiler_run_id": run_id,
            "candidate_type": kind,
            "value": value,
            "evidence_refs": evidence,
            "extraction_method": method,
        }
        candidate_id = "cand_" + sha256_bytes(canonical_json_bytes(payload))
        output.append(
            {
                "schema_version": "knowledge-compiler-extraction-candidate/v1",
                "candidate_id": candidate_id,
                **payload,
                "normalized_value": value.strip(),
                "subject_candidate_ids": [],
                "object_candidate_ids": [],
                "confidence": confidence,
                "effective_audience": audience,
                "status": "candidate",
                "rejection_reason": None,
                "synthesis_eligible": True,
                "canonical_write_permitted": False,
            }
        )

    for block in blocks:
        value = block["text"].strip()
        if block["kind"] == "heading" and value:
            add("concept", value, block, "heading", 1.0)
        if block["kind"] in {"paragraph", "list_item", "quote"} and value:
            add("claim", value, block, "bounded-text-block", 0.7)
            if DEF_RE.match(value):
                add("definition", value, block, "explicit-definition", 0.9)
        for match in LINK_RE.finditer(value):
            add("citation", match.group(2), block, "markdown-link", 1.0)
        for match in DATE_RE.finditer(value):
            add("date", match.group(0), block, "iso-date", 1.0)
    return output
