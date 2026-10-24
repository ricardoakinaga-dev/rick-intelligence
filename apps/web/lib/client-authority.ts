import { ApiError } from "./api-error";
import { readSessionCoordination } from "./session-coordination";

// Browser-only admission/epoch barrier, not a session cache. No identity or
// credentials are held here; SSR never mutates this process-global module.
let blocked = false;
let epoch = 0;
let controller: AbortController | undefined;
let authorityStamp: string | null | undefined;
function suspensionError() {
  return new DOMException("A sessão está sendo revalidada. Se uma alteração já foi enviada, ela pode ter sido executada; confirme o resultado antes de repetir.", "AbortError");
}
export function suspendClientAuthority() {
  if (typeof window === "undefined") return;
  blocked = true;
  epoch += 1;
  controller?.abort(suspensionError());
  controller = new AbortController();
}
function detectedAuthorityChange() {
  suspendClientAuthority();
  window.dispatchEvent(new Event("rick-session-invalid"));
}
export function resumeClientAuthority(expectedStamp?: string | null) {
  if (typeof window === "undefined") return;
  const state = readSessionCoordination();
  if (!state.available || !state.stable || state.pendingIds.length || expectedStamp !== undefined && state.stamp !== expectedStamp) { detectedAuthorityChange(); return; }
  authorityStamp = state.stamp;
  blocked = false;
}
export function privateRequestLease(signal?: AbortSignal) {
  if (typeof window === "undefined") return { signal, current: () => true, assert: () => {} };
  const start = readSessionCoordination();
  if (!blocked && (!start.available || !start.stable || start.pendingIds.length || authorityStamp !== undefined && start.stamp !== authorityStamp)) detectedAuthorityChange();
  if (blocked) throw new ApiError("Valide a sessão antes de continuar.", 0, "session_validation_pending");
  controller ??= new AbortController();
  const operation = epoch;
  const combined = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
  const fenceValid = () => {
    const state = readSessionCoordination();
    return state.available && state.stable && !state.pendingIds.length && state.stamp === start.stamp;
  };
  const current = () => {
    if (!fenceValid() && !blocked) detectedAuthorityChange();
    return !blocked && epoch === operation && !combined.aborted;
  };
  return { signal: combined, current, assert: () => {
    if (!fenceValid() && !blocked) detectedAuthorityChange();
    if (blocked || epoch !== operation) throw suspensionError();
    if (combined.aborted) throw combined.reason ?? new DOMException("Operação cancelada.", "AbortError");
  } };
}
