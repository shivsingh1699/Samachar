// Samachar Worker (Cloudflare Workers, free plan).
//   GET  /pins.json  -> the latest pins file from KV (public news data; CORS open)
//   PUT  /pins       -> store a new file. Needs "Authorization: Bearer <PUSH_TOKEN>". Only the one key below can change.
// Bindings: KV namespace PINS, secret PUSH_TOKEN, optional variable ALLOW_ORIGIN (default "*").
// The Worker never parses the JSON: a 10 ms CPU limit applies, so it only passes bytes through.

const KEY = "pins-latest";
const MAX_BYTES = 400_000;
const PREFIX = '{"schema":"hub-news-pins-v1"';
const enc = new TextEncoder();

function cors(env) {
  return {
    "access-control-allow-origin": env.ALLOW_ORIGIN || "*",
    "access-control-allow-methods": "GET, HEAD, OPTIONS",
    "access-control-allow-headers": "content-type",
    "access-control-max-age": "86400",
  };
}

function json(obj, status, extra = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "x-content-type-options": "nosniff", ...extra },
  });
}

// Compare two secrets without leaking where they differ: hash both, then XOR every byte.
async function sameSecret(a, b) {
  const [da, db] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(a)),
    crypto.subtle.digest("SHA-256", enc.encode(b)),
  ]);
  const x = new Uint8Array(da), y = new Uint8Array(db);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    const m = request.method;

    if (m === "OPTIONS") return new Response(null, { status: 204, headers: cors(env) });

    if (pathname === "/pins.json") {
      if (m !== "GET" && m !== "HEAD") return json({ error: "method not allowed" }, 405, { allow: "GET, HEAD, OPTIONS" });
      const body = await env.PINS.get(KEY, { cacheTtl: 60 });
      if (body === null) return json({ error: "no data yet" }, 404, cors(env));
      return new Response(m === "HEAD" ? null : body, {
        status: 200,
        headers: {
          "content-type": "application/json; charset=utf-8",
          "cache-control": "public, max-age=60",
          "x-content-type-options": "nosniff",
          ...cors(env),
        },
      });
    }

    if (pathname === "/pins") {
      if (m !== "PUT") return json({ error: "method not allowed" }, 405, { allow: "PUT" });
      const secret = env.PUSH_TOKEN;
      if (typeof secret !== "string" || secret.length < 20) return json({ error: "not configured" }, 503);
      const auth = request.headers.get("authorization") || "";
      if (!auth.startsWith("Bearer ") || !(await sameSecret(auth.slice(7), secret))) {
        return json({ error: "unauthorized" }, 401);
      }
      // Only now read the body: callers without the passphrase never make the Worker read anything.
      const declared = Number(request.headers.get("content-length") || 0);
      if (declared > MAX_BYTES) return json({ error: "too large" }, 413);
      const text = await request.text();
      const size = enc.encode(text).length;
      if (size > MAX_BYTES) return json({ error: "too large" }, 413);
      if (!text.startsWith(PREFIX)) return json({ error: "not a pins file" }, 400);
      await env.PINS.put(KEY, text);
      return json({ ok: true, bytes: size }, 200);
    }

    return json({ error: "not found" }, 404);
  },
};
