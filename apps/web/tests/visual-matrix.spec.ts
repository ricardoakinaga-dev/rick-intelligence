import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { AxeResults } from "axe-core";

const root = resolve(__dirname, "../../..");
const benchmark = JSON.parse(readFileSync(resolve(root, ".gauntlet-state-of-art/visual/benchmark.json"), "utf8")) as { id: string; states: { id: string; route: string }[] };
const identity = { authenticated: true, user_id: "fixture-reader", email: "leitor@example.invalid", role: "KNOWLEDGE_MANAGER", canonical_role: "KNOWLEDGE_MANAGER", permissions: ["chat.query", "documents.read", "documents.upload", "documents.manage", "ingestion.run", "reindex.run", "collections.read", "observability.read", "audit.read"],  tenant_id: "default", workspace_id: "default", session_id: "fixture-session" };
const denied = { error: { code: "forbidden", message: "A sessão não tem permissão para esta consulta.", details: null, request_id: "fixture" } };
const unavailable = { error: { code: "unavailable", message: "Não foi possível concluir a consulta. Tente novamente.", details: null, request_id: "fixture" } };
const title = "Guia de consulta do acervo";
const fixtureDocument = { document_id: "doc-reference", title, collection_id: "referencias", workspace_id: "default", status: "published", source_type: "md" };
const longTitle = "Referência documental com título extenso para avaliação de leitura, navegação e consulta em diferentes tamanhos de tela — edição revisada em português";
const longText = Array.from({ length: 12 }, (_, i) => `Seção ${i + 1}. Este é um texto sintético para avaliar leitura e quebra de linhas. A informação exibida não representa orientação clínica nem dados reais de pacientes.`).join("\n\n");
const longAnswer = Array.from({ length: 12 }, (_, i) => `## Seção ${i + 1}\n\nEste é um texto sintético para avaliar leitura e quebra de linhas. A informação exibida não representa orientação clínica nem dados reais de pacientes.`).join("\n\n");

function sendNativeBrowserZoomKey(zoomIn: boolean) {
  if (process.platform !== "linux") throw new Error("Native browser zoom evidence requires an X11 desktop session.");
  const keysyms = zoomIn ? ["0xffe3", "0xffe1", "0x3d"] : ["0xffe3", "0x30"];
  const script = [
    "import ctypes, ctypes.util, sys",
    "x11=ctypes.CDLL(ctypes.util.find_library('X11')); xtst=ctypes.CDLL(ctypes.util.find_library('Xtst'))",
    "x11.XOpenDisplay.argtypes=[ctypes.c_char_p]; x11.XOpenDisplay.restype=ctypes.c_void_p",
    "x11.XKeysymToKeycode.argtypes=[ctypes.c_void_p,ctypes.c_ulong]; x11.XKeysymToKeycode.restype=ctypes.c_uint",
    "xtst.XTestFakeKeyEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]",
    "display=x11.XOpenDisplay(None)",
    "if not display: raise SystemExit('X11 display unavailable')",
    "keycodes=[x11.XKeysymToKeycode(display,int(value,0)) for value in sys.argv[1:]]",
    "if any(not value for value in keycodes): raise SystemExit('X11 key mapping unavailable')",
    "for keycode in keycodes: xtst.XTestFakeKeyEvent(display,keycode,1,10)",
    "for keycode in reversed(keycodes): xtst.XTestFakeKeyEvent(display,keycode,0,10)",
    "x11.XSync(display,0)",
  ].join("\n");
  execFileSync("python3", ["-c", script, ...keysyms], { stdio: "ignore" });
}

async function prepare(page: Page, state: string, route: string) {
  const login = state.startsWith("custom-login-");
  const long = state.endsWith("long-content");
  const chatResponses = state === "custom-chat-metadata-fallback" ? [
    { conversation_id: "fixture", message_id: "missing", answer: "Resposta sintética", citations: [{ document_id: "" }], metadata: {} },
    { conversation_id: "fixture", message_id: "empty", answer: "Sem fontes", citations: [], metadata: {} },
  ] : undefined;
  let chatResponseIndex = 0;
  const defaultChatResponse = {
    conversation_id: "fixture",
    message_id: "fixture-message",
    answer: long ? longAnswer : "O acervo reúne documentos de referência. Confira a edição e a origem antes de usar o conteúdo.",
    citations: state === "custom-chat-empty-citations" ? [] : [{
      document_id: fixtureDocument.document_id,
      title: long ? longTitle : title,
      chunk_id: long ? "chunk-" + "identificador".repeat(16) : "chunk-reference-1",
      collection_id: "referencias",
      page_start: 2,
      page_end: 3,
      checksum: "sha256-" + "a".repeat(64),
    }],
    metadata: { evidence_status: state === "custom-chat-empty-citations" ? "NO_EVIDENCE" : "APPROVED_EVIDENCE" },
  };
  await page.route("**/api/v1/auth/me", request => request.fulfill(login ? { status: 401, json: denied } : { json: { ...identity, ...(state === "custom-admin-denied" ? { role: "VETERINARIAN", canonical_role: "VETERINARIAN", permissions: ["chat.query"] } : {}) } }));
  await page.route("**/api/v1/auth/login", request => request.fulfill({ status: 401, json: denied }));
  if (state.startsWith("custom-chat-")) {
    await page.route("**/api/v1/conversations**", request => {
      const routeRequest = request.request();
      const url = new URL(routeRequest.url());
      if (routeRequest.method() === "GET" && url.pathname === "/api/v1/conversations" && url.searchParams.get("limit") === "50") {
        return request.fulfill({ json: { items: [], total: 0 } });
      }
      return request.continue();
    });
  }
  await page.route("**/api/v1/collections?**", request => request.fulfill({ json: { items: [{ collection_id: "referencias", title: "Referências", workspace_id: "default" }], total: 1 } }));
  await page.route("**/api/v1/documents?**", request => {
    if (state === "custom-workbench-loading") return;
    if (state === "custom-workbench-forbidden") return request.fulfill({ status: 403, json: denied });
    if (state === "custom-workbench-error" || state === "custom-documents-error") return request.fulfill({ status: 500, json: unavailable });
    const empty = state === "custom-workbench-empty" || state === "custom-documents-empty";
    return request.fulfill({ json: { items: empty ? [] : [fixtureDocument], total: empty ? 0 : 1, next_cursor: null } });
  });
  await page.route("**/health/ready", request => {
    if (state === "custom-workbench-loading") return;
    if (state === "custom-workbench-error") return request.fulfill({ status: 503, json: unavailable });
    if (state === "custom-workbench-degraded") return request.fulfill({ json: { status: "degraded", checks: [{ name: "optional_provider", ok: false, required: false }] } });
    return request.fulfill({ json: { status: "ready", checks: [] } });
  });
  await page.route("**/api/v1/search", request => {
    if (state === "custom-search-error") return request.fulfill({ status: 503, json: unavailable });
    const items = state === "custom-search-empty" ? [] : [{ ...fixtureDocument, title: long ? longTitle : title, chunk_id: long ? "chunk-" + "identificador".repeat(16) : "chunk-reference-1", text: long ? longText : "O acervo reúne documentos de referência. Verifique a origem e a edição antes de usar o conteúdo.", source: "referencia.md", score: 0.91, rank: 1, page_start: 2, page_end: 3, section: "Consulta", checksum: "sha256-" + "a".repeat(64) }];
    return request.fulfill({ json: { query: "documentos de referência", items, total: items.length, metadata: { backend: "fixture-retrieval", candidate_count: items.length, selected_count: items.length, fallback_used: false, workspace_id: "default" } } });
  });
  await page.route("**/api/v1/chat", request => {
    if (chatResponses && chatResponseIndex < chatResponses.length) return request.fulfill({ json: chatResponses[chatResponseIndex++] });
    if (state === "custom-chat-error") return request.fulfill({ status: 503, json: unavailable });
    return request.fulfill({ json: defaultChatResponse });
  });
  await page.route("**/api/v1/admin/health", request => request.fulfill(state === "custom-admin-runtime-error" ? { status: 503, json: unavailable } : { json: { status: "ready", checks: [{ name: "kernel", ok: true, required: true, detail: "Verificação sintética concluída" }] } }));
  await page.route("**/api/v1/admin/audit", request => request.fulfill(state === "custom-admin-audit-error" ? { status: 500, json: unavailable } : { json: { total: 1, items: [{ action: "document.read", actor_user_id: "fixture-reader", target_id: "doc-reference", workspace_id: "default", request_id: "fixture-request", timestamp: "2026-09-05T12:00:00Z" }] } }));

  await page.goto(route + (state.startsWith("custom-search-") && state !== "custom-search-default" ? "?q=documentos%20de%20refer%C3%AAncia" : ""));
  if (login) {
    await expect(page.getByRole("heading", { name: "Entre para continuar." })).toBeVisible();
    if (state.endsWith("error")) {
      await page.getByLabel("E-mail").fill("leitor@example.invalid");
      await page.getByLabel("Senha").fill("synthetic-only");
      await page.getByRole("button", { name: "Entrar" }).click();
      await expect(page.locator(".login-form").getByRole("alert")).toBeVisible();
    }
  } else if (state.startsWith("custom-chat-")) {
    await page.getByLabel("Pergunta").fill("Quais documentos de referência estão disponíveis?");
    await page.getByRole("button", { name: "Consultar", exact: true }).click();
    if (state.endsWith("error")) await expect(page.locator(".answer-panel").getByRole("alert")).toBeVisible();
    else await expect(page.locator(".answer-text")).toBeVisible();
  } else if (state.startsWith("custom-workbench-")) {
    await expect(page.getByRole("heading", { name: "Seu espaço de evidências." })).toBeVisible();
    if (state.endsWith("loading")) await expect(page.getByText("Consultando documentos…", { exact: true })).toBeVisible();
    else await expect(page.getByRole("button", { name: state === "custom-workbench-error" || state === "custom-workbench-forbidden" ? "Tentar novamente" : "Atualizar", exact: true })).toBeEnabled();
  } else if (state.startsWith("custom-search-")) {
    if (state.endsWith("error")) await expect(page.locator(".search-page").getByRole("alert")).toBeVisible();
    else if (state.endsWith("default")) await expect(page.getByRole("heading", { name: "Comece uma busca" })).toBeVisible();
    else if (state.endsWith("empty")) await expect(page.getByRole("heading", { name: "Nenhuma evidência encontrada" })).toBeVisible();
    else await expect(page.locator(".evidence-detail")).toBeVisible();
  } else if (state.startsWith("custom-documents-")) {
    if (state.endsWith("error")) await expect(page.getByRole("heading", { name: "Catálogo não disponível" })).toBeVisible();
    else if (state.endsWith("empty")) await expect(page.getByRole("heading", { name: "Nenhum documento publicado" })).toBeVisible();
    else {
      await expect(page.getByText(title, { exact: true })).toBeVisible();
      if (state.endsWith("confirmation")) {
        await page.getByRole("button", { name: `Excluir ${title}`, exact: true }).click();
        await expect(page.getByRole("dialog")).toBeVisible();
      }
    }
  } else if (state === "custom-admin-denied") {
    await expect(page.getByRole("heading", { name: "Acesso restrito." })).toBeVisible();
    await expect(page.locator(".breadcrumb")).toContainText("Administração");
    await expect(page.getByRole("link", { name: "Voltar à visão geral", exact: true })).toBeVisible();
  }
  else if (state === "perf-chat") await expect(page.getByLabel("Pergunta")).toBeVisible();
  else await expect(page.getByRole("button", { name: state === "custom-admin-runtime-error" || state === "custom-admin-audit-error" ? "Tentar novamente" : "Atualizar", exact: true })).toBeEnabled();
}

async function writeQualityArtifact(testInfo: { outputPath: (name: string) => string }, name: string, payload: unknown) {
  const directory = resolve(process.env.RICK_VISUAL_EVIDENCE_DIR || testInfo.outputPath("matrix"));
  await mkdir(directory, { recursive: true });
  const report = resolve(directory, `${name}.json`);
  await writeFile(report, JSON.stringify(payload, null, 2));
  return report;
}

async function captureQualityState(page: Page, testInfo: { outputPath: (name: string) => string }, name: string, state: string, route: string, errors: string[], action: string) {
  const screenshot = await captureQualityScreenshot(page, testInfo, name, true);
  const measured = await page.evaluate(() => ({ overflow: document.documentElement.scrollWidth > innerWidth, width: innerWidth, scrollWidth: document.documentElement.scrollWidth }));
  const accessibility = await runQualityAccessibility(page);
  const evidence = { schema: "rick-web-quality-evidence.v1", kind: "recovery-state", state, route, viewport: page.viewportSize(), screenshot, action, measured, errors, accessibility: qualityAccessibilityEvidence(accessibility) };
  await writeQualityArtifact(testInfo, name, evidence);
  expect(errors, `${state} client errors`).toEqual([]);
  expect(measured.overflow, `${state} horizontal overflow`).toBe(false);
  expect(accessibility.violations, `${state} axe violations`).toEqual([]);
  return evidence;
}

async function captureQualityScreenshot(page: Page, testInfo: { outputPath: (name: string) => string }, name: string, fullPage: boolean) {
  const directory = resolve(process.env.RICK_VISUAL_EVIDENCE_DIR || testInfo.outputPath("matrix"));
  await mkdir(directory, { recursive: true });
  const screenshot = resolve(directory, `${name}.png`);
  const session = await page.context().newCDPSession(page);
  const metrics = await session.send("Page.getLayoutMetrics");
  const nativeZoom = (metrics.cssVisualViewport.zoom || 1) !== 1;
  if (fullPage && !nativeZoom) {
    await page.evaluate(async () => {
      scrollTo({ top: 0, left: 0, behavior: "instant" });
      await new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done())));
    });
  }
  const state = await page.evaluate(() => ({ scroll_x: scrollX, scroll_y: scrollY, css_width: innerWidth, css_height: innerHeight, device_pixel_ratio: devicePixelRatio }));
  let bytes: Buffer;
  if (nativeZoom) {
    const capture = await session.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: false });
    bytes = Buffer.from(capture.data, "base64");
    await writeFile(screenshot, bytes);
  } else {
    bytes = await page.screenshot({ path: screenshot, fullPage, animations: "disabled" });
  }
  await session.detach();
  await writeFile(resolve(directory, `${name}.capture.json`), JSON.stringify({ ...state, captured_at: new Date().toISOString(), full_page: fullPage && !nativeZoom, method: nativeZoom ? "CDP visible viewport at native browser zoom" : "Playwright screenshot", png_width: bytes.readUInt32BE(16), png_height: bytes.readUInt32BE(20), sha256: createHash("sha256").update(bytes).digest("hex") }, null, 2));
  return screenshot;
}

async function runQualityAccessibility(page: Page, confirmation = false, textStress = false) {
  const loaded = await page.evaluate(() => Boolean((window as unknown as { axe?: unknown }).axe));
  if (!loaded) await page.addScriptTag({ path: resolve(root, "apps/web/node_modules/axe-core/axe.min.js") });
  return page.evaluate(async ({ isConfirmation, textStress }) => {
    const engine = (window as unknown as { axe: { run: (context: Document | Element, options: unknown) => Promise<AxeResults> } }).axe;
    const context = isConfirmation ? document.querySelector("#confirm-dialog")! : document;
    return engine.run(context, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
      rules: { ...(isConfirmation || textStress ? { "color-contrast": { enabled: false } } : {}), ...(textStress ? { "avoid-inline-spacing": { enabled: false } } : {}) },
    });
  }, { isConfirmation: confirmation, textStress });
}

function qualityAccessibilityEvidence(result: AxeResults, excludedRules: string[] = []) {
  return { violations: result.violations, incomplete: result.incomplete, passes: result.passes.map(rule => rule.id), engine: result.testEngine, excluded_rules: excludedRules };
}

for (const state of benchmark.states) {
  test(`visual matrix ${state.id}`, async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.emulateMedia({ reducedMotion: "reduce" });
    await prepare(page, state.id, state.route);
    await page.evaluate(() => document.fonts.ready);
    await page.addScriptTag({ path: resolve(root, "apps/web/node_modules/axe-core/axe.min.js") });
    const accessibility = await page.evaluate(async (confirmation) => {
      const engine = (window as unknown as { axe: { run: (context: Document | Element, options: unknown) => Promise<AxeResults> } }).axe;
      const context = confirmation ? document.querySelector("#confirm-dialog")! : document;
      return engine.run(context, {
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
        // axe cannot resolve the fixed scrim's composited background for the
        // dialog paragraph. The dedicated deterministic contrast assertion
        // below remains the release check for this isolated overlay.
        rules: confirmation ? { "color-contrast": { enabled: false } } : undefined,
      });
    }, state.id.endsWith("confirmation"));
    const measured = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth > innerWidth,
      overflowNodes: Array.from(document.querySelectorAll<HTMLElement>("body *"))
        .filter(node => {
          const rect = node.getBoundingClientRect();
          return rect.width > 0 && rect.right > innerWidth + 1 && getComputedStyle(node).visibility !== "hidden" && !node.closest('[aria-hidden="true"]');
        })
        .slice(0, 20)
        .map(node => {
          const rect = node.getBoundingClientRect();
          return { tag: node.tagName, className: node.className, text: node.textContent?.slice(0, 90), right: rect.right, width: rect.width };
        }),
      layoutChain: ["html", "body", ".app-frame", ".workspace", ".topbar", ".main-content", "chat-workspace_root__", "chat-workspace_shell__", "chat-workspace_chatPanel__"].map(selector => {
        const element = selector.endsWith("__")
          ? Array.from(document.querySelectorAll<HTMLElement>("body *")).find(node => typeof node.className === "string" && node.className.includes(selector))
          : document.querySelector<HTMLElement>(selector);
        if (!element) return { selector, missing: true };
        const rect = element.getBoundingClientRect(), style = getComputedStyle(element);
        return { selector, tag: element.tagName, className: element.className, x: rect.x, width: rect.width, right: rect.right, cssWidth: style.width, minWidth: style.minWidth, maxWidth: style.maxWidth, display: style.display };
      }),
      width: innerWidth, height: innerHeight, documentHeight: document.documentElement.scrollHeight,
      headings: Array.from(document.querySelectorAll("h1,h2,h3")).map(node => ({ level: node.tagName, text: node.textContent, size: getComputedStyle(node).fontSize, lineHeight: getComputedStyle(node).lineHeight })),
      fontFamily: getComputedStyle(document.body).fontFamily,
      images: document.images.length,
      controls: Array.from(document.querySelectorAll<HTMLElement>("button,a,input,textarea,select,summary")).filter(node => { const rect = node.getBoundingClientRect(); return rect.width > 1 && rect.height > 1 && getComputedStyle(node).visibility !== "hidden" && !node.closest('[aria-hidden="true"]'); }).map(node => { const rect = node.getBoundingClientRect(); return { tag: node.tagName, name: node.getAttribute("aria-label") || node.textContent?.trim() || node.id, width: rect.width, height: rect.height }; }),
    }));
    const directory = process.env.RICK_VISUAL_EVIDENCE_DIR || testInfo.outputPath("matrix");
    await mkdir(directory, { recursive: true });
    const renderId = `${state.id}-${testInfo.project.name}`;
    const screenshot = resolve(directory, `${renderId}.png`);
    const viewportScreenshot = resolve(directory, `${renderId}-viewport.png`);
    await page.screenshot({ path: viewportScreenshot, fullPage: false, animations: "disabled" });
    // A fixed modal is a viewport surface; a full-page stitch misrepresents its scrim.
    await page.screenshot({ path: screenshot, fullPage: !state.id.endsWith("confirmation"), animations: "disabled" });
    const manualContrast = state.id.endsWith("confirmation") ? await page.locator("#confirm-dialog-description").evaluate(node => {
      const foreground = getComputedStyle(node).color;
      const background = getComputedStyle(node).backgroundColor;
      const luminance = (color: string) => {
        const rgb = color.match(/[\d.]+/g)!.slice(0, 3).map(Number).map(value => { const channel = value / 255; return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4; });
        return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
      };
      const foregroundLuminance = luminance(foreground), backgroundLuminance = luminance(background);
      return { foreground, background, ratio: (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) / (Math.min(foregroundLuminance, backgroundLuminance) + 0.05), method: "Computed opaque dialog paragraph surface; axe overlay ambiguity isolated" };
    }) : null;
    if (manualContrast) expect(manualContrast.ratio, "Dialog description contrast").toBeGreaterThanOrEqual(4.5);
    const reducedMotion = await page.evaluate(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    expect(reducedMotion, "Visual evidence must record the reduced-motion preference").toBe(true);
    const evidence = { benchmark_id: benchmark.id, render_id: renderId, state: state.id, viewport: page.viewportSize(), project: testInfo.project.name, route: state.route, captured_at: new Date().toISOString(), screenshot, sha256: createHash("sha256").update(await readFile(screenshot)).digest("hex"), viewport_screenshot: viewportScreenshot, viewport_sha256: createHash("sha256").update(await readFile(viewportScreenshot)).digest("hex"), environment: { browser: page.context().browser()?.version(), fixture: "Synthetic intercepted API responses; no patient data or external service", animation: "disabled during screenshot", prefers_reduced_motion: reducedMotion }, measured, errors, accessibility: { violations: accessibility.violations, incomplete: accessibility.incomplete, passed_rules: accessibility.passes.map(rule => rule.id), engine: accessibility.testEngine, contrast_scope: manualContrast ? "manual opaque dialog assertion; axe color-contrast disabled only for this overlay" : "axe color-contrast" }, manual_contrast: manualContrast };
    const report = resolve(directory, `${renderId}.json`);
    await writeFile(report, JSON.stringify(evidence, null, 2));
    await testInfo.attach("visual-evidence", { path: report, contentType: "application/json" });
    expect(errors, "Unexpected client exceptions").toEqual([]);
    expect(measured.overflow, "Horizontal overflow").toBe(false);
    expect(accessibility.violations, "Automated WCAG violations; manual audit still required").toEqual([]);
  });
}

test("quality search direct reading and compact filters", async ({ page }, testInfo) => {
  await prepare(page, "custom-search-long-content", "/app/search");
  const jump = page.getByRole("link", { name: "Ler trecho selecionado", exact: true });
  await expect(jump).toBeVisible();
  await expect(page.getByLabel("Coleção", { exact: true })).toBeHidden();
  const summary = page.locator(".search-filter-details summary");
  await expect(summary).toContainText("5");
  await summary.click();
  await expect(page.getByLabel("Coleção", { exact: true })).toBeVisible();
  await summary.click();
  await jump.focus();
  await page.keyboard.press("Enter");
  const reader = page.getByRole("heading", { name: "Trecho selecionado", exact: true });
  await expect(reader).toBeFocused();
  await expect(page.locator(".evidence-detail > p")).toHaveText(longText);
  const layout = await page.evaluate(() => {
    const reader = document.querySelector(".evidence-panel")!.getBoundingClientRect(), list = document.querySelector(".search-results-panel")!.getBoundingClientRect();
    return { width: innerWidth, readerWidth: reader.width, listWidth: list.width, overflow: document.documentElement.scrollWidth > innerWidth };
  });
  await testInfo.attach("search-reading-layout", { body: JSON.stringify(layout), contentType: "application/json" });
  if (layout.width > 1100) expect(layout.readerWidth).toBeGreaterThan(layout.listWidth);
  expect(layout.overflow).toBe(false);
  await page.screenshot({ path: testInfo.outputPath("search-reader-viewport.png") });
  await page.getByRole("button", { name: "Voltar aos resultados", exact: true }).click();
  await expect(page.locator('.search-result-card[aria-pressed="true"]')).toBeFocused();
});

test("quality chat source inspection and return", async ({ page }, testInfo) => {
  await prepare(page, "custom-chat-long-content", "/app/chat");
  const answer = page.locator(".answer-text");
  await expect(answer.locator("h3")).toHaveCount(12);
  await expect(answer.locator("h3").first()).toHaveText("Seção 1");
  await expect(answer.locator("h3 + p")).toHaveCount(12);
  const jump = page.getByRole("link", { name: "Consultar fontes (1)", exact: true });
  await expect(jump).toBeVisible();
  expect(await jump.evaluate(element => element.getBoundingClientRect().bottom <= document.querySelector(".answer-text")!.getBoundingClientRect().top)).toBe(true);
  await jump.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Fontes associadas", exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  const summary = page.locator(".source-details summary");
  await expect(summary).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator(".source-details")).toHaveAttribute("open", "");
  const metadata = page.locator(".source-details dl");
  for (const value of ["doc-reference", "referencias", "chunk-" + "identificador".repeat(16), "sha256-" + "a".repeat(64), "2", "3"]) await expect(metadata.getByText(value, { exact: true })).toBeVisible();
  await expect(page.locator(".source-details").getByRole("link")).toHaveCount(0);
  // Capture the actual scrolled viewport before resetting for a full-page
  // reference; sticky chrome otherwise appears mid-page in the stitched image.
  await page.screenshot({ path: testInfo.outputPath("chat-source-expanded-viewport.png") });
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("chat-source-expanded.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.keyboard.press("Space");
  await expect(page.locator(".source-details")).not.toHaveAttribute("open", "");
  await page.getByRole("link", { name: "Voltar ao início da resposta", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Leitura do resultado", exact: true })).toBeFocused();
});

test("quality chat missing metadata remains explicit", async ({ page }) => {
  await prepare(page, "custom-chat-metadata-fallback", "/app/chat");
  const source = page.locator(".source-details").last();
  const summary = source.locator("summary");
  await expect(summary).toContainText("Documento sem título");
  await summary.click();
  await expect(source.locator("dd")).toHaveText(Array(6).fill("Não informado"));
  await expect(page.getByText("Evidência fraca", { exact: true })).toBeVisible();
  await page.getByLabel("Pergunta", { exact: true }).fill("Agora valide uma resposta sem fontes.");
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
  const latestAnswer = page.getByRole("article", { name: "Resposta do corpus" }).last();
  await expect(latestAnswer.getByText("Nenhuma fonte retornada", { exact: true })).toBeVisible();
  await expect(latestAnswer.getByRole("link", { name: /Consultar fontes/ })).toHaveCount(0);
  await expect(latestAnswer.locator(".source-details")).toHaveCount(0);
});

test("quality search retry replaces the failure with current evidence", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await prepare(page, "custom-search-error", "/app/search");
  await expect(page.locator(".search-page").getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("Consulta", { exact: true })).toHaveValue("documentos de referência");
  await captureQualityState(page, testInfo, `search-retry-before-${testInfo.project.name}`, "custom-search-error", "/app/search", errors, "A falha preserva a consulta e oferece Tentar novamente.");

  await page.unroute("**/api/v1/search");
  await page.route("**/api/v1/search", route => route.fulfill({ json: {
    query: "documentos de referência",
    items: [{ ...fixtureDocument, chunk_id: "chunk-search-retry", text: "Trecho sintético recuperado para consulta da fonte autorizada.", source: "referencia.md", score: 0.91, rank: 1, page_start: 2, page_end: 3, section: "Consulta", checksum: "sha256-" + "b".repeat(64) }],
    total: 1,
    metadata: { backend: "fixture-retrieval", candidate_count: 1, selected_count: 1, fallback_used: false, workspace_id: "default" },
  } }));
  await page.getByRole("button", { name: "Tentar novamente", exact: true }).click();
  await expect(page.locator(".search-page").getByRole("alert")).toHaveCount(0);
  await expect(page.locator(".evidence-detail")).toBeVisible();
  await expect(page.locator(".evidence-detail")).toContainText("Trecho sintético recuperado");
  await expect(page.getByLabel("Consulta", { exact: true })).toHaveValue("documentos de referência");
  await captureQualityState(page, testInfo, `search-retry-after-${testInfo.project.name}`, "custom-search-results", "/app/search", errors, "Nova tentativa substitui o erro por um resultado e mantém a consulta.");
});

test("quality admin retry restores dependency health", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await prepare(page, "custom-admin-runtime-error", "/admin");
  await expect(page.locator(".admin-page").getByRole("alert")).toBeVisible();
  await captureQualityState(page, testInfo, `admin-retry-before-${testInfo.project.name}`, "custom-admin-runtime-error", "/admin", errors, "Falha de saúde preserva estado desconhecido e ação de retentativa.");

  await page.unroute("**/api/v1/admin/health");
  await page.route("**/api/v1/admin/health", route => route.fulfill({ json: { status: "ready", checks: [{ name: "kernel", ok: true, required: true, detail: "Verificação sintética concluída" }] } }));
  await page.getByRole("button", { name: "Tentar novamente", exact: true }).click();
  await expect(page.locator(".health-checks")).toContainText("kernel: Disponível");
  await expect(page.locator(".admin-page").getByRole("alert")).toHaveCount(0);
  await captureQualityState(page, testInfo, `admin-retry-after-${testInfo.project.name}`, "custom-admin-allowed", "/admin", errors, "Nova tentativa confirma dependência disponível sem manter o alerta anterior.");
});

test("quality reduced-motion preference disables animation and transitions", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await prepare(page, "custom-search-default", "/app/search");
  await page.unroute("**/api/v1/search");
  let releaseRequest!: () => void;
  const requestBarrier = new Promise<void>(resolveRequest => { releaseRequest = resolveRequest; });
  await page.route("**/api/v1/search", async route => {
    await requestBarrier;
    await route.abort("failed");
  });
  await page.getByLabel("Consulta", { exact: true }).fill("Quais documentos de referência estão disponíveis?");
  await page.getByRole("button", { name: "Buscar evidências", exact: true }).click();
  const spinner = page.locator(".search-form-actions .spinner");
  await expect(spinner).toBeVisible();
  const motion = await page.evaluate(() => {
    const toSeconds = (value: string) => value.split(",").map(part => part.trim()).map(part => part.endsWith("ms") ? Number.parseFloat(part) / 1000 : Number.parseFloat(part)).filter(Number.isFinite);
    const spinnerStyle = getComputedStyle(document.querySelector<HTMLElement>(".spinner")!);
    const buttonStyle = getComputedStyle(document.querySelector<HTMLElement>(".button")!);
    return {
      preference: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      animation_duration: spinnerStyle.animationDuration,
      animation_iteration_count: spinnerStyle.animationIterationCount,
      animation_max_seconds: Math.max(...toSeconds(spinnerStyle.animationDuration)),
      transition_duration: buttonStyle.transitionDuration,
      transition_max_seconds: Math.max(...toSeconds(buttonStyle.transitionDuration)),
    };
  });
  expect(motion.preference).toBe(true);
  expect(motion.animation_iteration_count).toBe("1");
  expect(motion.animation_max_seconds).toBeLessThanOrEqual(0.000001);
  expect(motion.transition_max_seconds).toBeLessThanOrEqual(0.000001);
  const screenshot = await captureQualityScreenshot(page, testInfo, `reduced-motion-search-loading-${testInfo.project.name}`, true);
  const accessibility = await runQualityAccessibility(page);
  await writeQualityArtifact(testInfo, `reduced-motion-search-loading-${testInfo.project.name}`, { schema: "rick-web-quality-evidence.v1", kind: "reduced-motion-computed-behavior", state: "search-loading", viewport: page.viewportSize(), screenshot, motion, errors, accessibility: qualityAccessibilityEvidence(accessibility), method: "Real pending search form with Playwright reduced-motion media preference; current production CSS computed animation/transition durations recorded while the visible spinner is active." });
  expect(errors).toEqual([]);
  expect(accessibility.violations).toEqual([]);
  releaseRequest();
  await expect(page.locator(".search-page").getByRole("alert")).toBeVisible();
});

if (process.env.RICK_WEB_E2E_NATIVE_ZOOM === "1") {
  test("quality native browser zoom reflows selected search evidence at 200 percent", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "native zoom acceptance is exercised from the 1440px desktop viewport");
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.emulateMedia({ reducedMotion: "reduce" });
    await prepare(page, "custom-search-long-content", "/app/search");
    await page.locator(".search-filter-details summary").click();
    const before = await page.evaluate(() => ({ css_width: innerWidth, device_pixel_ratio: devicePixelRatio, scroll_width: document.documentElement.scrollWidth }));
    expect(before.css_width).toBe(1440);

    let zoom = before;
    for (let attempt = 0; attempt < 10 && zoom.device_pixel_ratio < 1.95; attempt += 1) {
      sendNativeBrowserZoomKey(true);
      await page.waitForTimeout(120);
      zoom = await page.evaluate(() => ({ css_width: innerWidth, device_pixel_ratio: devicePixelRatio, scroll_width: document.documentElement.scrollWidth }));
    }
    expect(zoom.device_pixel_ratio).toBeGreaterThanOrEqual(1.95);
    expect(zoom.css_width).toBeLessThanOrEqual(Math.floor(before.css_width / 1.95));
    expect(zoom.scroll_width).toBeLessThanOrEqual(zoom.css_width);
    await expect(page.getByLabel("Consulta", { exact: true })).toBeVisible();
    await expect(page.locator(".evidence-detail")).toBeVisible();
    const screenshot = await captureQualityScreenshot(page, testInfo, "native-browser-zoom-search-desktop-200", true);
    const accessibility = await runQualityAccessibility(page);
    const evidence = { schema: "rick-web-quality-evidence.v1", kind: "native-browser-zoom-reflow", state: "custom-search-long-content", route: "/app/search", viewport: page.viewportSize(), before, after: zoom, screenshot, errors, accessibility: qualityAccessibilityEvidence(accessibility), method: "Headed Chromium browser accelerator via X11 Control+Shift+Equal from a 1440px viewport; browser DPR reaches 2 and CSS viewport reflows to half width." };
    await writeQualityArtifact(testInfo, "native-browser-zoom-search-desktop-200", evidence);
    expect(errors).toEqual([]);
    expect(accessibility.violations).toEqual([]);
    sendNativeBrowserZoomKey(false);
    const reset = await page.evaluate(() => ({ css_width: innerWidth, device_pixel_ratio: devicePixelRatio }));
    expect(reset.device_pixel_ratio).toBe(1);
    expect(reset.css_width).toBe(before.css_width);
  });
}

if (process.env.RICK_WEB_E2E_ATSPI === "1") {
  test("quality AT-SPI tree exposes source answer, status, focus and citation metadata", async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.emulateMedia({ reducedMotion: "reduce" });
    await prepare(page, "custom-chat-response", "/app/chat");

    const readAccessibilityTree = () => {
      const script = [
        "import json,pyatspi,time",
        "desktop=pyatspi.Registry.getDesktop(0)",
        "chrome=None",
        "for attempt in range(30):",
        "  for index in range(desktop.childCount):",
        "    candidate=desktop.getChildAtIndex(index)",
        "    if 'Chrome' in (candidate.name or ''): chrome=candidate; break",
        "  if chrome is not None: break",
        "  time.sleep(.1)",
        "if chrome is None: raise SystemExit('Chrome application is absent from the AT-SPI desktop')",
        "rows=[]",
        "def walk(node,depth=0):",
        "  try:",
        "    role=node.getRoleName(); name=node.name or ''; states=node.getState()",
        "    if name or role in ('document web','heading','link','push button','status','entry','paragraph'):",
        "      rows.append({'role':role,'name':name,'focused':states.contains(pyatspi.STATE_FOCUSED)})",
        "    if depth < 48:",
        "      for child_index in range(node.childCount): walk(node.getChildAtIndex(child_index),depth+1)",
        "  except Exception: return",
        "walk(chrome)",
        "print(json.dumps(rows,ensure_ascii=False))",
      ].join("\n");
      return JSON.parse(execFileSync("python3", ["-c", script], { encoding: "utf8", timeout: 10_000 }));
    };

    const answerTree = readAccessibilityTree();
    const requiredNames = ["Converse com o corpus.", "Consultar fontes (1)", "Fontes associadas", "Com evidência"];
    const normalizeName = (value: string) => value.toLocaleLowerCase("pt-BR");
    const missingNames = requiredNames.filter(label => !answerTree.some((node: { name: string }) => normalizeName(node.name).includes(normalizeName(label))));
    expect(missingNames, `AT-SPI Chrome names: ${JSON.stringify(answerTree.map((node: { role: string; name: string }) => `${node.role}:${node.name}`))}`).toEqual([]);
    const sourceJump = page.getByRole("link", { name: "Consultar fontes (1)", exact: true });
    await sourceJump.focus();
    await page.keyboard.press("Enter");
    const sourceHeading = page.getByRole("heading", { name: "Fontes associadas", exact: true });
    await expect(sourceHeading).toBeFocused();
    const focusedTree = readAccessibilityTree();
    expect(focusedTree.some((node: { name: string; focused: boolean }) => normalizeName(node.name).includes("fontes associadas") && node.focused)).toBe(true);
    await page.keyboard.press("Tab");
    const citation = page.locator(".source-details summary");
    await expect(citation).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator(".source-details")).toHaveAttribute("open", "");
    const expandedTree = readAccessibilityTree();
    for (const label of ["Guia de consulta do acervo", "Documento", "Coleção", "Trecho", "Código de integridade"]) {
      expect(expandedTree.some((node: { name: string }) => normalizeName(node.name).includes(normalizeName(label))), `AT-SPI tree exposes ${label}`).toBe(true);
    }

    const screenshot = await captureQualityScreenshot(page, testInfo, `atspi-chat-citation-${testInfo.project.name}`, true);
    const accessibility = await runQualityAccessibility(page);
    await writeQualityArtifact(testInfo, `atspi-chat-citation-${testInfo.project.name}`, { schema: "rick-web-quality-evidence.v1", kind: "atspi-accessibility-tree-path", state: "custom-chat-response-with-expanded-citation", viewport: page.viewportSize(), screenshot, accessible_names: answerTree.filter((node: { name: string }) => node.name).map((node: { role: string; name: string }) => ({ role: node.role, name: node.name })), focused_nodes: focusedTree.filter((node: { focused: boolean }) => node.focused), citation_tree: expandedTree.filter((node: { name: string }) => /Guia de consulta|Documento|Coleção|Trecho|Código de integridade/.test(node.name)), errors, accessibility: qualityAccessibilityEvidence(accessibility), method: "Headed Chromium with forced renderer accessibility under Xvfb/private D-Bus; PyAT-SPI reads the Chrome accessibility tree while keyboard activates source navigation and citation disclosure. No Orca speech output was captured." });
    expect(errors).toEqual([]);
    expect(accessibility.violations).toEqual([]);
  });
}

test("quality keyboard navigation and confirmation", async ({ page }, testInfo) => {
  const errors: string[] = [];
  const focusSequence: { step: string; name: string; outline: string; outlineWidth: string; outlineColor: string }[] = [];
  const recordFocus = async (step: string, locator: ReturnType<typeof page.getByRole>, requireVisibleIndicator = true) => {
    await expect(locator).toBeFocused();
    const focus = await locator.evaluate(element => {
      const style = getComputedStyle(element);
      return {
        name: element.getAttribute("aria-label") || element.textContent?.trim() || element.id,
        outline: style.outlineStyle,
        outlineWidth: style.outlineWidth,
        outlineColor: style.outlineColor,
      };
    });
    if (requireVisibleIndicator) {
      expect(focus.outline).not.toBe("none");
      expect(parseFloat(focus.outlineWidth)).toBeGreaterThanOrEqual(3);
    }
    focusSequence.push({ step, ...focus });
  };
  page.on("pageerror", error => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await prepare(page, "custom-workbench-success", "/app");
  await page.keyboard.press("Tab");
  await recordFocus("primeiro Tab: link para pular ao conteúdo", page.getByRole("link", { name: "Pular para o conteúdo" }));
  await page.keyboard.press("Enter");
  await page.keyboard.press("Tab");
  await recordFocus("Tab após salto: ação principal", page.getByRole("link", { name: "Fazer uma pergunta" }));
  if ((page.viewportSize()?.width || 0) <= 900) {
    const menu = page.getByRole("button", { name: "Abrir navegação" });
    await menu.click();
    await expect(page.locator(".rail-close")).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await recordFocus("Shift+Tab no menu móvel", page.locator(".profile-button"));
    await page.keyboard.press("Tab");
    await recordFocus("Tab no menu móvel", page.locator(".rail-close"));
    await page.keyboard.press("Escape");
    await recordFocus("Escape restaura foco no acionador do menu", menu, false);
  }
  await prepare(page, "custom-documents-confirmation", "/app/documents");
  const cancel = page.getByRole("button", { name: "Cancelar", exact: true });
  await expect(cancel).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  const remove = page.getByRole("dialog").getByRole("button", { name: "Excluir documento", exact: true });
  await recordFocus("Shift+Tab percorre para ação destrutiva", remove);
  await page.keyboard.press("Tab");
  await recordFocus("Tab retorna para cancelar", cancel);
  const contrast = await page.locator("#confirm-dialog").evaluate(dialog => {
    const luminance = (color: string) => {
      const rgb = color.match(/[\d.]+/g)!.slice(0, 3).map(Number).map(value => { const channel = value / 255; return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4; });
      return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
    };
    const ratio = (foreground: string, background: string) => {
      const foregroundLuminance = luminance(foreground), backgroundLuminance = luminance(background);
      return (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) / (Math.min(foregroundLuminance, backgroundLuminance) + 0.05);
    };
    const panel = getComputedStyle(dialog);
    const samples = Array.from(dialog.querySelectorAll<HTMLElement>(".eyebrow, h2, p, .dialog-actions button")).map(element => {
      const style = getComputedStyle(element);
      const ownBackground = style.backgroundColor;
      const channels = ownBackground.match(/[\d.]+/g) || [];
      const alpha = channels.length > 3 ? Number(channels[3]) : ownBackground === "transparent" ? 0 : 1;
      const background = alpha < 1 ? panel.backgroundColor : ownBackground;
      return { name: element.getAttribute("aria-label") || element.textContent?.trim(), foreground: style.color, background, ratio: ratio(style.color, background), fontSize: style.fontSize };
    });
    return { samples, minimum_ratio: Math.min(...samples.map(sample => sample.ratio)), transitionDuration: getComputedStyle(dialog.querySelector("p")!).transitionDuration, panelOpacity: panel.opacity, panelBackgroundImage: panel.backgroundImage };
  });
  expect(contrast.samples.length).toBe(5);
  expect(contrast.panelOpacity).toBe("1");
  expect(contrast.panelBackgroundImage).toBe("none");
  expect(contrast.minimum_ratio).toBeGreaterThanOrEqual(4.5);
  expect(parseFloat(contrast.transitionDuration)).toBeLessThanOrEqual(0.000001);
  await testInfo.attach("dialog-computed-contrast", { body: JSON.stringify(contrast, null, 2), contentType: "application/json" });
  const keyboardEvidence = { schema: "rick-web-quality-evidence.v1", kind: "keyboard-focus-trap", state: "custom-documents-confirmation", viewport: page.viewportSize(), activeElement: await page.evaluate(() => ({ tag: document.activeElement?.tagName, text: document.activeElement?.textContent, ariaLabel: document.activeElement?.getAttribute("aria-label") })), focusSequence, method: "Real Playwright Tab/Shift+Tab/Escape interaction with reduced motion; focus outline style and geometry recorded after keyboard traversal." };
  const keyboardName = `keyboard-confirmation-${testInfo.project.name}`;
  const keyboardScreenshot = await captureQualityScreenshot(page, testInfo, keyboardName, false);
  const accessibility = await runQualityAccessibility(page, true);
  await writeQualityArtifact(testInfo, keyboardName, { ...keyboardEvidence, screenshot: keyboardScreenshot, contrast, errors, accessibility: qualityAccessibilityEvidence(accessibility) });
  await page.screenshot({ path: testInfo.outputPath("dialog-keyboard-focus.png") });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const restoredTrigger = page.getByRole("button", { name: `Excluir ${title}`, exact: true });
  await recordFocus("Escape fecha diálogo e restaura foco ao acionador", restoredTrigger);
  await writeQualityArtifact(testInfo, `${keyboardName}-restored`, { schema: "rick-web-quality-evidence.v1", kind: "keyboard-focus-restored", state: "custom-documents-confirmation-closed", viewport: page.viewportSize(), activeElement: focusSequence.at(-1), focusSequence, errors, method: "Escape closes the modal and returns focus to its invoking action." });
});

test("quality 320 CSS pixel reflow on long and modal states", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.setViewportSize({ width: 320, height: 812 });
  for (const state of benchmark.states.filter(value => value.id.endsWith("long-content") || value.id.endsWith("confirmation") || value.id === "custom-login-default" || value.id === "custom-workbench-success" || value.id === "custom-admin-allowed")) {
    await prepare(page, state.id, state.route);
    const measured = await page.evaluate(() => ({ overflow: document.documentElement.scrollWidth > innerWidth, width: innerWidth, scrollWidth: document.documentElement.scrollWidth, height: innerHeight }));
    const name = `${state.id}-320-${testInfo.project.name}`;
    const screenshot = await captureQualityScreenshot(page, testInfo, name, !state.id.endsWith("confirmation"));
    const accessibility = await runQualityAccessibility(page, state.id.endsWith("confirmation"));
    await writeQualityArtifact(testInfo, name, { schema: "rick-web-quality-evidence.v1", kind: "320-css-pixel-reflow", state: state.id, viewport: page.viewportSize(), screenshot, measured, errors, accessibility: qualityAccessibilityEvidence(accessibility), method: "Explicit CSS viewport set to 320px; screenshot captured from the current production build; synthetic API fixture." });
    expect(measured.overflow, state.id).toBe(false);
  }
});

test("quality 200 percent text stress", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  for (const [state, route] of [["custom-login-default", "/login"], ["custom-workbench-success", "/app"], ["custom-search-long-content", "/app/search"], ["custom-chat-long-content", "/app/chat"], ["custom-documents-confirmation", "/app/documents"], ["custom-admin-allowed", "/admin"]]) {
    await prepare(page, state, route);
    if (state === "custom-chat-long-content") await page.locator(".source-details summary").click();
    if (state === "custom-search-long-content") await page.locator(".search-filter-details summary").click();
    await page.evaluate(() => scrollTo(0, 0));
    const measured = await page.evaluate(() => {
      // Snapshot first to avoid compounding inherited font sizes. This is a
      // text-only stress simulation, not a browser-menu zoom measurement.
      const elements = Array.from(document.querySelectorAll<HTMLElement>("body,body *"));
      const snapshot = elements.map(element => ({ element, size: parseFloat(getComputedStyle(element).fontSize), line: getComputedStyle(element).lineHeight }));
      for (const item of snapshot) {
        item.element.style.setProperty("font-size", `${item.size * 2}px`, "important");
        if (item.line !== "normal") item.element.style.setProperty("line-height", `${parseFloat(item.line) * 2}px`, "important");
      }
      const controls = elements.filter(element => element.matches("button,a,summary") && element.getBoundingClientRect().width > 0 && getComputedStyle(element).visibility !== "hidden" && !element.closest('[aria-hidden="true"]'));
      return { overflow: document.documentElement.scrollWidth > innerWidth, width: innerWidth, scrollWidth: document.documentElement.scrollWidth, clippedControls: controls.filter(element => element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1).map(element => ({ name: element.getAttribute("aria-label") || element.textContent?.trim(), className: element.className, width: element.clientWidth, scrollWidth: element.scrollWidth, height: element.clientHeight, scrollHeight: element.scrollHeight })), method: "All computed font sizes and explicit line heights doubled; no actual browser-menu zoom; screenshots require semantic inspection" };
    });
    const overflowNodes = await page.evaluate(() => Array.from(document.querySelectorAll<HTMLElement>("body *")).filter(node => { const rect = node.getBoundingClientRect(); return rect.width > 0 && rect.right > innerWidth + 1 && getComputedStyle(node).visibility !== "hidden" && !node.closest('[aria-hidden="true"]'); }).map(node => ({ tag: node.tagName, className: node.className, text: node.textContent?.slice(0, 90), right: node.getBoundingClientRect().right, width: node.getBoundingClientRect().width })));
    const overflowMetrics = await page.evaluate(() => Array.from(document.querySelectorAll<HTMLElement>("body *")).filter(node => {
      const style = getComputedStyle(node);
      return style.display !== "none" && style.visibility !== "hidden" && !node.closest('[aria-hidden="true"]') && (node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1);
    }).map(node => ({ tag: node.tagName, className: node.className, text: node.textContent?.slice(0, 90), clientWidth: node.clientWidth, scrollWidth: node.scrollWidth, clientHeight: node.clientHeight, scrollHeight: node.scrollHeight })).slice(0, 40));
    const name = `${state}-text-200-${testInfo.project.name}`;
    const screenshot = await captureQualityScreenshot(page, testInfo, name, !state.endsWith("confirmation"));
    const accessibility = await runQualityAccessibility(page, state.endsWith("confirmation"), true);
    await writeQualityArtifact(testInfo, name, { schema: "rick-web-quality-evidence.v1", kind: "200-percent-text-reflow", state, viewport: page.viewportSize(), screenshot, measured: { ...measured, overflowNodes, overflowMetrics }, errors, accessibility: qualityAccessibilityEvidence(accessibility, ["avoid-inline-spacing: disabled because the test injects inline font/line-height stress styles", "color-contrast: disabled because synthetic overlapping text invalidates axe background sampling during the injected stress"]), method: "Computed font sizes and explicit line heights doubled on a fresh page; this is a deterministic text-reflow stress test, not browser-menu zoom." });
    await testInfo.attach(`${state}-text-stress`, { body: JSON.stringify({ ...measured, overflowNodes, overflowMetrics }, null, 2), contentType: "application/json" });
    expect.soft(measured.overflow, `${state} text reflow`).toBe(false);
    expect.soft(measured.clippedControls, `${state} clipped control labels`).toEqual([]);
    const namedReflowOverflow = overflowMetrics.filter(node => String(node.className).includes("mobileActiveTitle") || ["search-form-actions", "search-summary-details", "result-number"].includes(String(node.className)));
    await testInfo.attach(`${state}-named-reflow-overflow`, { body: JSON.stringify(namedReflowOverflow, null, 2), contentType: "application/json" });
    expect.soft(namedReflowOverflow, `${state} conversation title, search metadata and actions fit enlarged text`).toEqual([]);
    const internalClipping = await page.evaluate(() => {
      const failures: { selector: string; text: string | null; kind: string }[] = [];
      for (const selector of [".login-statement h1", ".login-brand .brand-mark", ".rail-link small", ".profile-button strong", ".rail-trust small", ".mobileActiveTitle"]) {
        for (const element of document.querySelectorAll<HTMLElement>(selector)) {
          if (getComputedStyle(element).visibility === "hidden" || element.closest('[aria-hidden="true"]')) continue;
          const range = document.createRange();
          range.selectNodeContents(element);
          const box = element.getBoundingClientRect();
          // Headline glyphs may extend beyond a tight line box without being
          // clipped. Check their vertical clipping ancestor, not line metrics.
          const verticalBox = selector === ".login-statement h1" ? element.closest(".login-visual")!.getBoundingClientRect() : box;
          if (Array.from(range.getClientRects()).some(rect => rect.left < box.left - 1 || rect.right > box.right + 1 || rect.top < verticalBox.top - 1 || rect.bottom > verticalBox.bottom + 1)) failures.push({ selector, text: element.textContent, kind: "text outside its box or clipping ancestor" });
        }
      }
      for (const element of document.querySelectorAll<HTMLElement>(".search-form input,.search-form textarea")) {
        const panel = element.closest(".panel")!;
        const box = element.getBoundingClientRect(), parent = panel.getBoundingClientRect(), style = getComputedStyle(panel);
        if (box.left < parent.left + parseFloat(style.paddingLeft) - 1 || box.right > parent.right - parseFloat(style.paddingRight) + 1) failures.push({ selector: element.id, text: null, kind: "control outside panel gutter" });
      }
      return failures;
    });
    await testInfo.attach(`${state}-internal-clipping`, { body: JSON.stringify(internalClipping, null, 2), contentType: "application/json" });
    expect.soft(internalClipping, `${state} text and inputs retain their internal space`).toEqual([]);
    if (state.endsWith("confirmation")) {
      const dialog = page.getByRole("dialog");
      const boundary = await dialog.evaluate(element => {
        const box = element.getBoundingClientRect();
        const description = element.querySelector("#confirm-dialog-description")!.getBoundingClientRect();
        return { width: element.clientWidth, contentWidth: element.scrollWidth, left: box.left, right: box.right, descriptionLeft: description.left, descriptionRight: description.right };
      });
      const boundaryScreenshot = await captureQualityScreenshot(page, testInfo, `${state}-enlarged-dialog-boundary-${testInfo.project.name}`, false);
      await writeQualityArtifact(testInfo, `${state}-enlarged-dialog-boundary-${testInfo.project.name}`, { schema: "rick-web-quality-evidence.v1", kind: "200-percent-dialog-boundary", state, viewport: page.viewportSize(), screenshot: boundaryScreenshot, boundary, errors, accessibility: qualityAccessibilityEvidence(accessibility, ["avoid-inline-spacing: disabled because the test injects inline font/line-height stress styles", "color-contrast: disabled because synthetic overlapping text invalidates axe background sampling during the injected stress"]), method: "Keyboard reachability after deterministic text-reflow stress." });
      await testInfo.attach("enlarged-dialog-boundary", { body: JSON.stringify(boundary, null, 2), contentType: "application/json" });
      expect.soft(boundary.contentWidth, "Dialog contents must not require horizontal recovery").toBeLessThanOrEqual(boundary.width + 1);
      expect.soft(boundary.descriptionRight, "Consequence stays inside its clipping ancestor").toBeLessThanOrEqual(boundary.right - 1);
      const cancel = dialog.getByRole("button", { name: "Cancelar", exact: true });
      const remove = dialog.getByRole("button", { name: "Excluir documento", exact: true });
      await expect(cancel).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(remove).toBeFocused();
      const focusBounds = await remove.evaluate(element => {
        const box = element.getBoundingClientRect(), panel = element.closest('[role="dialog"]')!.getBoundingClientRect();
        return { left: box.left, right: box.right, top: box.top, bottom: box.bottom, panelLeft: panel.left, panelRight: panel.right, panelTop: panel.top, panelBottom: panel.bottom, viewportHeight: innerHeight };
      });
      await testInfo.attach("enlarged-dialog-keyboard-reachability", { body: JSON.stringify(focusBounds, null, 2), contentType: "application/json" });
      expect.soft(focusBounds.left).toBeGreaterThanOrEqual(focusBounds.panelLeft);
      expect.soft(focusBounds.right).toBeLessThanOrEqual(focusBounds.panelRight);
      expect.soft(focusBounds.top).toBeGreaterThanOrEqual(focusBounds.panelTop);
      expect.soft(focusBounds.bottom).toBeLessThanOrEqual(Math.min(focusBounds.panelBottom, focusBounds.viewportHeight));
      await page.keyboard.press("Shift+Tab");
      await expect(cancel).toBeFocused();
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
      await expect(page.getByRole("button", { name: `Excluir ${title}`, exact: true })).toBeFocused();
    }
    const skip = page.getByRole("link", { name: "Pular para o conteúdo" });
    if (await skip.count()) expect.soft(await skip.evaluate(element => element.getBoundingClientRect().bottom), `${state} unfocused skip link stays outside viewport`).toBeLessThanOrEqual(0);
  }
});

test("quality 200 percent effective viewport reflow", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const baseViewport = page.viewportSize()!;
  const effectiveViewport = { width: Math.max(320, Math.floor(baseViewport.width / 2)), height: baseViewport.height };
  await page.setViewportSize(effectiveViewport);
  for (const [state, route] of [["custom-workbench-success", "/app"], ["custom-search-long-content", "/app/search"], ["custom-chat-long-content", "/app/chat"], ["custom-documents-confirmation", "/app/documents"]]) {
    await prepare(page, state, route);
    if (state === "custom-chat-long-content") await page.locator(".source-details summary").click();
    if (state === "custom-search-long-content") await page.locator(".search-filter-details summary").click();
    const measured = await page.evaluate(() => ({ effective_zoom: 2, width: innerWidth, height: innerHeight, overflow: document.documentElement.scrollWidth > innerWidth, scrollWidth: document.documentElement.scrollWidth, scrollHeight: document.documentElement.scrollHeight }));
    const name = `${state}-viewport-200-${testInfo.project.name}`;
    const screenshot = await captureQualityScreenshot(page, testInfo, name, !state.endsWith("confirmation"));
    const accessibility = await runQualityAccessibility(page, state.endsWith("confirmation"));
    await writeQualityArtifact(testInfo, name, { schema: "rick-web-quality-evidence.v1", kind: "200-percent-effective-viewport-reflow", state, base_viewport: baseViewport, viewport: page.viewportSize(), screenshot, measured, errors, accessibility: qualityAccessibilityEvidence(accessibility), method: "Fresh CSS viewport constrained to at least 320px and set to half the canonical width, representing 200% browser reflow without pinch/page-scale cropping." });
    expect(measured.overflow, state).toBe(false);
  }
});

for (const [state, route] of [["custom-login-default", "/login"], ["custom-workbench-success", "/app"], ["custom-search-results", "/app/search"], ["perf-chat", "/app/chat"], ["custom-documents-list", "/app/documents"], ["custom-admin-allowed", "/admin"]]) {
  test(`quality performance ${route}`, async ({ page }, testInfo) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const client = await page.context().newCDPSession(page);
    await client.send("Network.enable");
    await client.send("Network.setCacheDisabled", { cacheDisabled: true });
    await client.send("Emulation.setCPUThrottlingRate", { rate: 4 });
    await page.addInitScript(() => {
      const measurement = { lcp: 0, cls: 0, shifts: [] as { value: number; at: number; sources: { node: string | null; previous: { x: number; y: number; width: number; height: number }; current: { x: number; y: number; width: number; height: number } }[] }[] };
      const layoutSnapshots: { at: number; nodes: { selector: string; rect: { x: number; y: number; width: number; height: number } | null }[] }[] = [];
      const selectors = [".topbar", ".main-content", ".page-heading", ".heading-actions", ".collection-management-panel", ".documents-toolbar", ".documents-panel", ".surface-footnote"];
      let previousLayout = "";
      const layoutSampler = window.setInterval(() => {
        const nodes = selectors.map(selector => {
          const element = document.querySelector(selector);
          if (!element) return { selector, rect: null };
          const rect = element.getBoundingClientRect();
          return { selector, rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height } };
        });
        const serialized = JSON.stringify(nodes);
        if (serialized !== previousLayout && layoutSnapshots.length < 24) {
          layoutSnapshots.push({ at: performance.now(), nodes });
          previousLayout = serialized;
        }
      }, 50);
      window.setTimeout(() => window.clearInterval(layoutSampler), 2500);
      Object.assign(window, { qualityPerformance: measurement, qualityLayoutSnapshots: layoutSnapshots });
      new PerformanceObserver(list => {
        for (const entry of list.getEntries()) measurement.lcp = entry.startTime;
      }).observe({ type: "largest-contentful-paint", buffered: true });
      new PerformanceObserver(list => {
        for (const item of list.getEntries()) {
          const entry = item as PerformanceEntry & { hadRecentInput: boolean; value: number; sources?: { node?: Node | null; previousRect: DOMRectReadOnly; currentRect: DOMRectReadOnly }[] };
          if (!entry.hadRecentInput) measurement.shifts.push({
            value: entry.value,
            at: entry.startTime,
            sources: entry.sources?.map(source => ({
              node: source.node instanceof Element
                ? `${source.node.tagName.toLowerCase()}${source.node.id ? `#${source.node.id}` : ""}${typeof source.node.className === "string" && source.node.className ? `.${source.node.className.trim().replace(/\s+/g, ".")}` : ""}`
                : source.node?.nodeName ?? null,
              previous: { x: source.previousRect.x, y: source.previousRect.y, width: source.previousRect.width, height: source.previousRect.height },
              current: { x: source.currentRect.x, y: source.currentRect.y, width: source.currentRect.width, height: source.currentRect.height },
            })) ?? [],
          });
        }
        let start = 0, previous = 0, total = 0;
        for (const shift of measurement.shifts) {
          if (shift.at - previous > 1000 || shift.at - start > 5000) { start = shift.at; total = 0; }
          total += shift.value;
          measurement.cls = Math.max(measurement.cls, total);
          previous = shift.at;
        }
      }).observe({ type: "layout-shift", buffered: true });
    });
    await prepare(page, state, route);
    await expect(page.locator("h1")).toBeVisible();
    // Fixed observation window, not a readiness substitute; no user input before LCP.
    await page.waitForTimeout(2000);
    const measured = await page.evaluate(() => ({
      ...(window as unknown as { qualityPerformance: { lcp: number; cls: number; shifts: unknown[] } }).qualityPerformance,
      layout_snapshots: (window as unknown as { qualityLayoutSnapshots: unknown[] }).qualityLayoutSnapshots,
      resources: performance.getEntriesByType("resource").map(item => { const entry = item as PerformanceResourceTiming; return { name: entry.name, type: entry.initiatorType, transferred: entry.transferSize, duration: entry.duration }; }),
      images: Array.from(document.images).map(image => ({ source: image.currentSrc, width: image.naturalWidth, height: image.naturalHeight })),
      fontStatus: document.fonts.status,
    }));
    const performanceEvidence = { schema: "rick-web-performance.v1", test: `quality performance ${route}`, route, viewport: page.viewportSize(), measured, thresholds: { lcp_ms_max: 2500, cls_max: 0.1 }, assertion: { lcp_positive: measured.lcp > 0, lcp_within_budget: measured.lcp <= 2500, cls_within_budget: measured.cls <= 0.1 }, profile: "Production build; fresh test context; cache disabled; 4x CPU throttle; synthetic instantaneous API; local assets; reduced-motion preference; 2s post-ready window. Single lab sample, not field p75, API latency or deployment acceptance." };
    const performanceRoot = resolve(process.env.RICK_PERFORMANCE_EVIDENCE_DIR || testInfo.outputPath("performance"));
    await mkdir(performanceRoot, { recursive: true });
    const routeId = route.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "") || "root";
    const performanceReport = resolve(performanceRoot, `${routeId}-${testInfo.project.name}.json`);
    await writeFile(performanceReport, JSON.stringify(performanceEvidence, null, 2));
    await testInfo.attach("local-renderer-performance", { path: performanceReport, contentType: "application/json" });
    expect(measured.lcp).toBeGreaterThan(0);
    expect(measured.lcp).toBeLessThanOrEqual(2500);
    expect(measured.cls).toBeLessThanOrEqual(0.1);
  });
}
