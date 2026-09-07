const RETURN_ROUTES = new Set([
  "/app",
  "/app/documents",
  "/app/search",
  "/app/chat",
  "/admin",
]);

/** Login accepts destinations, never executable or external router input. */
export function safeReturnPath(value: string | null): string {
  return value !== null && RETURN_ROUTES.has(value) ? value : "/app";
}
