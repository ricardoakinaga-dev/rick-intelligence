import type { ChatCitation, ChatResponse, ChatStreamEvent as WireChatStreamEvent } from "@/types/api";
import { ApiError } from "./api-error";

export type ChatStreamEvent = WireChatStreamEvent & { metadata?: Record<string, unknown> };

function invalidChatResponse(): ApiError {
  return new ApiError("A API retornou uma resposta inválida.", 0, "invalid_response");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function parseChatMetadata(value: unknown): Record<string, unknown> {
  if (value === undefined) return {};
  if (!isRecord(value)) throw invalidChatResponse();
  return value;
}

function parseChatCitations(value: unknown): ChatCitation[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || !value.every((item: unknown) => {
    if (!isRecord(item) || typeof item.document_id !== "string") return false;
    return ["chunk_id", "title", "collection_id", "checksum"].every((key) =>
      item[key] == null || typeof item[key] === "string",
    ) && ["page_start", "page_end"].every((key) =>
      item[key] == null || (typeof item[key] === "number" && Number.isInteger(item[key])),
    );
  })) throw invalidChatResponse();
  return value as ChatCitation[];
}

export function parseChatResult(value: unknown): ChatResponse {
  if (!isRecord(value) || typeof value.conversation_id !== "string" ||
      typeof value.message_id !== "string" || typeof value.answer !== "string") {
    throw invalidChatResponse();
  }
  return {
    conversation_id: value.conversation_id,
    message_id: value.message_id,
    answer: value.answer,
    citations: parseChatCitations(value.citations),
    metadata: parseChatMetadata(value.metadata),
  };
}

function parseChatEvent(value: unknown): ChatStreamEvent {
  if (!isRecord(value) || !["start", "delta", "citation", "completion", "error"].includes(String(value.type))) {
    throw invalidChatResponse();
  }
  for (const key of ["conversation_id", "message_id", "delta", "answer", "code", "message"]) {
    if (value[key] != null && typeof value[key] !== "string") throw invalidChatResponse();
  }
  if (value.provisional != null && typeof value.provisional !== "boolean") throw invalidChatResponse();
  if (value.citation != null) parseChatCitations([value.citation]);
  if (value.citations !== undefined) parseChatCitations(value.citations);
  return { ...value, metadata: parseChatMetadata(value.metadata) } as ChatStreamEvent;
}

export async function parseChatResponse(
  response: Response,
  onEvent?: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const checkAbort = () => {
    if (signal?.aborted) throw signal.reason ?? new DOMException("Aborted", "AbortError");
  };
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("text/event-stream")) {
    if (signal?.aborted) {
      await response.body?.cancel().catch(() => {});
      checkAbort();
    }
    let value: unknown;
    try { value = await response.json(); } catch { throw invalidChatResponse(); }
    checkAbort();
    const payload = parseChatResult(value);
    onEvent?.({ type: "completion", ...payload, provisional: false });
    return payload;
  }
  if (!response.body) throw new ApiError("A resposta foi interrompida antes da conclusão.", 0, "incomplete_response");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let dataLines: string[] = [];
  let conversationId = "";
  let messageId = "";
  let answer = "";
  let citations: ChatCitation[] = [];
  let completed: ChatResponse | null = null;
  let sawDone = false;
  let cancellation: Promise<void> | null = null;
  const cancel = () => {
    cancellation ??= reader.cancel().catch(() => {});
    return cancellation;
  };
  const onAbort = () => { void cancel(); };
  signal?.addEventListener("abort", onAbort, { once: true });

  const addCitation = (citation: ChatCitation | null | undefined) => {
    if (!citation) return;
    const key = `${citation.document_id || ""}:${citation.chunk_id || ""}`;
    if (!citations.some((item) => `${item.document_id || ""}:${item.chunk_id || ""}` === key)) citations = [...citations, citation];
  };
  const consume = (raw: string) => {
    checkAbort();
    if (sawDone) return;
    const data = raw.trim();
    if (!data) return;
    if (data === "[DONE]") {
      if (!completed) throw new ApiError("A resposta foi interrompida antes da conclusão.", 0, "incomplete_response");
      sawDone = true;
      return;
    }
    let value: unknown;
    try { value = JSON.parse(data); } catch { throw invalidChatResponse(); }
    const event = parseChatEvent(value);
    if (event.type === "error") {
      const status = event.code === "forbidden" ? 403 : event.code === "unauthorized" ? 401 : 0;
      throw new ApiError(event.message || "Não foi possível concluir a resposta.", status, event.code || "generation_failed");
    }
    // Completion freezes the payload. Only DONE may follow it; malformed
    // duplicate or provisional traffic cannot replace an accepted answer.
    if (completed) throw invalidChatResponse();
    if (event.conversation_id) conversationId = event.conversation_id;
    if (event.message_id) messageId = event.message_id;
    if (event.type === "delta" && event.delta) answer += event.delta;
    if (event.type === "citation") addCitation(event.citation);
    if (event.type === "completion") {
      if (event.provisional === true) throw invalidChatResponse();
      answer = event.answer ?? answer;
      citations = event.citations ?? citations;
      completed = parseChatResult({
        conversation_id: event.conversation_id || conversationId,
        message_id: event.message_id || messageId,
        answer,
        citations,
        metadata: event.metadata,
      });
    }
    onEvent?.(event);
  };

  try {
    checkAbort();
    while (true) {
      const { value, done } = await reader.read();
      checkAbort();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (line === "") { consume(dataLines.join("\n")); dataLines = []; }
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
        if (sawDone) break;
      }
      if (sawDone) break;
      if (done) {
        if (buffer.startsWith("data:")) dataLines.push(buffer.slice(5).trimStart());
        consume(dataLines.join("\n"));
        break;
      }
    }
    if (completed && sawDone) return completed;
    throw new ApiError("A resposta foi interrompida antes da conclusão.", 0, "incomplete_response");
  } finally {
    signal?.removeEventListener("abort", onAbort);
    // Also cancel a successfully terminated stream: its producer may keep the
    // connection open or queue extra frames. Cleanup must preserve the result
    // or original processing/consumer error even if cancellation rejects.
    await cancel();
    reader.releaseLock();
  }
}
