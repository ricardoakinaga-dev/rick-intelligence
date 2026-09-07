"use client";

import { useState, type FormEvent } from "react";
import { Copy, Send, ShieldCheck } from "lucide-react";
import { ChatSources } from "@/components/chat-sources";
import { useSession } from "@/components/session-provider";
import { api, ApiError } from "@/lib/api";
import { Button, EmptyState, Panel, Spinner, StatusPill } from "@/components/ui";
import type { ChatResponse } from "@/types/api";

export default function ChatPage() {
  const { session } = useSession();
  const [message, setMessage] = useState("");
  const [response, setResponse] = useState<ChatResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null);

  async function requestAnswer() {
    if (busy || !message.trim() || !session) return;
    setBusy(true); setError(null); setResponse(null); setCopyFeedback(null);
    try {
      setResponse(await api.chat({ message: message.trim(), workspace_id: session.workspace_id }));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Não foi possível consultar o conhecimento.");
    } finally { setBusy(false); }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await requestAnswer();
  }

  async function copyAnswer() {
    if (!response) return;
    try {
      if (!navigator.clipboard) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(response.answer);
      setCopyFeedback("Resposta copiada.");
    } catch {
      setCopyFeedback("Não foi possível copiar a resposta.");
    }
  }

  function evidenceState(result: ChatResponse) {
    const state = typeof result.metadata?.evidence_status === "string" ? result.metadata.evidence_status : "";
    if (state === "APPROVED_EVIDENCE" && result.citations.length) return { tone: "success" as const, label: "Com evidência" };
    if (state === "RETRIEVAL_FAILED") return { tone: "danger" as const, label: "Busca de fontes indisponível" };
    if (state === "NO_EVIDENCE" || !result.citations.length) return { tone: "warning" as const, label: "Sem evidência" };
    return { tone: "warning" as const, label: "Evidência fraca" };
  }

  const trust = response ? evidenceState(response) : null;
  const confidenceLabel = response
    ? trust?.tone === "success"
      ? `${response.citations.length} ${response.citations.length === 1 ? "fonte retornada" : "fontes retornadas"}. Confira o conteúdo antes de usar a resposta.`
      : "Não há fundamentação suficiente. Confira as fontes e reformule a pergunta."
    : null;

  return <div className="page"><div className="page-heading"><div><span className="eyebrow">Perguntas · {session?.workspace_id}</span><h1>Converse com o corpus.</h1><p>Faça uma pergunta objetiva. Confira a resposta e os documentos citados antes de decidir.</p></div><StatusPill tone="accent"><ShieldCheck size={13} />Resposta e fontes</StatusPill></div><div className="chat-layout"><Panel className="composer-panel"><div className="panel-heading"><div><span className="eyebrow">Nova consulta</span><h2>O que você precisa saber?</h2></div><span className="panel-index">01</span></div><form onSubmit={submit} className="chat-form"><label htmlFor="chat-message">Pergunta</label><textarea id="chat-message" value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Ex.: Quais documentos sustentam o protocolo de higiene?" rows={4} maxLength={20000} /><div className="composer-footer"><span>{message.length.toLocaleString("pt-BR")} / 20.000 caracteres</span><Button type="submit" disabled={busy || !message.trim()}>{busy ? <><Spinner label="Gerando resposta" />Consultando…</> : <><Send size={16} />Consultar</>}</Button></div></form><div className="trust-note"><ShieldCheck size={16} /><span>A consulta usa as permissões da sua sessão.</span></div></Panel><Panel className={`answer-panel${error ? " answer-panel-error" : ""}`}><div className="panel-heading"><div><span className="eyebrow">Resposta</span><h2 id="answer-start" tabIndex={-1}>{response ? "Leitura do resultado" : "A resposta aparece aqui"}</h2></div>{response ? <div className="answer-actions"><Button variant="ghost" onClick={() => void copyAnswer()}><Copy size={15} />Copiar</Button>{copyFeedback ? <span className="sr-only" role="status">{copyFeedback}</span> : null}</div> : null}</div>{error ? <div className="form-alert chat-error" role="alert"><span>{error}</span><Button type="button" variant="secondary" onClick={() => void requestAnswer()} disabled={busy || !message.trim()}>Tentar novamente</Button></div> : null}{busy ? <div className="answer-loading" role="status" aria-live="polite"><Spinner label="Gerando resposta" /><p>Consultando fontes autorizadas e montando evidência.</p></div> : response ? <div className="answer-content">{response.citations.length ? <a className="source-jump" href="#answer-sources">Consultar fontes ({response.citations.length})</a> : null}<p className="answer-text" role="status" aria-live="polite">{response.answer}</p><ChatSources citations={response.citations} /><div className={`answer-confidence ${trust?.tone === "success" ? "verified" : "unverified"}`} role="status"><ShieldCheck size={16} /><span><strong>{trust?.label}</strong><small>{confidenceLabel}</small></span></div>{trust?.tone !== "success" ? <div className="form-feedback warning" role="alert"><ShieldCheck size={16} />Esta saída não deve virar decisão sem revisar o corpus e reformular a consulta.</div> : null}</div> : !error ? <EmptyState title="Nenhuma resposta ainda" description="Envie uma pergunta para consultar os documentos deste espaço." /> : null}</Panel></div></div>;
}
