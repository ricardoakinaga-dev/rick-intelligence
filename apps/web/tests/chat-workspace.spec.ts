import { expect, test, type Page, type Route } from "@playwright/test";

const session = {
  authenticated: true,
  user_id: "chat-user",
  email: "vet@example.invalid",
  role: "viewer",
  canonical_role: "VETERINARIAN",
  permissions: ["chat.query", "history.read", "sources.read", "collections.read"],
  tenant_id: "tenant-chat",
  workspace_id: "workspace-chat",
  session_id: "chat-session",
};

const conversation = {
  conversation_id: "conv-protocol",
  title: "Protocolo de biossegurança",
  workspace_id: "workspace-chat",
  collection_id: "rag-vet",
  status: "active",
  created_at: 1_700_000_000,
  updated_at: 1_700_000_120,
  message_count: 2,
};

const detail = {
  conversation,
  total: 1,
  items: [{
    conversation_id: "conv-protocol",
    message_id: "msg-first",
    question: "Qual é o protocolo de biossegurança para este caso?",
    answer: "O protocolo começa pela avaliação do risco e pela revisão das fontes autorizadas.",
    citations: [{
      document_id: "doc-bio",
      chunk_id: "chunk-bio-01",
      title: "Manual de biossegurança veterinária",
      collection_id: "rag-vet",
      page_start: 12,
      page_end: 13,
      checksum: "sha256-bio",
    }],
    metadata: { evidence_status: "APPROVED_EVIDENCE" },
    created_at: 1_700_000_100,
  }],
};

async function json(route: Route, value: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(value),
  });
}

async function mockSession(page: Page) {
  await page.route("**/api/v1/auth/me", (route) => json(route, session));
}

async function mockConversations(page: Page, options: { listStatus?: number; items?: unknown[] } = {}) {
  await page.route("**/api/v1/conversations**", async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() !== "GET") return json(route, conversation, 201);
    if (url.pathname === "/api/v1/conversations") {
      if (options.listStatus && options.listStatus !== 200) {
        return json(route, { error: { code: "forbidden", message: "Histórico recusado para esta sessão." } }, options.listStatus);
      }
      return json(route, { items: options.items ?? [conversation], total: (options.items ?? [conversation]).length });
    }
    return json(route, detail);
  });
}

test("resumes a conversation, keeps turns together, and expands citations", async ({ page }) => {
  await mockSession(page);
  await mockConversations(page);
  let requestBody: Record<string, unknown> | null = null;
  await page.route("**/api/v1/chat", async (route) => {
    requestBody = JSON.parse(route.request().postData() || "{}") as Record<string, unknown>;
    const events = [
      { type: "start", conversation_id: "conv-protocol", message_id: "msg-second" },
      { type: "delta", conversation_id: "conv-protocol", message_id: "msg-second", delta: "A resposta mantém " },
      { type: "delta", conversation_id: "conv-protocol", message_id: "msg-second", delta: "o contexto da conversa." },
      { type: "citation", conversation_id: "conv-protocol", message_id: "msg-second", citation: {
        document_id: "doc-control",
        chunk_id: "chunk-control-02",
        title: "Controle de exposição no atendimento",
        collection_id: "rag-vet",
        page_start: 7,
        checksum: "sha256-control",
      } },
      { type: "completion", conversation_id: "conv-protocol", message_id: "msg-second", answer: "A resposta mantém o contexto da conversa.", citations: [{
        document_id: "doc-control",
        chunk_id: "chunk-control-02",
        title: "Controle de exposição no atendimento",
        collection_id: "rag-vet",
        page_start: 7,
        checksum: "sha256-control",
      }] },
    ];
    const body = `${events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("")}data: [DONE]\n\n`;
    await route.fulfill({ status: 200, contentType: "text/event-stream", body });
  });

  await page.goto("/app/chat?conversation=conv-protocol");
  await expect(page.getByRole("heading", { name: "Leitura do resultado", exact: true })).toBeVisible();
  const conversationDrawer = page.getByRole("button", { name: /Conversas/ }).first();
  if (await conversationDrawer.isVisible()) {
    await conversationDrawer.click();
    const sidebar = page.getByRole("complementary", { name: "Conversas" });
    await expect(sidebar.getByRole("button", { name: "Fechar conversas", exact: true })).toBeFocused();
    await expect(sidebar.getByRole("button", { name: "Protocolo de biossegurança", exact: true })).toBeVisible();
    await page.keyboard.press("Shift+Tab");
    await expect(sidebar.getByRole("button", { name: "Protocolo de biossegurança", exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(sidebar.getByRole("button", { name: "Fechar conversas", exact: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(conversationDrawer).toBeFocused();
  } else {
    await expect(page.getByRole("button", { name: "Protocolo de biossegurança", exact: true })).toBeVisible();
  }
  await expect(page.getByText("O protocolo começa pela avaliação do risco e pela revisão das fontes autorizadas.", { exact: true })).toBeVisible();

  await page.getByLabel("Pergunta", { exact: true }).fill("O que muda no controle de exposição?");
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
  await expect(page.getByText("A resposta mantém o contexto da conversa.", { exact: true })).toBeVisible();
  expect(requestBody).toMatchObject({
    message: "O que muda no controle de exposição?",
    conversation_id: "conv-protocol",
    workspace_id: "workspace-chat",
    stream: true,
  });

  const citation = page.locator("details").filter({ hasText: "Controle de exposição no atendimento" });
  await expect(citation).toBeVisible();
  await citation.locator("summary").click();
  await expect(citation).toContainText("chunk-control-02");
  await expect(citation).toContainText("sha256-control");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("keeps the question recoverable across forbidden and retry states", async ({ page }) => {
  await mockSession(page);
  await mockConversations(page, { items: [] });
  let attempts = 0;
  await page.route("**/api/v1/chat", async (route) => {
    attempts += 1;
    if (attempts === 1) return json(route, { error: { code: "forbidden", message: "Consulta recusada pelo escopo." } }, 403);
    return json(route, {
      conversation_id: "conv-recovered",
      message_id: "msg-recovered",
      answer: "A consulta foi retomada com o mesmo escopo.",
      citations: [],
      metadata: { evidence_status: "NO_EVIDENCE" },
    });
  });

  await page.goto("/app/chat");
  await page.getByLabel("Pergunta", { exact: true }).fill("Quais fontes posso revisar?");
  await page.getByLabel("Pergunta", { exact: true }).press("Enter");
  await expect(page.locator('[role="alert"]').filter({ hasText: "Acesso negado à consulta" })).toBeVisible();
  await expect(page.getByLabel("Pergunta", { exact: true })).toHaveValue("Quais fontes posso revisar?");
  await expect(page.getByRole("button", { name: "Tentar novamente", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Tentar novamente", exact: true }).click();
  await expect(page.getByText("A consulta foi retomada com o mesmo escopo.", { exact: true })).toBeVisible();
  expect(attempts).toBe(2);
});

test("offers a history permission state and a cancellable request at the target layouts", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockSession(page);
  await mockConversations(page, { listStatus: 403, items: [] });
  let pendingRoute: Route | null = null;
  const releasePending = { current: null as (() => void) | null };
  await page.route("**/api/v1/chat", async (route) => {
    pendingRoute = route;
    await new Promise<void>((resolve) => { releasePending.current = resolve; });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ conversation_id: "conv-cancelled", message_id: "msg-late", answer: "Resposta tardia", citations: [], metadata: {} }),
    }).catch(() => undefined);
  });

  await page.goto("/app/chat");
  const conversationDrawer = page.getByRole("button", { name: /Conversas/ }).first();
  if ((page.viewportSize()?.width || 1440) < 760) {
    await conversationDrawer.click();
  }
  await expect(page.getByText("Histórico indisponível", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Nova conversa", exact: true })).toBeVisible();
  if ((page.viewportSize()?.width || 1440) < 760) {
    await page.getByRole("complementary", { name: "Conversas" }).getByRole("button", { name: "Fechar conversas", exact: true }).click();
  }
  await page.getByLabel("Pergunta", { exact: true }).fill("Preciso cancelar esta consulta.");
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
  await expect.poll(() => pendingRoute !== null).toBe(true);
  await expect(page.getByText("Resposta provisória · consultando fontes…", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancelar", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Cancelar", exact: true }).click();
  await expect(page.locator('[role="status"]').filter({ hasText: "Consulta cancelada" })).toBeVisible();
  await expect(page.getByLabel("Pergunta", { exact: true })).toHaveValue("Preciso cancelar esta consulta.");
  releasePending.current?.();
});

test("keeps the draft editable while offline and recovers when the connection returns", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "onLine", { configurable: true, get: () => false });
  });
  await mockSession(page);
  await mockConversations(page, { items: [] });
  let chatRequests = 0;
  await page.route("**/api/v1/chat", async (route) => {
    chatRequests += 1;
    await json(route, {
      conversation_id: "conv-online-again",
      message_id: "msg-online-again",
      answer: "A conexão voltou e a consulta foi concluída.",
      citations: [],
      metadata: { evidence_status: "NO_EVIDENCE" },
    });
  });

  await page.goto("/app/chat");
  await expect(page.locator('[data-network-state="offline"]')).toBeVisible();
  const composer = page.getByLabel("Pergunta", { exact: true });
  const submit = page.getByRole("button", { name: "Consultar", exact: true });
  await composer.fill("Quais fontes posso revisar offline?");
  await expect(page.getByText("Consulta pausada sem conexão.", { exact: false })).toBeVisible();
  await expect(submit).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath("offline-state.png"), fullPage: true, animations: "disabled" });
  await composer.press("Enter");
  await expect(composer).toHaveValue("Quais fontes posso revisar offline?");
  expect(chatRequests).toBe(0);

  await page.evaluate(() => {
    Object.defineProperty(navigator, "onLine", { configurable: true, get: () => true });
    window.dispatchEvent(new Event("online"));
  });
  await expect(page.locator('[data-network-state="offline"]')).toHaveCount(0);
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(page.getByText("A conexão voltou e a consulta foi concluída.", { exact: true })).toBeVisible();
  expect(chatRequests).toBe(1);
});

test("preserves a partial stream as explicitly non-final and retries the same question", async ({ page }, testInfo) => {
  await mockSession(page);
  await mockConversations(page, { items: [] });
  let attempts = 0;
  await page.route("**/api/v1/chat", async (route) => {
    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          `data: ${JSON.stringify({ type: "start", conversation_id: "conv-partial", message_id: "msg-partial" })}`,
          "",
          `data: ${JSON.stringify({ type: "delta", conversation_id: "conv-partial", message_id: "msg-partial", delta: "Trecho parcial recebido." })}`,
          "",
        ].join("\n"),
      });
      return;
    }
    await json(route, {
      conversation_id: "conv-partial",
      message_id: "msg-recovered",
      answer: "Resposta recuperada depois da interrupção.",
      citations: [],
      metadata: { evidence_status: "NO_EVIDENCE" },
    });
  });

  await page.goto("/app/chat");
  const composer = page.getByLabel("Pergunta", { exact: true });
  await composer.fill("Quais fontes sustentam esta hipótese?");
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Resposta interrompida", exact: true })).toBeFocused();
  await expect(page.getByText("Trecho parcial recebido.", { exact: true })).toBeVisible();
  await expect(page.getByText("Resposta interrompida · não finalizada", { exact: true })).toBeVisible();
  await expect(page.getByText("não foi marcado como resposta concluída", { exact: false })).toBeVisible();
  await expect(composer).toHaveValue("Quais fontes sustentam esta hipótese?");
  await page.screenshot({ path: testInfo.outputPath("interrupted-stream.png"), fullPage: true, animations: "disabled" });

  await page.getByRole("button", { name: "Tentar novamente", exact: true }).click();
  await expect(page.getByText("Resposta recuperada depois da interrupção.", { exact: true })).toBeVisible();
  await expect(page.getByText("Trecho parcial recebido.", { exact: true })).toHaveCount(0);
  expect(attempts).toBe(2);
});
