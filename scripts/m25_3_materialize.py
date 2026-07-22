from __future__ import annotations

import hashlib
import io
import tarfile
import zlib
from pathlib import Path

ARCHIVE_SHA256 = "e66422869497f17721992d740f904f024f7dbb24a88409d464786575ab188773"
ROOT = Path(__file__).resolve().parents[1]


def _extract() -> None:
    parts = sorted((ROOT / "scripts").glob("m25_3_payload_*.hex"))
    payload = "".join(path.read_text(encoding="utf-8").strip() for path in parts)
    raw = zlib.decompress(bytes.fromhex(payload))
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise SystemExit("M25.3 materialization payload digest mismatch")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for member in archive.getmembers():
            target = (ROOT / member.name).resolve()
            target.relative_to(ROOT.resolve())
            if not member.isfile():
                raise SystemExit(f"unsupported payload member: {member.name}")
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit(f"missing payload bytes: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())
    for path in parts:
        path.unlink()


def _replace(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected M25.3 repair anchor missing: {relative}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _apply_lint_fixes() -> None:
    _replace(
        "src/knowledge_engine/m25_extraction_inputs.py",
        "    ExtractionInput,\n    MAX_INPUTS,\n    MAX_INPUT_TEXT_CHARS,",
        "    MAX_INPUT_TEXT_CHARS,\n    MAX_INPUTS,\n    ExtractionInput,",
    )
    _replace(
        "src/knowledge_engine/m25_extraction_worker.py",
        "    EXTRACTION_RECEIPT_SCHEMA,\n"
        "    MAX_CANDIDATES,\n"
        "    MAX_CANDIDATES_PER_INPUT,\n"
        "    MAX_EVIDENCE_SPANS,\n"
        "    MODEL_POLICY_SCHEMA,\n"
        "    M25_2_ACCEPTED_STATUS,\n"
        "    M25_3_ENGINE_BASE_SHA,",
        "    EXTRACTION_RECEIPT_SCHEMA,\n"
        "    FOUNDATION_SHA,\n"
        "    M25_2_ACCEPTED_STATUS,\n"
        "    M25_3_ENGINE_BASE_SHA,\n"
        "    MAX_CANDIDATES,\n"
        "    MAX_CANDIDATES_PER_INPUT,\n"
        "    MAX_EVIDENCE_SPANS,",
    )
    _replace(
        "src/knowledge_engine/m25_extraction_worker.py",
        "    SOURCE_SHA,\n    FOUNDATION_SHA,\n    ExtractionProvider,",
        "    SOURCE_SHA,\n    ExtractionProvider,",
    )
    test_path = "tests/test_m25_3_extraction_worker.py"
    _replace(
        test_path,
        '    bad = proposal(); bad["evidence"][0]["excerpt_sha256"] = "0" * 64\n',
        '    bad = proposal()\n    bad["evidence"][0]["excerpt_sha256"] = "0" * 64\n',
    )
    _replace(
        test_path,
        '    bad = proposal(); bad["canonical_knowledge"] = True\n',
        '    bad = proposal()\n    bad["canonical_knowledge"] = True\n',
    )
    _replace(
        test_path,
        "        self.calls = 0; self.final_response = final_response\n",
        "        self.calls = 0\n        self.final_response = final_response\n",
    )
    _replace(
        test_path,
        "    prepared = prepare_extraction_request(store, PLAN_ID, prompt_contract=prompt_contract(), model_policy=model_policy(), candidate_policy=candidate_policy())\n"
        "    provider = RecordedResponseProvider(provider_id=\"recorded-primary\", model_id=\"fixture-model\", model_revision=\"fixture-v1\", response_set=response_set(response(\"f\" * 64)))\n",
        "    prepare_extraction_request(\n"
        "        store,\n"
        "        PLAN_ID,\n"
        "        prompt_contract=prompt_contract(),\n"
        "        model_policy=model_policy(),\n"
        "        candidate_policy=candidate_policy(),\n"
        "    )\n"
        "    provider = RecordedResponseProvider(provider_id=\"recorded-primary\", model_id=\"fixture-model\", model_revision=\"fixture-v1\", response_set=response_set(response(\"f\" * 64)))\n",
    )
    _replace(
        test_path,
        '    policy = model_policy(); unsigned=dict(policy); unsigned.pop("model_policy_sha256"); unsigned["live_provider_calls_permitted"] = True; policy=signed(unsigned,"model_policy_sha256")\n',
        '    policy = model_policy()\n'
        '    unsigned = dict(policy)\n'
        '    unsigned.pop("model_policy_sha256")\n'
        '    unsigned["live_provider_calls_permitted"] = True\n'
        '    policy = signed(unsigned, "model_policy_sha256")\n',
    )
    _replace(
        test_path,
        '        "plan_sha256": PLAN_SHA,\n    }\n    m21_checkpoint = {',
        '    }\n    m21_plan["plan_sha256"] = _digest(m21_plan)\n    m21_checkpoint = {',
    )
    _replace(
        test_path,
        '        "plan_sha256": PLAN_SHA,\n        "identity": m21_plan["identity"],',
        '        "plan_sha256": m21_plan["plan_sha256"],\n        "identity": m21_plan["identity"],',
    )
    _replace(
        test_path,
        '        "checkpoint_sha256": CHECKPOINT_SHA,\n    }\n    bundle = {',
        '    }\n    m21_checkpoint["checkpoint_sha256"] = _digest(m21_checkpoint)\n    bundle = {',
    )
    _replace(
        "docs/architecture/m25/m25-2-intake-orchestrator.md",
        "M25.2 permits immutable intake writes and candidate-only admission references. It performs no live\n"
        "extraction, model call, review decision, canonical adoption, Source mutation, Foundation mutation,",
        "M25.2 permits immutable intake writes and candidate-only admission references. It performs no live extraction,\n"
        "model call, review decision, canonical adoption, Source mutation, Foundation mutation,",
    )
    _replace(
        ".github/workflows/m25-3-extraction-worker.yml",
        "          python -m pytest -q\n",
        "          PYTHONPATH=tests python -m pytest -q\n",
    )


def _patch_pyproject() -> None:
    path = ROOT / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    entry = 'knowledge-m25-extraction = "knowledge_engine.m25_extraction_cli:main"'
    if entry not in text:
        anchor = 'knowledge-m25-admission = "knowledge_engine.m25_intake_orchestrator_cli:main"'
        if anchor not in text:
            raise SystemExit("M25.2 CLI anchor missing from pyproject.toml")
        text = text.replace(anchor, anchor + "\n" + entry)
    ignore = '"tests/test_m25_3_extraction_worker.py" = ["E501"]'
    if ignore not in text:
        anchor = '"tests/test_m23_6_3_first_pilot_upsert.py" = ["E501", "I001"]'
        if anchor not in text:
            raise SystemExit("ruff ignore anchor missing from pyproject.toml")
        text = text.replace(anchor, anchor + "\n" + ignore)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    _extract()
    _apply_lint_fixes()
    _patch_pyproject()
    (ROOT / ".github" / "workflows" / "m25-3-bootstrap.yml").unlink()
    Path(__file__).unlink()

if __name__ == "__main__":
    main()
