import { afterEach, describe, expect, it, vi } from "vitest";
import { api, parseChatResponse, ApiError } from "../../lib/api";

const frame = (value: unknown) => `data: ${typeof value === "string" ? value : JSON.stringify(value)}\n\n`;
const completion = { type: "completion", conversation_id: "c", message_id: "m", answer: "accepted" };
function stream(chunks: string[], close = true) {
  const cancel = vi.fn();
  const body = new ReadableStream<Uint8Array>({
    start(controller) { for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk)); if (close) controller.close(); },
    cancel,
  });
  return { body, cancel, response: new Response(body, { headers: { "content-type": "text/event-stream" } }) };
}
afterEach(() => vi.unstubAllGlobals());

describe("chat response terminal protocol", () => {
  it("preserves the first completion and stops callbacks at the terminal event", async () => {
    const fixture = stream([frame(completion) + frame("[DONE]") + frame({ ...completion, answer: "injected" })], false);
    const onEvent = vi.fn();
    const result = await parseChatResponse(fixture.response, onEvent);
    expect(result.answer).toBe("accepted");
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(fixture.cancel).toHaveBeenCalledOnce();
    expect(fixture.body.locked).toBe(false);
  });
  it("rejects duplicate completion before DONE without publishing replacement", async () => {
    const fixture = stream([frame(completion) + frame({ ...completion, answer: "replacement" }) + frame("[DONE]")], false);
    await expect(parseChatResponse(fixture.response)).rejects.toMatchObject({ code: "invalid_response" });
    expect(fixture.cancel).toHaveBeenCalledOnce();
    expect(fixture.body.locked).toBe(false);
  });
  it.each(["generation_failed", "forbidden", "unauthorized"])("cancels and unlocks a %s stream", async code => {
    const fixture = stream([frame({ type: "error", code })], false);
    await expect(parseChatResponse(fixture.response)).rejects.toMatchObject({ code, status: code === "forbidden" ? 403 : code === "unauthorized" ? 401 : 0 });
    expect(fixture.cancel).toHaveBeenCalledOnce();
    expect(fixture.body.locked).toBe(false);
  });
  it.each(["data: invalid\n\n", frame({ type: "unknown" }), frame({ ...completion, provisional: true }), frame({ ...completion, citations: [{}] }), frame({ type: "delta", delta: 4 })])("cancels malformed frame %s", async raw => {
    const fixture = stream([raw], false);
    await expect(parseChatResponse(fixture.response)).rejects.toBeInstanceOf(ApiError);
    expect(fixture.cancel).toHaveBeenCalledOnce();
    expect(fixture.body.locked).toBe(false);
  });
  it("cancels if the event consumer throws and preserves the original failure", async () => {
    const fixture = stream([frame({ type: "start" })], false);
    const failure = new Error("consumer");
    await expect(parseChatResponse(fixture.response, () => { throw failure; })).rejects.toBe(failure);
    expect(fixture.cancel).toHaveBeenCalledOnce();
  });
  it("aborts a pending read through the public chatStream API", async () => {
    const fixture = stream([], false);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fixture.response));
    const controller = new AbortController();
    const result = api.chatStream({ message: "question", workspace_id: "w" }, controller.signal);
    await new Promise(resolve => setTimeout(resolve, 0));
    controller.abort();
    await expect(result).rejects.toMatchObject({ name: "AbortError" });
    expect(fixture.cancel).toHaveBeenCalledOnce();
    expect(fixture.body.locked).toBe(false);
  });
  it("accepts split UTF-8, CRLF and multi-line data frames", async () => {
    const raw = ': heartbeat\r\nevent: message\r\ndata: {"type":"completion",\r\ndata: "conversation_id":"c","message_id":"m","answer":"ação"}\r\n\r\ndata: [DONE]\r\n\r\n';
    const bytes = new TextEncoder().encode(raw);
    const body = new ReadableStream<Uint8Array>({ start(c) { for (const byte of bytes) c.enqueue(new Uint8Array([byte])); c.close(); } });
    expect((await parseChatResponse(new Response(body, { headers: { "content-type": "text/event-stream" } }))).answer).toBe("ação");
  });
  it.each(["", frame("[DONE]"), frame(completion), frame({ type: "delta", delta: "draft" })])("rejects incomplete EOF %s", async raw => {
    const fixture = stream([raw]);
    await expect(parseChatResponse(fixture.response)).rejects.toMatchObject({ code: "incomplete_response" });
    expect(fixture.body.locked).toBe(false);
  });
  it("validates JSON and emits a single non-provisional completion", async () => {
    const onEvent = vi.fn();
    expect((await parseChatResponse(new Response(JSON.stringify(completion)), onEvent)).answer).toBe("accepted");
    expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ type: "completion", provisional: false }));
    for (const value of [null, [], { ...completion, answer: 7 }, { ...completion, metadata: [] }, { ...completion, citations: [{ document_id: "d", page_start: 1.5 }] }]) {
      await expect(parseChatResponse(new Response(JSON.stringify(value)))).rejects.toMatchObject({ code: "invalid_response" });
    }
  });
});

it("cancels a pre-aborted stream and releases its lock", async () => {
  const fixture = stream([], false); const controller = new AbortController(); controller.abort();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fixture.response));
  await expect(api.chatStream({ message: "q" }, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
  expect(fixture.cancel).toHaveBeenCalledOnce(); expect(fixture.body.locked).toBe(false);
});
it("deduplicates provisional citations and accepts a final frame without a newline", async () => {
  const citation = { document_id: "d", chunk_id: "k" };
  const fixture = stream([frame({ type: "start", conversation_id: "c", message_id: "m" }) + frame({ type: "delta", delta: "draft" }) + frame({ type: "citation", citation }) + frame({ type: "citation", citation }) + frame({ type: "completion", metadata: { source: "fixture" } }) + "data: [DONE]"]);
  const result = await parseChatResponse(fixture.response);
  expect(result).toMatchObject({ answer: "draft", citations: [citation], metadata: { source: "fixture" } });
});
it("ignores every frame after DONE and cancels an open producer immediately", async () => {
  const fixture = stream([frame(completion) + frame("[DONE]") + "data: malformed\n\n" + frame({ type: "error", code: "forbidden" })], false);
  expect((await parseChatResponse(fixture.response)).answer).toBe("accepted"); expect(fixture.cancel).toHaveBeenCalledOnce();
});
it("preserves processing failure when stream cancellation itself rejects", async () => {
  const failure = new Error("consumer failure");
  const body = new ReadableStream<Uint8Array>({ start(c) { c.enqueue(new TextEncoder().encode(frame({ type: "start" }))); }, cancel() { throw new Error("cancel failed"); } });
  await expect(parseChatResponse(new Response(body, { headers: { "content-type": "text/event-stream" } }), () => { throw failure; })).rejects.toBe(failure);
  expect(body.locked).toBe(false);
});
it("rejects a missing body or invalid JSON", async () => {
  await expect(parseChatResponse(new Response(null, { headers: { "content-type": "text/event-stream" } }))).rejects.toMatchObject({ code: "incomplete_response" });
  await expect(parseChatResponse(new Response("not JSON"))).rejects.toMatchObject({ code: "invalid_response" });
});
