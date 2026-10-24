// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { ChatWorkspace } from "../../components/chat/chat-workspace";
import { chatAdapter } from "../../components/chat/chat-adapter";
import { api, ApiError } from "../../lib/api";
import type { Session, ConversationSummary, ChatHistoryEntry } from "../../types/api";
let session: Session | null;
let online = true;
vi.mock("../../components/session-provider", () => ({ useSession: () => ({ session }) }));
vi.mock("../../lib/network", () => ({ useOnlineStatus: () => online }));
const identity = { authenticated: true, user_id: "u", session_id: "s", tenant_id: "t", workspace_id: "w", permissions: ["chat.query", "history.read"] } as Session;
const conversation = (n: number): ConversationSummary => ({ conversation_id: `c${n}`, title: `Conversation ${n}`, workspace_id: "w", collection_id: null, status: "active", created_at: n, updated_at: n, message_count: 2 });
const turn = (n: number): ChatHistoryEntry => ({ conversation_id: "c1", message_id: `m${n}`, question: `question ${n}`, answer: `answer ${n}`, citations: [], created_at: n });
function deferred<T>() { let resolve!: (v:T)=>void; let reject!: (v:unknown)=>void; const promise = new Promise<T>((a,b)=>{resolve=a;reject=b;}); return { promise, resolve, reject }; }
let root: Root, container: HTMLDivElement;
async function render() { await act(async () => root.render(<ChatWorkspace />)); }
async function click(text: string) { await act(async () => Array.from(container.querySelectorAll("button")).find(b => b.textContent?.includes(text))!.click()); }
beforeEach(() => {
 Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); session = { ...identity }; online = true;
 window.history.replaceState({}, "", "/app/chat");
 Object.defineProperty(window, "matchMedia", { configurable: true, value: vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })) });
 Element.prototype.scrollTo = vi.fn(); Element.prototype.scrollIntoView = vi.fn();
 container = document.createElement("div"); document.body.append(container); root = createRoot(container);
 vi.spyOn(chatAdapter, "listConversations").mockResolvedValue({ items: [], total: 0 });
 vi.spyOn(chatAdapter, "getConversation").mockResolvedValue({ conversation: conversation(1), items: [turn(1)], total: 1 });
});
afterEach(async () => { await act(async () => root.unmount()); document.body.replaceChildren(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it("makes 51 conversations and 101 turns accessible with bounded explicit pages and deduplication", async () => {
 vi.mocked(chatAdapter.listConversations).mockResolvedValueOnce({ items: Array.from({length:50}, (_,i)=>conversation(i+1)), total:51, next_cursor:"list-next" }).mockResolvedValue({items:[conversation(50),conversation(51)],total:51,next_cursor:null});
 vi.mocked(chatAdapter.getConversation).mockResolvedValueOnce({conversation:conversation(1),items:Array.from({length:100},(_,i)=>turn(i+1)),total:101,next_cursor:"turn-next"}).mockResolvedValue({conversation:conversation(1),items:[turn(100),turn(101)],total:101,next_cursor:null});
 await render(); expect(chatAdapter.listConversations).toHaveBeenCalledTimes(1); expect(chatAdapter.getConversation).toHaveBeenCalledTimes(1);
 await click("Carregar mais conversas"); await click("Carregar mais mensagens");
 expect(chatAdapter.listConversations).toHaveBeenLastCalledWith(expect.any(AbortSignal), "list-next");
 expect(chatAdapter.getConversation).toHaveBeenLastCalledWith("c1", expect.any(AbortSignal), "turn-next");
 expect(container.querySelectorAll('nav button')).toHaveLength(51);
 const answers = Array.from(container.querySelectorAll('[aria-label="Resposta do corpus"]')).map(n=>n.textContent);
 expect(answers).toHaveLength(101); expect(answers[0]).toContain("answer 1"); expect(answers[100]).toContain("answer 101");
});
it("does not duplicate a persisted turn shared by an in-flight history page and send", async()=>{
 const page=deferred<Awaited<ReturnType<typeof chatAdapter.getConversation>>>();
 const send=deferred<Awaited<ReturnType<typeof chatAdapter.sendChat>>>();
 vi.mocked(chatAdapter.listConversations).mockResolvedValue({items:[conversation(1)],total:1});
 vi.mocked(chatAdapter.getConversation).mockResolvedValueOnce({conversation:conversation(1),items:[turn(1)],total:2,next_cursor:"more"}).mockReturnValueOnce(page.promise);
 vi.spyOn(chatAdapter,"sendChat").mockReturnValue(send.promise);
 await render(); await click("Carregar mais mensagens");
 await act(async()=>{const input=container.querySelector("textarea")!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value")!.set!.call(input,"question 2");input.dispatchEvent(new Event("input",{bubbles:true}));});
 await act(async()=>container.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})));
 if (!vi.mocked(chatAdapter.sendChat).mock.calls.length) {
  // Bounded exclusion is an acceptable implementation: rejected submit waits
  // for the page instead of overlapping two representations of the live turn.
  expect(container.querySelector("textarea")!.disabled).toBe(true);
  await act(async()=>page.resolve({conversation:conversation(1),items:[turn(2)],total:2,next_cursor:null}));
  await act(async()=>container.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})));
 } else {
  await act(async()=>page.resolve({conversation:conversation(1),items:[turn(2)],total:2,next_cursor:null}));
 }
 await act(async()=>send.resolve({conversation_id:"c1",message_id:"m2",answer:"answer 2",citations:[],metadata:{}} as Awaited<ReturnType<typeof chatAdapter.sendChat>>));
 expect(container.querySelectorAll('[aria-label="Resposta do corpus"]')).toHaveLength(2);
 expect(container.querySelectorAll('[aria-label="Consulta enviada"]')).toHaveLength(2);
});
it("does not duplicate the server question when a later page overlaps a completed live turn",async()=>{
 vi.mocked(chatAdapter.listConversations).mockResolvedValue({items:[conversation(1)],total:1});
 vi.mocked(chatAdapter.getConversation).mockResolvedValueOnce({conversation:conversation(1),items:[turn(1)],total:2,next_cursor:"more"}).mockResolvedValueOnce({conversation:conversation(1),items:[turn(2)],total:2,next_cursor:null});
 vi.spyOn(chatAdapter,"sendChat").mockResolvedValue({conversation_id:"c1",message_id:"m2",answer:"answer 2",citations:[],metadata:{}} as Awaited<ReturnType<typeof chatAdapter.sendChat>>);
 await render();await act(async()=>{const input=container.querySelector("textarea")!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value")!.set!.call(input,"question 2");input.dispatchEvent(new Event("input",{bubbles:true}));});
 await act(async()=>container.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})));
 await click("Carregar mais mensagens");
 expect(container.querySelectorAll('[aria-label="Resposta do corpus"]')).toHaveLength(2);
 expect(container.querySelectorAll('[aria-label="Consulta enviada"]')).toHaveLength(2);
});
it("excludes queued history-page and send actions in both directions while preserving the draft",async()=>{
 const page=deferred<Awaited<ReturnType<typeof chatAdapter.getConversation>>>();const send=deferred<Awaited<ReturnType<typeof chatAdapter.sendChat>>>();
 vi.mocked(chatAdapter.listConversations).mockResolvedValue({items:[conversation(1)],total:1});
 vi.mocked(chatAdapter.getConversation).mockResolvedValueOnce({conversation:conversation(1),items:[turn(1)],total:3,next_cursor:"more"}).mockReturnValueOnce(page.promise);
 vi.spyOn(chatAdapter,"sendChat").mockReturnValue(send.promise);
 await render();await act(async()=>{const input=container.querySelector("textarea")!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value")!.set!.call(input,"question 3");input.dispatchEvent(new Event("input",{bubbles:true}));});
 await act(async()=>{
  Array.from(container.querySelectorAll("button")).find(b=>b.textContent?.includes("Carregar mais mensagens"))!.click();
  container.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true}));
 });
 expect(chatAdapter.sendChat).not.toHaveBeenCalled();expect(container.querySelector("textarea")!.value).toBe("question 3");expect(container.querySelector("textarea")!.disabled).toBe(true);
 await act(async()=>page.resolve({conversation:conversation(1),items:[turn(2)],total:3,next_cursor:"last"}));
 await act(async()=>{
  container.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true}));
  Array.from(container.querySelectorAll("button")).find(b=>b.textContent?.includes("Carregar mais mensagens"))!.click();
 });
 expect(chatAdapter.sendChat).toHaveBeenCalledOnce();expect(chatAdapter.getConversation).toHaveBeenCalledTimes(2);
 await act(async()=>send.resolve({conversation_id:"c1",message_id:"m3",answer:"answer 3",citations:[],metadata:{}} as Awaited<ReturnType<typeof chatAdapter.sendChat>>));
 expect(container.querySelectorAll('[aria-label="Consulta enviada"]')).toHaveLength(3);expect(container.querySelectorAll('[aria-label="Resposta do corpus"]')).toHaveLength(3);
});
it("never claims corpus authorization from a session or a history listing", async () => {
 await render(); expect(container.textContent).not.toContain("Corpus autorizado");
});
it("disables composer and suggestions without chat.query", async () => {
 session = { ...identity, permissions: ["history.read"] }; await render();
 expect(container.querySelector("textarea")!.disabled).toBe(true);
 expect(Array.from(container.querySelectorAll('[aria-label="Sugestões de consulta"] button')).every(n=>(n as HTMLButtonElement).disabled)).toBe(true);
});
it("403 clears draft and streamed pending content instead of showing authorization or confidence", async () => {
 const pending = deferred<Awaited<ReturnType<typeof chatAdapter.sendChat>>>();
 vi.spyOn(chatAdapter,"sendChat").mockImplementation((_input,_signal,onEvent)=>{onEvent?.({type:"delta",delta:"PRIVATE PARTIAL"});return pending.promise;});
 await render();
 await act(async()=>{ const input=container.querySelector("textarea")!; Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value")!.set!.call(input,"private question"); input.dispatchEvent(new Event("input",{bubbles:true})); });
 await act(async()=>container.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})));
 await act(async()=>pending.reject(new ApiError("Denied",403,"forbidden")));
 expect(container.textContent).not.toContain("PRIVATE PARTIAL"); expect(container.textContent).not.toContain("Corpus autorizado"); expect(container.querySelector("textarea")!.value).toBe(""); expect(container.querySelector("textarea")!.disabled).toBe(true);
});
it("keeps prior pages and retries the same cursor after an invalid-cursor error, including empty filtered pages", async()=>{
 vi.mocked(chatAdapter.listConversations).mockResolvedValueOnce({items:[conversation(1)],total:2,next_cursor:"next"}).mockRejectedValueOnce(new ApiError("invalid cursor",422,"validation_error")).mockResolvedValueOnce({items:[],total:2,next_cursor:"last"}).mockResolvedValueOnce({items:[conversation(2)],total:2,next_cursor:null});
 await render(); await click("Carregar mais conversas"); expect(container.textContent).toContain("invalid cursor"); expect(container.querySelectorAll("nav button")).toHaveLength(1);
 await act(async()=>{ const input=container.querySelector('input[placeholder="Filtrar conversas"]')!; Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value")!.set!.call(input,"Conversation 2"); input.dispatchEvent(new Event("input",{bubbles:true})); });
 await click("Carregar mais conversas"); expect(chatAdapter.listConversations).toHaveBeenLastCalledWith(expect.any(AbortSignal),"next");
 await click("Carregar mais conversas"); expect(container.querySelectorAll("nav button")).toHaveLength(1); expect(container.textContent).toContain("Conversation 2");
});
for(const kind of ["list","detail"] as const) it(`discards late ${kind} page from a previous tenant`,async()=>{
 const pending=deferred<never>();
 vi.mocked(chatAdapter.listConversations).mockResolvedValueOnce({items:[conversation(1)],total:2,next_cursor:"next"}).mockResolvedValue({items:[],total:0});
 vi.mocked(chatAdapter.getConversation).mockResolvedValueOnce({conversation:conversation(1),items:[turn(1)],total:2,next_cursor:"next"});
 await render();
 if(kind==="list") vi.mocked(chatAdapter.listConversations).mockReturnValueOnce(pending.promise); else vi.mocked(chatAdapter.getConversation).mockReturnValueOnce(pending.promise);
 await click(kind==="list" ? "Carregar mais conversas" : "Carregar mais mensagens");
 const calls=kind==="list" ? vi.mocked(chatAdapter.listConversations).mock.calls : vi.mocked(chatAdapter.getConversation).mock.calls;
 const signal=calls[calls.length-1][kind==="list" ? 0 : 1] as AbortSignal;
 session={...identity,tenant_id:"new"}; await render(); expect(signal.aborted).toBe(true);
 await act(async()=>pending.resolve((kind==="list" ? {items:[{...conversation(2),title:"STALE PRIVATE"}],total:2} : {conversation:conversation(1),items:[{...turn(2),answer:"STALE PRIVATE"}],total:2}) as never));
 expect(container.textContent).not.toContain("STALE PRIVATE");
});
it("ignores an old detail arriving after a newer conversation selection and honors deep links",async()=>{
 const pending=deferred<Awaited<ReturnType<typeof chatAdapter.getConversation>>>();
 window.history.replaceState({},"","/app/chat?conversation=outside-first-page");
 vi.mocked(chatAdapter.listConversations).mockResolvedValue({items:[conversation(2)],total:1});
 vi.mocked(chatAdapter.getConversation).mockReturnValueOnce(pending.promise).mockResolvedValueOnce({conversation:conversation(2),items:[turn(2)],total:1});
 await render(); expect(chatAdapter.getConversation).toHaveBeenCalledWith("outside-first-page",expect.any(AbortSignal));
 await click("Conversation 2"); await act(async()=>pending.resolve({conversation:conversation(1),items:[turn(1)],total:1}));
 expect(container.textContent).toContain("answer 2"); expect(container.textContent).not.toContain("answer 1");
});
it("offline during send preserves retry identity and rejects late callbacks",async()=>{
 const pending=deferred<Awaited<ReturnType<typeof chatAdapter.sendChat>>>(); let late: Parameters<typeof chatAdapter.sendChat>[2];
 vi.spyOn(chatAdapter,"sendChat").mockImplementationOnce((_input,_signal,onEvent)=>{late=onEvent;return pending.promise;}).mockResolvedValue({conversation_id:"c1",message_id:"m",answer:"Recovered",citations:[],metadata:{}} as Awaited<ReturnType<typeof chatAdapter.sendChat>>);
 await render(); await act(async()=>{const input=container.querySelector("textarea")!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value")!.set!.call(input,"recover me");input.dispatchEvent(new Event("input",{bubbles:true}));});
 await act(async()=>container.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})));
 const first=vi.mocked(chatAdapter.sendChat).mock.calls[0][0]; online=false; await render();
 expect(container.querySelector("textarea")!.value).toBe("recover me");
 await act(async()=>late?.({type:"delta",delta:"STALE PRIVATE"})); expect(container.textContent).not.toContain("STALE PRIVATE");
 online=true;await render();await click("Tentar novamente");expect(vi.mocked(chatAdapter.sendChat).mock.calls[1][0].idempotencyKey).toBe(first.idempotencyKey);
});
it("history.read denial does not revoke independent chat.query",async()=>{
 vi.mocked(chatAdapter.listConversations).mockRejectedValue(new ApiError("History denied",403)); await render();
 expect(container.querySelector("textarea")!.disabled).toBe(false);
});
it("query denial requires explicit authority revalidation before retry",async()=>{
 vi.spyOn(chatAdapter,"sendChat").mockRejectedValueOnce(new ApiError("Denied",403)).mockResolvedValue({conversation_id:"c1",message_id:"m",answer:"Restored",citations:[],metadata:{}} as Awaited<ReturnType<typeof chatAdapter.sendChat>>);
 vi.spyOn(api,"me").mockResolvedValue(identity);
 await render(); await act(async()=>{const input=container.querySelector("textarea")!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value")!.set!.call(input,"question");input.dispatchEvent(new Event("input",{bubbles:true}));});
 await act(async()=>container.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})));
 expect(container.querySelector("textarea")!.disabled).toBe(true);
 online=false;await render();online=true;await render();expect(container.querySelector("textarea")!.disabled).toBe(true);
 await click("Revalidar autorização"); expect(api.me).toHaveBeenCalledOnce();
 expect(chatAdapter.sendChat).toHaveBeenCalledOnce(); expect(container.querySelector("textarea")!.disabled).toBe(false);
 await click("Tentar novamente");expect(chatAdapter.sendChat).toHaveBeenCalledTimes(2);
});
it("API success confirms only the query, and offline resets confidence and pending content",async()=>{
 vi.spyOn(chatAdapter,"sendChat").mockResolvedValue({conversation_id:"c1",message_id:"m",answer:"Good",citations:[],metadata:{}} as Awaited<ReturnType<typeof chatAdapter.sendChat>>);
 await render(); await act(async()=>{const input=container.querySelector("textarea")!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value")!.set!.call(input,"question");input.dispatchEvent(new Event("input",{bubbles:true}));});
 await act(async()=>container.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})));
 expect(container.textContent).toContain("Consulta autorizada pela API"); online=false; await render();
 expect(container.textContent).not.toContain("Consulta autorizada pela API"); expect(container.textContent).toContain("Escopo não confirmado"); expect(container.querySelector("textarea")!.disabled).toBe(false); expect(Array.from(container.querySelectorAll("button")).find(b=>b.textContent?.includes("Consultar"))!.disabled).toBe(true);
});
it("closes mobile drawer on desktop resize and moves focus to visible content", async()=>{
 let listener: (()=>void) | undefined;
 const media={matches:true,addEventListener:vi.fn((_event:string, callback:()=>void)=>{listener=callback;}),removeEventListener:vi.fn()};
 vi.mocked(window.matchMedia).mockImplementation(query=>query.includes("760") ? media as unknown as MediaQueryList : {matches:false} as MediaQueryList);
 await render(); await click("Conversas"); expect(container.querySelector("aside")!.getAttribute("data-open")).toBe("true");
 const last=container.querySelector('aside input')! as HTMLInputElement; last.focus();
 const trapped=new KeyboardEvent("keydown",{key:"Tab",bubbles:true,cancelable:true});
 await act(async()=>last.dispatchEvent(trapped)); expect(trapped.defaultPrevented).toBe(true);
 await act(async()=>{media.matches=false; listener?.(); window.dispatchEvent(new Event("resize"));});
 expect(container.querySelector("aside")!.getAttribute("data-open")).toBe("false");
 expect(document.activeElement?.id).toBe("chat-title");
 const released=new KeyboardEvent("keydown",{key:"Tab",bubbles:true,cancelable:true});
 await act(async()=>last.dispatchEvent(released));expect(released.defaultPrevented).toBe(false);
});
it("mobile Escape closes the drawer and returns focus to its opener",async()=>{
 vi.mocked(window.matchMedia).mockImplementation(query=>({matches:query.includes("760"),addEventListener:vi.fn(),removeEventListener:vi.fn()} as unknown as MediaQueryList));
 await render();await click("Conversas");
 expect(container.querySelector('aside')!.getAttribute('role')).toBe('dialog');
 expect(container.querySelector('aside')!.getAttribute('aria-modal')).toBe('true');
 expect((container.querySelector('.answer-panel') as HTMLElement).inert).toBe(true);
 expect(document.activeElement?.getAttribute("aria-label")).toBe("Fechar conversas");
 await act(async()=>container.querySelector("aside")!.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true,cancelable:true})));
 expect(container.querySelector("aside")!.getAttribute("data-open")).toBe("false");expect(document.activeElement?.getAttribute("aria-controls")).toBe("conversation-sidebar");
});
it("preserves positional signals and appends encoded cursors in API and adapter", async()=>{
 const fetchMock=vi.fn().mockImplementation(async()=>new Response(JSON.stringify({items:[],total:0}),{status:200})); vi.stubGlobal("fetch",fetchMock);
 const controller=new AbortController();const signal=controller.signal;
 await (api.listConversations as (...args: unknown[])=>Promise<unknown>)(50,signal,"a+b=");
 expect(fetchMock.mock.calls[0][0]).toContain("cursor=a%2Bb%3D"); expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(false);
 vi.mocked(chatAdapter.listConversations).mockRestore(); vi.mocked(chatAdapter.getConversation).mockRestore();
 await chatAdapter.listConversations(signal, "list cursor");
 expect(fetchMock.mock.calls[1][0]).toContain("cursor=list%20cursor"); expect(fetchMock.mock.calls[1][1].signal.aborted).toBe(false);
 await api.listConversations(50, signal); expect(fetchMock.mock.calls[2][0]).not.toContain("cursor");
 fetchMock.mockImplementation(async(url:string)=>new Response(JSON.stringify({conversation:{...conversation(1),conversation_id:decodeURIComponent(new URL(url,"http://localhost").pathname.split("/").pop()!)},items:[turn(1)],total:1,next_cursor:null}),{status:200}));
 await api.getConversation("id/encoded",100,signal,"turn+");
 expect(fetchMock.mock.calls[3][0]).toContain("id%2Fencoded?limit=100&cursor=turn%2B"); expect(fetchMock.mock.calls[3][1].signal.aborted).toBe(false);
 await chatAdapter.getConversation("c1",signal,"more"); expect(fetchMock.mock.calls[4][0]).toContain("cursor=more");
 await api.getConversation("c1",100,signal); expect(fetchMock.mock.calls[5][0]).not.toContain("cursor");
 controller.abort();expect(fetchMock.mock.calls.every(call=>call[1].signal.aborted)).toBe(true);
});

it("does not let an abandoned conversation-open controller block the next send (AUD24-04)", async()=>{
 const detail=deferred<Awaited<ReturnType<typeof chatAdapter.getConversation>>>();
 vi.mocked(chatAdapter.listConversations).mockResolvedValue({items:[conversation(1)],total:1});
 vi.mocked(chatAdapter.getConversation).mockReturnValueOnce(detail.promise);
 const send=deferred<Awaited<ReturnType<typeof chatAdapter.sendChat>>>();
 vi.spyOn(chatAdapter,"sendChat").mockReturnValue(send.promise);
 await render();
 await vi.waitFor(()=>expect(chatAdapter.getConversation).toHaveBeenCalledTimes(1));
 await click("Nova conversa");
 const input=container.querySelector("textarea")!;
 await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value")!.set!.call(input,"pergunta após abandonar");input.dispatchEvent(new Event("input",{bubbles:true}));});
 await act(async()=>container.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})));
 await vi.waitFor(()=>expect(chatAdapter.sendChat).toHaveBeenCalledTimes(1));
 expect(vi.mocked(chatAdapter.sendChat).mock.calls[0][0]).toMatchObject({message:"pergunta após abandonar"});
 await act(async()=>send.resolve({conversation_id:"c-new",message_id:"m-new",answer:"ok",citations:[],metadata:{}} as Awaited<ReturnType<typeof chatAdapter.sendChat>>));
});

it("shows a retry instead of an endless spinner after an external abort (AUD24-05)", async()=>{
 vi.mocked(chatAdapter.listConversations).mockResolvedValue({items:[conversation(1)],total:1});
 vi.mocked(chatAdapter.getConversation).mockRejectedValueOnce(new DOMException("aborted by authority","AbortError"));
 await render();
 await vi.waitFor(()=>expect(container.textContent).toContain("Não foi possível abrir a conversa"));
 expect(container.textContent).toContain("Tentar novamente");
 expect(container.textContent).not.toContain("Abrindo conversa…");
});
