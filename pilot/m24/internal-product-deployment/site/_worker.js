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
  if (!admission.ok) return jsonError(admission.reason, 403);
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
  if (!expectedOwnerHash) return denied("M26_OWNER_SUBJECT_HASH_UNCONFIGURED");

  if (env.M26_ALLOW_LOCAL_OWNER_HEADER === "true") {
    const supplied = String(request.headers.get("x-m26-owner-subject-hash") || "").toLowerCase();
    if (supplied && timingSafeEqualHex(supplied, expectedOwnerHash)) {
      return admitted(expectedOwnerHash, "local_owner_header");
    }
  }

  const token = request.headers.get("cf-access-jwt-assertion");
  if (!token) return denied("M26_OWNER_ACCESS_JWT_MISSING");

  const contract = resolveAccessJwtContract(token, env);
  if (!contract.ok) return denied(contract.reason);

  let payload;
  try {
    payload = await verifyAccessJwt(token, contract.issuer, contract.audience);
  } catch (_error) {
    return denied("M26_OWNER_ACCESS_JWT_INVALID");
  }

  const expectedEmailHash = String(env.M26_OWNER_EMAIL_SHA256 || "").toLowerCase();
  if (!expectedEmailHash) return denied("M26_OWNER_EMAIL_HASH_UNCONFIGURED");
  const email = String(payload.email || "").trim().toLowerCase();
  if (!email) return denied("M26_OWNER_ACCESS_EMAIL_MISSING");
  const actualEmailHash = await sha256Hex(email);
  if (!timingSafeEqualHex(actualEmailHash, expectedEmailHash)) {
    return denied("M26_OWNER_ACCESS_EMAIL_NOT_ALLOWLISTED");
  }
  return admitted(expectedOwnerHash, contract.identitySource);
}

function admitted(ownerSubjectHash, identitySource) {
  return { ok: true, ownerSubjectHash, identitySource };
}

function denied(reason) {
  return { ok: false, reason };
}

function resolveAccessJwtContract(token, env) {
  const configuredIssuer = normalizeTeamDomain(env.ACCESS_TEAM_DOMAIN || env.TEAM_DOMAIN);
  const configuredAudience = String(env.ACCESS_AUD || env.POLICY_AUD || "").trim();
  if (configuredIssuer && configuredAudience) {
    return {
      ok: true,
      issuer: configuredIssuer,
      audience: configuredAudience,
      identitySource: "verified_cloudflare_access_jwt_email",
    };
  }

  let unsignedPayload;
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return { ok: false, reason: "M26_OWNER_ACCESS_JWT_INVALID" };
    unsignedPayload = decodeJwtPart(parts[1]);
  } catch (_error) {
    return { ok: false, reason: "M26_OWNER_ACCESS_JWT_INVALID" };
  }

  const inferredIssuer = normalizeTeamDomain(unsignedPayload.iss || "");
  const inferredAudiences = Array.isArray(unsignedPayload.aud)
    ? unsignedPayload.aud.map((value) => String(value || "").trim()).filter(Boolean)
    : [String(unsignedPayload.aud || "").trim()].filter(Boolean);
  if (!inferredIssuer || inferredAudiences.length !== 1) {
    return { ok: false, reason: "M26_OWNER_ACCESS_JWT_CONFIG_MISSING" };
  }
  if (!isCloudflareAccessIssuer(inferredIssuer)) {
    return { ok: false, reason: "M26_OWNER_ACCESS_JWT_INVALID" };
  }
  return {
    ok: true,
    issuer: inferredIssuer,
    audience: inferredAudiences[0],
    identitySource: "verified_cloudflare_access_jwt_email_inferred_contract",
  };
}

function normalizeTeamDomain(value) {
  const raw = String(value || "").trim().replace(/\/$/, "");
  if (!raw) return "";
  return raw.startsWith("https://") ? raw : `https://${raw}`;
}

function isCloudflareAccessIssuer(value) {
  try {
    const hostname = new URL(value).hostname.toLowerCase();
    return hostname === "cloudflareaccess.com" || hostname.endsWith(".cloudflareaccess.com");
  } catch (_error) {
    return false;
  }
}

async function verifyAccessJwt(token, issuer, audience) {
  const parts = token.split(".");
  if (parts.length !== 3) throw new Error("malformed JWT");
  const header = decodeJwtPart(parts[0]);
  const payload = decodeJwtPart(parts[1]);
  if (header.alg !== "RS256" || !header.kid) throw new Error("unsupported JWT header");

  const now = Math.floor(Date.now() / 1000);
  if (payload.iss !== issuer) throw new Error("issuer mismatch");
  const audiences = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!audiences.includes(audience)) throw new Error("audience mismatch");
  if (!Number.isFinite(payload.exp) || payload.exp <= now) throw new Error("expired JWT");
  if (Number.isFinite(payload.nbf) && payload.nbf > now + 30) throw new Error("JWT not active");

  const certsResponse = await fetch(`${issuer}/cdn-cgi/access/certs`, {
    cf: { cacheTtl: 300, cacheEverything: true },
  });
  if (!certsResponse.ok) throw new Error("JWKS unavailable");
  const jwks = await certsResponse.json();
  const key = (Array.isArray(jwks.keys) ? jwks.keys : []).find((item) => item.kid === header.kid);
  if (!key) throw new Error("signing key missing");
  const cryptoKey = await crypto.subtle.importKey(
    "jwk",
    key,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["verify"],
  );
  const signature = base64UrlBytes(parts[2]);
  const signed = new TextEncoder().encode(`${parts[0]}.${parts[1]}`);
  const valid = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", cryptoKey, signature, signed);
  if (!valid) throw new Error("signature mismatch");
  return payload;
}

function decodeJwtPart(value) {
  return JSON.parse(new TextDecoder().decode(base64UrlBytes(value)));
}

function base64UrlBytes(value) {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((value.length + 3) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
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
      schema_version: "knowledge-engine-m26-pa7-ask-worker-error/v2",
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
