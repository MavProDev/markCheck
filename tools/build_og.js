// Render tools/og.template.html to web/og.png, the social preview card.
//
// Why this is a build step and not a Vercel Function: the card is identical on
// every request, so generating it per request would add a dependency, a cold
// start, and a running cost to produce the same image forever. Rendering it
// once at build time keeps the deployed site a set of static files and keeps
// the "no dependencies" claim on the about page honest.
//
// Unlike every other generated file here, CI cannot regenerate this one: the
// runners have no browser installed. It is therefore NOT diff-gated, and is
// regenerated on demand when the card design changes. That is a deliberate
// exception, called out here rather than left for someone to discover.
//
// Usage: NODE_PATH=<global node_modules> node tools/build_og.js
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.join(__dirname, "..");
const TEMPLATE = path.join(__dirname, "og.template.html");
const SHARED = path.join(__dirname, "shared.css");
const DEST = path.join(ROOT, "web", "og.png");

// Every scraper crops to this; anything else gets letterboxed or cropped badly.
const WIDTH = 1200;
const HEIGHT = 630;

// The card carries its own copy of the palette because it renders standalone,
// with no cascade from the site. Drift would be invisible until someone shared
// a link, so the build refuses rather than letting the two diverge quietly.
function assertPaletteMatchesSite() {
  const card = fs.readFileSync(TEMPLATE, "utf8");
  const shared = fs.readFileSync(SHARED, "utf8");
  const tokens = ["--accent: #0a84ff", "--high: #ff453a", "--med: #ff9f0a",
                  "--low: #64d2ff", "--ink: #f5f5f7", "--dim: #98989d"];
  const missing = tokens.filter(
    (t) => !card.includes(t) || !shared.includes(t.replace(": ", ": ")));
  if (missing.length) {
    throw new Error(
      "card palette has drifted from tools/shared.css: " + missing.join(", "));
  }
}

(async () => {
  assertPaletteMatchesSite();

  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: WIDTH, height: HEIGHT },
    // 1x: the card is consumed at or below its natural size, and a 2x PNG is
    // four times the bytes for no visible gain in any feed.
    deviceScaleFactor: 1,
  });

  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("file://" + TEMPLATE);
  await page.screenshot({ path: DEST });
  await browser.close();

  if (errors.length) {
    throw new Error("card rendered with errors: " + errors.join(" | "));
  }

  const bytes = fs.statSync(DEST).size;
  console.log(`wrote ${DEST} (${WIDTH}x${HEIGHT}, ${bytes} bytes)`);
  // Some scrapers refuse images over 5 MB; nothing here should come close, so
  // an overrun means something has gone wrong with the render.
  if (bytes > 5 * 1024 * 1024) {
    throw new Error("card exceeds the 5 MB scraper limit");
  }
})();
