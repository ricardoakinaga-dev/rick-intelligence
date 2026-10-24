// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "../../lib/api";
import { SessionProvider, useSession } from "../../components/session-provider";
import type { Session } from "../../types/api";
import { SessionCoordination, SESSION_OPERATION_PREFIX } from "../../lib/session-coordination";
let current: ReturnType<typeof useSession>;
let root: Root;
let container: HTMLDivElement;
const identity = (id: string) => ({ authenticated: true, user_id: id, workspace_id: id, session_id: id, permissions: ["cases.read"] }) as Session;
const login = { email: "a@example.invalid", password: "synthetic", tenant_id: "t" };
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (cause: unknown) => void; const promise = new Promise<T>((a,b) => {resolve=a;reject=b;}); return { promise, resolve, reject }; }
function Consumer() { current = useSession(); return <div>{current.ready ? "ready" : "loading"}:{current.session?.user_id || "anonymous"}:{current.errorKind}:{current.error}</div>; }
beforeEach(() => {
  localStorage.clear();
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  vi.spyOn(api, "me").mockResolvedValue(identity("initial"));
  vi.spyOn(api, "login").mockResolvedValue(identity("login"));
  vi.spyOn(api, "logout").mockResolvedValue({ status: "ok" });
});
afterEach(async () => { await act(async () => root.unmount()); document.body.replaceChildren(); vi.restoreAllMocks(); });
async function render() { await act(async () => root.render(<SessionProvider><Consumer /></SessionProvider>)); }
it("keeps validation failure anonymous and retries with updated permissions", async () => {
  vi.mocked(api.me).mockRejectedValueOnce(new ApiError("unavailable", 503, "down")); await render();
  expect(current.session).toBeNull(); expect(current.errorKind).toBe("validation"); expect(current.ready).toBe(false);
  await act(async () => current.refresh()); expect(current.session?.user_id).toBe("initial"); expect(current.error).toBeNull();
  vi.mocked(api.me).mockResolvedValue({ ...identity("initial"), permissions: [] });
  await act(async () => current.refresh()); expect(current.session?.permissions).toEqual([]);
});
it.each([401,403])("keeps %s anonymous without a service error", async status => {
  vi.mocked(api.me).mockRejectedValue(new ApiError("private", status)); await render();
  expect(current.session).toBeNull(); expect(current.error).toBeNull(); expect(current.errorKind).toBeNull();
});
it("ignores older refresh on successful login", async () => {
  const pending = deferred<Session>(); vi.mocked(api.me).mockReturnValueOnce(pending.promise); await render();
  expect(container.textContent).toContain("loading");
  await act(async () => current.signIn(login));
  await act(async () => pending.resolve(identity("old")));
  expect(current.session?.user_id).toBe("login");
});
it("preserves login error after an older successful refresh, then permits retry", async () => {
  const pending = deferred<Session>(); vi.mocked(api.me).mockReturnValueOnce(pending.promise); await render();
  vi.mocked(api.login).mockRejectedValueOnce(new Error("login failed"));
  await act(async () => { await expect(current.signIn(login)).rejects.toThrow("login failed"); });
  await act(async () => pending.resolve(identity("old"))); expect(current.session).toBeNull(); expect(current.errorKind).toBe("mutation");
  await act(async () => current.signIn(login)); expect(current.session?.user_id).toBe("login");
});
it("serializes login and logout, rejects superseded login and blocks duplicate mutations", async () => {
  const pending = deferred<Session>(); vi.mocked(api.login).mockReturnValue(pending.promise); await render();
  let signing!: Promise<Session>; let leaving!: Promise<void>;
  await act(async () => { signing = current.signIn(login); signing.catch(() => {}); });
  await act(async () => { await current.refresh(); await expect(current.signIn(login)).rejects.toMatchObject({ code: "session_busy" }); leaving = current.signOut(); });
  expect(current.session).toBeNull(); expect(api.logout).not.toHaveBeenCalled();
  await act(async () => pending.resolve(identity("old login")));
  await expect(signing).rejects.toMatchObject({ code: "session_superseded" }); await act(async () => leaving);
  expect(api.logout).toHaveBeenCalledOnce(); expect(current.session).toBeNull();
});
it("keeps logout failure anonymous and deduplicates pending logout", async () => {
  const pending = deferred<{ status: string }>(); vi.mocked(api.logout).mockReturnValue(pending.promise); await render();
  let first!: Promise<void>; let second!: Promise<void>;
  await act(async () => { first = current.signOut(); first.catch(() => {}); second = current.signOut(); second.catch(() => {}); });
  expect(current.session).toBeNull(); expect(api.logout).toHaveBeenCalledOnce();
  await act(async () => pending.reject(new ApiError("logout failed", 503)));
  await expect(first).rejects.toThrow("logout failed"); await expect(second).rejects.toThrow("logout failed");
  expect(current.errorKind).toBe("mutation"); expect(current.session).toBeNull();
});
it("invalidates private authority on cross-tab signal before deferred revalidation", async () => {
  await render(); const pending = deferred<Session>(); vi.mocked(api.me).mockReturnValueOnce(pending.promise);
  await act(async () => window.dispatchEvent(new StorageEvent("storage", { key: "rick-session-change", newValue: "opaque-change" })));
  expect(current.session?.user_id).toBe("initial"); expect(current.ready).toBe(false);
  await act(async () => pending.resolve(identity("B"))); expect(current.session?.user_id).toBe("B");
});
it("announces only opaque phases and never revalidates a pending cross-tab cookie mutation",async()=>{
 await render(); const writes=vi.spyOn(Storage.prototype,"setItem");
 await act(async()=>current.signIn(login));
 const announcements=writes.mock.calls.filter(([key])=>key==="rick-session-change").map(([,value])=>value);
 expect(announcements.map(value=>value.split(":")[0])).toEqual(["pending","settled"]);
 expect(announcements[0].slice("pending:".length)).toBe(announcements[1].slice("settled:".length));
 expect(writes.mock.calls.find(([key])=>key.startsWith("rick-session-op:"))?.[1]).toBe("pending");
 expect(JSON.stringify(writes.mock.calls)).not.toContain(login.email);expect(JSON.stringify(writes.mock.calls)).not.toContain(login.password);
 const before=vi.mocked(api.me).mock.calls.length;
 await act(async()=>window.dispatchEvent(new StorageEvent("storage",{key:"rick-session-change",newValue:"pending:nonce"})));
 expect(current.session?.user_id).toBe("login");expect(current.ready).toBe(false);expect(api.me).toHaveBeenCalledTimes(before);
 await act(async()=>{window.dispatchEvent(new Event("focus"));document.dispatchEvent(new Event("visibilitychange"));});
 expect(current.ready).toBe(false);expect(api.me).toHaveBeenCalledTimes(before);
 await act(async()=>window.dispatchEvent(new StorageEvent("storage",{key:"rick-session-change",newValue:"settled:nonce"})));
 expect(current.session?.user_id).toBe("initial");
});
it("does not reopen authority when one of two remote cookie mutations is still pending",async()=>{
 await render();const before=vi.mocked(api.me).mock.calls.length;
 for(const value of ["pending:B","pending:C","settled:B"]) await act(async()=>window.dispatchEvent(new StorageEvent("storage",{key:"rick-session-change",newValue:value})));
 await act(async()=>window.dispatchEvent(new Event("focus")));
 expect(current.ready).toBe(false);expect(api.me).toHaveBeenCalledTimes(before);
 await act(async()=>window.dispatchEvent(new StorageEvent("storage",{key:"rick-session-change",newValue:"settled:C"})));
 expect(current.ready).toBe(true);expect(api.me).toHaveBeenCalledTimes(before+1);
});
it("boot discovers an outstanding producer even when the last global signal settled another producer",async()=>{
 localStorage.setItem("rick-session-op:C","pending");localStorage.setItem("rick-session-change","settled:v2:B");await render();
 expect(current.ready).toBe(false);expect(api.me).not.toHaveBeenCalled();await act(async()=>window.dispatchEvent(new Event("focus")));expect(api.me).not.toHaveBeenCalled();
 localStorage.removeItem("rick-session-op:C");localStorage.setItem("rick-session-change","settled:v2:C");await act(async()=>window.dispatchEvent(new StorageEvent("storage",{key:"rick-session-change",newValue:"settled:v2:C"})));expect(current.ready).toBe(true);
});
it("rejects cookie logout while a remote mutation remains pending",async()=>{
 await render();await act(async()=>window.dispatchEvent(new StorageEvent("storage",{key:"rick-session-change",newValue:"pending:C"})));
 await act(async()=>{await expect(current.signOut()).rejects.toMatchObject({code:"session_busy"});});expect(api.logout).not.toHaveBeenCalled();expect(current.session).toBeNull();expect(current.ready).toBe(false);
});
it("does not publish me across an unseen completed producer fence",async()=>{
 await render();const read=deferred<Session>();vi.mocked(api.me).mockReturnValueOnce(read.promise);await act(async()=>window.dispatchEvent(new Event("focus")));
 const remote=new SessionCoordination();const id=remote.begin();remote.settle(id);await act(async()=>read.resolve(identity("STALE")));
 expect(current.ready).toBe(false);expect(current.session?.user_id).toBe("initial");expect(current.errorKind).toBe("validation");await act(async()=>current.refresh());expect(current.ready).toBe(true);
});
it("rejects a local login overlapping another producer without removing that producer marker",async()=>{
 await render();const response=deferred<Session>();vi.mocked(api.login).mockReturnValueOnce(response.promise);let signing!:Promise<Session>;
 await act(async()=>{signing=current.signIn(login);signing.catch(()=>{});});const remote=new SessionCoordination();const id=remote.begin();await act(async()=>response.resolve(identity("local-stale")));
 await expect(signing).rejects.toMatchObject({code:"session_superseded"});expect(current.ready).toBe(false);expect(current.session).toBeNull();expect(localStorage.getItem(`${SESSION_OPERATION_PREFIX}${id}`)).toBe("pending");
 remote.settle(id);await act(async()=>current.refresh());expect(current.ready).toBe(true);
});
it("never confirms a local logout while an unseen concurrent producer can still replace cookies",async()=>{
 await render();const response=deferred<{status:string}>();vi.mocked(api.logout).mockReturnValueOnce(response.promise);let leaving!:Promise<void>;
 await act(async()=>{leaving=current.signOut();leaving.catch(()=>{});});const remote=new SessionCoordination();const id=remote.begin();await act(async()=>response.resolve({status:"signed_out"}));
 await expect(leaving).rejects.toMatchObject({code:"session_superseded"});expect(current.ready).toBe(false);expect(current.session).toBeNull();expect(localStorage.getItem(`${SESSION_OPERATION_PREFIX}${id}`)).toBe("pending");remote.settle(id);
});
it("focus revalidation fails closed and ignores stale response", async () => {
  await render(); const old = deferred<Session>(); vi.mocked(api.me).mockReturnValueOnce(old.promise).mockRejectedValueOnce(new ApiError("down",503));
  await act(async () => window.dispatchEvent(new Event("focus"))); expect(current.ready).toBe(false);
  await act(async () => window.dispatchEvent(new Event("focus"))); expect(current.errorKind).toBe("validation");
  await act(async () => old.resolve(identity("STALE"))); expect(current.session?.user_id).toBe("initial");expect(current.ready).toBe(false);
});
it("discards pending reads after unmount", async () => {
  const pending = deferred<Session>(); vi.mocked(api.me).mockReturnValueOnce(pending.promise); await render();
  const old = current; await act(async () => root.unmount());
  await act(async () => { pending.resolve(identity("late")); await old.refresh(); await old.signOut(); });
  expect(document.documentElement.dataset.rickHydrated).toBeUndefined(); expect(api.logout).not.toHaveBeenCalled();
  await expect(old.signIn(login)).rejects.toMatchObject({ code: "session_busy" });
});
