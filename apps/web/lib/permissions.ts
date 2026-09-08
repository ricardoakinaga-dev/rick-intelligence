import type { Session } from "@/types/api";

/** Presentation only: the API remains the authorization boundary. */
export function hasPermission(session: Session | null | undefined, permission: string): boolean {
  const grants = session?.permissions;
  return Array.isArray(grants) && (grants.includes("*") || grants.includes(permission));
}

export function hasAdminReadAccess(session: Session | null | undefined): boolean {
  return hasPermission(session, "audit.read") || hasPermission(session, "observability.read");
}
