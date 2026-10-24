// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { SessionProvider } from "../../components/session-provider";
import { AppShell } from "../../components/app-shell";
import { ChatWorkspace } from "../../components/chat/chat-workspace";
import { chatAdapter } from "../../components/chat/chat-adapter";
import { api, ApiError } from "../../lib/api";
import type { Session } from "../../types/api";
import { SessionCoordination } from "../../lib/session-coordination";
vi.mock("next/navigation",()=>({usePathname:()=>"/app/chat",useRouter:()=>({replace:vi.fn()})}));
vi.mock("next/link",()=>({default:({children,...props}:React.AnchorHTMLAttributes<HTMLAnchorElement>)=><a {...props}>{children}</a>}));
const identity:Session={authenticated:true,user_id:"A",email:"A@example.invalid",role:"viewer",canonical_role:"VIEWER",tenant_id:"t",workspace_id:"w",session_id:"s",permissions:["chat.query","history.read"]};
function deferred<T>() { let resolve!:(v:T)=>void;let reject!:(v:unknown)=>void;const promise=new Promise<T>((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject}; }
let root:Root,container:HTMLDivElement;
const render=()=>act(async()=>root.render(<SessionProvider><AppShell><ChatWorkspace /></AppShell></SessionProvider>));
async function draft(text:string){await act(async()=>{const input=container.querySelector("textarea")!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value")!.set!.call(input,text);input.dispatchEvent(new Event("input",{bubbles:true}));});}
async function focus(){await act(async()=>window.dispatchEvent(new Event("focus")));}
async function network(online:boolean){await act(async()=>{Object.defineProperty(navigator,"onLine",{configurable:true,value:online});window.dispatchEvent(new Event(online?"online":"offline"));});}
beforeEach(()=>{
 localStorage.clear();
 Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});Object.defineProperty(navigator,"onLine",{configurable:true,value:true});
 vi.stubGlobal("matchMedia",vi.fn(()=>({matches:false,addEventListener:vi.fn(),removeEventListener:vi.fn()})));
 Element.prototype.scrollTo=vi.fn();Element.prototype.scrollIntoView=vi.fn();window.history.replaceState({},"","/app/chat");
 container=document.createElement("div");document.body.append(container);root=createRoot(container);
 vi.spyOn(api,"me").mockResolvedValue(identity);vi.spyOn(chatAdapter,"listConversations").mockResolvedValue({items:[],total:0});
});
afterEach(async()=>{await act(async()=>root.unmount());document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals();});
it("hides/inerts but retains a private draft across deferred same-authority focus revalidation",async()=>{
 await render();await draft("PRIVATE DRAFT");const input=container.querySelector("textarea")!;input.focus();const read=deferred<Session>();vi.mocked(api.me).mockReturnValueOnce(read.promise);
 await focus();expect(input.isConnected).toBe(true);expect(input.closest("[hidden][inert]")).not.toBeNull();expect(document.activeElement).not.toBe(input);
 await act(async()=>read.resolve({...identity}));expect(container.querySelector("textarea")).toBe(input);expect(input.value).toBe("PRIVATE DRAFT");expect(input.closest("[hidden]")).toBeNull();expect(document.activeElement).toBe(input);
});
it("retains offline retry/key through focus and suppresses the old callback across validation",async()=>{
 const send=deferred<Awaited<ReturnType<typeof chatAdapter.sendChat>>>();let late:Parameters<typeof chatAdapter.sendChat>[2];
 vi.spyOn(chatAdapter,"sendChat").mockImplementationOnce((_input,_signal,event)=>{late=event;return send.promise;}).mockResolvedValue({conversation_id:"c",message_id:"m",answer:"Recovered",citations:[],metadata:{}} as Awaited<ReturnType<typeof chatAdapter.sendChat>>);
 await render();await draft("recover question");await act(async()=>container.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})));
 const key=vi.mocked(chatAdapter.sendChat).mock.calls[0][0].idempotencyKey;await network(false);await focus();await network(true);
 expect(container.querySelector("textarea")!.value).toBe("recover question");await act(async()=>late?.({type:"delta",delta:"STALE PRIVATE"}));expect(container.textContent).not.toContain("STALE PRIVATE");
 await act(async()=>Array.from(container.querySelectorAll("button")).find(b=>b.textContent==="Tentar novamente")!.click());expect(vi.mocked(chatAdapter.sendChat).mock.calls[1][0].idempotencyKey).toBe(key);
});
it("a lease hides private UI when its durable producer was never delivered as a storage event",async()=>{
 await render();await draft("LOCAL ONLY");const input=container.querySelector("textarea")!;const remote=new SessionCoordination();const id=remote.begin();
 await act(async()=>{await expect(api.documents("w")).rejects.toMatchObject({code:"session_validation_pending"});});expect(input.closest("[hidden][inert]")).not.toBeNull();
 remote.settle(id);await focus();expect(container.querySelector("textarea")).toBe(input);expect(input.value).toBe("LOCAL ONLY");expect(input.closest("[hidden]")).toBeNull();
});
it("remote pending cannot be bypassed by focus and settled B destroys retained A",async()=>{
 await render();await draft("A ONLY");const input=container.querySelector("textarea")!;const before=vi.mocked(api.me).mock.calls.length;
 await act(async()=>window.dispatchEvent(new StorageEvent("storage",{key:"rick-session-change",newValue:"pending:remote-B"})));await focus();
 expect(api.me).toHaveBeenCalledTimes(before);expect(input.closest("[hidden][inert]")).not.toBeNull();await expect(api.deleteDocument("d")).rejects.toMatchObject({code:"session_validation_pending"});
 vi.mocked(api.me).mockResolvedValueOnce({...identity,user_id:"B",session_id:"B"});await act(async()=>window.dispatchEvent(new StorageEvent("storage",{key:"rick-session-change",newValue:"settled:remote-B"})));
 expect(input.isConnected).toBe(false);expect(container.querySelector("textarea")!.value).toBe("");
});
it("logout destroys retained state and cannot be undone by a previous authority response",async()=>{
 await render();await draft("A SECRET");const input=container.querySelector("textarea")!;const old=deferred<Session>();vi.mocked(api.me).mockReturnValueOnce(old.promise);await focus();
 vi.spyOn(api,"logout").mockResolvedValue({status:"signed_out"});await act(async()=>(container.querySelector('.profile-button') as HTMLButtonElement).click());
 expect(input.isConnected).toBe(false);await act(async()=>old.resolve(identity));expect(container.querySelector("textarea")).toBeNull();
});
it("keeps retained private state hidden during outage, restores only same authority, and destroys A on B",async()=>{
 await render();await draft("A PRIVATE");const input=container.querySelector("textarea")!;vi.mocked(api.me).mockRejectedValueOnce(new ApiError("outage",503));await focus();
 expect(input.isConnected).toBe(true);expect(input.closest("[hidden][inert]")).not.toBeNull();expect(container.querySelector('.session-error-state')).not.toBeNull();
 await focus();expect(container.querySelector("textarea")!.value).toBe("A PRIVATE");
 vi.mocked(api.me).mockResolvedValueOnce({...identity,user_id:"B",session_id:"B"});await focus();expect(input.isConnected).toBe(false);expect(container.querySelector("textarea")!.value).toBe("");
});
