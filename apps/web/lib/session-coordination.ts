// Per-operation opaque markers avoid read/modify/write races between tabs.
// They contain no principal, credentials, scope, content or timestamps. There is
// no expiry: a producer that dies while writing cookies remains fail-closed.
export const SESSION_CHANGE_KEY = "rick-session-change";
export const SESSION_OPERATION_PREFIX = "rick-session-op:";
export function readSessionCoordination() {
  if (typeof window === "undefined") return { available: true, stable: true, pendingIds: [] as string[], stamp: null as string | null };
  try {
    const pendingIds: string[] = [];
    const before = localStorage.getItem(SESSION_CHANGE_KEY);
    const length = localStorage.length;
    let stable = true;
    for (let index = 0; index < length; index += 1) {
      const key = localStorage.key(index);
      if (key === null) stable = false;
      if (key?.startsWith(SESSION_OPERATION_PREFIX)) {
        // A deletion can shift enumeration indexes. An observed disappearing
        // key is not proof that every other producer has completed.
        if (localStorage.getItem(key) === null) stable = false;
        else pendingIds.push(key.slice(SESSION_OPERATION_PREFIX.length));
      }
    }
    const stamp = localStorage.getItem(SESSION_CHANGE_KEY);
    stable = stable && length === localStorage.length && before === stamp;
    return { available: true, stable, pendingIds, stamp };
  } catch {
    return { available: false, stable: false, pendingIds: [] as string[], stamp: null as string | null };
  }
}
export class SessionCoordination {
  private readonly owned = new Set<string>();
  private readonly legacyPending = new Set<string>();
  snapshot() {
    const result = readSessionCoordination();
    // v1 signals cannot reconstruct producers omitted from its last-value key.
    // Retain observed v1 pending tokens until their matching settlement; never
    // let an unrelated v1 settlement release a known producer.
    if (result.stamp?.startsWith("pending:") && !result.stamp.startsWith("pending:v2:")) this.legacyPending.add(result.stamp.slice("pending:".length));
    return { ...result, pending: !result.available || !result.stable || result.pendingIds.some(id => !this.owned.has(id)) || this.legacyPending.size > 0 };
  }
  observe(event: StorageEvent) {
    if (event.key === SESSION_CHANGE_KEY && event.newValue && !event.newValue.includes(":v2:")) {
      if (event.newValue.startsWith("pending:")) this.legacyPending.add(event.newValue.slice("pending:".length));
      if (event.newValue.startsWith("settled:")) this.legacyPending.delete(event.newValue.slice("settled:".length));
    }
    return this.snapshot();
  }
  begin() {
    const id = crypto.randomUUID();
    // Publish durable state before the notification, and before any HTTP cookie
    // mutation. A failed write prevents the caller from starting that mutation.
    try {
      localStorage.setItem(`${SESSION_OPERATION_PREFIX}${id}`, "pending");
      this.owned.add(id);
      this.announce(id);
      return id;
    } catch (cause) {
      // No HTTP mutation has started, so only this unpublished operation may
      // be rolled back. Failure to clean up remains an orphan (fail-closed).
      this.owned.delete(id);
      try { localStorage.removeItem(`${SESSION_OPERATION_PREFIX}${id}`); } catch { /* retain unknown marker */ }
      throw cause;
    }
  }
  announce(id: string) {
    if (this.owned.has(id)) localStorage.setItem(SESSION_CHANGE_KEY, `pending:v2:${id}`);
  }
  settle(id: string) {
    if (!this.owned.has(id)) return;
    // Each writer removes only its own key. Other producers survive settlement,
    // delayed notification delivery, and a fresh observer's bootstrap.
    localStorage.removeItem(`${SESSION_OPERATION_PREFIX}${id}`);
    this.owned.delete(id);
    localStorage.setItem(SESSION_CHANGE_KEY, `settled:v2:${id}`);
  }
}
