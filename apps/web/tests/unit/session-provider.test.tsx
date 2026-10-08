// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "../../lib/api";
import { SessionProvider, useSession } from "../../components/session-provider";
import type { Session } from "../../types/api";
let current: ReturnType<typeof useSession>;
let root: Root;
let container: HTMLDivElement;
const identity = (id: string) => ({ authenticated: true, user_id: id, workspace_id: id, session_id: id, permissions: ["cases.read"] }) as Session;
const login = { email: "a@example.invalid", password: "synthetic", tenant_id: "t" };
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (cause: unknown) => void; const promise = new Promise<T>((a,b) => {resolve=a;reject=b;}); return { promise, resolve, reject }; }
function Consumer() { current = useSession(); return <div>{current.ready ? "ready" : "loading"}:{current.session?.user_id || "anonymous"}:{current.errorKind}:{current.error}</div>; }
beforeEach(() => {
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
  expect(current.session).toBeNull(); expect(current.errorKind).toBe("validation"); expect(current.ready).toBe(true);
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
it("discards pending reads after unmount", async () => {
  const pending = deferred<Session>(); vi.mocked(api.me).mockReturnValueOnce(pending.promise); await render();
  const old = current; await act(async () => root.unmount());
  await act(async () => { pending.resolve(identity("late")); await old.refresh(); await old.signOut(); });
  expect(document.documentElement.dataset.rickHydrated).toBeUndefined(); expect(api.logout).not.toHaveBeenCalled();
  await expect(old.signIn(login)).rejects.toMatchObject({ code: "session_busy" });
});
