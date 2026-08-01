let ACCESS_JWKS_CACHE = null;

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
    "x-m26-owner-identity-source": admission.identitySource,
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

  const expectedEmailHash = String(env.M26_OWNER_EMAIL_SHA256 || "").toLowerCase();
  if (!expectedEmailHash) return null;

  const accessJwt = request.headers.get("cf-access-jwt-assertion");
  if (accessJwt) {
    const jwtAdmission = await ownerAdmissionFromAccessJwt(accessJwt, env, expectedEmailHash);
    if (jwtAdmission) {
      return { ownerSubjectHash: expectedOwnerHash, identitySource: jwtAdmission.identitySource };
    }
  }

  const authenticatedEmail = request.headers.get("cf-access-authenticated-user-email");
  if (authenticatedEmail) {
    const actualEmailHash = await sha256Hex(authenticatedEmail.trim().toLowerCase());
    if (timingSafeEqualHex(actualEmailHash, expectedEmailHash)) {
      return {
        ownerSubjectHash: expectedOwnerHash,
        identitySource: "cloudflare_access_authenticated_email_header_hash",
      };
    }
  }
  return null;
}

async function ownerAdmissionFromAccessJwt(accessJwt, env, expectedEmailHash) {
  let payload = null;
  let verified = false;
  const teamDomain = normalizedAccessTeamDomain(env.ACCESS_TEAM_DOMAIN);
  const accessAud = String(env.ACCESS_AUD || "").trim();
  try {
    if (teamDomain && accessAud) {
      payload = await verifyAccessJwtPayload(accessJwt, teamDomain, accessAud);
      verified = true;
    } else {
      payload = decodeAccessJwtPayload(accessJwt);
    }
  } catch (_error) {
    return null;
  }
  const email = String(payload.email || payload.common_name || "").trim().toLowerCase();
  if (!email) return null;
  const actualEmailHash = await sha256Hex(email);
  if (!timingSafeEqualHex(actualEmailHash, expectedEmailHash)) return null;
  return {
    identitySource: verified
      ? "cloudflare_access_jwt_verified_email_hash"
      : "cloudflare_access_jwt_payload_email_hash_outer_access_boundary",
  };
}

function normalizedAccessTeamDomain(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const withScheme = raw.startsWith("https://") ? raw : `https://${raw}`;
  return withScheme.replace(/\/+$/, "");
}

async function verifyAccessJwtPayload(token, teamDomain, accessAud) {
  const parts = token.split(".");
  if (parts.length !== 3) throw new Error("invalid_access_jwt_shape");
  const header = base64UrlJson(parts[0]);
  const payload = base64UrlJson(parts[1]);
  if (header.alg !== "RS256") throw new Error("unsupported_access_jwt_alg");
  if (!header.kid) throw new Error("missing_access_jwt_kid");

  const jwks = await fetchAccessJwks(teamDomain);
  const jwk = jwks.keys.find((item) => item.kid === header.kid);
  if (!jwk) throw new Error("access_jwt_kid_not_found");
  const key = await crypto.subtle.importKey(
    "jwk",
    jwk,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["verify"],
  );
  const verified = await crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5",
    key,
    base64UrlBytes(parts[2]),
    new TextEncoder().encode(`${parts[0]}.${parts[1]}`),
  );
  if (!verified) throw new Error("access_jwt_signature_invalid");
  verifyAccessClaims(payload, teamDomain, accessAud);
  return payload;
}

async function fetchAccessJwks(teamDomain) {
  const now = Date.now();
  if (
    ACCESS_JWKS_CACHE &&
    ACCESS_JWKS_CACHE.teamDomain === teamDomain &&
    ACCESS_JWKS_CACHE.expiresAt > now
  ) {
    return ACCESS_JWKS_CACHE.jwks;
  }
  const response = await fetch(`${teamDomain}/cdn-cgi/access/certs`, {
    headers: { accept: "application/json" },
  });
  if (!response.ok) throw new Error("access_jwks_fetch_failed");
  const jwks = await response.json();
  if (!jwks || !Array.isArray(jwks.keys)) throw new Error("access_jwks_invalid");
  ACCESS_JWKS_CACHE = {
    teamDomain,
    jwks,
    expiresAt: now + 5 * 60 * 1000,
  };
  return jwks;
}

function verifyAccessClaims(payload, teamDomain, accessAud) {
  const now = Math.floor(Date.now() / 1000);
  if (typeof payload.exp !== "number" || payload.exp <= now) {
    throw new Error("access_jwt_expired");
  }
  if (typeof payload.nbf === "number" && payload.nbf > now + 60) {
    throw new Error("access_jwt_not_yet_valid");
  }
  if (payload.iss !== teamDomain) {
    throw new Error("access_jwt_issuer_mismatch");
  }
  const aud = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!aud.includes(accessAud)) {
    throw new Error("access_jwt_audience_mismatch");
  }
}

function decodeAccessJwtPayload(token) {
  const parts = token.split(".");
  if (parts.length !== 3) throw new Error("invalid_access_jwt_shape");
  return base64UrlJson(parts[1]);
}

function base64UrlJson(value) {
  return JSON.parse(new TextDecoder().decode(base64UrlBytes(value)));
}

function base64UrlBytes(value) {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(
    Math.ceil(value.length / 4) * 4,
    "=",
  );
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
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
