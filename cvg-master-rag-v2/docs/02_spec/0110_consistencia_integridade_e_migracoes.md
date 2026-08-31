# 0110 — Consistência, Integridade e Migrações

## Regras de Integridade

### Integridade de Documento
1. Document.workspace_id deve existir
2. Document.filename não pode ser vazio
3. Document.status em ["parsed", "failed", "partial"]

### Integridade de Chunk
1. Chunk.document_id deve referenciar Document existente
2. Chunk.workspace_id deve ser igual a Document.workspace_id
3. Chunk.text não pode ser vazio
4. Chunk.index único dentro do documento

### Integridade de Session
1. Session.user_id deve referenciar User existente
2. Session.expires_at > Session.created_at
3. Session.workspace_id deve existir

### Integridade de User/Tenant
1. User.email único
2. Tenant.name único
3. User.role em ["admin", "operator", "viewer"]

---

## Campos Críticos

### Não nulos
- Document.id, workspace_id, source_type, filename, status
- Chunk.id, document_id, workspace_id, chunk_index, text
- User.id, email, password_hash, role
- Session.id, user_id, workspace_id, created_at, expires_at
- Tenant.id, name

### Opcionais
- Document.page_count, char_count, tags, metadata
- Chunk.start_char, end_char, page_hint
- Tenant.settings

---

## Estratégia de Migração

### Script de Reindex

**Uso:** Restaurar consistência entre disco e Qdrant

```bash
# Reindex completo
python scripts/reindex_corpus.py default

# Local only (não recria collection)
python scripts/reindex_corpus.py default --local-only

# Skip recreate (preserva collection)
python scripts/reindex_corpus.py default --skip-recreate
```

**Pré-requisitos:**
- Qdrant acessível
- OPENAI_API_KEY configurada

---

## Backward/Forward Compatibility

### API Versioning
- V0: Versão inicial
- Breaking changes: nova versão (v1)
- Additive changes: mesma versão

### Data Format
- raw.json schema: versionado via campo "version"
- chunks.json schema: versionado via campo "version"

---

## Seed / Bootstrap

### Default Workspace
- Criado automaticamente se não existir
- Nome: "default"
- ID: UUID fixo ou gerado

### Default Tenant
- Criado automaticamente na primeira inicialização
- Bootstrap user admin@example.com / admin123

---

## Próximo Passo

Avançar para 0111_permissoes_governanca_e_auditoria.md