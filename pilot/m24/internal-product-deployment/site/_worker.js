export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const host = url.host;
    if (
      host === "llm-wiki-m24-internal.pages.dev" ||
      host.endsWith(".llm-wiki-m24-internal.pages.dev")
    ) {
      return new Response("Forbidden", forbiddenHeaders());
    }

    if (url.pathname === "/ask" || url.pathname === "/ask/") {
      return env.ASSETS.fetch(assetRequest(request, "/index.html"));
    }
    if (url.pathname === "/api/m26/health") {
      return handleOwnerApi(request, env, "/api/m26/health");
    }
    if (url.pathname === "/api/m26/query") {
      if (request.method !== "POST") return jsonError("M26_ASK_METHOD_NOT_ALLOWED", 405);
      return handleOwnerApi(request, env, "/api/m26/query");
    }
    return env.ASSETS.fetch(request);
  },
};

function forbiddenHeaders() {
  return {
    status: 403,
    headers: {
      "cache-control": "no-store",
      "content-type": "text/plain; charset=utf-8",
    },
  };
}

function assetRequest(original, path) {
  const url = new URL(original.url);
  url.pathname = path;
  url.search = "";
  url.hash = "";
  return new Request(url, original);
}

async function handleOwnerApi(request, env, backendPath) {
  const admission = await verifyOwnerAccess(request, env);
  if (!admission) return jsonError("M26_OWNER_ACCESS_DENIED", 403);
  const backend = env.M26_QUERY_BACKEND_URL;
  if (!backend) return jsonError("M26_QUERY_BACKEND_UNCONFIGURED", 503);

  let body = null;
  if (backendPath === "/api/m26/query") {
    const parsed = await boundedJsonRequest(request);
    if (!parsed.ok) return jsonError(parsed.reason, parsed.status);
    body = JSON.stringify({ question: parsed.question });
  }

  const backendUrl = new URL(backendPath, backend.endsWith("/") ? backend : `${backend}/`);
  const headers = new Headers({
    "content-type": "application/json",
    "x-m26-owner-subject-hash": admission.ownerSubjectHash,
  });
  if (env.M26_QUERY_BACKEND_TOKEN) {
    headers.set("authorization", `Bearer ${env.M26_QUERY_BACKEND_TOKEN}`);
  }
  const backendResponse = await fetch(backendUrl, {
    method: backendPath === "/api/m26/query" ? "POST" : "GET",
    headers,
    body,
  });
  return new Response(backendResponse.body, {
    status: backendResponse.status,
    headers: {
      "cache-control": "no-store",
      "content-type": backendResponse.headers.get("content-type") || "application/json",
    },
  });
}

async function verifyOwnerAccess(request, env) {
  const expectedOwnerHash = String(env.KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH || "").toLowerCase();
  if (!expectedOwnerHash) return null;
  if (env.M26_ALLOW_LOCAL_OWNER_HEADER === "true") {
    const supplied = String(request.headers.get("x-m26-owner-subject-hash") || "").toLowerCase();
    if (supplied && timingSafeEqualHex(supplied, expectedOwnerHash)) {
      return { ownerSubjectHash: expectedOwnerHash, identitySource: "local_owner_header" };
    }
  }

  const accessJwt = request.headers.get("cf-access-jwt-assertion");
  const authenticatedEmail = request.headers.get("cf-access-authenticated-user-email");
  const expectedEmailHash = String(env.M26_OWNER_EMAIL_SHA256 || "").toLowerCase();
  if (!accessJwt || !authenticatedEmail || !expectedEmailHash) return null;
  const actualEmailHash = await sha256Hex(authenticatedEmail.trim().toLowerCase());
  if (!timingSafeEqualHex(actualEmailHash, expectedEmailHash)) return null;
  return { ownerSubjectHash: expectedOwnerHash, identitySource: "cloudflare_access_email_hash" };
}

async function boundedJsonRequest(request) {
  const body = await request.text();
  if (body.length > 4096) return { ok: false, status: 413, reason: "M26_ASK_BODY_TOO_LARGE" };
  let payload = null;
  try {
    payload = JSON.parse(body);
  } catch (_error) {
    return { ok: false, status: 400, reason: "M26_ASK_INVALID_JSON" };
  }
  if (!payload || typeof payload !== "object" || typeof payload.question !== "string") {
    return { ok: false, status: 400, reason: "M26_ASK_QUESTION_MISSING" };
  }
  const question = payload.question.trim().replace(/\s+/g, " ");
  if (!question) return { ok: false, status: 400, reason: "M26_ASK_QUESTION_EMPTY" };
  if (question.length > 2000) {
    return { ok: false, status: 413, reason: "M26_ASK_QUESTION_TOO_LONG" };
  }
  return { ok: true, question };
}

function jsonError(reasonCode, status) {
  return new Response(
    JSON.stringify({
      schema_version: "knowledge-engine-m26-pa7-ask-worker-error/v1",
      status: "error",
      reason_code: reasonCode,
    }),
    {
      status,
      headers: {
        "cache-control": "no-store",
        "content-type": "application/json; charset=utf-8",
      },
    }
  );
}

async function sha256Hex(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function timingSafeEqualHex(left, right) {
  if (left.length !== right.length) return false;
  let mismatch = 0;
  for (let index = 0; index < left.length; index += 1) {
    mismatch |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return mismatch === 0;
}
