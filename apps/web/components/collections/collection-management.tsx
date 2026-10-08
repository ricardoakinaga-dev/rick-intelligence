"use client";

import { Archive, Folder, FolderPlus, Pencil, Save, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api, errorMessage } from "@/lib/api";
import { Button, ConfirmDialog, Panel, Spinner, StatusPill } from "@/components/ui";
import type { CollectionItem } from "@/types/api";

type CollectionManagementProps = {
  collections: CollectionItem[];
  workspaceId: string;
  loadingCollections: boolean;
  collectionsError: string | null;
  showCollectionsError: boolean;
  onChanged: () => void | Promise<void>;
};

type FormState = {
  collection_id: string;
  title: string;
  description: string;
};

const EMPTY_FORM: FormState = { collection_id: "", title: "", description: "" };

export function CollectionManagement({ collections, workspaceId, loadingCollections, collectionsError, showCollectionsError, onChanged }: CollectionManagementProps) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<CollectionItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  function openCreate() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFormOpen(true);
    setError(null);
    setFeedback(null);
  }

  function openEdit(collection: CollectionItem) {
    setEditingId(collection.collection_id);
    setForm({
      collection_id: collection.collection_id,
      title: collection.title || "",
      description: collection.description || "",
    });
    setFormOpen(true);
    setError(null);
    setFeedback(null);
  }

  function closeForm() {
    if (busy) return;
    setFormOpen(false);
    setEditingId(null);
    setForm(EMPTY_FORM);
    setError(null);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    setFeedback(null);
    try {
      if (editingId) {
        await api.updateCollection(editingId, { title: form.title.trim(), description: form.description.trim() });
        setFeedback("Coleção atualizada e confirmada pelo servidor.");
      } else {
        await api.createCollection({
          collection_id: form.collection_id.trim(),
          title: form.title.trim(),
          description: form.description.trim(),
          workspace_id: workspaceId,
        });
        setFeedback("Coleção criada e disponível para o corpus.");
      }
      setFormOpen(false);
      setEditingId(null);
      setForm(EMPTY_FORM);
      await onChanged();
    } catch (cause) {
      setError(errorMessage(cause, "Não foi possível salvar a coleção."));
    } finally {
      setBusy(false);
    }
  }

  async function archive() {
    if (!archiveTarget || busy) return;
    setBusy(true);
    setError(null);
    setFeedback(null);
    try {
      await api.archiveCollection(archiveTarget.collection_id);
      setFeedback(`A coleção “${archiveTarget.title || archiveTarget.collection_id}” foi arquivada.`);
      setArchiveTarget(null);
      if (editingId === archiveTarget.collection_id) {
        setFormOpen(false);
        setEditingId(null);
        setForm(EMPTY_FORM);
      }
      await onChanged();
    } catch (cause) {
      setError(errorMessage(cause, "Não foi possível arquivar a coleção."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel className="collection-management-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Governança do corpus</span>
          <h2>Coleções autorizadas</h2>
        </div>
        <div className="collection-heading-actions">
          <span className="panel-index">{collections.length === 0 && (loadingCollections || collectionsError) ? "—" : collections.length}</span>
          <Button onClick={openCreate} disabled={busy} aria-expanded={formOpen}>
            <FolderPlus size={15} />Nova coleção
          </Button>
        </div>
      </div>
      <p className="collection-management-intro">Organize documentos por domínio e mantenha o escopo de consulta claro para cada equipe.</p>
      {collectionsError && showCollectionsError ? <div className="form-alert collection-load-error" role="alert"><span>{collectionsError}</span><Button variant="secondary" onClick={() => void onChanged()}>Tentar novamente</Button></div> : null}
      {error ? <div className="form-alert" role="alert">{error}</div> : null}
      {feedback ? <div className="form-feedback success" role="status">{feedback}</div> : null}

      {formOpen ? (
        <form className="collection-form" onSubmit={(event) => void submit(event)}>
          <div className="collection-form-heading">
            <div><span className="eyebrow">{editingId ? "Editar coleção" : "Nova coleção"}</span><strong>{editingId || "Defina um identificador estável"}</strong></div>
            <Button type="button" variant="ghost" onClick={closeForm} disabled={busy} aria-label="Cancelar edição"><X size={15} />Cancelar</Button>
          </div>
          <div className="collection-form-grid">
            {!editingId ? <label><span className="eyebrow">Identificador</span><input required minLength={1} maxLength={128} pattern="[A-Za-z0-9][A-Za-z0-9._-]*" value={form.collection_id} onChange={(event) => setForm((current) => ({ ...current, collection_id: event.target.value }))} placeholder="guias-clinicos" /></label> : null}
            <label><span className="eyebrow">Nome</span><input required minLength={1} maxLength={256} value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} placeholder="Guias clínicos" /></label>
            <label className="collection-description-field"><span className="eyebrow">Descrição</span><textarea maxLength={2_000} rows={2} value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} placeholder="Para que este conjunto de documentos serve?" /></label>
          </div>
          <div className="collection-form-actions"><Button type="submit" disabled={busy}>{busy ? <Spinner label="Salvando coleção" /> : <Save size={15} />}{busy ? "Salvando…" : editingId ? "Salvar alterações" : "Criar coleção"}</Button></div>
        </form>
      ) : null}

      {collections.length ? <div className="collection-list">{collections.map((collection) => <article className="collection-row" key={collection.collection_id}>
        <div className="collection-mark" aria-hidden="true"><Folder size={17} /></div>
        <div className="collection-main"><strong>{collection.title || collection.collection_id}</strong><span>{collection.collection_id}{collection.description ? ` · ${collection.description}` : ""}</span></div>
        <div className="collection-meta"><StatusPill tone={collection.status === "archived" ? "warning" : "success"}>{collection.status === "archived" ? "Arquivada" : "Ativa"}</StatusPill>{collection.version ? <span>v{collection.version}</span> : null}</div>
        <div className="collection-actions"><Button variant="ghost" onClick={() => openEdit(collection)} disabled={busy} aria-label={`Editar ${collection.title || collection.collection_id}`}><Pencil size={14} />Editar</Button><Button variant="ghost" className="collection-archive-button" onClick={() => setArchiveTarget(collection)} disabled={busy} aria-label={`Arquivar ${collection.title || collection.collection_id}`}><Archive size={14} />Arquivar</Button></div>
      </article>)}</div> : collectionsError ? null : loadingCollections ? <div className="collection-state-row" role="status" aria-busy="true"><Spinner label="Carregando coleções" /><span>Consultando as coleções autorizadas.</span></div> : <div className="collection-state-row collection-empty-state"><div><strong>Nenhuma coleção ativa</strong><span>Crie uma coleção para separar documentos, permissões e consultas por domínio.</span></div><Button onClick={openCreate}><FolderPlus size={15} />Nova coleção</Button></div>}

      <ConfirmDialog open={Boolean(archiveTarget)} title="Arquivar esta coleção?" description={`Novos uploads deixam de usar “${archiveTarget?.title || archiveTarget?.collection_id || "esta coleção"}”. Os documentos já publicados permanecem preservados no catálogo.`} confirmLabel="Arquivar coleção" busy={busy} onCancel={() => setArchiveTarget(null)} onConfirm={() => void archive()} />
    </Panel>
  );
}
