import type { JobEnvelope } from "@/types/api";

export const JOB_POLL_BUDGET_MS = 9_600;
const TERMINAL = new Set(["published", "failed", "cancelled"]);

export type JobObservation = {
  last: JobEnvelope | null;
  reason: "terminal" | "budget" | "paused" | "unavailable";
};

function abortError() { return new DOMException("Job observation stopped", "AbortError"); }

function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(abortError()); return; }
    const stop = () => { clearTimeout(timer); reject(abortError()); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", stop); resolve(); }, ms);
    signal.addEventListener("abort", stop, { once: true });
  });
}

// Also bound callers whose transport ignores AbortSignal: late responses never
// regain authority, and the observation window still ends on time.
function lookup(jobId: string, fetchJob: (id: string, signal: AbortSignal) => Promise<JobEnvelope>, signal: AbortSignal): Promise<JobEnvelope> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(abortError()); return; }
    const stop = () => reject(abortError());
    signal.addEventListener("abort", stop, { once: true });
    Promise.resolve().then(() => {
      if (signal.aborted) throw abortError();
      return fetchJob(jobId, signal);
    }).then(resolve, reject).finally(() => signal.removeEventListener("abort", stop));
  });
}

/** A read-only, bounded observation of one server job. Never submits/retries it. */
export async function observeJob(options: {
  jobId: string;
  initial?: JobEnvelope | null;
  signal: AbortSignal;
  fetchJob: (id: string, signal: AbortSignal) => Promise<JobEnvelope>;
  onUpdate: (value: JobEnvelope) => void;
  refreshImmediately?: boolean;
}): Promise<JobObservation> {
  const controller = new AbortController();
  let expired = false;
  let last = options.initial ?? null;
  const stop = () => controller.abort();
  if (options.signal.aborted) stop();
  else options.signal.addEventListener("abort", stop, { once: true });
  const deadline = setTimeout(() => { expired = true; controller.abort(); }, JOB_POLL_BUDGET_MS);
  let wait = 120;
  try {
    if (controller.signal.aborted) return { last, reason: "paused" };
    if (last && (last.job_id !== options.jobId || last.job.job_id !== options.jobId)) return { last: null, reason: "unavailable" };
    if (last) options.onUpdate(last);
    let refresh = options.refreshImmediately || !last;
    while (refresh || (last && !TERMINAL.has(last.job.status))) {
      if (!refresh) await delay(wait, controller.signal);
      const next = await lookup(options.jobId, options.fetchJob, controller.signal);
      if (controller.signal.aborted) throw abortError();
      if (next.job_id !== options.jobId || next.job.job_id !== options.jobId) return { last, reason: "unavailable" };
      last = next;
      options.onUpdate(next);
      refresh = false;
      wait = Math.min(1_000, wait * 2);
    }
    return { last, reason: "terminal" };
  } catch {
    // Neither a lookup failure nor a bounded observation timeout is a failed
    // ingestion. Preserve its last known state for an explicit later lookup.
    return { last, reason: controller.signal.aborted ? (expired ? "budget" : "paused") : "unavailable" };
  } finally {
    clearTimeout(deadline);
    options.signal.removeEventListener("abort", stop);
  }
}
