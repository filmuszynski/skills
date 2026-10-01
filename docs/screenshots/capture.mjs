// Takes the README screenshots. Run through make.py, which renders the pages first.
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, appendFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const shots = JSON.parse(process.argv[2]);
const WIDTH = 1280, HEIGHT = 860;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function chromePath() {
  if (process.env.CHROME) return process.env.CHROME;
  const known = {
    win32: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    darwin: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    linux: "/usr/bin/google-chrome",
  };
  return known[process.platform];
}

async function launch() {
  const profile = mkdtempSync(join(tmpdir(), "review-doc-shots-"));
  const proc = spawn(chromePath(), ["--headless=new", "--remote-debugging-port=0",
    "--user-data-dir=" + profile, "--hide-scrollbars", "--window-size=" + WIDTH + "," + HEIGHT],
    { stdio: "ignore" });
  const portFile = join(profile, "DevToolsActivePort");
  for (let i = 0; i < 100 && !existsSync(portFile); i++) await sleep(100);
  const port = readFileSync(portFile, "utf8").split("\n")[0].trim();
  return { proc, port };
}

async function page(port) {
  const t = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  let id = 0;
  const waiting = new Map();
  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && waiting.has(msg.id)) { waiting.get(msg.id)(msg); waiting.delete(msg.id); }
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const n = ++id;
    waiting.set(n, (m) => (m.error ? reject(new Error(method + ": " + m.error.message)) : resolve(m.result)));
    ws.send(JSON.stringify({ id: n, method, params }));
  });
  await send("Emulation.setDeviceMetricsOverride", { width: WIDTH, height: HEIGHT, deviceScaleFactor: 1, mobile: false });
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "light" }] });
  return { send, close: () => ws.close() };
}

async function evaluate(p, js) {
  const r = await p.send("Runtime.evaluate", { expression: js, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception?.description || r.exceptionDetails.text) + " in: " + js.slice(0, 120));
  return r.result.value;
}

// Every shot starts from a clean page: the page keeps marks in localStorage, so an edit
// made for one picture would otherwise show up in the next.
async function go(p, url) {
  await p.send("Storage.clearDataForOrigin", { origin: new URL(url).origin, storageTypes: "local_storage" });
  await p.send("Page.navigate", { url });
  for (let i = 0; i < 100; i++) {
    if (await evaluate(p, "document.readyState === 'complete' && !!document.getElementById('doc')")) break;
    await sleep(100);
  }
  await sleep(400);
}

// The page scrolls inside a container between a fixed header and footer, so a
// full-page capture only sees the viewport. For the whole page, grow the viewport by
// whatever the tallest scroller hides, then shoot it as it is.
async function shoot(p, name, full = false) {
  if (full) {
    const extra = await evaluate(p, `Math.max(0, ...[document.documentElement, ...document.querySelectorAll("*")]
      .map((e) => e.scrollHeight - e.clientHeight))`);
    await p.send("Emulation.setDeviceMetricsOverride", { width: WIDTH, height: HEIGHT + extra, deviceScaleFactor: 1, mobile: false });
    await sleep(300);
  }
  const { data } = await p.send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(shots.out, name + ".png"), Buffer.from(data, "base64"));
  console.log("wrote", name + ".png");
  if (full) {
    await p.send("Emulation.setDeviceMetricsOverride", { width: WIDTH, height: HEIGHT, deviceScaleFactor: 1, mobile: false });
    // The resize closes any bubble; let it land before the next shot opens one.
    await sleep(500);
  }
}

// Select the first occurrence of `phrase` inside #doc and release the mouse there, as a
// reader dragging over it would. The page answers with its comment bubble.
const selectPhrase = (phrase) => `(() => {
  const doc = document.getElementById("doc");
  const walker = document.createTreeWalker(doc, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const i = n.data.indexOf(${JSON.stringify(phrase)});
    if (i < 0) continue;
    const r = document.createRange();
    r.setStart(n, i); r.setEnd(n, i + ${phrase.length});
    const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    n.parentElement.scrollIntoView({ block: "center" });
    doc.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    return true;
  }
  throw new Error("phrase not found");
})()`;

const click = (sel) => `(() => { const e = document.querySelector(${JSON.stringify(sel)});
  if (!e) throw new Error("no element " + ${JSON.stringify(sel)});
  e.scrollIntoView({ block: "center" }); e.click(); return true; })()`;

const { proc, port } = await launch();
try {
  const p = await page(port);

  await go(p, shots.doc);
  await shoot(p, "page", true);

  await evaluate(p, selectPhrase("the turning schedule fell apart"));
  for (let i = 0; i < 30 && !(await evaluate(p, "!!document.querySelector('.bubble textarea')")); i++) {
    await sleep(100);
  }
  await evaluate(p, `(() => { const ta = document.querySelector(".bubble textarea");
    if (!ta) throw new Error("no comment bubble");
    ta.value = "Can we put a name next to each week, like the watering rota?";
    ta.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  await shoot(p, "comment");

  await go(p, shots.doc);
  await evaluate(p, click("[data-mode=edit]"));
  await evaluate(p, `(() => { const el = [...document.querySelectorAll("[data-edit-id]")]
      .find((e) => e.textContent.includes("forty new members"));
    const n = [...el.childNodes].find((c) => c.nodeType === 3 && c.data.includes("forty"));
    const i = n.data.indexOf("forty");
    const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 5);
    const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    el.focus(); return true; })()`);
  await p.send("Input.insertText", { text: "forty-three" });
  await evaluate(p, click("[data-mode=comment]"));
  await sleep(300);
  await evaluate(p, `document.querySelector("mark.edited").scrollIntoView({ block: "center" })`);
  await shoot(p, "edit");

  await go(p, shots.doc);
  await evaluate(p, click("#open-settings"));
  await sleep(400);
  await shoot(p, "settings");

  await go(p, shots.doc);
  appendFileSync(shots.docSource, "\nOne more line, written after the page was built.\n");
  // The page checks its source when it loads and whenever its tab becomes visible
  // again, as when the reader comes back from the editor.
  await evaluate(p, "document.dispatchEvent(new Event('visibilitychange')), true");
  for (let i = 0; i < 40; i++) {
    if (await evaluate(p, "!document.getElementById('stale').hidden")) break;
    await sleep(500);
  }
  await evaluate(p, "window.scrollTo(0, 0)");
  await shoot(p, "reload");

  await go(p, shots.plan);
  await evaluate(p, click(".dec"));
  await sleep(200);
  await shoot(p, "plan");

  await go(p, shots.choice);
  await evaluate(p, click(".pick-row"));
  await sleep(200);
  await shoot(p, "choice");

  p.close();
} finally {
  proc.kill();
}
