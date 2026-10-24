// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "../../lib/api";
import { CaseWorkspace } from "../../components/cases/case-workspace";
import type { CaseListResponse, CaseRecord, Session } from "../../types/api";

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

it("clears case-bound notes, decision and feedback kind when switching A to B", async () => {
  const other = { ...record, case_id: "other", title: "OTHER CASE" };
  vi.mocked(api.listCases).mockResolvedValue({ items: [record, other], total: 2 });
  vi.mocked(api.getCase).mockImplementation(async id => ({ case: id === "other" ? other : record, reviews: [], feedback: [] }));
  await render();
  await act(async () => {
    field("Nota da revisão", "A review"); field("Nota", "A feedback");
    const selects = container.querySelectorAll("select");
    selects[0].value = "declined"; selects[0].dispatchEvent(new Event("change", { bubbles: true }));
    selects[1].value = "correction"; selects[1].dispatchEvent(new Event("change", { bubbles: true }));
  });
  await act(async () => Array.from(container.querySelectorAll("button")).find(b => b.textContent?.includes("OTHER CASE"))!.click());
  expect(Array.from(container.querySelectorAll(".case-event-form textarea")).map(n => (n as HTMLTextAreaElement).value)).toEqual(["", ""]);
  expect(Array.from(container.querySelectorAll("select")).map(n => n.value)).toEqual(["recorded", "clarification"]);
});

for (const kind of ["review", "feedback"] as const) for (const rejected of [false, true]) {
  it(`ignores late ${kind} ${rejected ? "failure" : "success"} after a queued case switch`, async () => {
    const other = { ...record, case_id: "other", title: "OTHER CASE" };
    vi.mocked(api.listCases).mockResolvedValue({ items: [record, other], total: 2 });
    vi.mocked(api.getCase).mockImplementation(async id => ({ case: id === "other" ? other : record, reviews: [], feedback: [] }));
    const pending = deferred<never>();
    const method = kind === "review" ? "reviewCase" : "feedbackCase";
    vi.spyOn(api, method).mockReturnValue(pending.promise);
    await render();
    await act(async () => field(kind === "review" ? "Nota da revisão" : "Nota", "A note"));
    // Both events are queued before React commits the mutation's busy state.
    await act(async () => {
      const form = container.querySelectorAll(".case-event-form")[kind === "review" ? 0 : 1];
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      Array.from(container.querySelectorAll("button")).find(b => b.textContent?.includes("OTHER CASE"))!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => field(kind === "review" ? "Nota da revisão" : "Nota", "B note"));
    const requests = vi.mocked(api.listCases).mock.calls.length;
    await act(async () => { if (rejected) pending.reject(new ApiError("A failure", 503, "failed")); else pending.resolve(record as never); });
    expect(api.listCases).toHaveBeenCalledTimes(requests);
    expect(container.textContent).not.toContain("A failure");
    expect(Array.from(container.querySelectorAll(".case-event-form textarea")).some(n => (n as HTMLTextAreaElement).value === "B note")).toBe(true);
  });
}

for (const kind of ["review", "feedback"] as const) {
  for (const edit of ["new note", "edit back", "selection only"] as const) {
    it(`preserves a newer same-case ${kind} draft on commit after ${edit}`, async () => {
      const pending = deferred<never>();
      const method = kind === "review" ? "reviewCase" : "feedbackCase";
      const label = kind === "review" ? "Nota da revisão" : "Nota";
      const index = kind === "review" ? 0 : 1;
      vi.spyOn(api, method).mockReturnValue(pending.promise);
      await render(); await act(async () => field(label, "R1 note"));
      await submit(kind === "review" ? "Registrar revisão" : "Registrar feedback");
      if (edit !== "selection only") {
        await act(async () => field(label, "R2 note"));
        if (edit === "edit back") await act(async () => field(label, "R1 note"));
      }
      if (edit !== "edit back") await act(async () => {
        const select = container.querySelectorAll(".case-event-form select")[index] as HTMLSelectElement;
        select.value = kind === "review" ? "declined" : "correction";
        select.dispatchEvent(new Event("change", { bubbles: true }));
      });
      await act(async () => pending.resolve(record as never));
      const note = container.querySelectorAll(".case-event-form textarea")[index] as HTMLTextAreaElement;
      expect(note.value).toBe(edit === "new note" ? "R2 note" : "R1 note");
      if (edit !== "edit back") expect((container.querySelectorAll(".case-event-form select")[index] as HTMLSelectElement).value).toBe(kind === "review" ? "declined" : "correction");
      expect(api[method]).toHaveBeenCalledOnce();
      expect(api[method]).toHaveBeenCalledWith("private", kind === "review" ? { decision: "recorded", review_note: "R1 note" } : { kind: "clarification", feedback_note: "R1 note" });
    });
  }
  it(`excludes duplicate queued same-case ${kind} submissions before the busy render`, async () => {
    const pending = deferred<never>();
    const method = kind === "review" ? "reviewCase" : "feedbackCase";
    vi.spyOn(api, method).mockReturnValue(pending.promise);
    await render(); await act(async () => field(kind === "review" ? "Nota da revisão" : "Nota", "R1 note"));
    await act(async () => {
      const form = container.querySelectorAll(".case-event-form")[kind === "review" ? 0 : 1];
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect(api[method]).toHaveBeenCalledOnce();
    await act(async () => pending.resolve(record as never));
  });
}

for (const label of ["Título", "Resumo humano", "Hipóteses registradas", "Referências de evidência"]) {
  it(`preserves a newer create draft revision when ${label} changes during POST`, async () => {
    const pending = deferred<CaseRecord>();
    vi.spyOn(api, "createCase").mockReturnValue(pending.promise);
    await render();
    await act(async () => { field("Título", "Submitted title"); field("Resumo humano", "Submitted summary"); });
    await submit("Registrar caso");
    await act(async () => field(label, "NEW UNSENT DRAFT"));
    await act(async () => pending.resolve(record));
    expect(caseInput(label).value).toBe("NEW UNSENT DRAFT");
    expect(api.createCase).toHaveBeenCalledOnce();
    expect(vi.mocked(api.createCase).mock.calls[0][0].title).toBe("Submitted title");
  });
}
it("does not erase an edit-and-back create draft and excludes duplicate queued submits", async () => {
  const pending = deferred<CaseRecord>();
  vi.spyOn(api, "createCase").mockReturnValue(pending.promise);
  await render();
  await act(async () => { field("Título", "Submitted"); field("Resumo humano", "Summary"); });
  await act(async () => {
    const form = container.querySelector(".case-form")!;
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  await act(async () => field("Título", "Second"));
  await act(async () => field("Título", "Submitted"));
  await act(async () => pending.resolve(record));
  expect(api.createCase).toHaveBeenCalledOnce();
  expect(caseInput("Título").value).toBe("Submitted");
});
it("keeps create draft recoverable after a failed POST and explicit list retry", async () => {
  vi.spyOn(api, "createCase").mockRejectedValue(new ApiError("Create down", 503, "unavailable"));
  await render();
  await act(async () => { field("Título", "Unsaved"); field("Resumo humano", "Unsaved summary"); });
  await submit("Registrar caso");
  await act(async () => Array.from(container.querySelectorAll("button")).find(b => b.textContent?.includes("Tentar novamente"))!.click());
  expect(caseInput("Título").value).toBe("Unsaved");
});
for (const kind of ["create", "review", "feedback"] as const) it(`keeps ${kind} draft visible with an indeterminate-result warning after authority cancellation`,async()=>{
 const pending=deferred<never>();const method=kind==="create"?"createCase":kind==="review"?"reviewCase":"feedbackCase";
 vi.spyOn(api,method).mockReturnValue(pending.promise);await render();
 const label=kind==="create"?"Título":kind==="review"?"Nota da revisão":"Nota";
 await act(async()=>{field(label,"Submitted A");if(kind==="create")field("Resumo humano","Human summary");});
 await submit(kind==="create"?"Registrar caso":kind==="review"?"Registrar revisão":"Registrar feedback");
 await act(async()=>field(label,"Unsaved B"));await act(async()=>pending.reject(new DOMException("Authority invalidated","AbortError")));
 expect(container.querySelector(".case-form")).not.toBeNull();expect(caseInput(label).value).toBe("Unsaved B");
 expect(container.querySelector('[role="alert"]')?.textContent).toContain("confirme o resultado antes de repetir");
 expect(container.textContent).not.toContain("Não foi possível confirmar os registros");
 expect(api[method]).toHaveBeenCalledOnce();expect(api.listCases).toHaveBeenCalledOnce();
});
function caseInput(label: string) {
  return Array.from(container.querySelectorAll("label")).find(item => item.childNodes[0]?.textContent === label)!.querySelector("input,textarea") as HTMLInputElement | HTMLTextAreaElement;
}
const casePage = () => Array.from({ length: 50 }, (_, index) => ({ ...record, case_id: `case-${index}`, title: `Case ${index}` }));
function moreCases() { return Array.from(container.querySelectorAll("button")).find(b => b.textContent?.includes("Carregar mais casos")); }
it("exposes case 51, deduplicates overlapping pages and uses authoritative totals", async () => {
  const first = casePage();
  const last = { ...record, case_id: "case-50", title: "FIFTY FIRST CASE" };
  vi.mocked(api.listCases).mockResolvedValueOnce({ items: first, total: 51, next_offset: 50 }).mockResolvedValueOnce({ items: [first[49], last], total: 51, next_offset: null });
  await render();
  expect(container.textContent).toContain("50 de 51");
  expect(moreCases()).toBeDefined();
  await act(async () => moreCases()!.click());
  expect(api.listCases).toHaveBeenLastCalledWith("workspace", 50, 50);
  expect(container.querySelectorAll(".case-list-item")).toHaveLength(51);
  expect(container.textContent).toContain("FIFTY FIRST CASE");
  expect(container.textContent).toContain("51 de 51");
  expect(moreCases()).toBeUndefined();
});
it("retains the earlier page and supports retry after a next-page error", async () => {
  vi.mocked(api.listCases).mockResolvedValueOnce({ items: [record], total: 2, next_offset: 1 }).mockRejectedValueOnce(new ApiError("Page down", 503, "unavailable")).mockResolvedValueOnce({ items: [{ ...record, case_id: "last", title: "LAST CASE" }], total: 2, next_offset: null });
  await render();
  await act(async () => moreCases()!.click());
  expect(container.textContent).toContain("PRIVATE CASE");
  expect(container.textContent).toContain("Page down");
  expect(moreCases()).toBeDefined();
  await act(async () => moreCases()!.click());
  expect(container.textContent).toContain("LAST CASE");
});
it("invalidates a pending page when identity changes and excludes duplicate queued page loads", async () => {
  const pending = deferred<CaseListResponse>();
  vi.mocked(api.listCases).mockResolvedValueOnce({ items: [record], total: 2, next_offset: 1 }).mockReturnValueOnce(pending.promise).mockResolvedValue({ items: [], total: 0 });
  await render();
  await act(async () => { moreCases()!.click(); moreCases()!.click(); });
  expect(api.listCases).toHaveBeenCalledTimes(2);
  session = { ...identity, user_id: "new-user" };
  await render();
  await act(async () => pending.resolve({ items: [{ ...record, case_id: "secret", title: "OLD PRIVATE PAGE" }], total: 2, next_offset: null }));
  expect(container.textContent).not.toContain("PRIVATE");
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

it("treats a 403 list as restricted rather than a service outage (AUD24-11)", async() => {
  vi.mocked(api.listCases).mockRejectedValueOnce(new ApiError("Forbidden.", 403, "forbidden"));
  await render();
  expect(container.textContent).toContain("Sem acesso aos casos");
  expect(container.textContent).not.toContain("Não foi possível confirmar os registros");
});
