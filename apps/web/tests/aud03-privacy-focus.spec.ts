import { expect, test, type Page } from "@playwright/test";
import { build } from "esbuild";
import { readFileSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

// An offline component boundary supplements the Next route tests. Only the
// session input is injected; React, cases, API transport, modal and CSS are the
// current application's code. It exercises authority changes without adding
// test controls or globals to the shipped product.
async function mount(page: Page) {
  await page.context().setOffline(true);
  const result = await build({
    absWorkingDir: process.cwd(),
    stdin: { contents: `import React from 'react'; import {createRoot} from 'react-dom/client'; import {CaseWorkspace} from './components/cases/case-workspace'; import {ConfirmDialog} from './components/ui';
      const root=createRoot(document.getElementById('root'));
      window.renderCase=()=>root.render(React.createElement(CaseWorkspace));
      window.renderDialog=(busy,open=true)=>root.render(React.createElement(ConfirmDialog,{open,busy,title:'Excluir documento?',description:'O documento será removido do acervo autorizado.',onCancel:()=>window.cancelCount++,onConfirm:()=>{}}));
`, resolveDir: process.cwd(), loader: "tsx" },
    bundle: true, write: false, format: "iife", jsx: "automatic",
    define: { "process.env.NODE_ENV": '"development"', "process.env.NEXT_PUBLIC_API_BASE_URL": '""' },
    plugins: [{ name: "session-input", setup(builder) {
      builder.onResolve({ filter: /@\/components\/session-provider/ }, () => ({ path: "session-input", namespace: "fixture" }));
      builder.onLoad({ filter: /.*/, namespace: "fixture" }, () => ({ contents: "export function useSession(){return {session:window.session,ready:true}}", loader: "js" }));
    } }],
  });
  await page.setContent('<html lang="pt-BR"><body><button id="trigger">Abrir confirmação</button><div id="root"></div></body></html>');
  await page.addStyleTag({ content: readFileSync(resolve("app/globals.css"), "utf8") });
  await page.addScriptTag({ content: result.outputFiles[0].text });
}
async function capture(page: Page, state: string, project: string) {
  const dir = process.env.RICK_AUD03_WEB_EVIDENCE_DIR;
  if (!dir) return;
  await mkdir(dir, { recursive: true });
  await page.screenshot({ path: resolve(dir, `${project}-${state}.png`), fullPage: true });
}

test("AUD03 busy modal contains Tab in both directions, blocks Escape and restores trigger", async ({ page }, testInfo) => {
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  await mount(page);
  await page.locator("#trigger").focus();
  await page.evaluate(() => {
    const harness = window as unknown as { renderDialog: (busy: boolean, open?: boolean) => void; cancelCount: number };
    harness.cancelCount = 0; harness.renderDialog(false);
  });
  await expect(page.getByRole("button", { name: "Cancelar", exact: true })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByRole("button", { name: "Confirmar", exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Cancelar", exact: true })).toBeFocused();
  await page.evaluate(() => (window as unknown as { renderDialog: (busy: boolean) => void }).renderDialog(true));
  const dialog = page.getByRole("dialog"); await expect(dialog).toHaveAttribute("aria-busy", "true");
  await expect(dialog).toBeFocused();
  for (const key of ["Tab", "Tab", "Shift+Tab", "Shift+Tab", "Escape"]) {
    await page.keyboard.press(key); await expect(dialog).toBeFocused();
  }
  expect(await page.evaluate(() => (window as unknown as { cancelCount: number }).cancelCount)).toBe(0);
  await capture(page, "modal-busy-keyboard", testInfo.project.name);
  await page.evaluate(() => (window as unknown as { renderDialog: (busy: boolean, open: boolean) => void }).renderDialog(false, false));
  await expect(page.locator("#trigger")).toBeFocused(); expect(errors).toEqual([]);
});

for (const pendingKind of ["list", "detail"] as const) {
  test(`AUD03 revoked cases.read keeps late ${pendingKind} private content out of the DOM`, async ({ page }, testInfo) => {
    const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await mount(page);
    await page.evaluate((kind) => {
      const harness = window as unknown as { session: Record<string, unknown>; renderCase: () => void; release: () => void; settled: boolean };
      harness.session = { authenticated: true, user_id: "u", session_id: "s", tenant_id: "t", workspace_id: "w", role: "VETERINARIAN", permissions: ["cases.read"] };
      const item = { case_id: "private", title: "PRIVATE CASE", summary: "PRIVATE SUMMARY", status: "open", owner_user_id: "u", updated_at: 1, clinical_scope_status: "human_only", hypotheses: [], evidence: [] };
      window.fetch = async (input) => {
        const path = String(input);
        const list = path.startsWith("/api/v1/cases?");
        const detail = path === "/api/v1/cases/private";
        if ((kind === "list" && list) || (kind === "detail" && detail)) {
          return new Promise<Response>(resolve => { harness.release = () => { resolve(new Response(JSON.stringify(list ? { items: [item], total: 1 } : { case: item, reviews: [], feedback: [] }))); setTimeout(() => requestAnimationFrame(() => requestAnimationFrame(() => { harness.settled = true; })), 0); }; });
        }
        if (list) return new Response(JSON.stringify({ items: [item], total: 1 }));
        if (path.endsWith("/catalog/agents")) return new Response(JSON.stringify({ catalog_status: "not_configured", items: [] }));
        if (detail) return new Response(JSON.stringify({ case: item, reviews: [], feedback: [] }));
        throw new Error(`Unexpected request ${path}`);
      };
      harness.renderCase();
    }, pendingKind);
    await page.waitForFunction(() => typeof (window as unknown as { release: unknown }).release === "function");
    await capture(page, `case-${pendingKind}-loading`, testInfo.project.name);
    await page.evaluate(() => {
      const harness = window as unknown as { session: Record<string, unknown>; renderCase: () => void };
      harness.session = { ...harness.session, permissions: [] }; harness.renderCase();
    });
    await expect(page.getByText("Sem acesso aos casos", { exact: true })).toBeVisible();
    await page.evaluate(() => (window as unknown as { release: () => void }).release());
    await page.waitForFunction(() => (window as unknown as { settled: boolean }).settled);
    await expect(page.getByText("PRIVATE CASE", { exact: true })).toHaveCount(0);
    await expect(page.getByText("PRIVATE SUMMARY", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Sem acesso aos casos", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await capture(page, `case-${pendingKind}-revoked`, testInfo.project.name);
    expect(errors).toEqual([]);
  });
}
