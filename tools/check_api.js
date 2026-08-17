// Exercise web/api/index.js without deploying it.
//
// The function is the one piece of this repository that only runs on Vercel,
// which makes it the one piece nobody sees fail until it is live. Its routing
// still cannot be proven here, but its behaviour can: that it injects the
// count when storage answers, that it serves the page unchanged when storage
// is absent or broken, and that it never takes the site down.
//
// Usage: node tools/check_api.js
const path = require("path");
const assert = require("assert");

const ROOT = path.join(__dirname, "..");
const HANDLER = path.join(ROOT, "web", "api", "index.js");
const PLACEHOLDER = "<!--VISITOR_COUNT-->";

let failures = 0;
function check(label, fn) {
  try {
    fn();
    console.log("  PASS  " + label);
  } catch (err) {
    console.log("  FAIL  " + label + "  — " + err.message);
    failures++;
  }
}

// Minimal stand-ins for Vercel's req/res.
function fakeRes() {
  return {
    statusCode: 0,
    headers: {},
    body: null,
    setHeader(k, v) { this.headers[k.toLowerCase()] = v; },
    end(payload) { this.body = payload === undefined ? "" : payload; },
  };
}

async function run(env) {
  delete require.cache[require.resolve(HANDLER)];
  const saved = {
    url: process.env.SUPABASE_URL,
    key: process.env.SUPABASE_KEY,
    fetch: global.fetch,
  };
  if (env.url === undefined) { delete process.env.SUPABASE_URL; }
  else { process.env.SUPABASE_URL = env.url; }
  if (env.key === undefined) { delete process.env.SUPABASE_KEY; }
  else { process.env.SUPABASE_KEY = env.key; }
  if (env.fetch) { global.fetch = env.fetch; }

  try {
    const handler = require(HANDLER);
    const res = fakeRes();
    await handler({ method: "GET", url: "/" }, res);
    return res;
  } finally {
    if (saved.url === undefined) { delete process.env.SUPABASE_URL; }
    else { process.env.SUPABASE_URL = saved.url; }
    if (saved.key === undefined) { delete process.env.SUPABASE_KEY; }
    else { process.env.SUPABASE_KEY = saved.key; }
    global.fetch = saved.fetch;
  }
}

(async () => {
  console.log("web/api/index.js");

  // Storage unconfigured: the page must still be served, minus the counter.
  const bare = await run({});
  check("unconfigured: serves the page", () => {
    assert.strictEqual(bare.statusCode, 200);
    assert.ok(bare.body.includes("<title>"), "no document returned");
    assert.ok(bare.body.length > 10000, "document looks truncated");
  });
  check("unconfigured: placeholder consumed, no counter shown", () => {
    assert.ok(!bare.body.includes(PLACEHOLDER), "placeholder left in the page");
    assert.ok(!/class="visits"/.test(bare.body), "counter rendered anyway");
  });
  check("unconfigured: html content type", () => {
    assert.match(bare.headers["content-type"], /text\/html/);
  });

  // Storage answers: the count is injected server-side.
  const ok = await run({
    url: "https://example.supabase.co",
    key: "test-key",
    fetch: async () => ({ ok: true, json: async () => 1234 }),
  });
  check("configured: count injected into the document", () => {
    assert.ok(/class="visits glass"/.test(ok.body), "counter markup missing");
    assert.ok(ok.body.includes('aria-label="1,234 visits.'),
              "count not formatted into the accessible name");
    assert.ok(!ok.body.includes(PLACEHOLDER), "placeholder left in the page");
  });
  check("configured: one odometer cell per digit", () => {
    const digits = (ok.body.match(/<span class="d">\d<\/span>/g) || []).length;
    const seps = (ok.body.match(/<span class="sep">,<\/span>/g) || []).length;
    assert.strictEqual(digits, 4, `expected 4 digit cells, got ${digits}`);
    assert.strictEqual(seps, 1, `expected 1 separator, got ${seps}`);
  });
  // The dial is driven entirely by --rev. If that were ever absent or out of
  // range the gauge would read a flat zero forever while the digits looked
  // right -- a failure nobody would think to check for.
  check("configured: gauge is driven to a sane position", () => {
    const found = ok.body.match(/--rev:([0-9.]+)/);
    assert.ok(found, "--rev not set on the counter");
    const rev = Number(found[1]);
    assert.ok(rev > 0 && rev < 1, `--rev out of range: ${rev}`);
    // log10(1235)/6 = 0.5163...
    assert.ok(Math.abs(rev - Math.log10(1235) / 6) < 1e-3,
              `--rev does not track log10(count): ${rev}`);
  });
  check("configured: response is not cached", () => {
    assert.match(ok.headers["cache-control"], /no-store/);
  });

  const one = await run({
    url: "https://example.supabase.co",
    key: "test-key",
    fetch: async () => ({ ok: true, json: async () => 1 }),
  });
  check("configured: '1 visit', not '1 visits'", () => {
    assert.ok(one.body.includes('aria-label="1 visit.'), "singular not handled");
    assert.ok(one.body.includes('class="cap">visit<'), "cap not singular");
  });
  check("configured: a single visit still moves the needle off the stop", () => {
    const rev = Number(one.body.match(/--rev:([0-9.]+)/)[1]);
    assert.ok(rev > 0, "one visit renders a dead gauge");
  });

  // A dollar sign in the replacement would be read as a pattern by
  // String.replace and splice the document into itself.
  check("substitution is literal, not pattern-expanded", () => {
    assert.ok(!ok.body.includes("<!--VISITOR_COUNT"), "placeholder residue");
    assert.strictEqual((ok.body.match(/<!DOCTYPE/gi) || []).length, 1,
                       "document appears spliced into itself");
  });

  // Storage broken: every failure path must still return the document.
  const failures_ = [
    ["storage returns an error status",
     async () => ({ ok: false, json: async () => ({}) })],
    ["storage throws", async () => { throw new Error("ECONNREFUSED"); }],
    ["storage returns nonsense",
     async () => ({ ok: true, json: async () => "not-a-number" })],
  ];
  for (const [label, fetchImpl] of failures_) {
    const res = await run({
      url: "https://example.supabase.co", key: "k", fetch: fetchImpl,
    });
    check(label + ": page still served, counter hidden", () => {
      assert.strictEqual(res.statusCode, 200);
      assert.ok(res.body.includes("<title>"), "no document returned");
      assert.ok(!res.body.includes(PLACEHOLDER), "placeholder left in page");
      assert.ok(!/class="visits"/.test(res.body), "counter rendered anyway");
    });
  }

  // The request shape storage actually requires. A publishable key is not a
  // JWT, so repeating it in Authorization makes the gateway reject the call --
  // and the rejection is invisible, because the function is built to swallow
  // failures and serve the page anyway. Nothing else would catch this.
  let sent = null;
  await run({
    url: "https://example.supabase.co/",
    key: "sb_publishable_example",
    fetch: async (target, init) => {
      sent = { target, init };
      return { ok: true, json: async () => 7 };
    },
  });
  check("storage is called with the documented header shape", () => {
    assert.ok(sent, "storage was never called");
    assert.strictEqual(
      sent.target, "https://example.supabase.co/rest/v1/rpc/increment_visits",
      "wrong endpoint, or a trailing slash was not trimmed");
    assert.strictEqual(sent.init.method, "POST");
    const names = Object.keys(sent.init.headers).map((h) => h.toLowerCase());
    assert.ok(names.includes("apikey"), "key must be sent on the apikey header");
    assert.ok(!names.includes("authorization"),
              "a publishable key in Authorization is rejected as a bad JWT");
  });

  // If the bundled document is missing, the function must NOT redirect. The
  // route table canonicalises /index.html to /, so a redirect there comes
  // straight back here and loops until the browser gives up.
  {
    const fs = require("fs");
    const real = fs.readFileSync;
    fs.readFileSync = function (p, enc) {
      if (String(p).endsWith("index.html")) {
        throw Object.assign(new Error("ENOENT"), { code: "ENOENT" });
      }
      return real.apply(this, arguments);
    };
    let res;
    try {
      res = await run({});
    } finally {
      fs.readFileSync = real;
    }
    check("missing document: does not redirect into a loop", () => {
      assert.ok(res.statusCode < 300 || res.statusCode >= 400,
                `redirected with ${res.statusCode}; /index.html returns here`);
      assert.strictEqual(res.headers.location, undefined,
                         "a Location header would bounce back to this handler");
    });
    check("missing document: still answers with something readable", () => {
      assert.ok(/text\/html/.test(res.headers["content-type"] || ""));
      assert.ok(res.body.length > 0, "empty response");
      assert.ok(/github\.com/.test(res.body), "no route to the tool offered");
    });
  }

  // The counter must never leak anything about the visitor.
  check("no request metadata is sent to storage", () => {
    const src = require("fs").readFileSync(HANDLER, "utf8");
    for (const leak of ["headers[", "x-forwarded-for", "req.headers",
                        "user-agent", "socket", "remoteAddress"]) {
      assert.ok(!src.includes(leak),
                `function references ${leak}; it must not read the request`);
    }
  });

  console.log(failures ? `\n${failures} CHECK(S) FAILED` : "\nAll checks passed.");
  process.exit(failures ? 1 : 0);
})();
