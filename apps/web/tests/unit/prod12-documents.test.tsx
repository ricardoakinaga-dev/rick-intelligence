// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import DocumentsPage from "../../app/app/documents/page";
import { api } from "../../lib/api";
import type { Session, JobEnvelope } from "../../types/api";
let session: Session;
vi.mock("../../components/session-provider",()=>({useSession:()=>({session})}));
const envelope=(status:string):JobEnvelope=>({status:"ok",job_id:"j",job:{job_id:"j",status,stage:status,progress:status==="published"?1:0,attempt:1,retryable:status==="failed"}});
let root:Root,container:HTMLDivElement;
async function render(){await act(async()=>root.render(<DocumentsPage/>));}
async function upload(){await act(async()=>{const input=container.querySelector('input[type="file"]')!; Object.defineProperty(input,"files",{configurable:true,value:[new File(["source"],"source.txt")]});input.dispatchEvent(new Event("change",{bubbles:true}));});}
async function retry(){await act(async()=>Array.from(container.querySelectorAll("button")).find(b=>b.textContent?.includes("Tentar novamente"))!.click());}
beforeEach(()=>{
 Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});session={authenticated:true,user_id:"u",session_id:"s",tenant_id:"t",workspace_id:"w",permissions:["documents.upload","ingestion.run"]} as Session;
 container=document.createElement("div");document.body.append(container);root=createRoot(container);
 vi.spyOn(api,"documents").mockResolvedValue({items:[],total:0});
 vi.spyOn(api,"collections").mockResolvedValue({items:[{collection_id:"col",title:"Collection",status:"active"}],total:1} as Awaited<ReturnType<typeof api.collections>>);
 vi.spyOn(api,"upload").mockResolvedValue(envelope("failed")); vi.spyOn(api,"retryJob").mockResolvedValue(envelope("published"));
});
afterEach(async()=>{await act(async()=>root.unmount());document.body.replaceChildren();vi.restoreAllMocks();vi.useRealTimers();});
it("refreshes real catalog after a published retry",async()=>{
 await render();await upload();expect(api.documents).toHaveBeenCalledTimes(1);
 vi.mocked(api.documents).mockResolvedValue({items:[{document_id:"d",title:"Published retry document",collection_id:"col",status:"published"}],total:1} as Awaited<ReturnType<typeof api.documents>>);
 await retry();expect(api.documents).toHaveBeenCalledTimes(2);expect(container.textContent).toContain("Published retry document");
});
it("uses the same publication refresh for upload",async()=>{
 vi.mocked(api.upload).mockResolvedValue(envelope("published"));await render();await upload();expect(api.documents).toHaveBeenCalledTimes(2);
});
it("uses the same publication refresh for reindex",async()=>{
 session={...session,permissions:[...session.permissions!,"reindex.run"]};
 vi.mocked(api.documents).mockResolvedValue({items:[{document_id:"d",title:"Document",collection_id:"col",status:"published"}],total:1} as Awaited<ReturnType<typeof api.documents>>);
 vi.spyOn(api,"reindexDocument").mockResolvedValue(envelope("published"));await render();
 await act(async()=>Array.from(container.querySelectorAll("button")).find(b=>b.textContent?.includes("Reindexar"))!.click());
 expect(api.reindexDocument).toHaveBeenCalledWith("d",{collection_id:"col"});expect(api.documents).toHaveBeenCalledTimes(2);
});
const documentRecord = {document_id:"d",title:"Published document",collection_id:"col",workspace_id:"w",status:"published"};
async function clickButton(label:string, source:ParentNode=container) {
 const button=Array.from(source.querySelectorAll("button")).find(b=>b.textContent?.trim()===label);
 expect(button,`button ${label}`).toBeDefined(); await act(async()=>button!.click());
}
for(const deleted of [true,false]) it(`uses the server deletion boolean ${deleted} without assuming success`,async()=>{
 session={...session,permissions:[...session.permissions!,"documents.manage"]};
 vi.mocked(api.documents).mockResolvedValue({items:[documentRecord],total:1});
 vi.spyOn(api,"deleteDocument").mockResolvedValue({document_id:"d",deleted});
 await render(); await clickButton("Excluir"); await clickButton("Excluir documento",document);
 expect(api.deleteDocument).toHaveBeenCalledWith("d");
 expect(container.textContent).toContain(deleted?"removido e confirmado pelo servidor":"sem confirmar a remoção");
 expect(container.querySelectorAll(".document-row")).toHaveLength(deleted?0:1);
});
it("preserves catalog after delete failure and rejects a late deletion in another scope",async()=>{
 session={...session,permissions:[...session.permissions!,"documents.manage"]};
 vi.mocked(api.documents).mockResolvedValue({items:[documentRecord],total:1});
 vi.spyOn(api,"deleteDocument").mockRejectedValueOnce(new Error("unavailable"));
 await render();await clickButton("Excluir");await clickButton("Excluir documento",document);
 expect(container.querySelectorAll(".document-row")).toHaveLength(1);expect(container.querySelector('[role="alert"]')?.textContent).toContain("unavailable");
 const pending=deferred<Awaited<ReturnType<typeof api.deleteDocument>>>();vi.mocked(api.deleteDocument).mockReturnValue(pending.promise);
 await clickButton("Excluir");await clickButton("Excluir documento",document);
 session={...session,user_id:"new-user"};vi.mocked(api.documents).mockResolvedValue({items:[],total:0});await render();
 await act(async()=>pending.resolve({document_id:"d",deleted:true}));
 expect(container.textContent).not.toContain("confirmou a remoção");
});
for(const status of ["cancelled","queued"]) it(`confirms cancellation only when server says ${status}`,async()=>{
 vi.useFakeTimers();vi.mocked(api.upload).mockResolvedValue(envelope("queued"));vi.spyOn(api,"job").mockResolvedValue(envelope("queued"));
 vi.spyOn(api,"cancelJob").mockResolvedValue({...envelope(status),cancelled:status==="cancelled"});
 await render();await upload();await clickButton("Pausar acompanhamento");await clickButton("Cancelar");
 expect(api.cancelJob).toHaveBeenCalledWith("j");expect(container.textContent).toContain(status==="cancelled"?"Cancelamento confirmado":"cancelamento ainda não foi confirmado");
 expect(api.documents).toHaveBeenCalledTimes(1);
});
it("exposes cancel failure without pretending cancellation",async()=>{
 vi.useFakeTimers();vi.mocked(api.upload).mockResolvedValue(envelope("queued"));vi.spyOn(api,"job").mockResolvedValue(envelope("queued"));vi.spyOn(api,"cancelJob").mockRejectedValue(new Error("down"));
 await render();await upload();await clickButton("Pausar acompanhamento");await clickButton("Cancelar");
 expect(container.querySelector('[role="alert"]')?.textContent).toContain("down");expect(container.textContent).not.toContain("Cancelamento confirmado");
});
it("asks for a new file when a failed job was looked up after remount and rejects an empty source",async()=>{
 vi.spyOn(api,"job").mockResolvedValue(envelope("failed"));await render();
 const lookup=container.querySelector('input[aria-label="Identificador do processo"]') as HTMLInputElement;
 await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value")!.set!.call(lookup,"j");lookup.dispatchEvent(new Event("input",{bubbles:true}));});
 await act(async()=>lookup.closest("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})));
 const source=container.querySelector('input[aria-label="Selecionar fonte para uma nova tentativa"]') as HTMLInputElement;const clicked=vi.spyOn(source,"click");
 await clickButton("Escolher fonte para uma nova tentativa");expect(clicked).toHaveBeenCalledOnce();
 await act(async()=>{Object.defineProperty(source,"files",{configurable:true,value:[new File([],"empty.txt")]});source.dispatchEvent(new Event("change",{bubbles:true}));});
 expect(container.textContent).toContain("A fonte escolhida está vazia.");expect(api.retryJob).not.toHaveBeenCalled();
 await act(async()=>{Object.defineProperty(source,"files",{configurable:true,value:[new File(["source"],"source.txt")]});source.dispatchEvent(new Event("change",{bubbles:true}));});
 expect(api.retryJob).toHaveBeenCalledOnce();expect(api.documents).toHaveBeenCalledTimes(2);
});
it("paginates documents with explicit recovery after a next-page failure",async()=>{
 vi.mocked(api.documents).mockResolvedValueOnce({items:[documentRecord],total:2,next_cursor:"cursor"}).mockRejectedValueOnce(new Error("next down")).mockResolvedValueOnce({items:[{...documentRecord,document_id:"second",title:"Second document"}],total:2,next_cursor:null});
 await render();await clickButton("Carregar mais");expect(container.querySelector('[role="alert"]')?.textContent).toContain("next down");expect(container.textContent).toContain("Published document");
 await clickButton("Carregar mais");expect(api.documents).toHaveBeenLastCalledWith("w",undefined,"cursor");expect(container.textContent).toContain("Second document");
});
function resumeButton() { return Array.from(container.querySelectorAll("button")).find(b => b.textContent?.includes("Retomar acompanhamento")); }
it("resumes the same queued job after the budget without uploading or retrying again", async () => {
 vi.useFakeTimers(); vi.mocked(api.upload).mockResolvedValue(envelope("queued")); vi.spyOn(api,"job").mockResolvedValue(envelope("queued"));
 await render(); await upload(); await act(async()=>vi.advanceTimersByTimeAsync(9600));
 expect(resumeButton()).toBeDefined();
 vi.mocked(api.job).mockResolvedValue(envelope("published"));
 await act(async()=>resumeButton()!.click()); await act(async()=>vi.advanceTimersByTimeAsync(120));
 expect(api.upload).toHaveBeenCalledOnce(); expect(api.retryJob).not.toHaveBeenCalled();
 expect(container.textContent).toContain("publicado"); expect(api.documents).toHaveBeenCalledTimes(2);
});
it("recovers the same job from a transient lookup failure", async () => {
 vi.useFakeTimers(); vi.mocked(api.upload).mockResolvedValue(envelope("queued")); vi.spyOn(api,"job").mockRejectedValueOnce(new Error("temporarily unavailable")).mockResolvedValue(envelope("published"));
 await render(); await upload(); await act(async()=>vi.advanceTimersByTimeAsync(120));
 expect(resumeButton()).toBeDefined(); expect(container.textContent).not.toContain("Documento publicado pelo servidor");
 await act(async()=>resumeButton()!.click()); await act(async()=>vi.advanceTimersByTimeAsync(120));
 expect(api.upload).toHaveBeenCalledOnce(); expect(api.job).toHaveBeenLastCalledWith("j",expect.any(AbortSignal)); expect(api.documents).toHaveBeenCalledTimes(2);
});
it("pauses local observation without cancelling the server job or accepting a late result", async () => {
 vi.useFakeTimers(); vi.mocked(api.upload).mockResolvedValue(envelope("queued"));
 const pending=deferred<JobEnvelope>(); vi.spyOn(api,"job").mockReturnValue(pending.promise); vi.spyOn(api,"cancelJob");
 await render(); await upload(); await act(async()=>vi.advanceTimersByTimeAsync(120));
 const pause=Array.from(container.querySelectorAll("button")).find(b=>b.textContent?.includes("Pausar acompanhamento")); expect(pause).toBeDefined();
 await act(async()=>pause!.click()); await act(async()=>pending.resolve(envelope("published")));
 expect(api.cancelJob).not.toHaveBeenCalled(); expect(api.documents).toHaveBeenCalledTimes(1); expect(resumeButton()).toBeDefined();
});
it("allows explicit same-job lookup after remount without storing a source file or resubmitting", async () => {
 vi.spyOn(api,"job").mockResolvedValue(envelope("published")); await render();
 const input=container.querySelector('input[aria-label="Identificador do processo"]') as HTMLInputElement; expect(input).not.toBeNull();
 await act(async()=>{ Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value")!.set!.call(input,"j"); input.dispatchEvent(new Event("input",{bubbles:true})); });
 await act(async()=>input.closest("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})));
 expect(api.job).toHaveBeenCalledWith("j",expect.any(AbortSignal)); expect(api.upload).not.toHaveBeenCalled(); expect(api.retryJob).not.toHaveBeenCalled();
 expect(container.textContent).toContain("publicado");
});
function deferred<T>() { let resolve!: (v:T)=>void; const promise=new Promise<T>(a=>{resolve=a;}); return {promise,resolve}; }
for(const change of ["tenant","permission","unmount"] as const) it(`ignores a published retry arriving after ${change}`,async()=>{
 const pending=deferred<JobEnvelope>(); vi.mocked(api.retryJob).mockReturnValue(pending.promise); await render();await upload();await retry();
 if(change==="unmount") {await act(async()=>root.unmount()); root=createRoot(container);} else {session={...session,...(change==="tenant"?{tenant_id:"new",workspace_id:"new"}:{permissions:[]})};await render();}
 const calls=vi.mocked(api.documents).mock.calls.length;
 await act(async()=>pending.resolve(envelope("published")));
 expect(api.documents).toHaveBeenCalledTimes(calls);expect(container.textContent).not.toContain("confirmou a publicação");
});
it("invalidates a retry queued with a collection change without leaving the new catalog busy",async()=>{
 const pending=deferred<JobEnvelope>();vi.mocked(api.retryJob).mockReturnValue(pending.promise);await render();await upload();
 await act(async()=>{
  Array.from(container.querySelectorAll("button")).find(b=>b.textContent?.includes("Tentar novamente"))!.click();
  const filter=container.querySelector('#collection-filter')! as HTMLSelectElement;filter.value="col";filter.dispatchEvent(new Event("change",{bubbles:true}));
 });
 const calls=vi.mocked(api.documents).mock.calls.length;
 await act(async()=>pending.resolve(envelope("published")));
 expect(api.documents).toHaveBeenCalledTimes(calls);expect(container.textContent).not.toContain("confirmou a publicação");expect((container.querySelector('#collection-filter')! as HTMLSelectElement).disabled).toBe(false);
});
it("does not let an older catalog response overwrite the catalog refreshed by publication",async()=>{
 const pending=deferred<Awaited<ReturnType<typeof api.documents>>>();vi.mocked(api.documents).mockReturnValueOnce(pending.promise).mockResolvedValue({items:[],total:0});
 await render();await upload();await retry();expect(api.documents).toHaveBeenCalledTimes(2);
 await act(async()=>pending.resolve({items:[{document_id:"old",title:"STALE CATALOG"}],total:1} as Awaited<ReturnType<typeof api.documents>>));
 expect(container.textContent).not.toContain("STALE CATALOG");
});
it("does not assume a pending retry is publication after the bounded polling window",async()=>{
 vi.useFakeTimers();vi.mocked(api.retryJob).mockResolvedValue(envelope("queued"));vi.spyOn(api,"job").mockResolvedValue(envelope("queued"));
 await render();await upload();await retry();await act(async()=>vi.advanceTimersByTimeAsync(9600));
 // Backoff (120,240,480,960,then1000ms) stays inside the original 9600ms window.
 expect(api.job).toHaveBeenCalledTimes(11);expect(api.documents).toHaveBeenCalledTimes(1);expect(container.textContent).toContain("estado final não foi confirmado");vi.useRealTimers();
});
for(const status of ["failed","cancelled"])it(`does not refresh catalog for ${status} retry`,async()=>{
 vi.mocked(api.retryJob).mockResolvedValue(envelope(status));await render();await upload();await retry();expect(api.documents).toHaveBeenCalledTimes(1);
});

it("rejects a non-advancing document cursor instead of duplicating rows (AUD24-11)", async () => {
  vi.mocked(api.documents)
    .mockResolvedValueOnce({ items: [{ document_id: "d1", title: "First", collection_id: "col", workspace_id: "w", status: "published" }], total: 2, next_cursor: "c1" } as Awaited<ReturnType<typeof api.documents>>)
    .mockResolvedValueOnce({ items: [{ document_id: "d1", title: "First", collection_id: "col", workspace_id: "w", status: "published" }], total: 2, next_cursor: "c1" } as Awaited<ReturnType<typeof api.documents>>);
  await render();
  await clickButton("Carregar mais");
  expect(container.querySelectorAll(".document-row")).toHaveLength(1);
  expect(container.textContent).toContain("não avançou o cursor");
});

it("deduplicates a repeated document across pages (AUD24-11)", async () => {
  vi.mocked(api.documents)
    .mockResolvedValueOnce({ items: [{ document_id: "d1", title: "First", collection_id: "col", workspace_id: "w", status: "published" }], total: 2, next_cursor: "c1" } as Awaited<ReturnType<typeof api.documents>>)
    .mockResolvedValueOnce({ items: [{ document_id: "d1", title: "First", collection_id: "col", workspace_id: "w", status: "published" }, { document_id: "d2", title: "Second", collection_id: "col", workspace_id: "w", status: "published" }], total: 2, next_cursor: null } as Awaited<ReturnType<typeof api.documents>>);
  await render();
  await clickButton("Carregar mais");
  expect(container.querySelectorAll(".document-row")).toHaveLength(2);
});
