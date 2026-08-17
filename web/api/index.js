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
// The credential below is a publishable key whose only privilege is EXECUTE on
// increment_visits(). It cannot read the table it increments, so even a full
// disclosure of this environment would reveal nothing but the ability to add
// one to a number.
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
  const key = process.env.SUPABASE_KEY;
  if (!url || !key) {
    return null; // not configured yet: render without a counter
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), DB_TIMEOUT_MS);
  try {
    const res = await fetch(url.replace(/\/$/, "") + "/rest/v1/rpc/increment_visits", {
      method: "POST",
      // The key travels on `apikey` and nowhere else. Modern publishable keys
      // are not JWTs, so repeating one in `Authorization: Bearer` makes the
      // gateway try to parse it as a token and reject the call. Sending only
      // `apikey` is the one shape that works for every key format.
      headers: {
        apikey: key,
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
  const shown = count.toLocaleString("en-US");
  const word = count === 1 ? "visit" : "visits";

  // The dial reads order of magnitude, not raw count: one major tick per
  // decade, six decades to full scale. A linear gauge would sit pinned at zero
  // for the site's first few thousand visitors and pinned at full ever after.
  // log10(count + 1) keeps a single visit slightly off the stop rather than
  // looking broken.
  const rev = Math.min(1, Math.log10(count + 1) / 6);

  // One cell per digit, the way an odometer drum reads. Commas sit between
  // cells rather than inside one.
  const cells = shown
    .split("")
    .map(function (ch) {
      return ch === ","
        ? '<span class="sep">,</span>'
        : '<span class="d">' + ch + "</span>";
    })
    .join("");

  // The whole instrument is one image to assistive tech: a single sentence,
  // rather than a gauge and a row of loose digits read out one at a time.
  return (
    '<div class="visits glass" style="--rev:' + rev.toFixed(4) + '"' +
    ' role="img" aria-label="' + shown + " " + word + ". Counted on the " +
    'server. No IP address, user agent, or per-visitor record is stored.">' +
    '<span class="tach" aria-hidden="true">' +
    '<i class="ticks"></i><i class="sweep"></i>' +
    '<i class="needle"></i><i class="hub"></i>' +
    "</span>" +
    '<span class="readout" aria-hidden="true">' +
    '<span class="odo">' + cells + "</span>" +
    '<span class="cap">' + word + "</span>" +
    "</span>" +
    "</div>"
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
  // A function replacement, not a string one: String.replace reads $& and $'
  // in a replacement *string* as patterns, which would splice parts of the
  // document into itself. Nothing markup() emits contains a dollar sign today,
  // but that is a property of the current copy rather than a guarantee.
  res.end(page.replace(PLACEHOLDER, function () { return markup(count); }));
};
