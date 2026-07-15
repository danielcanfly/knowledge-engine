const MESSAGE_SCHEMA = "knowledge-engine-m23-incremental-ingestion-message/v1";
const COLLECTION = "llm_wiki_m23_pilot_bge_m3_1024";
const VECTOR_NAME = "default";
const VECTOR_DIMENSION = 1024;
const MAX_BATCH_MESSAGES = 4;
const MAX_SECTIONS_PER_MESSAGE = 25;
const MAX_SECTIONS_PER_RUN = 500;
const MAX_ESTIMATED_USD_PER_RUN = 0.5;
const SOURCE_MEMBERSHIP = "evaluation-only-pending-proposal";
const RETRY_DELAY_SECONDS = 30;
const DISABLED_RETRY_DELAY_SECONDS = 900;

type JsonObject = Record<string, unknown>;

type IncrementalSection = {
  section_id: string;
  point_id: string;
  expected_previous_text_sha256: string | null;
  text: string;
  text_sha256: string;
  payload: JsonObject;
};

type IncrementalMessage = {
  schema_version: typeof MESSAGE_SCHEMA;
  message_id: string;
  collection: typeof COLLECTION;
  release_id: string;
  source_commit_sha: string;
  emitted_at: string;
  estimated_usd: number;
  sections: IncrementalSection[];
  authority: {
    canonical_knowledge: false;
    candidate_release_eligible: false;
    production_authority: false;
    delete_authorized: false;
  };
};

type ExistingPoint = {
  id: string;
  payload: JsonObject;
};

type PlannedSection = {
  section: IncrementalSection;
  action: "insert" | "replace" | "skip-duplicate" | "reject-stale";
  reason: string;
};

class TerminalMessageError extends Error {}
class TransientMessageError extends Error {}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown, field: string, maxLength: number): string {
  if (typeof value !== "string" || value.length === 0 || value.length > maxLength) {
    throw new TerminalMessageError(`invalid-${field}`);
  }
  return value;
}

function requiredSha256(value: unknown, field: string): string {
  const text = requiredString(value, field, 64);
  if (!/^[0-9a-f]{64}$/.test(text)) {
    throw new TerminalMessageError(`invalid-${field}`);
  }
  return text;
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }
  const object = value as JsonObject;
  return `{${Object.keys(object)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableStringify(object[key])}`)
    .join(",")}}`;
}

async function sha256Hex(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function log(event: string, fields: JsonObject = {}): void {
  console.log(
    JSON.stringify({
      timestamp: new Date().toISOString(),
      milestone: "M23.6.4",
      worker: "llm-wiki-m23-pilot-embed-consumer",
      event,
      ...fields,
    }),
  );
}

function parseSection(value: unknown): IncrementalSection {
  if (!isObject(value)) {
    throw new TerminalMessageError("invalid-section");
  }
  const sectionId = requiredString(value.section_id, "section-id", 500);
  const pointId = requiredString(value.point_id, "point-id", 64);
  const previous = value.expected_previous_text_sha256;
  const expectedPrevious = previous === null ? null : requiredSha256(previous, "previous-text-sha");
  const text = requiredString(value.text, "text", 50_000);
  const textSha = requiredSha256(value.text_sha256, "text-sha");
  if (!isObject(value.payload)) {
    throw new TerminalMessageError("invalid-payload");
  }
  const payload = value.payload;
  if (payload.section_id !== sectionId || payload.text_sha256 !== textSha) {
    throw new TerminalMessageError("payload-identity-mismatch");
  }
  if (payload.source_membership !== SOURCE_MEMBERSHIP) {
    throw new TerminalMessageError("source-membership-mismatch");
  }
  if (
    payload.canonical_knowledge !== false ||
    payload.candidate_release_eligible !== false ||
    payload.production_authority !== false
  ) {
    throw new TerminalMessageError("payload-authority-violation");
  }
  requiredSha256(payload.source_sha256, "source-sha");
  return {
    section_id: sectionId,
    point_id: pointId,
    expected_previous_text_sha256: expectedPrevious,
    text,
    text_sha256: textSha,
    payload,
  };
}

async function parseMessage(value: unknown): Promise<IncrementalMessage> {
  if (!isObject(value)) {
    throw new TerminalMessageError("invalid-message");
  }
  if (value.schema_version !== MESSAGE_SCHEMA) {
    throw new TerminalMessageError("unsupported-schema");
  }
  if (value.collection !== COLLECTION) {
    throw new TerminalMessageError("wrong-collection");
  }
  const messageId = requiredString(value.message_id, "message-id", 31);
  if (!/^m23inc-[0-9a-f]{24}$/.test(messageId)) {
    throw new TerminalMessageError("invalid-message-id");
  }
  const releaseId = requiredString(value.release_id, "release-id", 128);
  const sourceCommitSha = requiredString(value.source_commit_sha, "source-commit-sha", 40);
  if (!/^[0-9a-f]{40}$/.test(sourceCommitSha)) {
    throw new TerminalMessageError("invalid-source-commit-sha");
  }
  const emittedAt = requiredString(value.emitted_at, "emitted-at", 80);
  if (Number.isNaN(Date.parse(emittedAt))) {
    throw new TerminalMessageError("invalid-emitted-at");
  }
  if (
    typeof value.estimated_usd !== "number" ||
    !Number.isFinite(value.estimated_usd) ||
    value.estimated_usd < 0 ||
    value.estimated_usd > MAX_ESTIMATED_USD_PER_RUN
  ) {
    throw new TerminalMessageError("budget-exceeded");
  }
  if (!Array.isArray(value.sections) || value.sections.length < 1 || value.sections.length > MAX_SECTIONS_PER_MESSAGE) {
    throw new TerminalMessageError("oversize-message");
  }
  if (!isObject(value.authority)) {
    throw new TerminalMessageError("invalid-authority");
  }
  if (
    value.authority.canonical_knowledge !== false ||
    value.authority.candidate_release_eligible !== false ||
    value.authority.production_authority !== false ||
    value.authority.delete_authorized !== false
  ) {
    throw new TerminalMessageError("authority-violation");
  }

  const sections = value.sections.map(parseSection);
  if (new Set(sections.map((section) => section.section_id)).size !== sections.length) {
    throw new TerminalMessageError("duplicate-section-id");
  }
  if (new Set(sections.map((section) => section.point_id)).size !== sections.length) {
    throw new TerminalMessageError("duplicate-point-id");
  }
  for (const section of sections) {
    const actual = await sha256Hex(section.text);
    if (actual !== section.text_sha256) {
      throw new TerminalMessageError("text-digest-mismatch");
    }
  }

  const parsed: IncrementalMessage = {
    schema_version: MESSAGE_SCHEMA,
    message_id: messageId,
    collection: COLLECTION,
    release_id: releaseId,
    source_commit_sha: sourceCommitSha,
    emitted_at: emittedAt,
    estimated_usd: value.estimated_usd,
    sections,
    authority: {
      canonical_knowledge: false,
      candidate_release_eligible: false,
      production_authority: false,
      delete_authorized: false,
    },
  };
  const identityInput: JsonObject = { ...parsed };
  delete identityInput.message_id;
  const expectedId = `m23inc-${(await sha256Hex(stableStringify(identityInput))).slice(0, 24)}`;
  if (messageId !== expectedId) {
    throw new TerminalMessageError("message-identity-mismatch");
  }
  return parsed;
}

function qdrantBaseUrl(env: CloudflareEnv): URL {
  const url = new URL(env.QDRANT_URL);
  if (url.protocol !== "https:") {
    throw new TerminalMessageError("qdrant-url-must-use-https");
  }
  return url;
}

async function qdrantRequest(
  env: CloudflareEnv,
  path: string,
  init: RequestInit = {},
): Promise<JsonObject> {
  const url = new URL(path, qdrantBaseUrl(env));
  const response = await fetch(url, {
    ...init,
    headers: {
      "api-key": env.QDRANT_API_KEY,
      "content-type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    if (response.status >= 500 || response.status === 408 || response.status === 429) {
      throw new TransientMessageError(`qdrant-transient-${response.status}`);
    }
    throw new TerminalMessageError(`qdrant-terminal-${response.status}`);
  }
  const body: unknown = await response.json();
  if (!isObject(body)) {
    throw new TransientMessageError("qdrant-invalid-response");
  }
  return body;
}

async function assertCollectionContract(env: CloudflareEnv): Promise<void> {
  if (env.QDRANT_COLLECTION !== COLLECTION || env.QDRANT_VECTOR_NAME !== VECTOR_NAME) {
    throw new TerminalMessageError("binding-contract-mismatch");
  }
  const body = await qdrantRequest(env, `/collections/${COLLECTION}`);
  if (!isObject(body.result)) {
    throw new TransientMessageError("qdrant-collection-unavailable");
  }
  const result = body.result;
  if (result.status !== "green" || !isObject(result.config)) {
    throw new TransientMessageError("qdrant-collection-not-green");
  }
  const params = isObject(result.config.params) ? result.config.params : null;
  const vectors = params && isObject(params.vectors) ? params.vectors : null;
  const vector = vectors && isObject(vectors[VECTOR_NAME]) ? vectors[VECTOR_NAME] : null;
  if (!vector || vector.size !== VECTOR_DIMENSION || vector.distance !== "Cosine") {
    throw new TerminalMessageError("qdrant-vector-contract-mismatch");
  }
}

async function retrieveExisting(
  env: CloudflareEnv,
  pointIds: string[],
): Promise<Map<string, ExistingPoint>> {
  const body = await qdrantRequest(env, `/collections/${COLLECTION}/points`, {
    method: "POST",
    body: JSON.stringify({ ids: pointIds, with_payload: true, with_vector: false }),
  });
  if (!Array.isArray(body.result)) {
    throw new TransientMessageError("qdrant-retrieve-invalid-result");
  }
  const result = new Map<string, ExistingPoint>();
  for (const item of body.result) {
    if (!isObject(item) || typeof item.id !== "string" || !isObject(item.payload)) {
      throw new TransientMessageError("qdrant-retrieve-invalid-point");
    }
    result.set(item.id, { id: item.id, payload: item.payload });
  }
  return result;
}

function planSections(
  message: IncrementalMessage,
  existing: Map<string, ExistingPoint>,
): PlannedSection[] {
  return message.sections.map((section) => {
    const current = existing.get(section.point_id);
    if (!current) {
      if (section.expected_previous_text_sha256 !== null) {
        return { section, action: "reject-stale", reason: "missing-expected-previous" };
      }
      return { section, action: "insert", reason: "point-missing" };
    }
    if (current.payload.section_id !== section.section_id) {
      return { section, action: "reject-stale", reason: "point-id-section-id-conflict" };
    }
    const currentTextSha = current.payload.text_sha256;
    if (currentTextSha === section.text_sha256) {
      return { section, action: "skip-duplicate", reason: "text-sha-already-current" };
    }
    if (
      section.expected_previous_text_sha256 !== null &&
      currentTextSha === section.expected_previous_text_sha256
    ) {
      return { section, action: "replace", reason: "optimistic-precondition-matched" };
    }
    return { section, action: "reject-stale", reason: "optimistic-precondition-mismatch" };
  });
}

function parseEmbeddings(value: unknown, expectedRows: number): number[][] {
  if (!isObject(value) || !Array.isArray(value.data) || value.data.length !== expectedRows) {
    throw new TransientMessageError("workers-ai-invalid-embedding-response");
  }
  return value.data.map((row) => {
    if (!Array.isArray(row) || row.length !== VECTOR_DIMENSION) {
      throw new TransientMessageError("workers-ai-vector-dimension-mismatch");
    }
    const values = row.map((entry) => {
      if (typeof entry !== "number" || !Number.isFinite(entry)) {
        throw new TransientMessageError("workers-ai-nonfinite-vector");
      }
      return entry;
    });
    const norm = Math.sqrt(values.reduce((sum, entry) => sum + entry * entry, 0));
    if (!Number.isFinite(norm) || norm <= 0) {
      throw new TransientMessageError("workers-ai-zero-vector");
    }
    return values.map((entry) => entry / norm);
  });
}

async function upsertPlanned(
  env: CloudflareEnv,
  planned: PlannedSection[],
): Promise<number> {
  const writable = planned.filter(
    (item): item is PlannedSection & { action: "insert" | "replace" } =>
      item.action === "insert" || item.action === "replace",
  );
  if (writable.length === 0) {
    return 0;
  }
  const aiResult: unknown = await env.AI.run(env.EMBEDDING_MODEL, {
    text: writable.map((item) => item.section.text),
  });
  const vectors = parseEmbeddings(aiResult, writable.length);
  const points = writable.map((item, index) => ({
    id: item.section.point_id,
    vector: { [VECTOR_NAME]: vectors[index] },
    payload: item.section.payload,
  }));
  const response = await qdrantRequest(
    env,
    `/collections/${COLLECTION}/points?wait=true&ordering=strong`,
    { method: "PUT", body: JSON.stringify({ points }) },
  );
  if (!isObject(response.result) || response.result.status !== "completed") {
    throw new TransientMessageError("qdrant-upsert-not-completed");
  }
  return points.length;
}

async function processMessage(env: CloudflareEnv, message: IncrementalMessage): Promise<void> {
  const existing = await retrieveExisting(
    env,
    message.sections.map((section) => section.point_id),
  );
  const planned = planSections(message, existing);
  if (planned.some((item) => item.action === "reject-stale")) {
    log("message-terminal-rejected", {
      message_id: message.message_id,
      reason: "stale-event",
      outcomes: planned.map(({ section, action, reason }) => ({
        section_id: section.section_id,
        action,
        reason,
      })),
    });
    return;
  }
  const upserted = await upsertPlanned(env, planned);
  log("message-completed", {
    message_id: message.message_id,
    section_count: message.sections.length,
    inserted_or_replaced: upserted,
    skipped: planned.filter((item) => item.action === "skip-duplicate").length,
  });
}

const worker: ExportedHandler<CloudflareEnv> = {
  async fetch(): Promise<Response> {
    return new Response("Not Found", { status: 404 });
  },

  async queue(batch, env): Promise<void> {
    if (batch.messages.length > MAX_BATCH_MESSAGES) {
      log("batch-terminal-rejected", { reason: "batch-message-cap", count: batch.messages.length });
      batch.ackAll();
      return;
    }

    const parsed: Array<{ raw: Message<unknown>; value: IncrementalMessage }> = [];
    for (const message of batch.messages) {
      try {
        parsed.push({ raw: message, value: await parseMessage(message.body) });
      } catch (error) {
        const reason = error instanceof Error ? error.message : "invalid-message";
        log("message-terminal-rejected", { queue_message_id: message.id, reason });
        message.ack();
      }
    }

    const sectionCount = parsed.reduce((sum, item) => sum + item.value.sections.length, 0);
    const estimatedUsd = parsed.reduce((sum, item) => sum + item.value.estimated_usd, 0);
    if (sectionCount > MAX_SECTIONS_PER_RUN || estimatedUsd > MAX_ESTIMATED_USD_PER_RUN) {
      log("batch-terminal-rejected", {
        reason: sectionCount > MAX_SECTIONS_PER_RUN ? "run-section-cap" : "run-budget-cap",
        section_count: sectionCount,
        estimated_usd: estimatedUsd,
      });
      for (const item of parsed) item.raw.ack();
      return;
    }

    if (parsed.length === 0) return;
    if (env.EXECUTION_ENABLED !== "true") {
      log("batch-retry", { reason: "execution-disabled", message_count: parsed.length });
      for (const item of parsed) item.raw.retry({ delaySeconds: DISABLED_RETRY_DELAY_SECONDS });
      return;
    }

    try {
      await assertCollectionContract(env);
    } catch (error) {
      const reason = error instanceof Error ? error.message : "collection-preflight-failed";
      log("batch-retry", { reason, message_count: parsed.length });
      for (const item of parsed) item.raw.retry({ delaySeconds: RETRY_DELAY_SECONDS });
      return;
    }

    for (const item of parsed) {
      try {
        await processMessage(env, item.value);
        item.raw.ack();
      } catch (error) {
        const reason = error instanceof Error ? error.message : "unknown-processing-error";
        if (error instanceof TerminalMessageError) {
          log("message-terminal-rejected", { message_id: item.value.message_id, reason });
          item.raw.ack();
        } else {
          log("message-retry", { message_id: item.value.message_id, reason });
          item.raw.retry({ delaySeconds: RETRY_DELAY_SECONDS });
        }
      }
    }
  },
};

export default worker;
