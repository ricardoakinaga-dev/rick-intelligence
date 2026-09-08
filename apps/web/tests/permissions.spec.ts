import { expect, test } from "@playwright/test";

for (const [role, permissions, documents, admin] of [
  ["VETERINARIAN", ["chat.query", "sources.read"], false, false],
  ["KNOWLEDGE_MANAGER", ["documents.read", "chat.query", "audit.read"], true, true],
  ["PLATFORM_ADMIN", ["*"], true, true],
  ["PLATFORM_ADMIN", [], false, false],
  ["PLATFORM_ADMIN", undefined, false, false],
] as const) {
  test(`authoritative permissions ${role} ${JSON.stringify(permissions)}`, async ({ page }, testInfo) => {
    let documentRequests = 0;
    await page.route("**/api/v1/auth/me", route => route.fulfill({ json: {
      authenticated: true, user_id: "synthetic", email: "synthetic@example.invalid",
      role, canonical_role: role, permissions, tenant_id: "default", workspace_id: "default", session_id: "synthetic",
    } }));
    await page.route("**/api/v1/documents?**", route => {
      documentRequests += 1;
      return route.fulfill({ json: { items: [], total: 0 } });
    });
    await page.route("**/health/ready", route => route.fulfill({ json: { status: "ready" } }));
    await page.goto("/app");
    await expect(page.locator(".service-state")).toHaveText("Disponível");
    await expect(page.locator('.workbench-tools a[href="/app/documents"]')).toHaveCount(documents ? 1 : 0);
    const menu = page.getByRole("button", { name: "Abrir navegação" });
    if (await menu.count()) {
      await menu.click();
      await expect.poll(async () => Math.round((await page.locator(".rail").boundingBox())?.x ?? -1)).toBe(0);
    }
    await expect(page.locator('.rail a[href="/app/documents"]')).toHaveCount(documents ? 1 : 0);
    await expect(page.locator('.rail a[href="/admin"]')).toHaveCount(admin ? 1 : 0);
    if (!documents) {
      expect(documentRequests).toBe(0);
      await expect(page.locator(".workspace-status [role=alert]")).toHaveCount(0);
    }
    if (permissions?.length === 0 || permissions === undefined) {
      await expect(page.locator('.rail a[href="/app/chat"]')).toHaveCount(0);
    }
    await page.screenshot({ path: testInfo.outputPath("permissions.png"), fullPage: true, animations: "disabled" });
  });
}

for (const total of [0, 1]) {
test(`read-only catalog with ${total} documents exposes no mutation action`, async ({ page }) => {
  await page.route("**/api/v1/auth/me", route => route.fulfill({ json: {
    authenticated: true, user_id: "reader", email: "reader@example.invalid", role: "PLATFORM_ADMIN",
    canonical_role: "PLATFORM_ADMIN", permissions: ["documents.read", "collections.read"],
    tenant_id: "default", workspace_id: "default", session_id: "reader",
  } }));
  await page.route("**/api/v1/documents?**", route => route.fulfill({ json: { items: total ? [
    { document_id: "example", title: "Example", collection_id: "rag_phase0", workspace_id: "default", status: "published" },
  ] : [], total } }));
  await page.route("**/api/v1/collections?**", route => route.fulfill({ json: { items: [], total: 0 } }));
  await page.goto("/app/documents");
  await expect(page.getByText(total ? "Example" : "Nenhum documento publicado", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /Adicionar documento|Reindexar|Excluir/ })).toHaveCount(0);
});
}

for (const permission of ["audit.read", "observability.read"]) {
  test(`partial administrative grant ${permission} avoids the other endpoint`, async ({ page }) => {
    const calls: string[] = [];
    await page.route("**/api/v1/auth/me", route => route.fulfill({ json: {
      authenticated: true, user_id: "reader", email: "reader@example.invalid", role: "PLATFORM_ADMIN",
      canonical_role: "PLATFORM_ADMIN", permissions: [permission],
      tenant_id: "default", workspace_id: "default", session_id: "reader",
    } }));
    await page.route("**/api/v1/admin/**", route => {
      calls.push(new URL(route.request().url()).pathname);
      return route.fulfill({ json: { status: "ready", checks: [], items: [], total: 0 } });
    });
    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: "Controle sem improviso." })).toBeVisible();
    await expect(page.getByText(permission === "audit.read" ? "Nenhum evento de auditoria" : "Nenhuma verificação retornada")).toBeVisible();
    expect(calls).toEqual([permission === "audit.read" ? "/api/v1/admin/audit" : "/api/v1/admin/health"]);
  });
}
