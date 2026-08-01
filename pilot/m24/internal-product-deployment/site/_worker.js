let accessJwksCache = null;
let accessJwksCachedAt = 0;
const ACCESS_JWKS_TTL_MS = 15 * 60 * 1000;
const LEGACY_UNTRUSTED_EMAIL_HEADER = "cf-access-authenticated-user-email";

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
    if (url.pathname === "/api/m26/graph") {
      if (request.method !== "GET") return jsonError("M26_GRAPH_METHOD_NOT_ALLOWED", 405);
      return handleOwnerApi(request, env, "/api/m26/graph");
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
  if (!admission) return jsonError("M26_OWNER_ACCESS_INTERNAL_DENIAL", 403);
  if (!admission.ok) return jsonError(admission.reasonCode, 403);
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
  void LEGACY_UNTRUSTED_EMAIL_HEADER;
  const expectedOwnerHash = String(env.KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH || "").toLowerCase();
  if (!expectedOwnerHash) return denied("M26_OWNER_SUBJECT_HASH_UNCONFIGURED");
  if (env.M26_ALLOW_LOCAL_OWNER_HEADER === "true") {
    const supplied = String(request.headers.get("x-m26-owner-subject-hash") || "").toLowerCase();
    if (supplied && timingSafeEqualHex(supplied, expectedOwnerHash)) {
      return admitted(expectedOwnerHash, "local_owner_header");
    }
  }

  const accessJwt = request.headers.get("cf-access-jwt-assertion");
  if (!accessJwt) return denied("M26_OWNER_ACCESS_JWT_MISSING");
  const expectedEmailHash = String(env.M26_OWNER_EMAIL_SHA256 || "").toLowerCase();
  const teamDomain = normalizeTeamDomain(env.ACCESS_TEAM_DOMAIN);
  const audience = String(env.ACCESS_AUD || "").trim();
  if (!expectedEmailHash || !teamDomain || !audience) {
    return denied("M26_OWNER_ACCESS_CONFIG_MISSING");
  }

  let payload;
  try {
    payload = await verifyAccessJwt(accessJwt, teamDomain, audience);
  } catch (_error) {
    return denied("M26_OWNER_ACCESS_JWT_INVALID");
  }
  const authenticatedEmail = String(payload.email || "").trim().toLowerCase();
  if (!authenticatedEmail) return denied("M26_OWNER_ACCESS_EMAIL_MISSING");
  const actualEmailHash = await sha256Hex(authenticatedEmail);
  if (!timingSafeEqualHex(actualEmailHash, expectedEmailHash)) {
    return denied("M26_OWNER_ACCESS_EMAIL_MISMATCH");
  }
  return admitted(expectedOwnerHash, "verified_cloudflare_access_jwt_email");
}

function admitted(ownerSubjectHash, identitySource) {
  return { ok: true, ownerSubjectHash, identitySource };
}

function denied(reasonCode) {
  return { ok: false, reasonCode };
}

function normalizeTeamDomain(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  try {
    const url = new URL(raw.includes("://") ? raw : `https://${raw}`);
    if (url.protocol !== "https:" || !url.hostname.endsWith(".cloudflareaccess.com")) return "";
    return `${url.protocol}//${url.hostname}`;
  } catch (_error) {
    return "";
  }
}

async function verifyAccessJwt(token, teamDomain, expectedAudience) {
  const parts = token.split(".");
  if (parts.length !== 3) throw new Error("invalid JWT shape");
  const header = JSON.parse(new TextDecoder().decode(base64UrlBytes(parts[0])));
  const payload = JSON.parse(new TextDecoder().decode(base64UrlBytes(parts[1])));
  if (header.alg !== "RS256" || typeof header.kid !== "string") {
    throw new Error("unsupported JWT header");
  }
  const key = await accessVerificationKey(teamDomain, header.kid);
  const verified = await crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5",
    key,
    base64UrlBytes(parts[2]),
    new TextEncoder().encode(`${parts[0]}.${parts[1]}`),
  );
  if (!verified) throw new Error("JWT signature invalid");

  const now = Math.floor(Date.now() / 1000);
  if (String(payload.iss || "").replace(/\/$/, "") !== teamDomain.replace(/\/$/, "")) {
    throw new Error("JWT issuer mismatch");
  }
  const audiences = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!audiences.includes(expectedAudience)) throw new Error("JWT audience mismatch");
  if (!Number.isFinite(payload.exp) || payload.exp <= now) throw new Error("JWT expired");
  if (Number.isFinite(payload.nbf) && payload.nbf > now + 30) throw new Error("JWT not active");
  return payload;
}

async function accessVerificationKey(teamDomain, kid) {
  const now = Date.now();
  if (!accessJwksCache || now - accessJwksCachedAt > ACCESS_JWKS_TTL_MS) {
    const response = await fetch(`${teamDomain}/cdn-cgi/access/certs`, {
      headers: { accept: "application/json" },
      cf: { cacheTtl: 900, cacheEverything: true },
    });
    if (!response.ok) throw new Error("Access JWKS unavailable");
    const document = await response.json();
    if (!document || !Array.isArray(document.keys)) throw new Error("Access JWKS invalid");
    accessJwksCache = document.keys;
    accessJwksCachedAt = now;
  }
  let jwk = accessJwksCache.find((candidate) => candidate && candidate.kid === kid);
  if (!jwk) {
    accessJwksCache = null;
    accessJwksCachedAt = 0;
    const response = await fetch(`${teamDomain}/cdn-cgi/access/certs`, {
      headers: { accept: "application/json" },
      cf: { cacheTtl: 0, cacheEverything: false },
    });
    if (!response.ok) throw new Error("Access JWKS refresh unavailable");
    const document = await response.json();
    if (!document || !Array.isArray(document.keys)) throw new Error("Access JWKS refresh invalid");
    accessJwksCache = document.keys;
    accessJwksCachedAt = Date.now();
    jwk = accessJwksCache.find((candidate) => candidate && candidate.kid === kid);
  }
  if (!jwk) throw new Error("Access signing key missing");
  return crypto.subtle.importKey(
    "jwk",
    jwk,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["verify"],
  );
}

function base64UrlBytes(value) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
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
    },
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
