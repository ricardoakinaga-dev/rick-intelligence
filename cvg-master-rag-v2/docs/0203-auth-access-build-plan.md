# 0203 — Auth Access Build Plan

## Ordem Exata de Construção

### Fase 0 — Preparação e compatibilidade
1. Congelar o inventário atual em docs.
2. Expandir tipos e contratos sem quebrar os atuais.
3. Introduzir catálogo canônico de roles/permissões com alias de compatibilidade.

### Fase 1 — Modelo de domínio de acesso
1. Normalização de role legado `admin -> super_admin`.
2. Permission catalog e resolver de permissões efetivas.
3. Evolução do schema de usuário/sessão/reset token.

### Fase 2 — Persistência e migração
1. Migração tolerante de `admin_state.json`.
2. Migração tolerante de `session_state.json`.
3. Introdução da persistência de reset tokens.
4. Seeds mínimos seguros para roles base.

### Fase 3 — Backend de autenticação
1. endurecer login
2. implementar change-password
3. implementar request-password-reset
4. implementar confirm-password-reset
5. implementar list/revoke sessions

### Fase 4 — Backend de autorização
1. adicionar guard por permissão
2. proteger ações críticas existentes
3. auditar acesso negado

### Fase 5 — Frontend mínimo
1. atualizar tipos e navegação
2. ajustar login/recovery
3. adicionar UX mínima de senha e sessões
4. esconder ações proibidas

### Fase 6 — Testes
1. unitários de hashing, roles, permissões, reset
2. integração de login/sessão/guards
3. regressão de chat/search/documents

### Fase 7 — Fechamento
1. atualizar runtime/log/backlog
2. publicar relatório final

## Fases e Subfases

### Subfase 3.1
- contratos novos em `schemas.py`
- sem mudar comportamento legado

### Subfase 3.2
- serviços de senha e reset
- testes unitários

### Subfase 4.1
- guard genérico `require_permission`
- mapping de permissões para rotas atuais

### Subfase 4.2
- retrofit das rotas críticas:
  - usuários
  - runtime admin
  - upload
  - evaluation
  - corpus repair/audit

### Subfase 5.1
- session provider/types
- navegação por permissão ou role canônica

### Subfase 5.2
- UI mínima para password change/reset/session revoke

## Checkpoints
- Checkpoint A: docs canônicos criados.
- Checkpoint B: schema evolutivo carregando dados legados sem erro.
- Checkpoint C: login legado continua funcional.
- Checkpoint D: viewer perde capacidade indevida de upload.
- Checkpoint E: reset/change password funcionam.
- Checkpoint F: ações críticas auditadas.
- Checkpoint G: regressão principal verde.

## Dependências Entre Tarefas
- Permissões dependem da normalização de roles.
- Change-password e reset dependem do schema de usuário/reset token.
- Proteção do frontend depende dos contratos atualizados do backend.
- Testes finais dependem da preservação dos fluxos de chat/search/documents.

## Plano de Migração
- Migração “read-repair” dos arquivos JSON:
  - ao carregar, completar campos faltantes
  - ao salvar, persistir no novo formato
- Não remover campos legados no primeiro passo.
- Tratar `admin` legado como role canônica compatível.

## Plano de Compatibilidade
- Manter endpoints existentes.
- Adicionar endpoints novos em paralelo.
- Não renomear rotas existentes de admin/observability/query.
- Manter leitura dos hashes legados.

## Plano de Validação por Etapa
- Após Fase 2:
  - testes unitários de carga/salvamento do estado
- Após Fase 3:
  - login válido/inválido
  - usuário inativo
  - change-password
  - reset token
- Após Fase 4:
  - matrix role x rota crítica
- Após Fase 5:
  - render das telas principais
- Após Fase 6:
  - regressão focada backend + frontend

## Plano de Rollout Sem Quebra
- Primeiro endurecer backend mantendo compatibilidade.
- Depois ajustar frontend para explorar novos recursos.
- Não retirar comportamento legado até os testes passarem.
