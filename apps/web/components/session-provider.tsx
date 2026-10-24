"use client";

import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "@/lib/api";
import type { Session } from "@/types/api";
import { suspendClientAuthority, resumeClientAuthority } from "@/lib/client-authority";
import { sessionScopeKey } from "@/lib/session-scope";
import { SESSION_CHANGE_KEY, SESSION_OPERATION_PREFIX, SessionCoordination } from "@/lib/session-coordination";

type SessionContextValue = {
  session: Session | null;
  ready: boolean;
  waitingForRemoteMutation: boolean;
  error: string | null;
  errorKind: "validation" | "mutation" | null;
  signIn: (body: { email: string; password: string; tenant_id: string; workspace_id?: string }) => Promise<Session>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
};
const SessionContext = createContext<SessionContextValue | null>(null);
const remoteMessage = "Uma operação de sessão está em andamento em outra aba. Conclua-a nessa aba antes de continuar.";
const coordinationMessage = "Não foi possível coordenar a sessão entre abas. As operações permanecem bloqueadas; confirme o resultado antes de repetir uma alteração.";
const superseded = () => new ApiError("A operação de sessão foi substituída. Confirme a sessão atual antes de continuar.", 409, "session_superseded");

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [waitingForRemoteMutation, setWaitingForRemoteMutation] = useState(false);
  const [authorityRevision, setAuthorityRevision] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [errorKind, setErrorKind] = useState<"validation" | "mutation" | null>(null);
  const generation = useRef(0);
  const mounted = useRef(false);
  const coordination = useRef(new SessionCoordination());
  const validatedStamp = useRef<string | null>(null);
  const mutation = useRef<{ kind: "login" | "logout"; settled: Promise<void> } | null>(null);
  const nextGeneration = useCallback(() => ++generation.current, []);
  const isCurrent = useCallback((operation: number) => mounted.current && generation.current === operation, []);

  const synchronize = useCallback((event?: StorageEvent) => {
    const state = event ? coordination.current.observe(event) : coordination.current.snapshot();
    if (!mounted.current) return state;
    setWaitingForRemoteMutation(state.available && state.pending);
    if (state.pending) {
      nextGeneration();
      suspendClientAuthority();
      setReady(false);
      setError(state.available ? remoteMessage : coordinationMessage);
      setErrorKind("validation");
    }
    return state;
  }, [nextGeneration]);

  const refresh = useCallback(async () => {
    if (!mounted.current || mutation.current) return;
    const start = synchronize();
    if (start.pending) return;
    const operation = nextGeneration();
    suspendClientAuthority();
    setReady(false);
    try {
      const next = await api.me();
      const current = synchronize();
      if (!isCurrent(operation)) return;
      // A completed producer can also change cookies before its storage event
      // is delivered. A read across that fence cannot establish authority.
      if (current.stamp !== start.stamp) {
        setError("A sessão mudou durante a validação. Valide novamente antes de continuar.");
        setErrorKind("validation");
        return;
      }
      validatedStamp.current = current.stamp;
      setSession(previous => sessionScopeKey(previous) === sessionScopeKey(next) ? previous : next);
      setReady(true);
      setAuthorityRevision(value => value + 1);
      setError(null);
      setErrorKind(null);
    } catch (cause) {
      if (!isCurrent(operation)) return;
      const unauthenticated = cause instanceof ApiError && (cause.status === 401 || cause.status === 403);
      if (unauthenticated) setSession(null);
      setReady(unauthenticated);
      setError(unauthenticated ? null : cause instanceof ApiError ? cause.message : "Não foi possível validar a sessão.");
      setErrorKind(unauthenticated ? null : "validation");
    }
  }, [isCurrent, nextGeneration, synchronize]);

  useEffect(() => {
    mounted.current = true;
    document.documentElement.dataset.rickHydrated = "true";
    suspendClientAuthority();
    void refresh();
    const invalidate = () => {
      nextGeneration();
      suspendClientAuthority();
      setReady(false);
      if (synchronize().pending) return;
      if (mutation.current) void mutation.current.settled.then(() => refresh());
      else void refresh();
    };
    const storage = (event: StorageEvent) => {
      if (event.key !== null && event.key !== SESSION_CHANGE_KEY && !event.key.startsWith(SESSION_OPERATION_PREFIX)) return;
      if (!synchronize(event).pending) invalidate();
    };
    const visibility = () => {
      if (document.visibilityState === "visible") invalidate();
      else { nextGeneration(); suspendClientAuthority(); setReady(false); }
    };
    window.addEventListener("storage", storage);
    window.addEventListener("focus", invalidate);
    window.addEventListener("rick-session-invalid", invalidate);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      window.removeEventListener("storage", storage);
      window.removeEventListener("focus", invalidate);
      window.removeEventListener("rick-session-invalid", invalidate);
      document.removeEventListener("visibilitychange", visibility);
      mounted.current = false;
      delete document.documentElement.dataset.rickHydrated;
      nextGeneration();
      suspendClientAuthority();
    };
  }, [nextGeneration, refresh, synchronize]);

  useLayoutEffect(() => {
    if (!ready || !session) return;
    const current = synchronize();
    if (current.pending) return;
    if (current.stamp !== validatedStamp.current) {
      nextGeneration(); suspendClientAuthority(); setReady(false);
      setError("A sessão mudou. Valide novamente antes de continuar."); setErrorKind("validation");
      return;
    }
    resumeClientAuthority(validatedStamp.current);
  }, [authorityRevision, nextGeneration, ready, session, synchronize]);

  const value = useMemo<SessionContextValue>(() => ({
    session, ready, waitingForRemoteMutation, error, errorKind,
    signIn: async (body) => {
      if (!mounted.current || mutation.current || synchronize().pending) throw new ApiError("Uma operação de sessão já está em andamento.", 409, "session_busy");
      const operation = nextGeneration();
      suspendClientAuthority(); setSession(null); setReady(false); setError(null); setErrorKind(null);
      let token: string;
      try { token = coordination.current.begin(); }
      catch { synchronize(); setReady(false); setError(coordinationMessage); setErrorKind("validation"); throw new ApiError(coordinationMessage, 503, "session_coordination_unavailable"); }
      const pending = { kind: "login" as const, settled: Promise.resolve() };
      mutation.current = pending;
      let accepted = false;
      const result = (async () => {
        try {
          const next = await api.login(body);
          const current = synchronize();
          if (!isCurrent(operation) || current.pending || current.stamp !== `pending:v2:${token}`) throw superseded();
          setSession(next); setError(null); setErrorKind(null); setReady(true);
          setAuthorityRevision(value => value + 1);
          accepted = true;
          return next;
        } catch (cause) {
          if (isCurrent(operation)) {
            setSession(null); setError(cause instanceof ApiError ? cause.message : "Não foi possível abrir a sessão."); setErrorKind("mutation"); setReady(true);
          }
          throw cause;
        } finally {
          if (mutation.current === pending) mutation.current = null;
          try { coordination.current.settle(token); }
          catch { synchronize(); if (accepted) throw new ApiError(coordinationMessage, 503, "session_coordination_unavailable"); }
          const current = synchronize();
          if (accepted) {
            if (!isCurrent(operation) || current.pending || current.stamp !== `settled:v2:${token}`) throw superseded();
            validatedStamp.current = current.stamp;
          }
        }
      })();
      pending.settled = result.then(() => {}, () => {});
      return result;
    },
    signOut: async () => {
      if (!mounted.current) return;
      if (mutation.current?.kind === "logout") return mutation.current.settled;
      if (synchronize().pending) {
        // Hide this tab immediately, but never race another producer's cookie
        // write or report logout complete while that producer is outstanding.
        setSession(null);
        throw new ApiError(remoteMessage, 409, "session_busy");
      }
      const previous = mutation.current;
      const operation = nextGeneration();
      suspendClientAuthority(); setSession(null); setError(null); setErrorKind(null); setReady(true);
      let token: string;
      try { token = coordination.current.begin(); }
      catch { synchronize(); setReady(false); setError(coordinationMessage); setErrorKind("validation"); throw new ApiError(coordinationMessage, 503, "session_coordination_unavailable"); }
      const pending = { kind: "logout" as const, settled: Promise.resolve() };
      mutation.current = pending;
      let completed = false;
      pending.settled = (async () => {
        try {
          if (previous) await previous.settled;
          if (synchronize().pending) throw new ApiError(remoteMessage, 409, "session_busy");
          coordination.current.announce(token);
          await api.logout();
          const current = synchronize();
          if (current.pending || current.stamp !== `pending:v2:${token}`) throw superseded();
          completed = true;
        } catch (cause) {
          if (isCurrent(operation)) {
            setError(cause instanceof ApiError ? cause.message : "Não foi possível encerrar a sessão no servidor."); setErrorKind("mutation");
          }
          throw cause;
        } finally {
          if (mutation.current === pending) mutation.current = null;
          try { coordination.current.settle(token); }
          catch { synchronize(); if (completed) throw new ApiError(coordinationMessage, 503, "session_coordination_unavailable"); }
          synchronize();
        }
      })();
      return pending.settled;
    },
    refresh,
  }), [error, errorKind, isCurrent, nextGeneration, ready, refresh, session, synchronize, waitingForRemoteMutation]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside SessionProvider");
  return value;
}
