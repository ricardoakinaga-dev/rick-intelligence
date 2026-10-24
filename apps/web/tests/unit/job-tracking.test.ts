import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { JOB_POLL_BUDGET_MS, observeJob } from "../../lib/job-tracking";
import type { JobEnvelope } from "../../types/api";

const job = (status: string, id = "j") => ({ job_id: id, job: { job_id: id, status } }) as JobEnvelope;
let controller: AbortController;
beforeEach(() => { vi.useFakeTimers(); controller = new AbortController(); });
afterEach(() => { controller.abort(); vi.useRealTimers(); });
function harness(initial: JobEnvelope | null = job("queued"), refreshImmediately = false) {
  const fetchJob = vi.fn().mockResolvedValue(job("queued"));
  const onUpdate = vi.fn();
  const result = observeJob({ jobId: "j", initial, signal: controller.signal, fetchJob, onUpdate, refreshImmediately });
  return { fetchJob, onUpdate, result };
}
it("ends at the wall-clock budget with bounded backoff and no leftover timers", async () => {
  const h = harness();
  await vi.advanceTimersByTimeAsync(120); expect(h.fetchJob).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(239); expect(h.fetchJob).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1); expect(h.fetchJob).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(JOB_POLL_BUDGET_MS - 360);
  expect(await h.result).toEqual({ last: job("queued"), reason: "budget" });
  expect(h.fetchJob).toHaveBeenCalledTimes(11);
  expect(vi.getTimerCount()).toBe(0);
});
it("enforces the budget even when a lookup ignores cancellation and never resolves", async () => {
  const h = harness(); h.fetchJob.mockReturnValue(new Promise(() => {}));
  await vi.advanceTimersByTimeAsync(JOB_POLL_BUDGET_MS);
  expect((await h.result).reason).toBe("budget");
  expect(h.fetchJob.mock.calls[0][1].aborted).toBe(true);
  expect(vi.getTimerCount()).toBe(0);
});
it("pauses pending lookup without accepting a late publication", async () => {
  let resolve!: (value: JobEnvelope) => void;
  const h = harness(); h.fetchJob.mockReturnValue(new Promise<JobEnvelope>(done => { resolve = done; }));
  await vi.advanceTimersByTimeAsync(120); controller.abort();
  expect((await h.result).reason).toBe("paused");
  resolve(job("published")); await Promise.resolve(); await Promise.resolve();
  expect(h.onUpdate).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});
it("pauses a sleep without starting a lookup", async () => {
  const h = harness(); controller.abort();
  expect((await h.result).reason).toBe("paused");
  expect(h.fetchJob).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
});
it("does not look up terminal initial state", async () => {
  const h = harness(job("published"));
  expect((await h.result).reason).toBe("terminal");
  expect(h.fetchJob).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
});
it("refreshes immediately on explicit resume and terminates on publication", async () => {
  const h = harness(null, true); h.fetchJob.mockResolvedValue(job("published"));
  expect(await h.result).toEqual({ last: job("published"), reason: "terminal" });
  expect(h.fetchJob).toHaveBeenCalledWith("j", expect.any(AbortSignal)); expect(vi.getTimerCount()).toBe(0);
});
it("preserves last-known state after a transient lookup failure", async () => {
  const h = harness(); h.fetchJob.mockRejectedValue(new Error("down"));
  await vi.advanceTimersByTimeAsync(120);
  expect(await h.result).toEqual({ last: job("queued"), reason: "unavailable" });
  expect(vi.getTimerCount()).toBe(0);
});
it("rejects a mismatched job rather than publishing its result", async () => {
  const h = harness(); h.fetchJob.mockResolvedValue(job("published", "other"));
  await vi.advanceTimersByTimeAsync(120);
  expect(await h.result).toEqual({ last: job("queued"), reason: "unavailable" });
  expect(h.onUpdate).toHaveBeenCalledTimes(1);
});
it("rejects inconsistent inner job identity rather than confirming the outer envelope", async () => {
  const h = harness();
  h.fetchJob.mockResolvedValue({ ...job("published"), job: { ...job("published").job, job_id: "other" } });
  await vi.advanceTimersByTimeAsync(120);
  expect(await h.result).toEqual({ last: job("queued"), reason: "unavailable" });
  expect(h.onUpdate).toHaveBeenCalledTimes(1);
});
it("rejects initial mismatched identity and does not call observers when already aborted", async () => {
  const mismatch = harness(job("published", "other"));
  expect(await mismatch.result).toEqual({ last: null, reason: "unavailable" });
  expect(mismatch.onUpdate).not.toHaveBeenCalled();
  controller.abort(); const stopped = harness();
  expect((await stopped.result).reason).toBe("paused");
  expect(stopped.onUpdate).not.toHaveBeenCalled(); expect(stopped.fetchJob).not.toHaveBeenCalled();
});
