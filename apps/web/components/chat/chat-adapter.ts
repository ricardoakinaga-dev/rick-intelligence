import { ApiError } from "@/lib/api";
import type { ChatResponse } from "@/types/api";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");

export type ChatCitation = ChatResponse["citations"][number];

export type ConversationSummary = {
  conversation_id: string;
  title: string;
  workspace_id: string;
  collection_id: string | null;
  status: "active" | "archived" | string;
  created_at: number | string;
  updated_at: number | string;
  message_count: number;
};

export type ChatHistoryEntry = {
  conversation_id: string;
  message_id: string;
  question: string;
  answer: string;
  citations: ChatCitation[];
  metadata?: Record<string, unknown>;
  created_at?: number | string | null;
};

export type ConversationListResponse = {
  items: ConversationSummary[];
  total: number;
  next_cursor?: string | null;
};

export type ConversationDetailResponse = {
  conversation: ConversationSummary;
  items: ChatHistoryEntry[];
  total: number;
  next_cursor?: string | null;
};

export type ChatStreamEvent =
  | { type: "start"; conversation_id?: string | null; message_id?: string | null; provisional?: boolean | null }
  | { type: "delta"; conversation_id?: string | null; message_id?: string | null; delta?: string | null; provisional?: boolean | null }
  | { type: "citation"; conversation_id?: string | null; message_id?: string | null; citation?: ChatCitation | null; provisional?: boolean | null }
  | { type: "completion"; conversation_id?: string | null; message_id?: string | null; answer?: string | null; citations?: ChatCitation[]; provisional?: boolean | null }
  | { type: "error"; code?: string | null; message?: string | null; provisional?: boolean | null };

export type ChatStreamInput = {
  message: string;
  workspaceId: string;
  conversationId?: string | null;
  collectionId?: string | null;
  idempotencyKey: string;
};

type ChatEventHandler = (event: ChatStreamEvent) => void;

async function fetchResponse(path: string, init: RequestInit, signal?: AbortSignal): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json, text/event-stream");
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      credentials: "include",
      signal,
    });
  } catch (cause) {
    if (cause instanceof Error && cause.name === "AbortError") throw cause;
    throw new ApiError("A API não está disponível neste momento.", 0, "network_unavailable");
  }

  if (!response.ok) {
    const payload = await readPayload(response);
    const error = payload && typeof payload === "object" && "error" in payload
      ? (payload as { error?: { message?: string; code?: string; request_id?: string } }).error
      : undefined;
    throw new ApiError(
      error?.message || "Não foi possível concluir a operação.",
      response.status,
      error?.code || "request_failed",
      error?.request_id || response.headers.get("x-request-id") || undefined,
    );
  }

  return response;
}

async function readPayload(response: Response): Promise<unknown> {
  const body = await response.text();
  if (!body) return null;
  try {
    return JSON.parse(body) as unknown;
  } catch {
    return null;
  }
}

async function requestJson<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const response = await fetchResponse(path, init, signal);
  const payload = await readPayload(response);
  if (payload === null) throw new ApiError("A API retornou uma resposta vazia.", 0, "invalid_response");
  return payload as T;
}

function streamError(event: Extract<ChatStreamEvent, { type: "error" }>): ApiError {
  const code = event.code || "generation_failed";
  const status = code === "forbidden" ? 403 : code === "unauthorized" ? 401 : 0;
  return new ApiError(event.message || "Não foi possível concluir a resposta.", status, code);
}

function isCitation(value: unknown): value is ChatCitation {
  return Boolean(value && typeof value === "object" && "document_id" in value);
}

function mergeCitations(current: ChatCitation[], next: ChatCitation | undefined): ChatCitation[] {
  if (!next) return current;
  const key = `${next.document_id || ""}:${next.chunk_id || ""}`;
  if (current.some((item) => `${item.document_id || ""}:${item.chunk_id || ""}` === key)) return current;
  return [...current, next];
}

async function readChatStream(response: Response, onEvent?: ChatEventHandler): Promise<ChatResponse> {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("text/event-stream") || !response.body) {
    const payload = await readPayload(response) as ChatResponse | null;
    if (!payload) throw new ApiError("A API retornou uma resposta inválida.", 0, "invalid_response");
    onEvent?.({
      type: "completion",
      conversation_id: payload.conversation_id,
      message_id: payload.message_id,
      answer: payload.answer,
      citations: payload.citations,
    });
    return payload;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let conversationId = "";
  let messageId = "";
  let answer = "";
  let citations: ChatCitation[] = [];
  let completed: ChatResponse | null = null;
  let sawDone = false;
  let dataLines: string[] = [];

  const consume = (rawData: string) => {
    const data = rawData.trim();
    if (!data) return;
    if (data === "[DONE]") {
      sawDone = true;
      return;
    }
    let event: ChatStreamEvent;
    try {
      event = JSON.parse(data) as ChatStreamEvent;
    } catch {
      return;
    }
    if (event.type === "error") throw streamError(event);
    if (event.conversation_id) conversationId = event.conversation_id;
    if (event.message_id) messageId = event.message_id;
    if (event.type === "delta" && event.delta) answer += event.delta;
    if (event.type === "citation" && isCitation(event.citation)) citations = mergeCitations(citations, event.citation);
    if (event.type === "completion") {
      answer = event.answer ?? answer;
      for (const citation of event.citations || []) citations = mergeCitations(citations, citation);
      completed = {
        conversation_id: event.conversation_id || conversationId,
        message_id: event.message_id || messageId,
        answer,
        citations,
        metadata: {},
      };
    }
    onEvent?.(event);
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (line === "") {
          consume(dataLines.join("\n"));
          dataLines = [];
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
      if (done) {
        if (buffer.startsWith("data:")) dataLines.push(buffer.slice(5).trimStart());
        consume(dataLines.join("\n"));
        break;
      }
    }
  } finally {
    reader.releaseLock();
  }

  if (completed && sawDone) return completed;
  throw new ApiError("A resposta foi interrompida antes da conclusão.", 0, "incomplete_response");
}

export const chatAdapter = {
  listConversations: (signal?: AbortSignal) =>
    requestJson<ConversationListResponse>("/api/v1/conversations?limit=50", {}, signal),

  getConversation: (conversationId: string, signal?: AbortSignal) =>
    requestJson<ConversationDetailResponse>(
      `/api/v1/conversations/${encodeURIComponent(conversationId)}?limit=100`,
      {},
      signal,
    ),

  sendChat: async (input: ChatStreamInput, signal?: AbortSignal, onEvent?: ChatEventHandler) => {
    const payload = {
      message: input.message,
      conversation_id: input.conversationId || undefined,
      collection_id: input.collectionId || undefined,
      workspace_id: input.workspaceId,
      mode: "grounded",
      stream: true,
      idempotency_key: input.idempotencyKey,
    };
    const response = await fetchResponse(
      "/api/v1/chat",
      { method: "POST", body: JSON.stringify(payload) },
      signal,
    );
    return readChatStream(response, onEvent);
  },
};
