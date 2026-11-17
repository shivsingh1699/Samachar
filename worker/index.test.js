import { test } from "node:test";
import assert from "node:assert/strict";
import worker from "./index.js";

const TOKEN = "t".repeat(40);
const GOOD = '{"schema":"hub-news-pins-v1","count":0,"pins":[]}';

function env(extra = {}) {
  const store = new Map();
  return { store, PUSH_TOKEN: TOKEN, PINS: { get: async (k) => (store.has(k) ? store.get(k) : null), put: async (k, v) => void store.set(k, v) }, ...extra };
}
const put = (body, token = TOKEN, headers = {}) =>
  new Request("https://w.example/pins", { method: "PUT", body, headers: { authorization: `Bearer ${token}`, ...headers } });

test("PUT with the right passphrase stores the file and GET serves it", async () => {
  const e = env();
  const r = await worker.fetch(put(GOOD), e);
  assert.equal(r.status, 200);
  assert.equal(e.store.get("pins-latest"), GOOD);
  const g = await worker.fetch(new Request("https://w.example/pins.json"), e);
  assert.equal(g.status, 200);
  assert.equal(await g.text(), GOOD);
  assert.equal(g.headers.get("access-control-allow-origin"), "*");
  assert.match(g.headers.get("cache-control"), /max-age=60/);
});

test("wrong, missing or malformed passphrase is refused and nothing is stored", async () => {
  const e = env();
  for (const req of [put(GOOD, "x".repeat(40)), put(GOOD, ""), new Request("https://w.example/pins", { method: "PUT", body: GOOD })]) {
    assert.equal((await worker.fetch(req, e)).status, 401);
  }
  assert.equal(e.store.size, 0);
});

test("a short or missing secret in the Worker refuses everything (misconfigured)", async () => {
  assert.equal((await worker.fetch(put(GOOD, "short"), env({ PUSH_TOKEN: "short" }))).status, 503);
  assert.equal((await worker.fetch(put(GOOD), env({ PUSH_TOKEN: undefined }))).status, 503);
});

test("oversize and non-pins bodies are refused", async () => {
  const e = env();
  const big = GOOD.slice(0, -2) + "x".repeat(400_001) + "]}";
  assert.equal((await worker.fetch(put(big), e)).status, 413);
  assert.equal((await worker.fetch(put("<html>hi</html>"), e)).status, 400);
  assert.equal(e.store.size, 0);
});

test("a refused upload keeps the last good file", async () => {
  const e = env();
  await worker.fetch(put(GOOD), e);
  await worker.fetch(put("nonsense"), e);
  await worker.fetch(put(GOOD, "x".repeat(40)), e);
  assert.equal(e.store.get("pins-latest"), GOOD);
});

test("GET before any data is a 404; other paths and methods are refused", async () => {
  const e = env();
  assert.equal((await worker.fetch(new Request("https://w.example/pins.json"), e)).status, 404);
  assert.equal((await worker.fetch(new Request("https://w.example/pins.json", { method: "POST", body: "x" }), e)).status, 405);
  assert.equal((await worker.fetch(new Request("https://w.example/pins", { method: "GET" }), e)).status, 405);
  assert.equal((await worker.fetch(new Request("https://w.example/other"), e)).status, 404);
});

test("CORS preflight answers 204, and ALLOW_ORIGIN narrows the origin", async () => {
  const e = env({ ALLOW_ORIGIN: "https://shiv-hub.netlify.app" });
  const r = await worker.fetch(new Request("https://w.example/pins.json", { method: "OPTIONS" }), e);
  assert.equal(r.status, 204);
  assert.equal(r.headers.get("access-control-allow-origin"), "https://shiv-hub.netlify.app");
});
