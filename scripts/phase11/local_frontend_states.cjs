// Real browser actions. No page.route, response fulfillment or fake UI state.
const path = require("node:path");
const { execFileSync } = require("node:child_process");

async function visible(locator, timeout = 30000) { await locator.waitFor({ state: "visible", timeout }); }
function requireFact(value, code) { if (!value) throw new Error(code); }

async function control(command) {
  const response = await fetch(process.env.RICK_FRONTEND_LOCAL_CONTROL_URL, {
    method: "POST", headers: { Authorization: `Bearer ${process.env.RICK_FRONTEND_LOCAL_CONTROL_SECRET}`, "Content-Type": "application/json" },
    body: JSON.stringify({ command }), signal: AbortSignal.timeout(10000),
  });
  requireFact(response.ok, "owned_control_failed");
  return response.json();
}

async function capture(page, result, state, screenshotDir, viewport, sha256) {
  const target = path.join(screenshotDir, `${state}-${viewport.name}.png`);
  await page.screenshot({ path: target, fullPage: false, caret: "initial" });
  result.screenshots.push({ state, path: target, sha256: await sha256(target) });
}

async function submit(page, query) {
  await page.getByLabel("Pergunta", { exact: true }).fill(query);
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
}

async function waitIdle(page) {
  await page.getByRole("button", { name: "Cancelar", exact: true }).waitFor({ state: "hidden", timeout: 45000 });
  await visible(page.getByRole("button", { name: "Consultar", exact: true }));
}

async function newConversation(page) {
  const button = page.getByRole("button", { name: "Nova conversa", exact: true }).first();
  if (!await button.isVisible()) await page.getByRole("button", { name: /^Conversas/ }).click();
  await button.click();
  await visible(page.getByLabel("Pergunta", { exact: true }));
}

async function observePublication(page) {
  const deadline = Date.now() + 90000;
  const published = page.locator(".job-banner").getByText("Documento publicado", { exact: true });
  while (Date.now() < deadline) {
    if (await published.isVisible()) return;
    const resume = page.getByRole("button", { name: "Retomar acompanhamento", exact: true });
    if (await resume.isVisible() && await resume.isEnabled()) await resume.click();
    await page.waitForTimeout(250);
  }
  throw new Error("native_browser_publication_not_observed");
}

function nativeKey(zoomIn) {
  const script = [
    "import ctypes, ctypes.util, sys",
    "x11=ctypes.CDLL(ctypes.util.find_library('X11')); xtst=ctypes.CDLL(ctypes.util.find_library('Xtst'))",
    "x11.XOpenDisplay.argtypes=[ctypes.c_char_p]; x11.XOpenDisplay.restype=ctypes.c_void_p",
    "x11.XKeysymToKeycode.argtypes=[ctypes.c_void_p,ctypes.c_ulong]; x11.XKeysymToKeycode.restype=ctypes.c_uint",
    "xtst.XTestFakeKeyEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]",
    "x11.XSync.argtypes=[ctypes.c_void_p,ctypes.c_int]",
    "x11.XCloseDisplay.argtypes=[ctypes.c_void_p]",
    "display=x11.XOpenDisplay(None)",
    "if not display: raise SystemExit('owned X11 unavailable')",
    "codes=[x11.XKeysymToKeycode(display,int(value,0)) for value in sys.argv[1:]]",
    "if any(not code for code in codes): raise SystemExit('X11 key unavailable')",
    "for code in codes: xtst.XTestFakeKeyEvent(display,code,1,10)",
    "for code in reversed(codes): xtst.XTestFakeKeyEvent(display,code,0,10)",
    "x11.XSync(display,0); x11.XCloseDisplay(display)",
  ].join("\n");
  execFileSync("python3", ["-c", script, ...(zoomIn ? ["0xffe3", "0xffe1", "0x3d"] : ["0xffe3", "0x30"])], { stdio: "ignore", timeout: 5000 });
}

async function zoomAndReflow({ page, result, viewport, screenshotDir, sha256 }) {
  const measured = () => page.evaluate(() => ({ css_width: innerWidth, dpr: devicePixelRatio,
    scroll_width: document.documentElement.scrollWidth, main_visible: Boolean(document.querySelector("main")) }));
  const oldStress = result.checks.zoom;
  await page.setViewportSize({ width: 320, height: viewport.height });
  const narrow = await measured();
  await capture(page, result, "reflow-320", screenshotDir, viewport, sha256);
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  const reflowPass = narrow.css_width === 320 && narrow.scroll_width <= 320 && narrow.main_visible;
  result.checks.reflow_320 = { ...narrow, passed: reflowPass };
  result.checks.css_zoom_stress = oldStress;
  result.checks.zoom = { method: "reflow-320-only", passed: false, reflow_passed: reflowPass };
  if (viewport.name !== "desktop") {
    result.checks.zoom = { method: "reflow-320-companion", passed: reflowPass };
    return;
  }
  if (process.env.RICK_FRONTEND_NATIVE_ZOOM !== "1") return;
  await page.bringToFront();
  const before = await measured();
  let after = before;
  try {
    for (let count = 0; count < 10 && after.dpr < before.dpr * 1.95; count += 1) {
      nativeKey(true);
      await page.waitForTimeout(150);
      after = await measured();
    }
    await capture(page, result, "native-zoom-200", screenshotDir, viewport, sha256);
    result.checks.zoom = { method: "native-browser-zoom-x11", before, after,
      passed: reflowPass && after.dpr >= before.dpr * 1.95 && after.dpr <= before.dpr * 2.05
        && after.css_width <= Math.floor(before.css_width / 1.95) && after.scroll_width <= after.css_width && after.main_visible };
  } finally {
    nativeKey(false);
    await page.waitForTimeout(150);
    const reset = await measured();
    requireFact(reset.dpr === before.dpr && reset.css_width === before.css_width, "native_zoom_reset_failed");
  }
}

async function run(args) {
  const { page, context, result, webBase, screenshotDir, viewport, sha256, consoleErrors, requestFailures } = args;
  const query = process.env.RICK_FRONTEND_PROBE_QUERY || "Quais documentos estão disponíveis?";
  const hasControl = Boolean(process.env.RICK_FRONTEND_LOCAL_CONTROL_URL && process.env.RICK_FRONTEND_LOCAL_CONTROL_SECRET);
  result.expected_console_indices = [];
  result.expected_request_failure_indices = [];
  const snap = (state) => capture(page, result, state, screenshotDir, viewport, sha256);
  async function expectedFault(action) {
    const firstConsole = consoleErrors.length;
    const firstFailure = requestFailures.length;
    await action();
    // Only known fault transport messages within the observed fault window.
    for (let i = firstConsole; i < consoleErrors.length; i += 1) {
      if (/Failed to load resource:.*status of (403|503)|net::ERR_INTERNET_DISCONNECTED/.test(consoleErrors[i])) result.expected_console_indices.push(i);
    }
    for (let i = firstFailure; i < requestFailures.length; i += 1) {
      if (["net::ERR_INTERNET_DISCONNECTED", "net::ERR_ABORTED"].includes(requestFailures[i].error)) result.expected_request_failure_indices.push(i);
    }
  }

  await waitIdle(page);
  const disclosure = page.locator(".source-details summary").last();
  await visible(disclosure);
  await disclosure.click();
  const source = page.locator(".source-details[open] dl").last();
  await visible(source);
  requireFact((await source.innerText()).includes("Documento"), "source_metadata_missing");
  result.states.sources = { observed: true, expanded_metadata: true };
  await snap("sources");

  await page.goto(`${webBase}/app/documents`, { waitUntil: "domcontentloaded" });
  await visible(page.getByRole("heading", { name: "Biblioteca de documentos", exact: true }));
  const input = page.getByLabel("Selecionar documento para upload", { exact: true });
  await page.waitForFunction(() => { const el = document.querySelector("#document-upload-input"); return el && !el.disabled; });
  const filename = `browser-${viewport.name}-${Date.now()}.txt`;
  async function upload(name) {
    const pending = page.waitForResponse(response => response.url().includes("/api/v1/documents/upload") && response.request().method() === "POST");
    await input.setInputFiles({ name, mimeType: "text/plain", buffer: Buffer.from(`Segundo a fonte autorizada, o documento confirma o laboratório local. ${name}`) });
    const response = await pending;
    requireFact(response.status() === 202, "native_browser_upload_not_accepted");
    const body = await response.json();
    requireFact(typeof body.job_id === "string", "native_browser_job_identity_missing");
    await visible(page.locator(".job-banner"));
    return body.job_id;
  }
  const job = await upload(filename);
  result.states.upload = { observed: true, http_status: 202 };
  await snap("upload");
  await observePublication(page);
  requireFact((await page.locator(".job-banner").innerText()).includes(job), "native_job_binding_missing");
  result.states.jobs = { observed: true, publication_confirmed: true };
  await visible(page.locator(".document-list").getByText(filename, { exact: true }), 30000);
  result.states.documents = { observed: true, uploaded_document_visible: true };
  await snap("documents-jobs");

  if (hasControl) {
    await control("worker-pause");
    try {
      await upload("paused-" + filename);
      await visible(page.locator(".job-banner").getByText("Ingestão na fila", { exact: true }));
      await page.waitForTimeout(500);
      requireFact(await page.locator(".job-banner").getByText("Ingestão na fila", { exact: true }).isVisible(), "paused_worker_falsely_published");
      result.states.worker_unavailable = { observed: true, owned_worker_stopped: true, queued_ui_preserved: true };
      await snap("worker-unavailable");
    } finally { await control("worker-resume"); }
    await observePublication(page);
    result.states.worker_unavailable.recovered = true;
  }

  await page.goto(`${webBase}/app/chat`, { waitUntil: "domcontentloaded" });
  await visible(page.getByLabel("Pergunta", { exact: true }));
  await expectedFault(async () => {
    await context.setOffline(true);
    try {
      await visible(page.locator('[data-network-state="offline"]'));
      requireFact(await page.getByRole("button", { name: "Consultar", exact: true }).isDisabled(), "offline_submit_not_disabled");
      result.states.offline = { observed: true, real_browser_offline: true, submit_disabled: true };
      await snap("offline");
    } finally { await context.setOffline(false); }
  });
  await page.locator('[data-network-state="offline"]').waitFor({ state: "hidden" });

  if (hasControl) {
    const retired = await control("retire-browser-uploads");
    requireFact(retired.counts.retired_documents === 2, "browser_uploaded_documents_not_retired");
    await newConversation(page);
    await control("slow");
    try {
      await submit(page, query);
      await visible(page.getByRole("button", { name: "Cancelar", exact: true }));
      await snap("slow-backend");
      await waitIdle(page);
      const state = await control("normal");
      requireFact(state.counts.slow > 0, "slow_fixture_not_exercised");
      result.states.slow_backend = { observed: true, cancel_available: true, completed: true, fixture_calls: state.counts.slow };
    } finally { await control("normal"); }

    await expectedFault(async () => {
      await newConversation(page);
      await control("deny");
      try {
        await submit(page, query);
        await visible(page.getByRole("heading", { name: "Acesso negado à consulta", exact: true }));
        result.states.permission_denied = { observed: true, native_membership_denied: true };
        await snap("permission-denied");
      } finally { await control("allow"); }
      await page.getByRole("button", { name: "Revalidar autorização", exact: true }).click();
      await page.waitForFunction(() => { const el = document.querySelector("#chat-message"); return el && !el.disabled; });
    });

    await expectedFault(async () => {
      await newConversation(page);
      await control("unavailable");
      try {
        await submit(page, query);
        await visible(page.getByRole("heading", { name: "Não foi possível concluir a consulta", exact: true }), 45000);
        const state = await control("normal");
        requireFact(state.counts.unavailable > 0, "provider_fault_not_exercised");
        result.states.provider_unavailable = { observed: true, fixture_calls: state.counts.unavailable, error_visible: true };
        await snap("provider-unavailable");
      } finally { await control("normal"); }
    });
    // Each failure uses a new conversation; its persisted interrupted request
    // must not be replayed as a successful final response.
    await newConversation(page);
    await control("stream-interruption");
    try {
      await submit(page, query);
      await visible(page.locator('article[aria-label="Resposta interrompida"]'), 45000);
      await visible(page.getByText("Este conteúdo parcial não foi marcado como resposta concluída nem deve ser usado sem uma nova consulta.", { exact: true }));
      const state = await control("normal");
      requireFact(state.counts["stream-interruption"] > 0, "stream_fault_not_exercised");
      result.states.stream_interruption = { observed: true, partial_not_final: true, fixture_calls: state.counts["stream-interruption"] };
      await snap("stream-interruption");
    } finally { await control("normal"); }
  }
  await zoomAndReflow(args);
}

module.exports = { run, zoomAndReflow, prepareViewport: ({ page }) => newConversation(page) };
