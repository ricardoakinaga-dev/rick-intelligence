// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "../../lib/api";
import { CaseWorkspace } from "../../components/cases/case-workspace";
import type { CaseRecord, Session } from "../../types/api";

let session: Session | null;
vi.mock("../../components/session-provider", () => ({ useSession: () => ({ session }) }));
const identity = { authenticated: true, user_id: "u", session_id: "s", tenant_id: "t", workspace_id: "w", role: "VETERINARIAN", permissions: ["cases.read", "cases.manage", "cases.review", "cases.feedback"] } as Session;
const record = { case_id: "private", title: "PRIVATE CASE", summary: "PRIVATE SUMMARY", status: "open", owner_user_id: "u", updated_at: 1, clinical_scope_status: "human_only", hypotheses: [], evidence: [] } as unknown as CaseRecord;
const detail = { case: record, reviews: [], feedback: [] };
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (cause: unknown) => void; const promise = new Promise<T>((a,b) => {resolve=a;reject=b;}); return { promise, resolve, reject }; }
let root: Root;
let container: HTMLDivElement;
async function render() { await act(async () => root.render(<CaseWorkspace />)); }
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  session = { ...identity }; container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  vi.spyOn(api, "listCases").mockResolvedValue({ items: [record], total: 1 });
  vi.spyOn(api, "getCase").mockResolvedValue(detail);
  vi.spyOn(api, "agentModelCatalog").mockResolvedValue({ catalog_status: "not_configured", items: [] });
});
afterEach(async () => { await act(async () => root.unmount()); document.body.replaceChildren(); vi.restoreAllMocks(); });
const changes = [
  ["permission", () => { session = { ...identity, permissions: [] }; }],
  ["tenant", () => { session = { ...identity, tenant_id: "other" }; }],
  ["workspace", () => { session = { ...identity, workspace_id: "other" }; }],
  ["logout", () => { session = null; }],
  ["management permission", () => { session = { ...identity, permissions: ["cases.read"] }; }],
] as const;
for (const [name, change] of changes) {
  it(`discards pending list and clears private inputs on ${name}`, async () => {
    const pending = deferred<{ items: CaseRecord[]; total: number }>();
    vi.mocked(api.listCases).mockReturnValueOnce(pending.promise).mockResolvedValue({ items: [], total: 0 });
    await render(); change(); await render();
    await act(async () => pending.resolve({ items: [record], total: 1 }));
    expect(container.textContent).not.toContain("PRIVATE");
    expect(api.getCase).not.toHaveBeenCalled();
    if (!session || !session.permissions?.includes("cases.read")) expect(container.textContent).toContain("Sem acesso aos casos");
  });
  it(`discards pending detail on ${name}`, async () => {
    const pending = deferred<typeof detail>(); vi.mocked(api.getCase).mockReturnValueOnce(pending.promise);
    await render(); expect(api.getCase).toHaveBeenCalledOnce();
    vi.mocked(api.listCases).mockResolvedValue({ items: [], total: 0 });
    change(); await render();
    await act(async () => pending.resolve(detail));
    expect(container.textContent).not.toContain("PRIVATE");
  });
}
it("keeps revocation after a late list error", async () => {
  const pending = deferred<{ items: CaseRecord[]; total: number }>(); vi.mocked(api.listCases).mockReturnValue(pending.promise);
  await render(); session = { ...identity, permissions: [] }; await render();
  await act(async () => pending.reject(new ApiError("private error", 503, "failed")));
  expect(container.textContent).toContain("Sem acesso aos casos"); expect(container.textContent).not.toContain("private error");
});
it("shows loading, service error, and a successful retry instead of a false empty state", async () => {
  const pending = deferred<{ items: CaseRecord[]; total: number }>(); vi.mocked(api.listCases).mockReturnValueOnce(pending.promise);
  await render(); expect(container.textContent).toContain("Consultando registros");
  await act(async () => pending.reject(new ApiError("indisponível", 503, "failed")));
  expect(container.textContent).toContain("Não foi possível confirmar os registros");
  await act(async () => Array.from(container.querySelectorAll("button")).find(b => b.textContent?.includes("Tentar novamente"))?.click());
  expect(container.textContent).toContain("PRIVATE SUMMARY");
});
it("honors the disabled D04 gate", async () => {
  vi.mocked(api.listCases).mockRejectedValue(new ApiError("disabled", 409, "conflict")); await render();
  expect(container.textContent).toContain("O módulo está fechado por padrão"); expect(api.getCase).not.toHaveBeenCalled();
});

function field(label: string, value: string) {
  const input = Array.from(container.querySelectorAll("label")).find(item => item.childNodes[0]?.textContent === label)?.querySelector("input,textarea") as HTMLInputElement | HTMLTextAreaElement;
  const proto = input instanceof HTMLInputElement ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}
async function submit(buttonText: string) {
  await act(async () => {
    const button = Array.from(container.querySelectorAll("button")).find(b => b.textContent?.includes(buttonText))!;
    button.closest("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}
for (const kind of ["create", "review", "feedback"] as const) {
  for (const rejected of [false, true]) {
    it(`discards late ${kind} ${rejected ? "failure" : "success"} after revocation without reloading or resurrecting drafts`, async () => {
      const pending = deferred<never>();
      const method = kind === "create" ? "createCase" : kind === "review" ? "reviewCase" : "feedbackCase";
      vi.spyOn(api, method).mockReturnValueOnce(pending.promise);
      await render();
      await act(async () => {
        if (kind === "create") { field("Título", "PRIVATE DRAFT"); field("Resumo humano", "PRIVATE DRAFT SUMMARY"); }
        else field(kind === "review" ? "Nota da revisão" : "Nota", "PRIVATE NOTE");
      });
      await submit(kind === "create" ? "Registrar caso" : kind === "review" ? "Registrar revisão" : "Registrar feedback");
      expect(api[method]).toHaveBeenCalledOnce(); const requests = vi.mocked(api.listCases).mock.calls.length;
      session = { ...identity, permissions: [] }; await render();
      await act(async () => {
        if (rejected) pending.reject(new ApiError("PRIVATE FAILURE", 503, "failed"));
        else pending.resolve(record as never);
      });
      expect(api.listCases).toHaveBeenCalledTimes(requests);
      expect(container.textContent).toContain("Sem acesso aos casos"); expect(container.textContent).not.toContain("PRIVATE");
      vi.mocked(api.listCases).mockResolvedValue({ items: [], total: 0 });
      session = { ...identity }; await render();
      expect(container.textContent).not.toContain("PRIVATE");
      expect(Array.from(container.querySelectorAll("input,textarea")).every(input => !(input as HTMLInputElement).value)).toBe(true);
    });
  }
  it(`keeps successful ${kind} behavior`, async () => {
    const method = kind === "create" ? "createCase" : kind === "review" ? "reviewCase" : "feedbackCase";
    vi.spyOn(api, method).mockResolvedValue(record as never); await render();
    await act(async () => {
      if (kind === "create") { field("Título", "New title"); field("Resumo humano", "New summary"); field("Hipóteses registradas", "One\n Two "); field("Referências de evidência", "doc-1"); }
      else field(kind === "review" ? "Nota da revisão" : "Nota", "Human note");
    });
    await submit(kind === "create" ? "Registrar caso" : kind === "review" ? "Registrar revisão" : "Registrar feedback");
    expect(api[method]).toHaveBeenCalledOnce(); expect(container.textContent).toContain("PRIVATE SUMMARY");
  });
  it(`shows current ${kind} failure`, async () => {
    const method = kind === "create" ? "createCase" : kind === "review" ? "reviewCase" : "feedbackCase";
    vi.spyOn(api, method).mockRejectedValue(new ApiError("Current failure", 503, "failed")); await render();
    await act(async () => {
      if (kind === "create") { field("Título", "New title"); field("Resumo humano", "New summary"); }
      else field(kind === "review" ? "Nota da revisão" : "Nota", "Human note");
    });
    await submit(kind === "create" ? "Registrar caso" : kind === "review" ? "Registrar revisão" : "Registrar feedback");
    expect(container.textContent).toContain("Current failure");
  });
}
it("discards late catalog after authority changes", async () => {
  const pending = deferred<Awaited<ReturnType<typeof api.agentModelCatalog>>>();
  vi.mocked(api.agentModelCatalog).mockReturnValueOnce(pending.promise); await render();
  session = { ...identity, permissions: [] }; await render();
  await act(async () => pending.resolve({ catalog_status: "configured", items: [{ agent_id: "private", model_id: "PRIVATE MODEL", catalog_version: "v1", status: "authorized", purpose: "human_review_assist" }] }));
  expect(container.textContent).not.toContain("PRIVATE");
});
it("separates catalog failure from case availability and detail failure from empty case data", async () => {
  vi.mocked(api.agentModelCatalog).mockRejectedValue(new Error("down")); await render();
  expect(container.textContent).toContain("catálogo de agentes não está disponível");
  vi.mocked(api.getCase).mockRejectedValue(new Error("down"));
  await act(async () => Array.from(container.querySelectorAll("button")).find(b => b.classList.contains("case-list-item"))!.click());
  expect(container.textContent).toContain("Não foi possível carregar os detalhes");
});
it("renders populated reviewed case references, human review history, and authorized catalog", async () => {
  const expanded = { ...record, status: "reviewed", hypotheses: [{ hypothesis_id: "h", statement: "Human hypothesis", status: "open" }], evidence: [{ evidence_id: "e", source_type: "manual", source_id: "doc", locator: "page 1" }] } as CaseRecord;
  vi.mocked(api.listCases).mockResolvedValue({ items: [expanded], total: 1 });
  vi.mocked(api.getCase).mockResolvedValue({ case: expanded, reviews: [{ review_id: "r", decision: "recorded", review_note: "Review history", reviewer_user_id: "u", created_at: 1 }], feedback: [{ feedback_id: "f", kind: "clarification", feedback_note: "Feedback history", feedback_user_id: "u", created_at: 1 }] } as unknown as typeof detail);
  vi.mocked(api.agentModelCatalog).mockResolvedValue({ catalog_status: "configured", items: [{ agent_id: "agent", model_id: "model", catalog_version: "v1", status: "authorized", purpose: "human_review_assist" }] });
  await render(); expect(container.textContent).toContain("Review history"); expect(container.textContent).toContain("Feedback history"); expect(container.textContent).toContain("Human hypothesis"); expect(container.textContent).toContain("page 1"); expect(container.textContent).toContain("model");
});
