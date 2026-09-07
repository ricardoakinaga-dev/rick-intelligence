import { ChevronDown, FileText } from "lucide-react";
import { EmptyState } from "@/components/ui";
import type { ChatResponse } from "@/types/api";

/** Inspect only metadata actually returned; a citation is not a verified URL. */
export function ChatSources({ citations }: Pick<ChatResponse, "citations">) {
  return <section className="evidence-stack" aria-labelledby="answer-sources">
    <h3 className="section-label source-heading" id="answer-sources" tabIndex={-1}><FileText size={15} aria-hidden="true" />Fontes associadas</h3>
    {citations.length ? citations.map((citation, index) => {
      const metadata: Array<[string, string | number | null | undefined]> = [
        ["Documento", citation.document_id],
        ["Coleção", citation.collection_id],
        ["Trecho", citation.chunk_id],
        ["Página inicial", citation.page_start],
        ["Página final", citation.page_end],
        ["Código de integridade", citation.checksum],
      ];
      const technicalLabels = new Set(["Documento", "Coleção", "Trecho", "Código de integridade"]);
      const pages = citation.page_start != null
        ? citation.page_end != null && citation.page_end !== citation.page_start
          ? `Páginas ${citation.page_start}–${citation.page_end}`
          : `Página ${citation.page_start}`
        : "Página inicial não informada";
      return <details className="citation-card source-details" key={`${index}:${citation.document_id || ""}:${citation.chunk_id || ""}`}>
        <summary>
          <span className="citation-number" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
          <span className="source-summary"><strong>{citation.title || citation.document_id || "Documento sem título"}</strong><small>{pages}</small><span className="source-disclosure">Detalhes da fonte {index + 1}</span></span>
          <ChevronDown size={18} aria-hidden="true" />
        </summary>
        <dl className="source-metadata">{metadata.map(([label, value]) => <div key={label}><dt>{label}</dt><dd className={technicalLabels.has(label) ? "technical-value" : undefined}>{value == null || value === "" ? "Não informado" : technicalLabels.has(label) ? <code>{value}</code> : value}</dd></div>)}</dl>
      </details>;
    }) : <EmptyState title="Nenhuma fonte retornada" description="Trate esta resposta como não fundamentada e refine a pergunta ou o corpus." />}
    {citations.length ? <a className="source-return" href="#answer-start">Voltar ao início da resposta</a> : null}
  </section>;
}
