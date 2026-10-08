import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { expect, test, type Route } from "@playwright/test";

const session = { authenticated: true, user_id: "synthetic", email: "km@example.invalid", role: "KNOWLEDGE_MANAGER", canonical_role: "KNOWLEDGE_MANAGER", permissions: ["chat.query", "documents.read", "documents.upload", "documents.manage", "ingestion.run", "reindex.run", "collections.read", "observability.read", "audit.read"],  tenant_id: "default", workspace_id: "default", session_id: "synthetic" };
const catalog = (name: string) => ({ total: 1, next_cursor: null, items: [{ document_id: name, title: `Documento ${name}`, collection_id: name, workspace_id: "default", status: "published", source_type: "md" }] });

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/auth/me", route => route.fulfill({ json: session }));
  await page.route("**/api/v1/collections?**", route => route.fulfill({ json: { total: 2, items: ["a", "b"].map(id => ({ collection_id: id, title: id, workspace_id: "default" })) } }));
});

test("document denial does not render empty catalog or a known count", async ({ page }) => {
  await page.route("**/api/v1/documents?**", route => route.fulfill({ status: 403, json: { error: { message: "Synthetic denied" } } }));
  await page.goto("/app/documents");
  await expect(page.getByRole("heading", { name: "Sem acesso aos documentos" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Nenhum documento publicado" })).toHaveCount(0);
  await expect(page.locator(".documents-panel .panel-index")).toHaveText("—");
  await expect(page.locator(".documents-panel").getByRole("button", { name: "Adicionar documento", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Tentar novamente", exact: true })).toBeEnabled();
});

test("collection loading and failure remain distinct from a confirmed empty collection list", async ({ page }) => {
  const heldCollectionRequests: Route[] = [];
  let retryRequested = false;
  await page.unrouteAll({ behavior: "wait" });
  await page.route("**/api/v1/auth/me", route => route.fulfill({ json: session }));
  await page.route("**/api/v1/collections?**", route => {
    if (!retryRequested) {
      heldCollectionRequests.push(route);
      return;
    }
    return route.fulfill({ json: { total: 1, items: [{ collection_id: "a", title: "Coleção A", workspace_id: "default" }] } });
  });
  await page.route("**/api/v1/documents?**", route => route.fulfill({ json: { total: 0, next_cursor: null, items: [] } }));

  await page.goto("/app/documents");
  await expect(page.locator(".collection-management-panel .collection-state-row")).toContainText("Consultando as coleções autorizadas.");
  await expect(page.getByText("Nenhuma coleção ativa", { exact: true })).toHaveCount(0);
  const uploadCollection = page.getByLabel("Coleção de destino do upload");
  await expect(uploadCollection).toBeDisabled();
  await expect(uploadCollection.locator("option")).toHaveText("Carregando coleções…");
  await expect(page.locator("#upload-collection-state")).toHaveText("Carregando coleções autorizadas.");
  await expect.poll(() => heldCollectionRequests.length).toBeGreaterThan(0);

  await Promise.all(heldCollectionRequests.splice(0).map(route => route.fulfill({ status: 503, json: { error: { message: "Synthetic unavailable" } } })));
  const collectionError = page.locator(".upload-collections-alert");
  await expect(collectionError).toContainText("Não foi possível consultar as coleções");
  await expect(uploadCollection).toBeDisabled();
  await expect(uploadCollection.locator("option")).toHaveText("Coleções indisponíveis");
  await expect(uploadCollection).toHaveAttribute("title", "A lista de coleções está indisponível. O envio está pausado até a lista atualizar.");
  await expect(page.locator("#upload-collection-state")).toContainText("O envio está pausado até a lista atualizar.");
  await expect(page.getByText("Nenhuma coleção ativa", { exact: true })).toHaveCount(0);

  retryRequested = true;
  await collectionError.getByRole("button", { name: "Tentar novamente", exact: true }).click();
  await expect(collectionError).toHaveCount(0);
  await expect(page.locator(".collection-management-panel .collection-row")).toContainText("Coleção A");
  await expect(uploadCollection).toBeEnabled();
  await expect(uploadCollection).toHaveValue("a");
  await expect(page.locator("#upload-collection-state")).toHaveText("");
});

test("upload-only users see a collection outage and can retry from the upload controls", async ({ page }, testInfo) => {
  const uploader = {
    ...session,
    role: "VETERINARIAN",
    canonical_role: "VETERINARIAN",
    permissions: ["chat.query", "documents.read", "documents.upload", "ingestion.run", "collections.read"],
  };
  await page.unrouteAll({ behavior: "wait" });
  await page.route("**/api/v1/auth/me", route => route.fulfill({ json: uploader }));
  let collectionRequests = 0;
  await page.route("**/api/v1/collections?**", route => {
    collectionRequests += 1;
    if (collectionRequests === 1) return route.fulfill({ status: 503, json: { error: { message: "Synthetic unavailable" } } });
    return route.fulfill({ json: { total: 1, items: [{ collection_id: "references", title: "Coleção de referências clínicas com um nome longo", workspace_id: "default" }] } });
  });
  await page.route("**/api/v1/documents?**", route => route.fulfill({ json: { total: 0, next_cursor: null, items: [] } }));

  await page.goto("/app/documents");
  const collectionError = page.locator(".upload-collections-alert");
  await expect(collectionError).toContainText("O envio fica pausado até a lista atualizar.");
  await expect(collectionError.getByRole("button", { name: "Tentar novamente", exact: true })).toBeEnabled();
  const selector = page.getByLabel("Coleção de destino do upload");
  await expect(selector).toBeDisabled();
  await expect(selector.locator("option")).toHaveText("Coleções indisponíveis");
  await expect(selector).toHaveAttribute("title", "A lista de coleções está indisponível. O envio está pausado até a lista atualizar.");
  const selectorBox = await selector.boundingBox();
  expect(selectorBox?.width).toBeGreaterThanOrEqual(218);
  const selectorLabelBox = await page.locator(".upload-collection-select > .eyebrow").boundingBox();
  if (!selectorBox || !selectorLabelBox) throw new Error("The destination selector must expose both its label and control.");
  expect(selectorLabelBox.y + selectorLabelBox.height).toBeLessThan(selectorBox.y);
  if ((page.viewportSize()?.width || 0) <= 440) {
    const messageBox = await collectionError.locator("span").boundingBox();
    const retryBox = await collectionError.getByRole("button", { name: "Tentar novamente", exact: true }).boundingBox();
    if (!messageBox || !retryBox) throw new Error("The mobile collection alert must expose its message and retry control.");
    expect(retryBox.y).toBeGreaterThan(messageBox.y + messageBox.height - 1);
  }
  const uploadButton = page.getByRole("button", { name: "Adicionar documento", exact: true });
  await expect(uploadButton).toBeDisabled();
  await expect(uploadButton).toHaveCSS("background-color", "rgb(231, 236, 233)");
  await expect(page.locator(".documents-panel").getByRole("button", { name: "Adicionar documento", exact: true })).toHaveCount(0);
  const evidenceDirectory = resolve(process.env.RICK_VISUAL_EVIDENCE_DIR || testInfo.outputPath("evidence"));
  await mkdir(evidenceDirectory, { recursive: true });
  const screenshotPath = resolve(evidenceDirectory, `upload-only-collection-error-${testInfo.project.name}-viewport.png`);
  await page.screenshot({ path: screenshotPath, fullPage: false });
  await testInfo.attach("upload-only-collection-error-viewport", { path: screenshotPath, contentType: "image/png" });

  await collectionError.getByRole("button", { name: "Tentar novamente", exact: true }).click();
  await expect(collectionError).toHaveCount(0);
  await expect(selector).toBeEnabled();
  await expect(selector).toHaveValue("references");
  await expect(selector).toHaveAttribute("title", "Coleção de referências clínicas com um nome longo");
  await expect(page.locator(".documents-panel").getByRole("button", { name: "Adicionar documento", exact: true })).toBeEnabled();
});

test("catalog refresh failure hides stale documents and permits a real retry", async ({ page }) => {
  let failed = false;
  await page.route("**/api/v1/documents?**", route => route.fulfill(failed ? { status: 500, json: { error: { message: "Synthetic unavailable" } } } : { json: catalog("atual") }));
  await page.goto("/app/documents");
  await expect(page.getByText("Documento atual", { exact: true })).toBeVisible();
  failed = true;
  await page.getByRole("button", { name: "Atualizar", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Catálogo não disponível" })).toBeVisible();
  await expect(page.getByText("Documento atual", { exact: true })).toHaveCount(0);
  await expect(page.locator(".documents-panel .panel-index")).toHaveText("—");
  failed = false;
  await page.getByRole("button", { name: "Tentar novamente", exact: true }).click();
  await expect(page.getByText("Documento atual", { exact: true })).toBeVisible();
});

test("upload targets the user-selected authorized collection", async ({ page }) => {
  const uploads: { collection: string | null; file?: { name: string; type: string } }[] = [];
  await page.route("**/api/v1/documents/upload", async route => {
    const request = route.request();
    const body = request.postDataBuffer() || Buffer.alloc(0);
    const form = await new Response(new Uint8Array(body), {
      headers: { "content-type": request.headers()["content-type"] || "" },
    }).formData();
    const collection = form.get("collection_id");
    const file = form.get("file");
    uploads.push({
      collection: typeof collection === "string" ? collection : null,
      file: file && typeof file !== "string" ? { name: file.name, type: file.type } : undefined,
    });
    await route.fulfill({ json: { status: "queued", job_id: "upload-job", job: { job_id: "upload-job", status: "published", stage: "published", progress: 1, attempt: 1 } } });
  });
  await page.route("**/api/v1/ingestion/jobs/upload-job", route => route.fulfill({ json: { status: "published", job_id: "upload-job", job: { job_id: "upload-job", status: "published", stage: "published", progress: 1, attempt: 1, retryable: false } } }));
  await page.route("**/api/v1/documents?**", route => route.fulfill({ json: catalog("atual") }));
  await page.goto("/app/documents");
  const selector = page.getByLabel("Coleção de destino do upload");
  await expect(selector).toBeVisible();
  await expect(page.getByRole("button", { name: "Adicionar documento", exact: true })).toBeEnabled();
  await page.setInputFiles("#document-upload-input", { name: "fonte.md", mimeType: "text/markdown", buffer: Buffer.from("fonte de teste") });
  await expect(page.getByText("Documento publicado pelo servidor.")).toBeVisible();
  await expect.poll(() => uploads.length).toBe(1);
  expect(uploads[0].collection).toBe("a");
  expect(uploads[0].file).toEqual({ name: "fonte.md", type: "text/markdown" });
  await selector.selectOption("b");
  await page.setInputFiles("#document-upload-input", { name: "fonte-b.md", mimeType: "text/markdown", buffer: Buffer.from("segunda fonte") });
  await expect.poll(() => uploads.length).toBe(2);
  expect(uploads[1].collection).toBe("b");
});

test("retry resubmits the original binary file without text conversion", async ({ page }) => {
  const original = Buffer.from("%PDF-1.4\n%\xE2\xE3\xCF\xD3\nsynthetic-binary\n", "latin1");
  let retryBody: Buffer | null = null;
  let retryContentType = "";

  await page.route("**/api/v1/documents/upload", route => route.fulfill({
    json: {
      status: "failed",
      job_id: "failed-upload",
      job: {
        job_id: "failed-upload",
        status: "failed",
        stage: "failed",
        progress: 0.6,
        attempt: 1,
        retryable: true,
        error_message: "Synthetic transient failure",
      },
    },
  }));
  await page.route("**/api/v1/ingestion/jobs/failed-upload/retry", route => {
    retryBody = route.request().postDataBuffer();
    retryContentType = route.request().headers()["content-type"] || "";
    return route.fulfill({
      json: {
        status: "published",
        job_id: "retry-published",
        job: {
          job_id: "retry-published",
          status: "published",
          stage: "published",
          progress: 1,
          attempt: 2,
          retryable: false,
        },
      },
    });
  });
  await page.route("**/api/v1/documents?**", route => route.fulfill({ json: catalog("atual") }));

  await page.goto("/app/documents");
  await page.setInputFiles("#document-upload-input", {
    name: "source.pdf",
    mimeType: "application/pdf",
    buffer: original,
  });
  await expect(page.getByText("Synthetic transient failure")).toBeVisible();
  await page.getByRole("button", { name: "Tentar novamente", exact: true }).click();
  await expect(page.getByText("A nova tentativa confirmou a publicação pelo servidor.")).toBeVisible();

  expect(retryContentType).toContain("multipart/form-data; boundary=");
  expect(retryBody).not.toBeNull();
  const retryForm = await new Response(new Uint8Array(retryBody!), {
    headers: { "content-type": retryContentType },
  }).formData();
  const retryFile = retryForm.get("file");
  expect(retryFile).not.toBeNull();
  expect(typeof retryFile).not.toBe("string");
  if (!retryFile || typeof retryFile === "string") throw new Error("Missing binary retry file");
  expect(Buffer.from(await retryFile.arrayBuffer())).toEqual(original);
  expect(retryFile.name).toBe("source.pdf");
  expect(retryFile.type).toBe("application/pdf");
});

for (const collectionState of ["empty", "archived"] as const) {
  test(`upload is disabled when authorized collections are ${collectionState}`, async ({ page }) => {
    let uploads = 0;
    await page.route("**/api/v1/collections?**", route => route.fulfill({ json: {
      total: collectionState === "empty" ? 0 : 1,
      items: collectionState === "empty" ? [] : [{ collection_id: "a", title: "Arquivada", workspace_id: "default", status: "archived" }],
    } }));
    await page.route("**/api/v1/documents?**", route => route.fulfill({ json: { total: 0, next_cursor: null, items: [] } }));
    await page.route("**/api/v1/documents/upload", route => { uploads += 1; return route.abort(); });
    await page.goto("/app/documents");
    await expect(page.getByRole("heading", { name: "Nenhum documento publicado" })).toBeVisible();
    const uploadCollection = page.getByLabel("Coleção de destino do upload");
    await expect(uploadCollection).toBeDisabled();
    await expect(uploadCollection.locator("option")).toHaveText("Nenhuma coleção ativa");
    await expect(page.locator("#upload-collection-state")).toContainText("Nenhuma coleção ativa.");
    if (collectionState === "empty") await expect(page.locator(".collection-management-panel .collection-empty-state strong")).toHaveText("Nenhuma coleção ativa");
    await expect(page.getByRole("button", { name: "Adicionar documento", exact: true })).toBeDisabled();
    await expect(page.locator("#document-upload-input")).toBeDisabled();
    expect(uploads).toBe(0);
  });
}

test("an older collection response cannot replace the selected collection", async ({ page }) => {
  await page.addInitScript(() => {
    const original = Response.prototype.text;
    Response.prototype.text = async function () {
      const body = await original.call(this);
      if (this.url.includes("/api/v1/documents")) setTimeout(() => requestAnimationFrame(() => requestAnimationFrame(() => {
        document.documentElement.dataset.catalogReads = String(Number(document.documentElement.dataset.catalogReads || 0) + 1);
      })), 0);
      return body;
    };
  });
  let held: Route | undefined;
  await page.route("**/api/v1/documents?**", route => {
    const selected = new URL(route.request().url()).searchParams.get("collection_id") || "initial";
    if (selected === "a") { held = route; return; }
    return route.fulfill({ json: catalog(selected) });
  });
  await page.goto("/app/documents");
  await expect(page.getByText("Documento initial", { exact: true })).toBeVisible();
  await page.getByLabel("Filtrar coleção").selectOption("a");
  await expect.poll(() => Boolean(held)).toBe(true);
  await page.getByLabel("Filtrar coleção").selectOption("b");
  await expect(page.getByText("Documento b", { exact: true })).toBeVisible();
  await expect.poll(async () => Number(await page.locator("html").getAttribute("data-catalog-reads"))).toBeGreaterThan(0);
  // Let already-consumed current responses finish their scheduled render barrier.
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  const before = Number(await page.locator("html").getAttribute("data-catalog-reads") || 0);
  await held!.fulfill({ json: catalog("a") });
  await expect(page.locator("html")).toHaveAttribute("data-catalog-reads", String(before + 1));
  await expect(page.getByLabel("Filtrar coleção")).toHaveValue("b");
  await expect(page.getByText("Documento b", { exact: true })).toBeVisible();
  await expect(page.getByText("Documento a", { exact: true })).toHaveCount(0);
});
