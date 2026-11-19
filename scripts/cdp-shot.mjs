// Screenshot a page with headless Chrome over the DevTools protocol (no Puppeteer). Waits for rendering, prints
// console errors. Used to check the dashboard (qcc review) at fixed widths.
//
//   node scripts/cdp-shot.mjs <url> <out.png> [width=1440] [height=1000] [js-to-run-before-shot] [fullPage]
//
// Chrome: $CHROME, else the path in .chrome-path, else the Windows default.
// Uses its own temporary profile and port, so it never touches a running browser.
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [, , url, out, w = "1440", h = "1000", action = "", full = ""] = process.argv;
if (!url || !out) {
  console.error("usage: node scripts/cdp-shot.mjs <url> <out.png> [width] [height] [js] [fullPage]");
  process.exit(2);
}
const chromePath =
  process.env.CHROME ||
  (existsSync(".chrome-path") && readFileSync(".chrome-path", "utf8").trim()) ||
  "C:/Program Files/Google/Chrome/Application/chrome.exe";
const PORT = 9333 + Math.floor(Math.random() * 500);
const profile = mkdtempSync(join(tmpdir(), "qcc-cdp-"));
const chrome = spawn(
  chromePath,
  [
    "--headless=new",
    "--disable-gpu",
    "--no-sandbox",
    "--hide-scrollbars",
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    `--window-size=${w},${h}`,
    "about:blank",
  ],
  { stdio: "ignore" },
);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

try {
  let target;
  for (let i = 0; i < 75 && !target; i++) {
    await sleep(200);
    try {
      target = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: "PUT" })).json();
    } catch {}
  }
  if (!target) throw new Error(`Chrome did not start (${chromePath})`);
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  let id = 0;
  const pending = new Map();
  const events = [];
  ws.addEventListener("message", (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    } else if (msg.method) events.push(msg);
  });
  const send = (method, params = {}) =>
    new Promise((r) => {
      const i = ++id;
      pending.set(i, r);
      ws.send(JSON.stringify({ id: i, method, params }));
    });

  await send("Emulation.setDeviceMetricsOverride", { width: +w, height: +h, deviceScaleFactor: 1, mobile: false });
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Page.navigate", { url });
  await sleep(2500);
  if (action) {
    const r = await send("Runtime.evaluate", { expression: action, awaitPromise: true, returnByValue: true });
    console.log("action ->", JSON.stringify(r.result?.result?.value ?? r.result?.exceptionDetails?.text ?? null));
    await sleep(800);
  }
  const errors = events.filter(
    (e) =>
      e.method === "Runtime.exceptionThrown" || (e.method === "Runtime.consoleAPICalled" && e.params.type === "error"),
  );
  for (const e of errors) console.log("console error:", JSON.stringify(e.params).slice(0, 300));
  let clip;
  if (full) {
    const m = await send("Runtime.evaluate", { expression: "document.documentElement.scrollHeight", returnByValue: true });
    clip = { x: 0, y: 0, width: +w, height: m.result.result.value, scale: 1 };
  }
  const shot = await send("Page.captureScreenshot", {
    format: "png",
    ...(clip ? { clip, captureBeyondViewport: true } : {}),
  });
  writeFileSync(out, Buffer.from(shot.result.data, "base64"));
  console.log(out);
  ws.close();
} finally {
  chrome.kill();
  await sleep(300);
  rmSync(profile, { recursive: true, force: true });
}
