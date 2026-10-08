import type { Session } from "@/types/api";

/** A change of client authority discards all state owned by the old session. */
export function sessionScopeKey(session: Session | null | undefined): string {
  if (!session?.authenticated) return "anonymous";
  return JSON.stringify([
    session.session_id, session.user_id, session.tenant_id, session.workspace_id,
    session.role, session.canonical_role, [...(session.permissions || [])].sort(),
  ]);
}
