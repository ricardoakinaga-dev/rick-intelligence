// @vitest-environment jsdom
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AppShell } from "../../components/app-shell";
import type { Session } from "../../types/api";
let pathname: string;
let value: { session: Session | null; ready: boolean; error: string | null; errorKind: string | null; refresh: ReturnType<typeof vi.fn>; signOut: ReturnType<typeof vi.fn> };
const router = { replace: vi.fn() };
vi.mock("next/navigation", () => ({ usePathname: () => pathname, useRouter: () => router }));
vi.mock("next/link", () => ({ default: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a href={href} {...props}>{children}</a> }));
vi.mock("../../components/session-provider", () => ({ useSession: () => value }));
const identity = { authenticated: true, user_id: "u", email: "synthetic@example.invalid", session_id: "s", tenant_id: "t", workspace_id: "w", role: "VETERINARIAN", canonical_role: "VETERINARIAN", permissions: ["cases.read", "chat.query"] } as Session;
let root: Root; let container: HTMLDivElement;
function PrivateChild() { const [draft, setDraft] = useState(""); return <input aria-label="Private draft" value={draft} onChange={event => setDraft(event.target.value)} />; }
async function render() { await act(async () => root.render(<AppShell><PrivateChild /></AppShell>)); }
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  pathname = "/app/cases"; value = { session: { ...identity }, ready: true, error: null, errorKind: null, refresh: vi.fn(), signOut: vi.fn().mockResolvedValue(undefined) };
  container = document.createElement("div"); document.body.append(container); root = createRoot(container); router.replace.mockClear();
});
afterEach(async () => { await act(async () => root.unmount()); document.body.replaceChildren(); vi.unstubAllGlobals(); });
const changes = [
  { permissions: ["chat.query"] }, { user_id: "other" }, { session_id: "other" },
  { tenant_id: "other" }, { workspace_id: "other" }, { role: "VIEWER" }, { canonical_role: "VIEWER" },
];
for (const patch of changes) {
  it(`discards child private state when ${Object.keys(patch)[0]} changes`, async () => {
    await render();
    const input = container.querySelector("input")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "PRIVATE DRAFT");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(input.value).toBe("PRIVATE DRAFT");
    value = { ...value, session: { ...identity, ...patch } }; await render();
    expect(container.querySelector("input")!.value).toBe(""); expect(input.isConnected).toBe(false);
  });
}
it("preserves a draft for a semantically unchanged permission set", async () => {
  await render(); const child = container.querySelector("input");
  value = { ...value, session: { ...identity, permissions: [...identity.permissions!].reverse() } }; await render();
  expect(container.querySelector("input")).toBe(child);
});
it("keeps loading and validation failure private, exposes retry and redirects logout", async () => {
  value = { ...value, session: null, ready: false }; await render(); expect(container.querySelector("input")).toBeNull();
  value = { ...value, ready: true, error: "unavailable", errorKind: "validation" }; await render();
  expect(container.textContent).toContain("Nenhum conteúdo privado foi exibido");
  await act(async () => Array.from(container.querySelectorAll("button")).find(b => b.textContent === "Tentar novamente")!.click()); expect(value.refresh).toHaveBeenCalledOnce();
  value = { ...value, error: null, errorKind: null }; await render(); expect(router.replace).toHaveBeenCalledWith("/login?next=%2Fapp%2Fcases");
  pathname = "/login"; await render(); expect(container.querySelector("input")).not.toBeNull();
});
it("traps mobile navigation keyboard, restores opener focus and releases body scroll",async()=>{
 vi.stubGlobal("requestAnimationFrame",vi.fn((callback:FrameRequestCallback)=>{callback(0);return 1;}));vi.stubGlobal("cancelAnimationFrame",vi.fn());
 vi.stubGlobal("matchMedia",vi.fn(()=>({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()})));
 await render();const opener=container.querySelector('[aria-label="Abrir navegação"]') as HTMLButtonElement;const close=container.querySelector('[aria-label="Fechar navegação"]') as HTMLButtonElement;const last=container.querySelector('.profile-button') as HTMLButtonElement;
 opener.focus();await act(async()=>opener.click());expect(document.activeElement).toBe(close);expect(document.body.style.overflow).toBe("hidden");
 const backward=new KeyboardEvent("keydown",{key:"Tab",shiftKey:true,bubbles:true,cancelable:true});await act(async()=>close.dispatchEvent(backward));expect(backward.defaultPrevented).toBe(true);expect(document.activeElement).toBe(last);
 const forward=new KeyboardEvent("keydown",{key:"Tab",bubbles:true,cancelable:true});await act(async()=>last.dispatchEvent(forward));expect(forward.defaultPrevented).toBe(true);expect(document.activeElement).toBe(close);
 await act(async()=>close.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true,cancelable:true})));expect(document.activeElement).toBe(opener);expect(document.body.style.overflow).toBe("");
});
it("deduplicates logout and keeps failure safely recoverable after private teardown",async()=>{
 let reject!:(reason:unknown)=>void;value.signOut.mockImplementationOnce(()=>new Promise<void>((_resolve,fail)=>{reject=fail;}));await render();
 const profile=container.querySelector('.profile-button') as HTMLButtonElement;await act(async()=>{profile.click();profile.click();});expect(value.signOut).toHaveBeenCalledOnce();
 value={...value,session:null};await render();await act(async()=>reject(new Error("SECRET INTERNAL ERROR")));expect(container.querySelector('input')).toBeNull();expect(container.textContent).toContain("não foi possível confirmar a saída");expect(container.textContent).not.toContain("SECRET INTERNAL ERROR");
 await act(async()=>Array.from(container.querySelectorAll('button')).find(b=>b.textContent==="Tentar sair novamente")!.click());expect(value.signOut).toHaveBeenCalledTimes(2);expect(container.textContent).not.toContain("não foi possível confirmar a saída");
});
it("shows permitted navigation and executes profile logout", async () => {
  value = { ...value, session: { ...identity, permissions: ["cases.read", "documents.read", "audit.read"] } }; await render();
  expect(container.querySelector('a[href="/app/cases"]')).not.toBeNull(); expect(container.querySelector('a[href="/admin"]')).not.toBeNull();
  expect(container.querySelector('a[href="/app/chat"]')).toBeNull();
  await act(async () => (container.querySelector(".profile-button") as HTMLButtonElement).click()); expect(value.signOut).toHaveBeenCalledOnce();
});
