from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

BASE = "a98030daf0fd7760c38fa62b46683df63197dc9b"


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"replacement count for {path}: {count}\n{old}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def append_once(path: str, marker: str, addition: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if marker in text:
        return
    target.write_text(text.rstrip() + "\n\n" + addition.strip() + "\n", encoding="utf-8")


# Worker: expose only a bounded placement class, never the IATA code.
worker = "workers/m23-7-r3-8-latency-repair/worker.mjs"
replace_once(
    worker,
    'const ROUTE = "/v1/m23-7-r3-8/observe";\n',
    'const ROUTE = "/v1/m23-7-r3-8/observe";\n'
    'const PLACEMENT_RESPONSE_HEADER = "X-M23-R3-8-Placement";\n',
)
replace_once(
    worker,
    "class WorkerFailure extends Error {\n",
    "function placementClass(request) {\n"
    "  const value = request.headers.get(\"cf-placement\") || \"\";\n"
    "  if (/^remote-[A-Z]{3}$/.test(value)) return \"remote\";\n"
    "  if (/^local-[A-Z]{3}$/.test(value)) return \"local\";\n"
    "  return \"absent\";\n"
    "}\n\n"
    "function placementResponseHeaders(request) {\n"
    "  return { [PLACEMENT_RESPONSE_HEADER]: placementClass(request) };\n"
    "}\n\n"
    "class WorkerFailure extends Error {\n",
)
replace_once(
    worker,
    "async function handleRequest(request, env) {\n  try {\n",
    "async function handleRequest(request, env) {\n"
    "  const placementHeaders = placementResponseHeaders(request);\n"
    "  try {\n",
)
replace_once(
    worker,
    '    return responseJson(result, 200, {\n      "Server-Timing":\n',
    '    return responseJson(result, 200, {\n      ...placementHeaders,\n      "Server-Timing":\n',
)
replace_once(
    worker,
    '      return responseJson({ status: "error", code: error.code }, error.status);\n',
    '      return responseJson(\n'
    '        { status: "error", code: error.code },\n'
    '        error.status,\n'
    '        placementHeaders,\n'
    '      );\n',
)
replace_once(
    worker,
    '    return responseJson({ status: "error", code: "internal-failure" }, 500);\n',
    '    return responseJson(\n'
    '      { status: "error", code: "internal-failure" },\n'
    '      500,\n'
    '      placementHeaders,\n'
    '    );\n',
)
replace_once(
    worker,
    "  parseEmbeddingRows,\n  timingSafeEqualText,\n",
    "  parseEmbeddingRows,\n  placementClass,\n  timingSafeEqualText,\n",
)

# Worker tests: verify sanitization and propagation on bounded error responses.
worker_test = "workers/m23-7-r3-8-latency-repair/worker.test.mjs"
replace_once(
    worker_test,
    "  handleRequest,\n  validateBody,\n",
    "  handleRequest,\n  placementClass,\n  validateBody,\n",
)
replace_once(
    worker_test,
    "test(\"validateBody accepts exactly 24 unique digests\", async () => {\n",
    "test(\"placement header is reduced to a bounded class\", () => {\n"
    "  for (const [value, expected] of [\n"
    "    [\"remote-LHR\", \"remote\"],\n"
    "    [\"local-EWR\", \"local\"],\n"
    "    [\"remote-lhr\", \"absent\"],\n"
    "    [\"remote-LONDON\", \"absent\"],\n"
    "    [null, \"absent\"],\n"
    "  ]) {\n"
    "    const headers = value === null ? {} : { \"cf-placement\": value };\n"
    "    const request = new Request(\"https://worker.example/\", { headers });\n"
    "    assert.equal(placementClass(request), expected);\n"
    "  }\n"
    "});\n\n"
    "test(\"validateBody accepts exactly 24 unique digests\", async () => {\n",
)
replace_once(
    worker_test,
    '      "Content-Length": String(Buffer.byteLength(raw)),\n    },\n    body: raw,\n  });\n  const response = await handleRequest(request, {\n',
    '      "Content-Length": String(Buffer.byteLength(raw)),\n'
    '      "cf-placement": "remote-LHR",\n'
    '    },\n'
    '    body: raw,\n'
    '  });\n'
    '  const response = await handleRequest(request, {\n',
)
replace_once(
    worker_test,
    "  assert.equal(response.status, 401);\n  assert.deepEqual(await response.json(), {\n",
    "  assert.equal(response.status, 401);\n"
    "  assert.equal(response.headers.get(\"X-M23-R3-8-Placement\"), \"remote\");\n"
    "  assert.deepEqual(await response.json(), {\n",
)

# Core invoker: successful observations must independently prove remote placement.
latency = "src/knowledge_engine/m23_7_r3_8_latency_repair.py"
replace_once(
    latency,
    '_WORKER_ERROR_CODE = re.compile(r"^[a-z0-9-]{1,80}$")\n',
    '_WORKER_ERROR_CODE = re.compile(r"^[a-z0-9-]{1,80}$")\n'
    'PLACEMENT_RESPONSE_HEADER = "X-M23-R3-8-Placement"\n',
)
replace_once(
    latency,
    "            if response.status_code >= 400:\n"
    "                raise LatencyRepairError(\n"
    "                    worker_http_error_code(response),\n"
    "                    \"Worker returned bounded error status\",\n"
    "                )\n"
    "            try:\n",
    "            if response.status_code >= 400:\n"
    "                raise LatencyRepairError(\n"
    "                    worker_http_error_code(response),\n"
    "                    \"Worker returned bounded error status\",\n"
    "                )\n"
    "            _require(\n"
    "                response.headers.get(PLACEMENT_RESPONSE_HEADER) == \"remote\",\n"
    "                \"worker_placement_not_remote\",\n"
    "                \"Worker invocation did not prove remote placement\",\n"
    "            )\n"
    "            try:\n",
)

latency_test = "tests/test_m23_7_r3_8_latency_repair.py"
replace_once(
    latency_test,
    "def test_duplicate_worker_variant_is_rejected() -> None:\n",
    "@pytest.mark.parametrize(\"placement\", [None, \"absent\", \"local\"])\n"
    "def test_http_worker_invoker_requires_remote_placement(\n"
    "    placement: str | None,\n"
    ") -> None:\n"
    "    def handler(_request: httpx.Request) -> httpx.Response:\n"
    "        headers = (\n"
    "            {}\n"
    "            if placement is None\n"
    "            else {subject.PLACEMENT_RESPONSE_HEADER: placement}\n"
    "        )\n"
    "        return httpx.Response(200, json={\"status\": \"ok\"}, headers=headers)\n\n"
    "    invoker = subject.HttpWorkerInvoker(\n"
    "        \"https://worker.example.test/observe\", \"a\" * 32\n"
    "    )\n"
    "    invoker._http.close()\n"
    "    invoker._http = httpx.Client(transport=httpx.MockTransport(handler))\n"
    "    with pytest.raises(subject.LatencyRepairError) as exc:\n"
    "        invoker.invoke({\"schema_version\": \"test\"}, clock_ns=lambda: 1)\n"
    "    assert exc.value.code == \"worker_placement_not_remote\"\n\n\n"
    "def test_http_worker_invoker_accepts_remote_placement() -> None:\n"
    "    def handler(_request: httpx.Request) -> httpx.Response:\n"
    "        return httpx.Response(\n"
    "            200,\n"
    "            json={\"status\": \"ok\"},\n"
    "            headers={subject.PLACEMENT_RESPONSE_HEADER: \"remote\"},\n"
    "        )\n\n"
    "    invoker = subject.HttpWorkerInvoker(\n"
    "        \"https://worker.example.test/observe\", \"a\" * 32\n"
    "    )\n"
    "    invoker._http.close()\n"
    "    invoker._http = httpx.Client(transport=httpx.MockTransport(handler))\n"
    "    payload, _elapsed = invoker.invoke(\n"
    "        {\"schema_version\": \"test\"}, clock_ns=lambda: 1\n"
    "    )\n"
    "    assert payload == {\"status\": \"ok\"}\n\n\n"
    "def test_duplicate_worker_variant_is_rejected() -> None:\n",
)

# Remote operator: bounded wait for two consecutive remote placement proofs.
operator = "scripts/m23_7_r3_8_remote_operator.py"
replace_once(
    operator,
    "READINESS_CONSECUTIVE_SUCCESSES = 2\nLIVE_OBSERVATION_ATTEMPTS = 9\n",
    "READINESS_CONSECUTIVE_SUCCESSES = 2\n"
    "PLACEMENT_READINESS_ATTEMPTS = 120\n"
    "PLACEMENT_READINESS_RETRY_SECONDS = 5\n"
    'PLACEMENT_RESPONSE_HEADER = "X-M23-R3-8-Placement"\n'
    "LIVE_OBSERVATION_ATTEMPTS = 9\n",
)
replace_once(
    operator,
    '        "worker_http_502_qdrant_single_query_unavailable",\n',
    '        "worker_http_502_qdrant_single_query_unavailable",\n'
    '        "worker_placement_not_remote",\n',
)
replace_once(
    operator,
    "def worker_ready_response(status_code: int, payload: object) -> bool:\n"
    "    return status_code == 400 and payload == {\n"
    "        \"status\": \"error\",\n"
    "        \"code\": \"request-schema-drift\",\n"
    "    }\n",
    "def worker_ready_response(\n"
    "    status_code: int, payload: object, placement: str | None\n"
    ") -> bool:\n"
    "    return (\n"
    "        status_code == 400\n"
    "        and payload\n"
    "        == {\"status\": \"error\", \"code\": \"request-schema-drift\"}\n"
    "        and placement == \"remote\"\n"
    "    )\n",
)
replace_once(
    operator,
    "            for _ in range(30):\n",
    "            for _ in range(PLACEMENT_READINESS_ATTEMPTS):\n",
)
replace_once(
    operator,
    "                    if worker_ready_response(response.status_code, response.json()):\n",
    "                    if worker_ready_response(\n"
    "                        response.status_code,\n"
    "                        response.json(),\n"
    "                        response.headers.get(PLACEMENT_RESPONSE_HEADER),\n"
    "                    ):\n",
)
replace_once(
    operator,
    "                    time.sleep(2)\n",
    "                    time.sleep(PLACEMENT_READINESS_RETRY_SECONDS)\n",
)
replace_once(
    operator,
    '                "local_terminal_operator_used": False,\n',
    '                "local_terminal_operator_used": False,\n'
    '                "placement_remote_readiness_verified": True,\n'
    '                "placement_response_class": "remote",\n'
    '                "placement_location_persisted": False,\n',
)

operator_test = "tests/test_m23_7_r3_8_remote_operator.py"
replace_once(
    operator_test,
    "def test_worker_readiness_requires_authorized_schema_probe() -> None:\n"
    "    assert subject.worker_ready_response(\n"
    "        400, {\"status\": \"error\", \"code\": \"request-schema-drift\"}\n"
    "    )\n"
    "    assert not subject.worker_ready_response(\n"
    "        405, {\"status\": \"error\", \"code\": \"method-not-allowed\"}\n"
    "    )\n"
    "    assert not subject.worker_ready_response(\n"
    "        500, {\"status\": \"error\", \"code\": \"operator-secret-missing\"}\n"
    "    )\n"
    "    assert not subject.worker_ready_response(\n"
    "        401, {\"status\": \"error\", \"code\": \"unauthorized\"}\n"
    "    )\n",
    "def test_worker_readiness_requires_authorized_remote_schema_probe() -> None:\n"
    "    payload = {\"status\": \"error\", \"code\": \"request-schema-drift\"}\n"
    "    assert subject.worker_ready_response(400, payload, \"remote\")\n"
    "    assert not subject.worker_ready_response(400, payload, \"local\")\n"
    "    assert not subject.worker_ready_response(400, payload, \"absent\")\n"
    "    assert not subject.worker_ready_response(400, payload, None)\n"
    "    assert not subject.worker_ready_response(\n"
    "        405, {\"status\": \"error\", \"code\": \"method-not-allowed\"}, \"remote\"\n"
    "    )\n"
    "    assert not subject.worker_ready_response(\n"
    "        500,\n"
    "        {\"status\": \"error\", \"code\": \"operator-secret-missing\"},\n"
    "        \"remote\",\n"
    "    )\n"
    "    assert not subject.worker_ready_response(\n"
    "        401, {\"status\": \"error\", \"code\": \"unauthorized\"}, \"remote\"\n"
    "    )\n",
)
replace_once(
    operator_test,
    '    assert "READINESS_CONSECUTIVE_SUCCESSES = 2" in text\n',
    '    assert "READINESS_CONSECUTIVE_SUCCESSES = 2" in text\n'
    '    assert "PLACEMENT_READINESS_ATTEMPTS = 120" in text\n'
    '    assert "PLACEMENT_READINESS_RETRY_SECONDS = 5" in text\n'
    '    assert "PLACEMENT_RESPONSE_HEADER" in text\n',
)
replace_once(
    operator_test,
    '    assert \'"worker_http_502_qdrant_single_query_unavailable"\' in text\n',
    '    assert \'"worker_http_502_qdrant_single_query_unavailable"\' in text\n'
    '    assert \'"worker_placement_not_remote"\' in text\n',
)

# Remote execution contract: add bounded placement proof without changing quality/latency gates.
remote_contract = Path("pilot/m23/m23-7-r3-8-7-remote-operator-contract.json")
contract = json.loads(remote_contract.read_text(encoding="utf-8"))
contract["observation"].update(
    {
        "placement_location_persisted": False,
        "placement_readiness_attempts": 120,
        "placement_readiness_retry_seconds": 5,
        "placement_remote_consecutive_successes": 2,
        "placement_remote_header_required_on_observation": True,
        "worker_placement_retry_authorized": True,
    }
)
contract["worker"].update(
    {
        "placement_location_persisted": False,
        "placement_response_header": "X-M23-R3-8-Placement",
        "placement_response_values": ["absent", "local", "remote"],
    }
)
contract.pop("contract_sha256", None)
contract_digest = hashlib.sha256(
    json.dumps(
        contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
).hexdigest()
contract["contract_sha256"] = contract_digest
remote_contract.write_text(
    json.dumps(
        contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    + "\n",
    encoding="utf-8",
)

# Dedicated CI: pin the repair to the current lifecycle-clean main and exact scope.
ci = ".github/workflows/m23-7-r3-8-7-remote-operator-ci.yml"
replace_once(
    ci,
    "git merge-base --is-ancestor 771538d3b95fccefc3f32bd568770e08ce3552ac HEAD",
    f"git merge-base --is-ancestor {BASE} HEAD",
)
replace_once(
    ci,
    '          assert digest == "5c7ae99cf9892b9f76a917cf691fd2ce4d4f7f0f255e04f48c90af9d7ea6b67b"\n',
    f'          assert digest == "{contract_digest}"\n',
)
replace_once(
    ci,
    '          assert stored["observation"]["live_observation_retry_seconds"] == 5\n',
    '          assert stored["observation"]["live_observation_retry_seconds"] == 5\n'
    '          assert stored["observation"]["placement_readiness_attempts"] == 120\n'
    '          assert stored["observation"]["placement_readiness_retry_seconds"] == 5\n'
    '          assert stored["observation"]["placement_remote_consecutive_successes"] == 2\n'
    '          assert stored["observation"]["placement_remote_header_required_on_observation"] is True\n'
    '          assert stored["observation"]["placement_location_persisted"] is False\n'
    '          assert stored["observation"]["worker_placement_retry_authorized"] is True\n'
    '          assert stored["worker"]["placement_response_header"] == "X-M23-R3-8-Placement"\n'
    '          assert stored["worker"]["placement_response_values"] == ["absent", "local", "remote"]\n'
    '          assert stored["worker"]["placement_location_persisted"] is False\n',
)
ci_path = Path(ci)
ci_text = ci_path.read_text(encoding="utf-8")
pattern = re.compile(
    r'          baseline = "4e7c7a10345aab63ed84b429ae2c360c02985810"\n'
    r"          allowed = \{\n.*?          \}\n",
    re.DOTALL,
)
replacement = (
    f'          baseline = "{BASE}"\n'
    "          allowed = {\n"
    '              ".github/workflows/m23-7-r3-8-7-remote-operator-ci.yml",\n'
    '              "docs/architecture/m23-7-r3-8-7-remote-operator.md",\n'
    '              "pilot/m23/m23-7-r3-8-7-remote-operator-contract.json",\n'
    '              "scripts/m23_7_r3_8_remote_operator.py",\n'
    '              "src/knowledge_engine/m23_7_r3_8_latency_repair.py",\n'
    '              "tests/test_m23_7_r3_8_latency_repair.py",\n'
    '              "tests/test_m23_7_r3_8_remote_operator.py",\n'
    '              "workers/m23-7-r3-8-latency-repair/worker.mjs",\n'
    '              "workers/m23-7-r3-8-latency-repair/worker.test.mjs",\n'
    "          }\n"
)
ci_text, count = pattern.subn(replacement, ci_text, count=1)
if count != 1:
    raise RuntimeError(f"remote CI scope replacement count: {count}")
ci_path.write_text(ci_text, encoding="utf-8")

append_once(
    "docs/architecture/m23-7-r3-8-7-remote-operator.md",
    "## Remote placement proof gate",
    """
## Remote placement proof gate

After observation run `29636761264` passed exact retrieval-quality parity but
failed the immutable Worker-internal latency gate, the operator was hardened to
prove that Cloudflare actually routed requests with placement before measuring.

The Worker reduces the inbound `cf-placement` value to one of `remote`, `local`,
or `absent` in `X-M23-R3-8-Placement`. It never returns or persists the airport
code. Readiness now requires two consecutive authenticated schema probes with
`remote`, within 120 bounded attempts separated by five seconds. A successful
formal observation response must also prove `remote`; otherwise the operator
fails closed with `worker_placement_not_remote` and may retry only within the
existing bounded observation loop.

This repair does not alter the 24 frozen query identities, ranking semantics,
quality thresholds, Qdrant read-only surface, or the 1200 ms latency maximum.
""",
)

# Bootstrap files must not survive the patch commit.
Path("scripts/bootstrap_m23_7_r3_8_placement_proof.py").unlink()
Path(".github/workflows/m23-7-r3-8-placement-proof-bootstrap.yml").unlink()

print(contract_digest)
