// Serves the scanner page with the visit count substituted in.
//
// Why this exists at all: the page advertises `connect-src 'none'` and "you can
// turn off your wifi and it still works". A counter that the browser fetched
// would make that claim false. So the count is resolved here, on the server,
// and the number is already in the HTML by the time it reaches the browser. The
// client makes zero extra requests and the Content-Security-Policy is untouched.
//
// What is stored: one integer. No IP address, no user agent, no per-visitor row,
// no timestamp. There is nothing here to correlate a visit back to a person.
//
// Everything is best effort. A missing environment variable, an unreachable
// database, or a slow response must never cost the visitor the page, so every
// failure path still returns the document with the counter simply absent.

const fs = require("fs");
const path = require("path");

const PLACEHOLDER = "<!--VISITOR_COUNT-->";
const DB_TIMEOUT_MS = 800;

let cachedPage = null;

function loadPage() {
  if (cachedPage !== null) {
    return cachedPage;
  }
  // includeFiles (see vercel.json) puts index.html beside the bundled function;
  // the cwd fallback covers a local `vercel dev` run.
  const candidates = [
    path.join(__dirname, "..", "index.html"),
    path.join(process.cwd(), "index.html"),
  ];
  for (const candidate of candidates) {
    try {
      cachedPage = fs.readFileSync(candidate, "utf8");
      return cachedPage;
    } catch (err) {
      // try the next candidate
    }
  }
  return null;
}

async function bumpVisits() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_KEY;
  if (!url || !key) {
    return null; // not configured yet: render without a counter
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), DB_TIMEOUT_MS);
  try {
    const res = await fetch(url.replace(/\/$/, "") + "/rest/v1/rpc/increment_visits", {
      method: "POST",
      headers: {
        apikey: key,
        Authorization: "Bearer " + key,
        "Content-Type": "application/json",
      },
      body: "{}",
      signal: controller.signal,
    });
    if (!res.ok) {
      return null;
    }
    const value = await res.json();
    const count = typeof value === "number" ? value : Number(value);
    return Number.isFinite(count) ? count : null;
  } catch (err) {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function markup(count) {
  if (count === null) {
    return "";
  }
  return (
    '<span class="visits" title="Counted on the server. No IP address, user ' +
    'agent, or per-visitor record is stored.">' +
    count.toLocaleString("en-US") +
    (count === 1 ? " visit" : " visits") +
    "</span>"
  );
}

module.exports = async function handler(req, res) {
  const page = loadPage();
  if (page === null) {
    // Could not read the document. The static file is still served by the
    // filesystem handler, so hand the visitor straight to it rather than 500.
    res.statusCode = 302;
    res.setHeader("Location", "/index.html");
    res.end();
    return;
  }

  let count = null;
  try {
    count = await bumpVisits();
  } catch (err) {
    count = null;
  }

  res.setHeader("Content-Type", "text/html; charset=utf-8");
  // The count changes per request, so this response cannot be shared from the
  // edge cache. The static /index.html remains cacheable for everything else.
  res.setHeader("Cache-Control", "no-store");
  res.statusCode = 200;
  res.end(page.replace(PLACEHOLDER, markup(count)));
};
