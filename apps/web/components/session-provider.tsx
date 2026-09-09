"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "@/lib/api";
import type { Session } from "@/types/api";

type SessionContextValue = {
  session: Session | null;
  ready: boolean;
  error: string | null;
  errorKind: "validation" | "mutation" | null;
  signIn: (body: { email: string; password: string; tenant_id: string }) => Promise<Session>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
};

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorKind, setErrorKind] = useState<"validation" | "mutation" | null>(null);
  const generation = useRef(0);
  const mounted = useRef(false);
  const mutation = useRef<{ kind: "login" | "logout"; settled: Promise<void> } | null>(null);
  const nextGeneration = useCallback(() => ++generation.current, []);
  const isCurrent = useCallback((operation: number) => mounted.current && generation.current === operation, []);

  const refresh = useCallback(async () => {
    // Reads during a cookie mutation cannot establish authoritative identity.
    if (!mounted.current || mutation.current) return;
    const operation = nextGeneration();
    try {
      const next = await api.me();
      if (!isCurrent(operation)) return;
      setSession(next);
      setError(null);
      setErrorKind(null);
    } catch (cause) {
      if (!isCurrent(operation)) return;
      setSession(null);
      const unauthenticated = cause instanceof ApiError && (cause.status === 401 || cause.status === 403);
      setError(unauthenticated ? null : cause instanceof ApiError ? cause.message : "Não foi possível validar a sessão.");
      setErrorKind(unauthenticated ? null : "validation");
    } finally {
      if (isCurrent(operation)) setReady(true);
    }
  }, [isCurrent, nextGeneration]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => {
      mounted.current = false;
      nextGeneration();
    };
  }, [nextGeneration, refresh]);

  const value = useMemo<SessionContextValue>(() => ({
    session,
    ready,
    error,
    errorKind,
    signIn: async (body) => {
      if (!mounted.current || mutation.current) {
        throw new ApiError("Uma operação de sessão já está em andamento.", 409, "session_busy");
      }
      const operation = nextGeneration();
      setError(null);
      setErrorKind(null);
      const pending = { kind: "login" as const, settled: Promise.resolve() };
      mutation.current = pending;
      const result = (async () => {
        try {
          const next = await api.login(body);
          // LoginPage navigates on resolution: discarded results must reject.
          if (!isCurrent(operation)) {
            throw new ApiError("A operação de sessão foi substituída.", 409, "session_superseded");
          }
          setSession(next);
          setError(null);
          setErrorKind(null);
          setReady(true);
          return next;
        } catch (cause) {
          if (isCurrent(operation)) {
            setSession(null);
            setError(cause instanceof ApiError ? cause.message : "Não foi possível abrir a sessão.");
            setErrorKind("mutation");
            setReady(true);
          }
          throw cause;
        } finally {
          if (mutation.current === pending) mutation.current = null;
        }
      })();
      pending.settled = result.then(() => {}, () => {});
      return result;
    },
    signOut: async () => {
      if (!mounted.current) return;
      if (mutation.current?.kind === "logout") return mutation.current.settled;
      const previous = mutation.current;
      const operation = nextGeneration();
      setSession(null);
      setError(null);
      setErrorKind(null);
      setReady(true);
      const pending = { kind: "logout" as const, settled: Promise.resolve() };
      mutation.current = pending;
      pending.settled = (async () => {
        try {
          // At most one login followed by one logout; never race cookie writes
          // or admit an unbounded queue of authentication mutations.
          if (previous) await previous.settled;
          await api.logout();
        } catch (cause) {
          // Local identity is cleared, but server logout failure is still a failure
          // for callers; the UI must catch and present it.
          if (isCurrent(operation)) {
            setError(cause instanceof ApiError ? cause.message : "Não foi possível encerrar a sessão no servidor.");
            setErrorKind("mutation");
          }
          throw cause;
        } finally {
          if (mutation.current === pending) mutation.current = null;
        }
      })();
      return pending.settled;
    },
    refresh,
  }), [error, errorKind, isCurrent, nextGeneration, ready, refresh, session]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside SessionProvider");
  return value;
}
