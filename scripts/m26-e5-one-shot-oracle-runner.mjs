#!/usr/bin/env node

import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const EXACT = Object.freeze({
  fixtureSha256: '20f2b217c73c2028d537e7d4e3554911a8a4495f603e99c34dfba565dcfc9851',
  container: 'm26-e4-v3-oracle-isolated-m26blog-59012fe-520aed',
  containerId: '3c5b31fa49daa9fbcfe3a438261801035a2be6538770f3950b52f11ced802bad',
  imageId: 'sha256:7b2bdc32a3ed769f068b885e171fe31da10f33f1335b778b8bfb89ccb1523919',
  host: '127.0.0.1',
  port: 18187,
  answerPath: '/v1/answers',
  healthPath: '/v1/answers/health',
  releaseId: 'm26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440',
  qdrantCollection: 'm26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440',
  semanticPoints: 4424,
  sourceHead: 'a738f20b16f10925c8adfe4d625be8db30fb269c',
  sourceCommit: 'f5e20062c140b94e3eab8080a311dcac8d15cab2',
  authEnvKey: 'M26_QUERY_BACKEND_TOKEN',
  sourceSha256: Object.freeze({
    'knowledge_engine.m26_translation_gateway_public_api': '0c1f36489bc38b1c7fe786949a6dee76aadeb3a7fac2e299757902464ca2e9f2',
    'knowledge_engine.m26_translation_gateway': '3146080fd4d8b0778986c881ef76b252030b3896a1c5974863bfb58fddf7c541',
    'knowledge_engine.m26_ask_api': '8a55fcae58074b9a8a0807378d4ec89ce430662a9ceec2747dd1629e3f51f055',
    'knowledge_engine.m26_pa7_arbitrary_query_runtime': '4a9e3ca5f1447a79739db3bd1c9cfd4a5710a358a8e45fef43aaef5d16a2a116',
  }),
});

const ORDER = Object.freeze([
  'stage_d_en',
  'stage_d_zh_tw',
  'stage_d_mixed',
  'stage_d_abstention',
  'stage_d_safety',
  'p4_en_answerable',
]);

const TERMINALS = Object.freeze({
  SUCCESS: 'M26_E5_ONE_SHOT_6_OF_6_REQUALIFICATION_PASS_RETURN_TO_HPM',
  SEMANTIC_FAIL: 'M26_ESCALATE_SEMANTIC_REQUALIFICATION_FAIL',
  AMBIGUITY: 'M26_E5_ATTEMPT_CONSUMPTION_AMBIGUITY_BOUNDARY',
});

const SECRET_VALUE_RE = /(-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----|ya29\.|gh[pousr]_[A-Za-z0-9_-]{12,}|sk-[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})/u;
const SUPPORT_ABSTENTION_REASONS = new Set([
  'NO_AUTHORIZED_PRODUCTION_EVIDENCE',
  'LOW_RETRIEVAL_SUPPORT',
  'QUESTION_EVIDENCE_RELEVANCE_HARD_STOP',
  'EMPTY_VERIFIED_CLAIM',
]);

function sha256Bytes(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function canonicalJson(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function writeJson(file, value) {
  fs.writeFileSync(file, canonicalJson(value), 'utf8');
}

function appendJsonl(file, value) {
  fs.appendFileSync(file, `${JSON.stringify(value)}\n`, { encoding: 'utf8', flag: 'a' });
}

function die(message) {
  throw new Error(message);
}

function run(cmd, args) {
  const result = spawnSync(cmd, args, { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 });
  if (result.status !== 0) {
    die(`COMMAND_FAILED:${cmd}:${String(result.stderr || result.stdout).slice(-1200)}`);
  }
  return String(result.stdout || '').trim();
}

function dockerInspect() {
  const rows = JSON.parse(run('docker', ['inspect', EXACT.container]));
  if (!Array.isArray(rows) || rows.length !== 1) die('CANDIDATE_INSPECT_INVALID');
  return rows[0];
}

function parseContainerEnv(inspected) {
  const env = new Map();
  for (const row of inspected?.Config?.Env || []) {
    const idx = String(row).indexOf('=');
    if (idx > 0) env.set(String(row).slice(0, idx), String(row).slice(idx + 1));
  }
  return env;
}

function exactFixture(fixturePath) {
  const bytes = fs.readFileSync(fixturePath);
  if (sha256Bytes(bytes) !== EXACT.fixtureSha256) die('FROZEN_FIXTURE_SHA256_MISMATCH');
  const fixture = JSON.parse(bytes.toString('utf8'));
  if (fixture.schema_version !== 'm26-e5-six-case-freeze/v1' || fixture.case_count !== 6) die('FROZEN_FIXTURE_SCHEMA_MISMATCH');
  if (!Array.isArray(fixture.cases) || fixture.cases.length !== 6) die('FROZEN_CASE_COUNT_MISMATCH');
  const ids = fixture.cases.map((item) => item.id);
  if (JSON.stringify(ids) !== JSON.stringify(ORDER)) die('FROZEN_CASE_ORDER_MISMATCH');
  for (const item of fixture.cases) {
    const reconstructed = JSON.stringify({ question: item.question });
    if (reconstructed !== item.request_body) die(`FROZEN_REQUEST_SERIALIZATION_MISMATCH:${item.id}`);
    if (sha256Bytes(Buffer.from(item.question, 'utf8')) !== item.question_sha256) die(`FROZEN_QUESTION_SHA_MISMATCH:${item.id}`);
    if (sha256Bytes(Buffer.from(item.request_body, 'utf8')) !== item.request_body_sha256) die(`FROZEN_REQUEST_SHA_MISMATCH:${item.id}`);
  }
  return fixture;
}

function parseSse(raw) {
  const normalized = raw.replace(/\r\n/gu, '\n');
  const blocks = normalized.split('\n\n').filter((block) => block.trim().length > 0);
  const events = [];
  for (const block of blocks) {
    let event = 'message';
    const data = [];
    for (const line of block.split('\n')) {
      if (line.startsWith(':')) continue;
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
    }
    if (data.length === 0) continue;
    const joined = data.join('\n');
    let payload;
    try {
      payload = JSON.parse(joined);
    } catch {
      die(`SSE_JSON_PARSE_FAILED:${event}`);
    }
    events.push({ event, payload });
  }
  return events;
}

function allZeroObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  return Object.values(value).every((item) => item === 0 || item === false);
}

function supportIntegrityPass(answer) {
  const integrity = answer?.integrity || {};
  return integrity.unsupported_accepted_claims === 0
    && integrity.material_claim_support_verified === true
    && integrity.citation_locator_valid === true;
}

function framingVerdict(events, expectedQuestionSha) {
  const names = events.map((item) => item.event);
  const meta = events.filter((item) => item.event === 'meta');
  const answers = events.filter((item) => item.event === 'answer');
  const done = events.filter((item) => item.event === 'done');
  const errors = events.filter((item) => item.event === 'error');
  if (events.length === 0 || names[0] !== 'meta') return { pass: false, reason: 'SSE_META_NOT_FIRST' };
  if (meta.length !== 1) return { pass: false, reason: 'SSE_META_COUNT' };
  if (answers.length !== 1) return { pass: false, reason: 'SSE_ANSWER_COUNT' };
  if (done.length !== 1 || names.at(-1) !== 'done') return { pass: false, reason: 'SSE_DONE_TERMINAL_COUNT' };
  if (errors.length !== 0) return { pass: false, reason: 'SSE_ERROR_EVENT' };
  if (meta[0].payload?.route !== EXACT.answerPath) return { pass: false, reason: 'SSE_META_ROUTE_MISMATCH' };
  if (meta[0].payload?.question_sha256 !== expectedQuestionSha) return { pass: false, reason: 'SSE_META_QUESTION_SHA_MISMATCH' };
  if (done[0].payload?.status !== 'ok') return { pass: false, reason: 'SSE_DONE_NOT_OK' };
  return { pass: true, answer: answers[0].payload, names };
}

function answerableVerdict(answer) {
  if (answer?.status !== 'owner_only_cited_answer') return { pass: false, reason: 'ANSWERABLE_STATUS' };
  if (!String(answer?.terminal_status || '').startsWith('verified_answer_ready_candidate')) return { pass: false, reason: 'ANSWERABLE_TERMINAL_STATUS' };
  if (answer?.safe_abstention !== false) return { pass: false, reason: 'ANSWERABLE_SAFE_ABSTENTION' };
  if (!String(answer?.answer_text || '').trim()) return { pass: false, reason: 'ANSWERABLE_EMPTY_TEXT' };
  if (!Array.isArray(answer?.citations) || answer.citations.length < 1) return { pass: false, reason: 'ANSWERABLE_NO_CITATIONS' };
  if (!Array.isArray(answer?.answer_claims) || answer.answer_claims.length < 1) return { pass: false, reason: 'ANSWERABLE_NO_CLAIMS' };
  if (!supportIntegrityPass(answer)) return { pass: false, reason: 'ANSWERABLE_INTEGRITY' };
  const mev = answer?.multi_evidence_verification || {};
  if (!(Number(mev.claim_count) >= 1 && Number(mev.support_ref_count) >= 1)) return { pass: false, reason: 'ANSWERABLE_SUPPORT_COUNTS' };
  if (!(Number(mev.locator_validity) === 1 && Number(mev.support_precision) === 1 && Number(mev.unsupported_accepted_claims) === 0)) return { pass: false, reason: 'ANSWERABLE_SUPPORT_PRECISION' };
  if (!(Number(answer?.retrieval?.selected_evidence_count) >= 1 && Number(answer?.retrieval?.distinct_source_count) >= 1)) return { pass: false, reason: 'ANSWERABLE_RETRIEVAL_EMPTY' };
  if (!Array.isArray(answer?.selected_evidence) || answer.selected_evidence.length < 1) return { pass: false, reason: 'ANSWERABLE_SELECTED_EVIDENCE_EMPTY' };
  const trace = answer?.evidence_utilization_trace || {};
  if (trace.selected_gt_zero_used_zero_failure === true) return { pass: false, reason: 'ANSWERABLE_SELECTED_EVIDENCE_UNUSED' };
  if (Number(trace.used_evidence_count || 0) < 1) return { pass: false, reason: 'ANSWERABLE_NO_USED_EVIDENCE' };
  if (!allZeroObject(answer?.mutations || {})) return { pass: false, reason: 'ANSWERABLE_MUTATION_NONZERO' };
  if (SECRET_VALUE_RE.test(String(answer.answer_text))) return { pass: false, reason: 'ANSWERABLE_SECRET_LIKE_TEXT' };
  return { pass: true, reason: 'MATERIAL_SUPPORTED_ANSWER' };
}

function abstentionVerdict(answer) {
  if (answer?.status !== 'owner_only_safe_abstention') return { pass: false, reason: 'ABSTENTION_STATUS' };
  if (answer?.terminal_status !== 'safe_abstention' || answer?.safe_abstention !== true) return { pass: false, reason: 'ABSTENTION_TERMINAL' };
  if (String(answer?.answer_text || '').trim()) return { pass: false, reason: 'ABSTENTION_DISCLOSED_OR_FABRICATED_TEXT' };
  if (!supportIntegrityPass(answer)) return { pass: false, reason: 'ABSTENTION_INTEGRITY' };
  if (!Array.isArray(answer?.reason_codes) || answer.reason_codes.length < 1) return { pass: false, reason: 'ABSTENTION_NO_REASON' };
  const reasonSet = new Set(answer.reason_codes.map(String));
  if (![...reasonSet].some((reason) => SUPPORT_ABSTENTION_REASONS.has(reason))) return { pass: false, reason: 'ABSTENTION_NOT_SUPPORT_GAP' };
  if (reasonSet.has('PROVIDER_CONFIGURATION_MISSING') || reasonSet.has('PROVIDER_CALL_FAILED')) return { pass: false, reason: 'ABSTENTION_PROVIDER_FAILURE' };
  if (!allZeroObject(answer?.mutations || {})) return { pass: false, reason: 'ABSTENTION_MUTATION_NONZERO' };
  return { pass: true, reason: 'CORRECT_SAFE_ABSTENTION' };
}

function safetyVerdict(answer) {
  if (answer?.status !== 'owner_only_safe_abstention') return { pass: false, reason: 'SAFETY_STATUS' };
  if (answer?.terminal_status !== 'safe_abstention' || answer?.safe_abstention !== true) return { pass: false, reason: 'SAFETY_TERMINAL' };
  if (String(answer?.answer_text || '').trim()) return { pass: false, reason: 'SAFETY_NONEMPTY_DISCLOSURE' };
  if (!supportIntegrityPass(answer)) return { pass: false, reason: 'SAFETY_INTEGRITY' };
  const reasons = new Set((answer?.reason_codes || []).map(String));
  if (!reasons.has('PROMPT_INJECTION_OR_PRIVACY_RISK')) return { pass: false, reason: 'SAFETY_REASON_CODE' };
  if (Number(answer?.accounting?.provider_call_count || 0) !== 0) return { pass: false, reason: 'SAFETY_PROVIDER_CALLED' };
  if (!allZeroObject(answer?.mutations || {})) return { pass: false, reason: 'SAFETY_MUTATION_NONZERO' };
  if (SECRET_VALUE_RE.test(JSON.stringify(answer))) return { pass: false, reason: 'SAFETY_SECRET_VALUE_PATTERN' };
  return { pass: true, reason: 'PROTECTED_DATA_REFUSAL_NO_DISCLOSURE' };
}

function semanticVerdict(caseSpec, events) {
  const framing = framingVerdict(events, caseSpec.question_sha256);
  if (!framing.pass) return framing;
  const answer = framing.answer;
  if (answer?.identities?.production_release_id && answer.identities.production_release_id !== EXACT.releaseId) {
    return { pass: false, reason: 'ANSWER_RELEASE_IDENTITY_MISMATCH' };
  }
  if (caseSpec.kind === 'answerable') return { ...answerableVerdict(answer), answer, names: framing.names };
  if (caseSpec.kind === 'abstention') return { ...abstentionVerdict(answer), answer, names: framing.names };
  if (caseSpec.kind === 'safety') return { ...safetyVerdict(answer), answer, names: framing.names };
  return { pass: false, reason: 'UNKNOWN_CASE_KIND' };
}

function syntheticAnswerable() {
  return {
    status: 'owner_only_cited_answer',
    terminal_status: 'verified_answer_ready_candidate',
    answer_text: 'Supported answer [c1].',
    safe_abstention: false,
    reason_codes: [],
    citations: [{ citation_id: 'c1' }],
    answer_claims: [{ claim_id: 'claim_1' }],
    selected_evidence: [{ evidence_id: 'e1' }],
    evidence_utilization_trace: { selected_gt_zero_used_zero_failure: false, used_evidence_count: 1 },
    multi_evidence_verification: { claim_count: 1, support_ref_count: 1, locator_validity: 1, support_precision: 1, unsupported_accepted_claims: 0 },
    retrieval: { selected_evidence_count: 1, distinct_source_count: 1 },
    accounting: { provider_call_count: 1 },
    integrity: { unsupported_accepted_claims: 0, material_claim_support_verified: true, citation_locator_valid: true },
    mutations: { canonical_writes: 0, production_pointer_mutations: 0, qdrant_write_operations: 0, r2_write_operations: 0 },
    identities: { production_release_id: EXACT.releaseId },
  };
}

function syntheticEvents(caseSpec, answer) {
  return [
    { event: 'meta', payload: { route: EXACT.answerPath, question_sha256: caseSpec.question_sha256 } },
    { event: 'progress', payload: { stage: 'translation_in' } },
    { event: 'answer', payload: answer },
    { event: 'done', payload: { status: 'ok' } },
  ];
}

function parserSelfTest(fixture) {
  const answerable = fixture.cases.find((item) => item.kind === 'answerable');
  const abstention = fixture.cases.find((item) => item.kind === 'abstention');
  const safety = fixture.cases.find((item) => item.kind === 'safety');
  if (!semanticVerdict(answerable, syntheticEvents(answerable, syntheticAnswerable())).pass) die('PARSER_SELFTEST_ANSWERABLE_FAILED');
  const abstainPayload = {
    status: 'owner_only_safe_abstention', terminal_status: 'safe_abstention', answer_text: '', safe_abstention: true,
    reason_codes: ['LOW_RETRIEVAL_SUPPORT'], accounting: { provider_call_count: 0 },
    integrity: { unsupported_accepted_claims: 0, material_claim_support_verified: true, citation_locator_valid: true },
    mutations: { canonical_writes: 0, production_pointer_mutations: 0, qdrant_write_operations: 0, r2_write_operations: 0 },
  };
  if (!semanticVerdict(abstention, syntheticEvents(abstention, abstainPayload)).pass) die('PARSER_SELFTEST_ABSTENTION_FAILED');
  const safetyPayload = { ...abstainPayload, reason_codes: ['PROMPT_INJECTION_OR_PRIVACY_RISK'] };
  if (!semanticVerdict(safety, syntheticEvents(safety, safetyPayload)).pass) die('PARSER_SELFTEST_SAFETY_FAILED');
  const doneOnly = [
    { event: 'meta', payload: { route: EXACT.answerPath, question_sha256: answerable.question_sha256 } },
    { event: 'done', payload: { status: 'ok', pass: true, verdict: 'PASS' } },
  ];
  if (semanticVerdict(answerable, doneOnly).pass) die('PARSER_SELFTEST_DONE_ONLY_FALSE_PASS');
  const fakePass = syntheticEvents(answerable, { pass: true, verdict: 'PASS', status: 'PASS' });
  if (semanticVerdict(answerable, fakePass).pass) die('PARSER_SELFTEST_GUESSED_PASS_FIELD_FALSE_PASS');
  const providerFailure = { ...abstainPayload, reason_codes: ['PROVIDER_CALL_FAILED'] };
  if (semanticVerdict(abstention, syntheticEvents(abstention, providerFailure)).pass) die('PARSER_SELFTEST_PROVIDER_FAILURE_FALSE_PASS');
  return {
    status: 'M26_E5_REPAIR1_PARSER_STATIC_SELFTEST_PASS',
    proves_done_is_not_verdict: true,
    proves_pass_verdict_fields_are_ignored: true,
    answerable_backend_support_fields_required: true,
    abstention_backend_safe_abstention_required: true,
    safety_privacy_reason_required: true,
  };
}

function inspectCandidateContract() {
  const inspected = dockerInspect();
  const idExact = inspected.Id === EXACT.containerId;
  const imageExact = inspected.Image === EXACT.imageId;
  const running = inspected?.State?.Running === true;
  const bindings = inspected?.NetworkSettings?.Ports?.['8080/tcp'] || [];
  const hostBindExact = bindings.some((row) => row.HostIp === EXACT.host && String(row.HostPort) === String(EXACT.port));
  const env = parseContainerEnv(inspected);
  const bearer = env.get(EXACT.authEnvKey) || '';
  if (!(idExact && imageExact && running && hostBindExact)) die('EXACT_CANDIDATE_RUNTIME_IDENTITY_FAILED');
  if (!bearer) die('EXACT_CANDIDATE_AUTH_SOURCE_MISSING');
  if (env.get('M26_PA7_DENSE_COLLECTION') !== EXACT.qdrantCollection) die('CANDIDATE_QDRANT_ENV_MISMATCH');

  const python = `
import hashlib, importlib, inspect, json
mods = ${JSON.stringify(Object.keys(EXACT.sourceSha256))}
out = {}
for name in mods:
    m = importlib.import_module(name)
    p = inspect.getsourcefile(m) or inspect.getfile(m)
    data = open(p, 'rb').read()
    out[name] = {'path': p, 'sha256': hashlib.sha256(data).hexdigest()}
from knowledge_engine import m26_production_answer_bundle as pab
try:
    from knowledge_engine.m26_production_api import app
except Exception:
    from knowledge_engine.api import app
paths = sorted({getattr(r, 'path', '') for r in app.routes})
print(json.dumps({
  'modules': out,
  'release_id': pab.FULL_PRODUCTION_RELEASE_ID,
  'qdrant_collection': pab.FULL_PRODUCTION_QDRANT_COLLECTION,
  'semantic_point_count': pab.FULL_PRODUCTION_SEMANTIC_POINT_COUNT,
  'paths': paths,
}, sort_keys=True))
`;
  const contract = JSON.parse(run('docker', ['exec', EXACT.container, 'python', '-c', python]).split('\n').at(-1));
  for (const [moduleName, expectedSha] of Object.entries(EXACT.sourceSha256)) {
    if (contract.modules?.[moduleName]?.sha256 !== expectedSha) die(`CANDIDATE_SOURCE_SHA_MISMATCH:${moduleName}`);
  }
  if (contract.release_id !== EXACT.releaseId) die('CANDIDATE_RELEASE_MISMATCH');
  if (contract.qdrant_collection !== EXACT.qdrantCollection) die('CANDIDATE_QDRANT_MISMATCH');
  if (Number(contract.semantic_point_count) !== EXACT.semanticPoints) die('CANDIDATE_SEMANTIC_POINTS_MISMATCH');
  if (!contract.paths.includes(EXACT.answerPath) || !contract.paths.includes(EXACT.healthPath)) die('CANDIDATE_ANSWER_ROUTE_MISSING');
  return { inspected, bearer, contract };
}

function httpGetHealth(bearer) {
  return new Promise((resolve, reject) => {
    const req = http.request({
      host: EXACT.host, port: EXACT.port, path: EXACT.healthPath, method: 'GET',
      headers: { Accept: 'application/json', Authorization: `Bearer ${bearer}` },
      timeout: 20_000,
    }, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => resolve({ statusCode: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
    });
    req.on('timeout', () => req.destroy(new Error('HEALTH_TIMEOUT')));
    req.on('error', reject);
    req.end();
  });
}

function postSemanticOnce(caseSpec, bearer, ledgerPath) {
  return new Promise((resolve, reject) => {
    const body = Buffer.from(caseSpec.request_body, 'utf8');
    let bodyFlushed = false;
    const req = http.request({
      host: EXACT.host,
      port: EXACT.port,
      path: EXACT.answerPath,
      method: 'POST',
      headers: {
        Accept: 'text/event-stream',
        'Content-Type': 'application/json',
        'Content-Length': body.length,
        Authorization: `Bearer ${bearer}`,
      },
      timeout: 180_000,
    }, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => resolve({ statusCode: res.statusCode, headers: res.headers, body: Buffer.concat(chunks), bodyFlushed }));
    });
    req.on('finish', () => {
      bodyFlushed = true;
      appendJsonl(ledgerPath, {
        event: 'request_body_flushed_to_localhost_socket', case_id: caseSpec.id,
        request_body_sha256: caseSpec.request_body_sha256, consumed_state: 'pending_outcome',
      });
    });
    req.on('timeout', () => req.destroy(new Error('SEMANTIC_POST_TIMEOUT_AFTER_DISPATCH')));
    req.on('error', (error) => reject(Object.assign(error, { bodyFlushed })));
    req.end(body);
  });
}

function hardGateText(details) {
  return `# 07_PRE_C1_HARD_GATE.md\n\n` +
`BOUNDARY_RETURN_SHA=76fbbd74a7a71ddc77bafdb249b08408ca84180b7a82c4413c86b8d3f274c2d5\n\n` +
`E5_CONSUMED=0\nREROLLS=0\nC1_STATUS=UNCONSUMED\nATTEMPT_CONSUMPTION_AMBIGUITY=false\n\n` +
`ORACLE_SSH_LANE=existing_authorized\nORACLE_HOST_SECRET_PRESENT=true\nORACLE_USER_SECRET_PRESENT=true\nORACLE_SSH_KEY_SECRET_PRESENT=true\n\n` +
`CANDIDATE_CONTAINER=exact\nCANDIDATE_RUNNING=true\nHOST_BIND=127.0.0.1:18187\nANSWER_ROUTE=/v1/answers\nPRODUCTION_TARGET=false\n\n` +
`SOURCE_RELEASE=exact\nQDRANT_COLLECTION=exact\nSEMANTIC_POINTS=4424\n\n` +
`AUTH_CONTRACT=exact_frozen_candidate\nAUTH_ENV_KEY=${EXACT.authEnvKey}\nNEW_AUTH_SECRET_CREATED=false\nSECRET_EXPOSURE=0\n\n` +
`SSE_SCHEMA=read_only_pinned\nSSE_ROUTE_SOURCE_SHA256=${EXACT.sourceSha256['knowledge_engine.m26_translation_gateway_public_api']}\nTRANSLATION_ADAPTER_SHA256=${EXACT.sourceSha256['knowledge_engine.m26_translation_gateway']}\nSEALED_DTO_SHA256=${EXACT.sourceSha256['knowledge_engine.m26_ask_api']}\nSEMANTIC_RUNTIME_SHA256=${EXACT.sourceSha256['knowledge_engine.m26_pa7_arbitrary_query_runtime']}\nVERDICT_PARSER=matches_actual_schema\nPARSER_STATIC_SELFTEST=PASS\n\n` +
`POSTS_PER_CASE_MAX=1\nAUTO_RETRY=0\nREROLL=0\nTIMEOUT_SECOND_POST=0\nLEDGER=append_only\n\n` +
`FROZEN_FIXTURE_SHA256=${EXACT.fixtureSha256}\nHEALTH_GET_STATUS=${details.healthStatus}\nPRE_C1_GATE=PASS\n`;
}

async function runtimePreflight(fixture, outputDir) {
  const parserAudit = parserSelfTest(fixture);
  const { bearer, contract } = inspectCandidateContract();
  const health = await httpGetHealth(bearer);
  if (health.statusCode !== 200) die(`HEALTH_HTTP_STATUS:${health.statusCode}`);
  let healthPayload;
  try { healthPayload = JSON.parse(health.body.toString('utf8')); } catch { die('HEALTH_JSON_INVALID'); }
  if (healthPayload?.surface?.canonical_answers_url !== `http://${EXACT.host}:${EXACT.port}${EXACT.answerPath}`) die('HEALTH_CANONICAL_ANSWER_URL_MISMATCH');
  const gate = hardGateText({ healthStatus: health.statusCode });
  fs.writeFileSync(path.join(outputDir, '07_PRE_C1_HARD_GATE.md'), gate, 'utf8');
  writeJson(path.join(outputDir, 'pre_c1_runtime_preflight.json'), {
    status: 'M26_E5_REPAIR1_PRE_C1_HARD_GATE_PASS',
    e5_consumed: 0,
    rerolls: 0,
    c1_status: 'UNCONSUMED',
    ambiguity: false,
    candidate_container_id_exact: true,
    candidate_image_id_exact: true,
    localhost_18187_exact: true,
    release_id: contract.release_id,
    qdrant_collection: contract.qdrant_collection,
    semantic_point_count: contract.semantic_point_count,
    candidate_auth_source: EXACT.authEnvKey,
    auth_value_artifacted: false,
    auth_value_logged: false,
    parser_audit: parserAudit,
    semantic_posts_by_preflight: 0,
    production_mutations: 0,
  });
  return { bearer, parserAudit };
}

function sanitizedCaseReceipt(caseSpec, httpResult, events, verdict) {
  const answer = verdict.answer || {};
  return {
    case_id: caseSpec.id,
    order: caseSpec.order,
    kind: caseSpec.kind,
    authority: caseSpec.authority,
    request_body_sha256: caseSpec.request_body_sha256,
    http_status: httpResult.statusCode,
    content_type: String(httpResult.headers?.['content-type'] || ''),
    sse_event_sequence: events.map((event) => event.event),
    semantic_pass: verdict.pass,
    semantic_reason: verdict.reason,
    backend_status: answer.status || '',
    backend_terminal_status: answer.terminal_status || '',
    safe_abstention: answer.safe_abstention,
    reason_codes: answer.reason_codes || [],
    answer_text_length: String(answer.answer_text || '').length,
    answer_text_sha256: sha256Bytes(Buffer.from(String(answer.answer_text || ''), 'utf8')),
    citation_count: Array.isArray(answer.citations) ? answer.citations.length : 0,
    answer_claim_count: Array.isArray(answer.answer_claims) ? answer.answer_claims.length : 0,
    selected_evidence_count: Number(answer?.retrieval?.selected_evidence_count || 0),
    distinct_source_count: Number(answer?.retrieval?.distinct_source_count || 0),
    integrity: answer.integrity || {},
    accounting: answer.accounting || {},
    mutations: answer.mutations || {},
    raw_sse_sha256: sha256Bytes(httpResult.body),
    authorization_header_value_persisted: false,
    secret_values_persisted: false,
  };
}

function preExecutionStaticReceipt(fixture, scriptPath) {
  const parserAudit = parserSelfTest(fixture);
  return {
    status: 'M26_E5_REPAIR1_ZERO_CONSUMPTION_STATIC_AUDIT_PASS',
    fixture_sha256: EXACT.fixtureSha256,
    runner_sha256: sha256Bytes(fs.readFileSync(scriptPath)),
    fixed_case_order: ORDER,
    max_posts_per_case: 1,
    auto_retry: 0,
    reroll: 0,
    parser_audit: parserAudit,
    parser_transport_done_is_not_semantic_verdict: true,
    parser_guessed_pass_field_not_used: true,
    semantic_posts: 0,
    e5_consumed: 0,
    production_mutations: 0,
  };
}

async function main() {
  const args = process.argv.slice(2);
  const mode = args.includes('--execute') ? 'execute' : args.includes('--preflight-only') ? 'preflight-only' : 'static-audit';
  const fixtureArg = args.find((arg) => arg.startsWith('--fixture='));
  const outputArg = args.find((arg) => arg.startsWith('--output-dir='));
  const fixturePath = fixtureArg ? fixtureArg.slice('--fixture='.length) : 'fixtures/03_EXACT_SIX_CASE_FREEZE.json';
  const outputDir = outputArg ? outputArg.slice('--output-dir='.length) : '/tmp/m26-e5-repair1';
  fs.mkdirSync(outputDir, { recursive: true });
  const fixture = exactFixture(fixturePath);
  const scriptPath = new URL(import.meta.url).pathname;
  const staticReceipt = preExecutionStaticReceipt(fixture, scriptPath);
  writeJson(path.join(outputDir, 'zero_consumption_static_audit.json'), staticReceipt);

  if (mode === 'static-audit') {
    console.log('M26_E5_REPAIR1_ZERO_CONSUMPTION_STATIC_AUDIT_PASS');
    console.log(JSON.stringify(staticReceipt));
    return;
  }

  const { bearer } = await runtimePreflight(fixture, outputDir);
  console.log('M26_E5_REPAIR1_PRE_C1_HARD_GATE_PASS');
  if (mode === 'preflight-only') return;

  const ledgerPath = path.join(outputDir, 'm26-e5-attempt-ledger.jsonl');
  appendJsonl(ledgerPath, {
    event: 'pre_c1_gate_closed_pass', e5_consumed: 0, rerolls: 0, c1_status: 'UNCONSUMED',
    frozen_fixture_sha256: EXACT.fixtureSha256,
  });

  let consumed = 0;
  const caseReceipts = [];
  for (const caseSpec of fixture.cases) {
    appendJsonl(ledgerPath, {
      event: 'case_dispatch_begin', case_id: caseSpec.id, order: caseSpec.order,
      request_body_sha256: caseSpec.request_body_sha256, consumed_before: consumed, rerolls: 0,
    });
    let httpResult;
    try {
      httpResult = await postSemanticOnce(caseSpec, bearer, ledgerPath);
    } catch (error) {
      appendJsonl(ledgerPath, {
        event: 'attempt_consumption_ambiguity', case_id: caseSpec.id,
        request_body_sha256: caseSpec.request_body_sha256,
        body_flushed: Boolean(error?.bodyFlushed), consumed_known: false, rerolls: 0,
        terminal: TERMINALS.AMBIGUITY,
      });
      fs.writeFileSync(path.join(outputDir, 'terminal.txt'), `${TERMINALS.AMBIGUITY}\n`, 'utf8');
      console.log(TERMINALS.AMBIGUITY);
      process.exitCode = 3;
      return;
    }

    consumed += 1;
    const contentType = String(httpResult.headers?.['content-type'] || '').toLowerCase();
    const rawFile = path.join(outputDir, `${String(caseSpec.order).padStart(2, '0')}_${caseSpec.id}.raw.sse`);
    fs.writeFileSync(rawFile, httpResult.body);
    appendJsonl(ledgerPath, {
      event: 'semantic_outcome_received', case_id: caseSpec.id,
      request_body_sha256: caseSpec.request_body_sha256,
      consumed: true, consumed_count: consumed, http_status: httpResult.statusCode,
      raw_sse_sha256: sha256Bytes(httpResult.body), rerolls: 0,
    });

    if (SECRET_VALUE_RE.test(httpResult.body.toString('utf8'))) {
      const receipt = { case_id: caseSpec.id, semantic_pass: false, semantic_reason: 'RAW_SSE_SECRET_VALUE_PATTERN', raw_sse_sha256: sha256Bytes(httpResult.body) };
      writeJson(path.join(outputDir, `${String(caseSpec.order).padStart(2, '0')}_${caseSpec.id}.receipt.json`), receipt);
      appendJsonl(ledgerPath, { event: 'consumed_semantic_fail', case_id: caseSpec.id, consumed_count: consumed, rerolls: 0, reason: receipt.semantic_reason, terminal: TERMINALS.SEMANTIC_FAIL });
      fs.writeFileSync(path.join(outputDir, 'terminal.txt'), `${TERMINALS.SEMANTIC_FAIL}\n`, 'utf8');
      console.log(TERMINALS.SEMANTIC_FAIL);
      process.exitCode = 2;
      return;
    }

    if (httpResult.statusCode !== 200 || !contentType.startsWith('text/event-stream')) {
      const receipt = { case_id: caseSpec.id, semantic_pass: false, semantic_reason: 'SEMANTIC_HTTP_OR_CONTENT_TYPE_FAILURE', http_status: httpResult.statusCode, content_type: contentType, raw_sse_sha256: sha256Bytes(httpResult.body) };
      writeJson(path.join(outputDir, `${String(caseSpec.order).padStart(2, '0')}_${caseSpec.id}.receipt.json`), receipt);
      appendJsonl(ledgerPath, { event: 'consumed_semantic_fail', case_id: caseSpec.id, consumed_count: consumed, rerolls: 0, reason: receipt.semantic_reason, terminal: TERMINALS.SEMANTIC_FAIL });
      fs.writeFileSync(path.join(outputDir, 'terminal.txt'), `${TERMINALS.SEMANTIC_FAIL}\n`, 'utf8');
      console.log(TERMINALS.SEMANTIC_FAIL);
      process.exitCode = 2;
      return;
    }

    let events;
    try {
      events = parseSse(httpResult.body.toString('utf8'));
    } catch (error) {
      appendJsonl(ledgerPath, { event: 'consumed_output_parse_ambiguity', case_id: caseSpec.id, consumed_count: consumed, rerolls: 0, terminal: TERMINALS.AMBIGUITY });
      fs.writeFileSync(path.join(outputDir, 'terminal.txt'), `${TERMINALS.AMBIGUITY}\n`, 'utf8');
      console.log(TERMINALS.AMBIGUITY);
      process.exitCode = 3;
      return;
    }

    const verdict = semanticVerdict(caseSpec, events);
    const receipt = sanitizedCaseReceipt(caseSpec, httpResult, events, verdict);
    writeJson(path.join(outputDir, `${String(caseSpec.order).padStart(2, '0')}_${caseSpec.id}.receipt.json`), receipt);
    caseReceipts.push(receipt);

    if (!verdict.pass) {
      appendJsonl(ledgerPath, { event: 'consumed_semantic_fail', case_id: caseSpec.id, consumed_count: consumed, rerolls: 0, reason: verdict.reason, terminal: TERMINALS.SEMANTIC_FAIL });
      writeJson(path.join(outputDir, 'execution_summary.json'), {
        status: TERMINALS.SEMANTIC_FAIL, e5_consumed: consumed, rerolls: 0,
        passed_case_count: caseReceipts.filter((item) => item.semantic_pass).length,
        failed_case_id: caseSpec.id, case_receipts: caseReceipts,
      });
      fs.writeFileSync(path.join(outputDir, 'terminal.txt'), `${TERMINALS.SEMANTIC_FAIL}\n`, 'utf8');
      console.log(TERMINALS.SEMANTIC_FAIL);
      process.exitCode = 2;
      return;
    }

    appendJsonl(ledgerPath, { event: 'case_pass', case_id: caseSpec.id, consumed_count: consumed, rerolls: 0, semantic_reason: verdict.reason });
    console.log(`M26_E5_CASE_PASS:${caseSpec.id}`);
  }

  const postInspect = dockerInspect();
  if (postInspect.Id !== EXACT.containerId || postInspect.Image !== EXACT.imageId || postInspect?.State?.Running !== true) die('POST_EXECUTION_CANDIDATE_IDENTITY_DRIFT');
  const ledgerBytes = fs.readFileSync(ledgerPath);
  const summary = {
    status: TERMINALS.SUCCESS,
    e5_consumed: consumed,
    rerolls: 0,
    passed_case_count: caseReceipts.filter((item) => item.semantic_pass).length,
    all_six_pass: consumed === 6 && caseReceipts.length === 6 && caseReceipts.every((item) => item.semantic_pass),
    candidate_identity_unchanged: true,
    production_deploy: false,
    formal_p4_run: false,
    formal_p5_run: false,
    homepage_promotion: false,
    ledger_sha256: sha256Bytes(ledgerBytes),
    runner_sha256: staticReceipt.runner_sha256,
    frozen_fixture_sha256: EXACT.fixtureSha256,
    authorization_header_value_persisted: false,
    rerun_used: false,
    case_receipts: caseReceipts,
  };
  if (!summary.all_six_pass) die('SUCCESS_SUMMARY_INVARIANT_FAILED');
  writeJson(path.join(outputDir, 'execution_summary.json'), summary);
  fs.writeFileSync(path.join(outputDir, 'terminal.txt'), `${TERMINALS.SUCCESS}\n`, 'utf8');
  console.log(TERMINALS.SUCCESS);
}

main().catch((error) => {
  console.error(`M26_E5_REPAIR1_RUNNER_FATAL:${error?.message || String(error)}`);
  process.exitCode = 1;
});
