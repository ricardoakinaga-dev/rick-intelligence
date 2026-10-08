import { api } from "@/lib/api";
import type { ChatStreamEvent } from "@/lib/api";

export type {
  ChatCitation,
  ChatHistoryEntry,
  ConversationSummary,
  ConversationListResponse,
  ConversationDetailResponse,
} from "@/types/api";
export type { ChatStreamEvent } from "@/lib/api";

export type ChatStreamInput = {
  message: string;
  workspaceId: string;
  conversationId?: string | null;
  collectionId?: string | null;
  idempotencyKey: string;
};

type ChatEventHandler = (event: ChatStreamEvent) => void;

export const chatAdapter = {
  listConversations: (signal?: AbortSignal) => api.listConversations(50, signal),

  getConversation: (conversationId: string, signal?: AbortSignal) =>
    api.getConversation(conversationId, 100, signal),

  sendChat: (input: ChatStreamInput, signal?: AbortSignal, onEvent?: ChatEventHandler) =>
    api.chatStream({
      message: input.message,
      conversation_id: input.conversationId || undefined,
      collection_id: input.collectionId || undefined,
      workspace_id: input.workspaceId,
      mode: "grounded",
      idempotency_key: input.idempotencyKey,
    }, signal, onEvent),
};
