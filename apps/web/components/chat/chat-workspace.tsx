"use client";

import {
  Archive,
  Bot,
  ChevronDown,
  CircleAlert,
  Copy,
  FileText,
  History,
  MessageCircle,
  PanelLeft,
  Plus,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Square,
  UserRound,
  WifiOff,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { useSession } from "@/components/session-provider";
import { Button, Spinner, StatusPill } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useOnlineStatus } from "@/lib/network";
import {
  chatAdapter,
  type ChatCitation,
  type ChatHistoryEntry,
  type ChatStreamEvent,
  type ConversationSummary,
} from "./chat-adapter";
import styles from "./chat-workspace.module.css";

type MessageStatus = "sending" | "sent" | "failed" | "cancelled";

type WorkspaceMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: ChatCitation[];
  metadata?: Record<string, unknown>;
  createdAt?: number | string | null;
  status?: MessageStatus;
};

type PendingAssistant = {
  id: string;
  answer: string;
  citations: ChatCitation[];
  state?: "streaming" | "interrupted";
};

type NormalizedError = {
  status: number;
  code: string;
  message: string;
};

type RequestState =
  | { kind: "idle" }
  | {
      kind: "loading";
      question: string;
      userMessageId: string;
      idempotencyKey: string;
      conversationId: string | null;
    }
  | ({ kind: "error" } | { kind: "cancelled" }) & {
      question: string;
      userMessageId: string;
      idempotencyKey: string;
      conversationId: string | null;
      error?: NormalizedError;
    };

type SidebarState = "loading" | "ready" | "error" | "forbidden";
type ConversationState = "ready" | "loading" | "error" | "forbidden";
type FocusIntent = "composer" | "conversation" | "conversation-error" | "request-error" | null;

const EMPTY_REQUEST: RequestState = { kind: "idle" };

function makeClientId(prefix: string) {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function readConversationIdFromUrl() {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("conversation");
}

function updateConversationUrl(conversationId: string | null) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (conversationId) url.searchParams.set("conversation", conversationId);
  else url.searchParams.delete("conversation");
  window.history.pushState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

function timestamp(value: number | string | null | undefined) {
  if (value == null || value === "") return 0;
  const numeric = typeof value === "number" ? value : Number(value);
  if (Number.isFinite(numeric)) return numeric < 10_000_000_000 ? numeric * 1000 : numeric;
  const parsed = Date.parse(String(value));
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatTime(value: number | string | null | undefined) {
  const time = timestamp(value);
  if (!time) return "Agora";
  return new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" }).format(time);
}

function formatDate(value: number | string | null | undefined) {
  const time = timestamp(value);
  if (!time) return "Agora";
  return new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short" }).format(time).replace(" de ", " ");
}

function shortTitle(value: string) {
  const clean = value.trim().replace(/\s+/g, " ");
  return clean.length > 58 ? `${clean.slice(0, 57).trimEnd()}…` : clean || "Nova conversa";
}

function placeholderConversation(conversationId: string, workspaceId: string): ConversationSummary {
  const now = Date.now();
  return {
    conversation_id: conversationId,
    title: "Abrindo conversa…",
    workspace_id: workspaceId,
    collection_id: null,
    status: "active",
    created_at: now,
    updated_at: now,
    message_count: 0,
  };
}

function normalizeError(cause: unknown): NormalizedError {
  if (cause instanceof ApiError) {
    if (cause.code === "network_unavailable") {
      return { status: cause.status, code: cause.code, message: "A conexão com a API foi perdida. Verifique sua rede e tente novamente." };
    }
    if (cause.code === "incomplete_response") {
      return { status: cause.status, code: cause.code, message: "A resposta foi interrompida antes da conclusão. Tente novamente para consultar as fontes outra vez." };
    }
    return { status: cause.status, code: cause.code, message: cause.message };
  }
  if (cause instanceof Error && cause.name === "AbortError") {
    return { status: 0, code: "cancelled", message: "Consulta cancelada." };
  }
  return { status: 0, code: "request_failed", message: "Não foi possível concluir a consulta." };
}

function isAbortError(cause: unknown) {
  return cause instanceof Error && cause.name === "AbortError";
}

function citationKey(citation: ChatCitation) {
  return `${citation.document_id || ""}:${citation.chunk_id || ""}`;
}

function appendCitation(current: ChatCitation[], citation: ChatCitation | null | undefined) {
  if (!citation || current.some((item) => citationKey(item) === citationKey(citation))) return current;
  return [...current, citation];
}

function sourceHeadingId(messageId: string) {
  return `${messageId.replace(/[^a-zA-Z0-9_-]/g, "-")}-sources`;
}

function focusAnchor(event: ReactMouseEvent<HTMLAnchorElement>, targetId: string) {
  event.preventDefault();
  const target = document.getElementById(targetId);
  if (!target) return;
  target.focus({ preventScroll: true });
  target.scrollIntoView({ block: "start" });
}

function evidenceState(message: WorkspaceMessage) {
  const state = typeof message.metadata?.evidence_status === "string" ? message.metadata.evidence_status : "";
  if (state === "APPROVED_EVIDENCE" && message.citations.length) {
    return { tone: "success" as const, label: "Com evidência", description: `${message.citations.length} ${message.citations.length === 1 ? "fonte retornada" : "fontes retornadas"}. Confira o conteúdo antes de usar a resposta.` };
  }
  if (state === "RETRIEVAL_FAILED") {
    return { tone: "danger" as const, label: "Busca de fontes indisponível", description: "A resposta não deve ser usada até que a busca autorizada seja restabelecida." };
  }
  if (state === "NO_EVIDENCE" || !message.citations.length) {
    return { tone: "warning" as const, label: "Sem evidência", description: "Não há fundamentação suficiente. Confira as fontes e reformule a pergunta." };
  }
  return { tone: "warning" as const, label: "Evidência fraca", description: "Confira as fontes e reformule a pergunta antes de usar a resposta." };
}

function pageLabel(citation: ChatCitation) {
  if (citation.page_start != null && citation.page_end != null && citation.page_end !== citation.page_start) {
    return `Páginas ${citation.page_start}–${citation.page_end}`;
  }
  if (citation.page_start != null) return `Página ${citation.page_start}`;
  return "Página não informada";
}

function toMessages(entries: ChatHistoryEntry[]): WorkspaceMessage[] {
  return entries
    .map((entry, index) => ({ entry, index }))
    .sort((left, right) => timestamp(left.entry.created_at) - timestamp(right.entry.created_at) || left.index - right.index)
    .flatMap(({ entry }) => [
      {
        id: `${entry.message_id}-question`,
        role: "user" as const,
        content: entry.question,
        citations: [],
        createdAt: entry.created_at,
        status: "sent" as const,
      },
      {
        id: entry.message_id,
        role: "assistant" as const,
        content: entry.answer,
        citations: entry.citations || [],
        metadata: entry.metadata,
        createdAt: entry.created_at,
        status: "sent" as const,
      },
    ])
    .filter((message) => message.content || message.role === "assistant");
}

function CitationList({ citations, messageId }: { citations: ChatCitation[]; messageId: string }) {
  const headingId = sourceHeadingId(messageId);
  return (
    <section className={`${styles.sources} evidence-stack`} aria-labelledby={headingId}>
      <div className={`${styles.sourcesHeading} source-heading`}>
        <h3 id={headingId} tabIndex={-1}><FileText size={15} aria-hidden="true" />Fontes associadas</h3>
        <span>{citations.length}</span>
      </div>
      {citations.length ? (
        <div className={styles.citationList}>
          {citations.map((citation, index) => (
            <details className={`${styles.citation} source-details`} key={`${messageId}-${citationKey(citation)}-${index}`}>
              <summary>
                <span className={styles.citationNumber} aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                <span className={styles.citationSummary}>
                  <strong>{citation.title || citation.document_id || "Documento sem título"}</strong>
                  <small>{pageLabel(citation)} · fonte autorizada</small>
                </span>
                <ChevronDown size={17} aria-hidden="true" />
              </summary>
              <dl>
                <div><dt>Documento</dt><dd>{citation.document_id || "Não informado"}</dd></div>
                <div><dt>Coleção</dt><dd>{citation.collection_id || "Não informado"}</dd></div>
                <div><dt>Trecho</dt><dd>{citation.chunk_id || "Não informado"}</dd></div>
                <div><dt>Página inicial</dt><dd>{citation.page_start ?? "Não informado"}</dd></div>
                <div><dt>Página final</dt><dd>{citation.page_end ?? "Não informado"}</dd></div>
                <div><dt>Código de integridade</dt><dd>{citation.checksum || "Não informado"}</dd></div>
              </dl>
            </details>
          ))}
        </div>
      ) : (
        <p className={styles.noCitations}><strong>Nenhuma fonte retornada</strong><span>Trate esta resposta como não fundamentada e refine a pergunta ou o corpus.</span></p>
      )}
      {citations.length ? <a className="source-return" href="#chat-title" onClick={(event) => focusAnchor(event, "chat-title")}>Voltar ao início da resposta</a> : null}
    </section>
  );
}

function MessageBubble({ message, onCopy }: { message: WorkspaceMessage; onCopy: (content: string) => void }) {
  const assistant = message.role === "assistant";
  const sourcesId = sourceHeadingId(message.id);
  return (
    <article className={`${styles.message} ${assistant ? styles.assistantMessage : styles.userMessage}`} aria-label={assistant ? "Resposta do corpus" : "Consulta enviada"}>
      <div className={styles.messageHeader}>
        <span className={styles.messageAuthor}>
          <span className={`${styles.messageAvatar} ${assistant ? styles.assistantAvatar : styles.userAvatar}`} aria-hidden="true">
            {assistant ? <Bot size={15} /> : <UserRound size={15} />}
          </span>
          <strong>{assistant ? "RICK" : "Você"}</strong>
        </span>
        <time dateTime={message.createdAt ? new Date(timestamp(message.createdAt)).toISOString() : undefined}>{formatTime(message.createdAt)}</time>
      </div>
      {assistant && message.citations.length ? <a className="source-jump" href={`#${sourcesId}`} onClick={(event) => focusAnchor(event, sourcesId)}>Consultar fontes ({message.citations.length})</a> : null}
      <div className={`${styles.messageContent}${assistant ? " answer-text" : ""}`} role={assistant ? "status" : undefined} aria-live={assistant ? "polite" : undefined}>{message.content || "A resposta não trouxe texto."}</div>
      {!assistant && message.status && message.status !== "sent" ? (
        <p className={`${styles.messageStatus} ${message.status === "failed" ? styles.failedStatus : ""}`}>
          {message.status === "sending" ? "Enviando consulta…" : message.status === "cancelled" ? "Consulta cancelada." : "Consulta não concluída."}
        </p>
      ) : null}
      {assistant ? (
        <>
          <div className={styles.messageActions}>
            <Button type="button" variant="ghost" className={styles.copyButton} onClick={() => onCopy(message.content)} aria-label="Copiar">
              <Copy size={14} />Copiar
            </Button>
          </div>
          <CitationList citations={message.citations} messageId={message.id} />
          {(() => {
            const trust = evidenceState(message);
            return (
              <div className={`answer-confidence ${trust.tone === "success" ? "verified" : "unverified"}`} role="status">
                <ShieldCheck size={16} aria-hidden="true" />
                <span><strong>{trust.label}</strong><small>{trust.description}</small></span>
              </div>
            );
          })()}
        </>
      ) : null}
    </article>
  );
}

export function ChatWorkspace() {
  const { session } = useSession();
  const online = useOnlineStatus();
  const workspaceId = session?.workspace_id || "default";
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [sidebarState, setSidebarState] = useState<SidebarState>("loading");
  const [sidebarError, setSidebarError] = useState<NormalizedError | null>(null);
  const [conversationFilter, setConversationFilter] = useState("");
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeSummary, setActiveSummary] = useState<ConversationSummary | null>(null);
  const [messages, setMessages] = useState<WorkspaceMessage[]>([]);
  const [conversationState, setConversationState] = useState<ConversationState>("ready");
  const [conversationError, setConversationError] = useState<NormalizedError | null>(null);
  const [draft, setDraft] = useState("");
  const [request, setRequest] = useState<RequestState>(EMPTY_REQUEST);
  const [pendingAssistant, setPendingAssistant] = useState<PendingAssistant | null>(null);
  const [copyNotice, setCopyNotice] = useState<string | null>(null);
  const [focusIntent, setFocusIntent] = useState<FocusIntent>(null);

  const listAbortRef = useRef<AbortController | null>(null);
  const detailAbortRef = useRef<AbortController | null>(null);
  const sendAbortRef = useRef<AbortController | null>(null);
  const conversationOperation = useRef(0);
  const sendOperation = useRef(0);
  const activeIdRef = useRef<string | null>(null);
  const conversationsRef = useRef<ConversationSummary[]>([]);
  const requestRef = useRef<RequestState>(EMPTY_REQUEST);
  const messageListRef = useRef<HTMLDivElement>(null);
  const mainHeadingRef = useRef<HTMLHeadingElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const conversationErrorRef = useRef<HTMLHeadingElement>(null);
  const requestErrorRef = useRef<HTMLHeadingElement>(null);
  const mobileToolbarRef = useRef<HTMLButtonElement>(null);
  const mobileCloseRef = useRef<HTMLButtonElement>(null);
  const wasMobileSidebarOpen = useRef(false);

  useEffect(() => {
    activeIdRef.current = activeId;
  }, [activeId]);

  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  useEffect(() => {
    requestRef.current = request;
  }, [request]);

  const filteredConversations = useMemo(() => {
    const query = conversationFilter.trim().toLocaleLowerCase("pt-BR");
    if (!query) return conversations;
    return conversations.filter((conversation) => conversation.title.toLocaleLowerCase("pt-BR").includes(query));
  }, [conversationFilter, conversations]);

  const startNewConversation = useCallback(() => {
    if (requestRef.current.kind === "loading") return;
    conversationOperation.current += 1;
    detailAbortRef.current?.abort();
    setActiveId(null);
    activeIdRef.current = null;
    setActiveSummary(null);
    setMessages([]);
    setConversationState("ready");
    setConversationError(null);
    requestRef.current = EMPTY_REQUEST;
    setRequest(EMPTY_REQUEST);
    setPendingAssistant(null);
    setDraft("");
    setCopyNotice(null);
    setMobileSidebarOpen(false);
    updateConversationUrl(null);
    setFocusIntent("composer");
  }, []);

  const openConversation = useCallback(async (summaryOrId: ConversationSummary | string, updateUrl = true) => {
    if (requestRef.current.kind === "loading") return;
    const summary = typeof summaryOrId === "string"
      ? conversationsRef.current.find((conversation) => conversation.conversation_id === summaryOrId) || placeholderConversation(summaryOrId, workspaceId)
      : summaryOrId;
    const conversationId = summary.conversation_id;
    const operation = ++conversationOperation.current;
    detailAbortRef.current?.abort();
    const controller = new AbortController();
    detailAbortRef.current = controller;
    setMobileSidebarOpen(false);
    setActiveId(conversationId);
    activeIdRef.current = conversationId;
    setActiveSummary(summary);
    setMessages([]);
    setConversationState("loading");
    setConversationError(null);
    setPendingAssistant(null);
    setCopyNotice(null);
    requestRef.current = EMPTY_REQUEST;
    setRequest(EMPTY_REQUEST);
    if (updateUrl) updateConversationUrl(conversationId);

    try {
      const detail = await chatAdapter.getConversation(conversationId, controller.signal);
      if (operation !== conversationOperation.current) return;
      setActiveSummary(detail.conversation);
      setMessages(toMessages(detail.items || []));
      setConversationState("ready");
      setFocusIntent("conversation");
    } catch (cause) {
      if (operation !== conversationOperation.current || isAbortError(cause)) return;
      const error = normalizeError(cause);
      setConversationError(error);
      setConversationState(error.status === 403 ? "forbidden" : "error");
      setFocusIntent("conversation-error");
    } finally {
      if (operation === conversationOperation.current) detailAbortRef.current = null;
    }
  }, [workspaceId]);

  const loadConversations = useCallback(async () => {
    listAbortRef.current?.abort();
    const controller = new AbortController();
    listAbortRef.current = controller;
    setSidebarState("loading");
    setSidebarError(null);
    try {
      const result = await chatAdapter.listConversations(controller.signal);
      if (controller.signal.aborted) return;
      const items = Array.isArray(result.items) ? result.items : [];
      setConversations(items);
      setSidebarState("ready");
      const urlConversationId = readConversationIdFromUrl();
      const nextId = urlConversationId || (!activeIdRef.current ? items[0]?.conversation_id : null);
      if (nextId && nextId !== activeIdRef.current) {
        const nextSummary = items.find((conversation) => conversation.conversation_id === nextId) || nextId;
        void openConversation(nextSummary, false);
      }
    } catch (cause) {
      if (controller.signal.aborted) return;
      const error = normalizeError(cause);
      setSidebarError(error);
      setSidebarState(error.status === 403 ? "forbidden" : "error");
    } finally {
      if (listAbortRef.current === controller) listAbortRef.current = null;
    }
  }, [openConversation]);

  useEffect(() => {
    if (!session) return;
    void loadConversations();
    return () => {
      listAbortRef.current?.abort();
      detailAbortRef.current?.abort();
      sendAbortRef.current?.abort();
      conversationOperation.current += 1;
      sendOperation.current += 1;
    };
  }, [loadConversations, session, workspaceId]);

  useEffect(() => {
    const onPopState = () => {
      if (requestRef.current.kind === "loading") return;
      const nextId = readConversationIdFromUrl();
      if (nextId) void openConversation(nextId, false);
      else startNewConversation();
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [openConversation, startNewConversation]);

  useLayoutEffect(() => {
    const wasOpen = wasMobileSidebarOpen.current;
    if (mobileSidebarOpen) mobileCloseRef.current?.focus({ preventScroll: true });
    else if (wasOpen) mobileToolbarRef.current?.focus({ preventScroll: true });
    wasMobileSidebarOpen.current = mobileSidebarOpen;
  }, [mobileSidebarOpen]);

  const handleMobileSidebarKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (!mobileSidebarOpen) return;
    if (event.key === "Escape") {
      event.preventDefault();
      setMobileSidebarOpen(false);
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("button:not(:disabled):not([tabindex='-1']), a[href], input:not(:disabled):not([tabindex='-1']), select:not(:disabled):not([tabindex='-1']), textarea:not(:disabled):not([tabindex='-1'])"));
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  useEffect(() => {
    const list = messageListRef.current;
    if (!list) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) list.scrollTop = list.scrollHeight;
    else list.scrollTo({ top: list.scrollHeight, behavior: "smooth" });
  }, [messages.length, pendingAssistant?.answer, request.kind, conversationState]);

  useLayoutEffect(() => {
    if (!focusIntent) return;
    const target = focusIntent === "composer"
      ? composerRef.current
      : focusIntent === "conversation"
        ? mainHeadingRef.current
        : focusIntent === "conversation-error"
          ? conversationErrorRef.current
          : requestErrorRef.current;
    if (target) {
      target.focus({ preventScroll: true });
      if (focusIntent !== "composer") target.scrollIntoView({ block: "nearest" });
      setFocusIntent(null);
    }
  }, [conversationError, conversationState, focusIntent, messages.length, request.kind]);

  const sendMessage = useCallback(async (question: string, options?: { retry?: boolean }) => {
    const trimmed = question.trim();
    if (!session || !trimmed || requestRef.current.kind === "loading") return;
    if (!online) {
      setDraft(trimmed);
      setFocusIntent("composer");
      return;
    }
    const previous = options?.retry && (requestRef.current.kind === "error" || requestRef.current.kind === "cancelled")
      ? requestRef.current
      : null;
    const userMessageId = previous?.userMessageId || makeClientId("user");
    const idempotencyKey = previous?.idempotencyKey || makeClientId("turn");
    const conversationId = previous?.conversationId || activeIdRef.current;
    const nextRequest: RequestState = {
      kind: "loading",
      question: trimmed,
      userMessageId,
      idempotencyKey,
      conversationId,
    };
    if (previous) {
      setMessages((current) => current.map((message) => message.id === userMessageId ? { ...message, status: "sending" } : message));
    } else {
      setMessages((current) => [...current, {
        id: userMessageId,
        role: "user",
        content: trimmed,
        citations: [],
        createdAt: Date.now(),
        status: "sending",
      }]);
    }
    setDraft("");
    setCopyNotice(null);
    const pendingAssistantId = makeClientId("assistant");
    let streamedAnswer = "";
    let streamedCitations: ChatCitation[] = [];
    setPendingAssistant({ id: pendingAssistantId, answer: "", citations: [], state: "streaming" });
    requestRef.current = nextRequest;
    setRequest(nextRequest);
    const operation = ++sendOperation.current;
    sendAbortRef.current?.abort();
    const controller = new AbortController();
    sendAbortRef.current = controller;

    const onEvent = (event: ChatStreamEvent) => {
      if (operation !== sendOperation.current) return;
      if (event.type === "delta" && event.delta) {
        streamedAnswer += event.delta;
        setPendingAssistant((current) => current ? { ...current, answer: streamedAnswer } : current);
      }
      if (event.type === "citation") {
        streamedCitations = appendCitation(streamedCitations, event.citation);
        setPendingAssistant((current) => current ? { ...current, citations: streamedCitations } : current);
      }
      if (event.type === "completion") {
        streamedAnswer = event.answer ?? streamedAnswer;
        streamedCitations = (event.citations || []).reduce(appendCitation, streamedCitations);
        setPendingAssistant((current) => current ? { ...current, answer: streamedAnswer, citations: streamedCitations } : current);
      }
    };

    try {
      const result = await chatAdapter.sendChat({
        message: trimmed,
        workspaceId,
        conversationId,
        collectionId: activeSummary?.collection_id,
        idempotencyKey,
      }, controller.signal, onEvent);
      if (operation !== sendOperation.current) return;
      const summary: ConversationSummary = {
        conversation_id: result.conversation_id,
        title: activeSummary?.title && activeSummary.title !== "Abrindo conversa…" ? activeSummary.title : shortTitle(trimmed),
        workspace_id: workspaceId,
        collection_id: activeSummary?.collection_id || null,
        status: "active",
        created_at: activeSummary?.created_at || Date.now(),
        updated_at: Date.now(),
        message_count: (activeSummary?.message_count || 0) + 2,
      };
      const assistantMessage: WorkspaceMessage = {
        id: result.message_id,
        role: "assistant",
        content: result.answer,
        citations: result.citations || [],
        metadata: result.metadata,
        createdAt: Date.now(),
        status: "sent",
      };
      setMessages((current) => [
        ...current.map((message) => message.id === userMessageId ? { ...message, status: "sent" as const } : message),
        assistantMessage,
      ]);
      setActiveId(result.conversation_id);
      activeIdRef.current = result.conversation_id;
      setActiveSummary(summary);
      setConversations((current) => [summary, ...current.filter((item) => item.conversation_id !== summary.conversation_id)]);
      setConversationState("ready");
      setConversationError(null);
      setPendingAssistant(null);
      requestRef.current = EMPTY_REQUEST;
      setRequest(EMPTY_REQUEST);
      updateConversationUrl(result.conversation_id);
      setFocusIntent("composer");
    } catch (cause) {
      if (operation !== sendOperation.current) return;
      setPendingAssistant(null);
      if (isAbortError(cause)) {
        const cancelled: RequestState = { ...nextRequest, kind: "cancelled" };
        setMessages((current) => current.map((message) => message.id === userMessageId ? { ...message, status: "cancelled" as const } : message));
        requestRef.current = cancelled;
        setRequest(cancelled);
        setDraft(trimmed);
        setFocusIntent("composer");
      } else {
        const error = normalizeError(cause);
        const hasPartialResponse = Boolean(streamedAnswer.trim() || streamedCitations.length);
        setPendingAssistant(hasPartialResponse ? { id: pendingAssistantId, answer: streamedAnswer, citations: streamedCitations, state: "interrupted" } : null);
        const failed: RequestState = { ...nextRequest, kind: "error", error };
        setMessages((current) => current.map((message) => message.id === userMessageId ? { ...message, status: "failed" as const } : message));
        requestRef.current = failed;
        setRequest(failed);
        setDraft(trimmed);
        setFocusIntent("request-error");
      }
    } finally {
      if (operation === sendOperation.current) sendAbortRef.current = null;
    }
  }, [activeSummary, online, session, workspaceId]);

  const cancelRequest = useCallback((event: ReactMouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (requestRef.current.kind === "loading") sendAbortRef.current?.abort();
  }, []);

  const retryRequest = useCallback(() => {
    const current = requestRef.current;
    if (current.kind === "error" || current.kind === "cancelled") void sendMessage(current.question, { retry: true });
  }, [sendMessage]);

  const copyAnswer = useCallback(async (content: string) => {
    try {
      if (!navigator.clipboard) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(content);
      setCopyNotice("Resposta copiada.");
    } catch {
      setCopyNotice("Não foi possível copiar a resposta.");
    }
  }, []);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void sendMessage(draft);
  };

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void sendMessage(draft);
  };

  const choosePrompt = (prompt: string) => {
    setDraft(prompt);
    setFocusIntent("composer");
  };

  const inputDisabled = request.kind === "loading" || conversationState !== "ready" || activeSummary?.status === "archived";
  const hasHistory = conversations.length > 0;
  const requestError = request.kind === "error" ? request.error : null;
  const requestIsForbidden = Boolean(requestError?.status === 403);
  const requestIsOffline = requestError?.code === "network_unavailable";
  const requestIsInterrupted = requestError?.code === "incomplete_response";
  const isArchived = activeSummary?.status === "archived";
  const pendingIsInterrupted = pendingAssistant?.state === "interrupted";
  const submitDisabled = inputDisabled || !draft.trim() || !online;

  return (
    <div className={styles.root}>
      <div className={styles.pageHeading}>
        <div>
          <span className="eyebrow">Workspace conversacional · {workspaceId}</span>
          <h1>Converse com o corpus.</h1>
          <p>Investigue casos com respostas rastreáveis, mantendo cada pergunta e fonte no seu espaço de trabalho.</p>
        </div>
        <StatusPill tone="success"><ShieldCheck size={13} />Corpus autorizado</StatusPill>
      </div>

      <div className={styles.mobileToolbar}>
        <Button ref={mobileToolbarRef} type="button" variant="secondary" onClick={() => setMobileSidebarOpen(true)} aria-expanded={mobileSidebarOpen} aria-controls="conversation-sidebar">
          <PanelLeft size={16} />Conversas<span className={styles.toolbarCount}>{conversations.length}</span>
        </Button>
        <span className={styles.mobileActiveTitle}>{activeSummary?.title || "Nova conversa"}</span>
      </div>

      <div className={styles.shell}>
        <aside id="conversation-sidebar" onKeyDown={handleMobileSidebarKeyDown} className={`${styles.sidebar} ${mobileSidebarOpen ? styles.sidebarOpen : ""}`} aria-label="Conversas" data-open={mobileSidebarOpen}>
          <div className={styles.sidebarHeader}>
            <div><span className="eyebrow">Navegar</span><h2 id="conversation-sidebar-title">Conversas</h2></div>
            <Button ref={mobileCloseRef} type="button" variant="ghost" className={styles.mobileClose} onClick={() => setMobileSidebarOpen(false)} aria-label="Fechar conversas"><X size={18} /></Button>
          </div>
          <Button type="button" className={styles.newConversation} onClick={startNewConversation} disabled={request.kind === "loading"}><Plus size={16} />Nova conversa</Button>
          <label className={styles.filterField}>
            <Search size={15} aria-hidden="true" />
            <span className="sr-only">Filtrar conversas</span>
            <input value={conversationFilter} onChange={(event) => setConversationFilter(event.target.value)} placeholder="Filtrar conversas" />
          </label>
          <div className={styles.sidebarList} aria-busy={sidebarState === "loading"}>
            {sidebarState === "loading" ? (
              <div className={styles.sidebarLoading}><Spinner label="Carregando conversas" /><span>Buscando seu histórico…</span></div>
            ) : sidebarState === "forbidden" ? (
              <div className={styles.sidebarState} role="status">
                <CircleAlert size={18} />
                <strong>Histórico indisponível</strong>
                <p>Sua sessão pode consultar o corpus, mas não pode listar conversas.</p>
                <Button type="button" variant="secondary" onClick={() => void loadConversations()}>Tentar novamente</Button>
              </div>
            ) : sidebarState === "error" ? (
              <div className={styles.sidebarState} role="alert">
                <CircleAlert size={18} />
                <strong>Não foi possível carregar</strong>
                <p>{sidebarError?.message || "O histórico não respondeu."}</p>
                <Button type="button" variant="secondary" onClick={() => void loadConversations()}>Tentar novamente</Button>
              </div>
            ) : filteredConversations.length ? (
              <nav className={styles.conversationNav} aria-label="Seu histórico">
                <span className={styles.listLabel}>{conversationFilter ? "Resultados" : "Recentes"}</span>
                {filteredConversations.map((conversation) => {
                  const active = conversation.conversation_id === activeId;
                  const archived = conversation.status === "archived";
                  return (
                    <button
                      key={conversation.conversation_id}
                      type="button"
                      className={`${styles.conversationItem} ${active ? styles.activeConversation : ""}`}
                      aria-current={active ? "page" : undefined}
                      aria-label={`${conversation.title}${archived ? ", arquivada" : ""}`}
                      onClick={() => void openConversation(conversation)}
                      disabled={request.kind === "loading"}
                    >
                      <span className={styles.conversationIcon}>{archived ? <Archive size={15} /> : <MessageCircle size={15} />}</span>
                      <span className={styles.conversationCopy}><strong>{conversation.title}</strong><small>{Math.max(0, conversation.message_count || 0)} mensagens · {formatDate(conversation.updated_at)}</small></span>
                      {archived ? <span className={styles.archivedLabel}>Arquivada</span> : null}
                    </button>
                  );
                })}
              </nav>
            ) : hasHistory && conversationFilter ? (
              <div className={styles.emptyHistory}><Search size={18} /><strong>Nenhuma conversa encontrada</strong><p>Ajuste o termo para encontrar uma conversa do seu histórico.</p></div>
            ) : (
              <div className={styles.emptyHistory}><History size={18} /><strong>Seu histórico começa aqui</strong><p>As consultas que você enviar aparecerão neste espaço.</p></div>
            )}
          </div>
          <div className={styles.sidebarFoot}><ShieldCheck size={15} /><span>Histórico privado do workspace<strong>{workspaceId}</strong></span></div>
        </aside>
        {mobileSidebarOpen ? <button type="button" className={styles.mobileBackdrop} aria-label="Fechar conversas" onClick={() => setMobileSidebarOpen(false)} /> : null}

        <section className={`${styles.chatPanel} answer-panel`} aria-labelledby="chat-title">
          <header className={styles.chatHeader}>
            <div className={styles.chatHeaderTitle}>
              <span className="eyebrow">Conversa ativa</span>
              <h2 id="chat-title" ref={mainHeadingRef} tabIndex={-1}>Leitura do resultado</h2>
              <p>{activeSummary?.title || "Nova conversa"}</p>
            </div>
            <div className={styles.chatHeaderMeta}>
              {activeSummary ? <span className={styles.conversationId}>ID · {activeSummary.conversation_id}</span> : null}
              <StatusPill tone={isArchived ? "warning" : "accent"}>{isArchived ? "Arquivada" : "Modo fundamentado"}</StatusPill>
            </div>
          </header>

          <div ref={messageListRef} className={styles.messageList} role="log" aria-label="Mensagens da conversa" aria-busy={conversationState === "loading" || request.kind === "loading"}>
            {conversationState === "loading" ? (
              <div className={styles.stateCard} role="status"><Spinner label="Abrindo conversa" /><h3>Abrindo conversa…</h3><p>Recuperando o contexto autorizado.</p></div>
            ) : conversationState === "forbidden" ? (
              <div className={styles.stateCard}>
                <span className={styles.stateIcon}><ShieldCheck size={20} /></span>
                <h3 ref={conversationErrorRef} tabIndex={-1}>Acesso restrito ao histórico</h3>
                <p>{conversationError?.message || "Sua sessão não pode abrir esta conversa."}</p>
                <div className={styles.stateActions}><Button type="button" variant="secondary" onClick={() => activeId && void openConversation(activeId, false)}>Tentar novamente</Button><Button type="button" variant="ghost" onClick={startNewConversation}>Nova conversa</Button></div>
              </div>
            ) : conversationState === "error" ? (
              <div className={styles.stateCard} role="alert">
                <span className={`${styles.stateIcon} ${styles.dangerIcon}`}><CircleAlert size={20} /></span>
                <h3 ref={conversationErrorRef} tabIndex={-1}>Não foi possível abrir a conversa</h3>
                <p>{conversationError?.message || "O histórico não respondeu."}</p>
                <div className={styles.stateActions}><Button type="button" variant="secondary" onClick={() => activeId && void openConversation(activeId, false)}>Tentar novamente</Button><Button type="button" variant="ghost" onClick={startNewConversation}>Nova conversa</Button></div>
              </div>
            ) : messages.length || pendingAssistant ? (
              <div className={styles.messageStack}>
                {messages.map((message) => <MessageBubble key={message.id} message={message} onCopy={(content) => void copyAnswer(content)} />)}
                {pendingAssistant ? (
                  <article className={`${styles.message} ${styles.assistantMessage} ${styles.streamingMessage} ${pendingIsInterrupted ? styles.interruptedMessage : ""}`} aria-label={pendingIsInterrupted ? "Resposta interrompida" : "Resposta provisória em andamento"} aria-live={pendingIsInterrupted ? undefined : "polite"}>
                    <div className={styles.messageHeader}><span className={styles.messageAuthor}><span className={`${styles.messageAvatar} ${styles.assistantAvatar}`} aria-hidden="true"><Bot size={15} /></span><strong>RICK</strong></span><span className={pendingIsInterrupted ? styles.interruptedLabel : styles.streamingLabel}>{pendingIsInterrupted ? "Resposta interrompida · não finalizada" : `Resposta provisória · ${pendingAssistant.answer ? "validando fontes…" : "consultando fontes…"}`}</span></div>
                    <div className={styles.messageContent}>{pendingAssistant.answer || <span className={styles.typingDots} aria-label="Gerando resposta"><i /><i /><i /></span>}</div>
                    {pendingAssistant.citations.length ? <CitationList citations={pendingAssistant.citations} messageId={pendingAssistant.id} /> : null}
                    {pendingIsInterrupted ? <p className={styles.interruptedNote} role="status">Este conteúdo parcial não foi marcado como resposta concluída nem deve ser usado sem uma nova consulta.</p> : null}
                  </article>
                ) : null}
                {request.kind === "error" ? (
                  <div className={`${styles.requestNotice} ${requestIsForbidden ? styles.forbiddenNotice : ""}`} role="alert">
                    <div className={styles.requestNoticeIcon}>{requestIsForbidden ? <ShieldCheck size={18} /> : <CircleAlert size={18} />}</div>
                    <div><h3 ref={requestErrorRef} tabIndex={-1}>{requestIsForbidden ? "Acesso negado à consulta" : requestIsOffline ? "Sem conexão para concluir a consulta" : requestIsInterrupted ? "Resposta interrompida" : "Não foi possível concluir a consulta"}</h3><p>{requestError?.message || "Tente novamente mantendo a pergunta para o corpus."}</p></div>
                    <div className={styles.requestActions}><Button type="button" variant="secondary" onClick={retryRequest}>Tentar novamente</Button><Button type="button" variant="ghost" onClick={startNewConversation}>Nova conversa</Button></div>
                  </div>
                ) : request.kind === "cancelled" ? (
                  <div className={styles.requestNotice} role="status">
                    <div className={styles.requestNoticeIcon}><CircleAlert size={18} /></div>
                    <div><h3>Consulta cancelada</h3><p>A pergunta ficou no campo de edição para você ajustar ou enviar novamente.</p></div>
                    <div className={styles.requestActions}><Button type="button" variant="secondary" onClick={retryRequest}>Tentar novamente</Button></div>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className={styles.welcomeState}>
                <span className={styles.welcomeIcon}><Sparkles size={22} /></span>
                <span className="eyebrow">Pronto para investigar</span>
                <h3>Qual caso você quer entender?</h3>
                <p>Faça uma pergunta objetiva. A resposta e os identificadores das fontes ficam juntos para facilitar a revisão.</p>
                <div className={styles.promptGrid} aria-label="Sugestões de consulta">
                  <button type="button" onClick={() => choosePrompt("Quais fontes sustentam esta hipótese?")}><span>01</span>Quais fontes sustentam esta hipótese?</button>
                  <button type="button" onClick={() => choosePrompt("Resuma o protocolo de vacinação deste caso.")}><span>02</span>Resuma o protocolo de vacinação deste caso.</button>
                  <button type="button" onClick={() => choosePrompt("Compare os sinais clínicos descritos nas fontes autorizadas.")}><span>03</span>Compare os sinais clínicos descritos nas fontes autorizadas.</button>
                </div>
              </div>
            )}
          </div>

          <div className={styles.composerArea}>
            {isArchived ? <div className={styles.archivedNotice} role="status"><Archive size={15} />Esta conversa está arquivada e não aceita novas perguntas.</div> : null}
            {!online ? <div className={styles.composerOffline} role="alert" aria-live="assertive"><WifiOff size={15} aria-hidden="true" /><span><strong>Consulta pausada sem conexão.</strong> A pergunta continua editável; você poderá enviá-la quando a rede voltar.</span></div> : null}
            <form className={styles.composer} onSubmit={submit} aria-label="Enviar consulta">
              <label htmlFor="chat-message">Pergunta</label>
              <div className={`${styles.composerBox} ${request.kind === "loading" ? styles.composerBusy : ""}`}>
                <textarea
                  ref={composerRef}
                  id="chat-message"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={handleComposerKeyDown}
                  placeholder="Ex.: Quais documentos sustentam o protocolo de higiene?"
                  rows={3}
                  maxLength={20_000}
                  disabled={inputDisabled}
                  aria-describedby="chat-composer-help chat-character-count"
                />
                <div className={styles.composerFooter}>
                  <span id="chat-composer-help">Enter envia · Shift + Enter cria uma nova linha</span>
                  <span id="chat-character-count" className={styles.characterCount}>{draft.length.toLocaleString("pt-BR")} / 20.000</span>
                  {request.kind === "loading" ? (
                    <Button type="button" variant="danger" onClick={cancelRequest}><Square size={14} fill="currentColor" />Cancelar</Button>
                  ) : (
                    <Button type="submit" disabled={submitDisabled}><Send size={15} />Consultar</Button>
                  )}
                </div>
              </div>
            </form>
            <div className={styles.composerNote}><ShieldCheck size={14} /><span>As fontes são filtradas pelas permissões da sessão. Revise a evidência antes de decidir.</span></div>
            <div className="sr-only" role="status" aria-live="polite">{request.kind === "loading" ? "Consultando fontes autorizadas." : copyNotice || ""}</div>
          </div>
        </section>
      </div>
    </div>
  );
}
