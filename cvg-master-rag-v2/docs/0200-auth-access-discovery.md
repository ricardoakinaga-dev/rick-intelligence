# 0200 — Auth Access Discovery

## Objetivo
Auditar o estado real da camada de usuários, autenticação, senhas, sessões, papéis, permissões e auditoria antes de qualquer alteração de código.

## Estado Atual Encontrado

### Arquitetura real de auth/acesso
- Backend FastAPI centralizado em `src/api/main.py`.
- Estado administrativo persistido em JSON local via `src/services/enterprise_store.py`.
- Usuários e tenants persistidos em `src/data/enterprise/admin_state.json`.
- Sessões persistidas em `src/data/enterprise/session_state.json`.
- Solicitações de recuperação persistidas em `src/data/enterprise/recovery_state.json`.
- Eventos administrativos/auditáveis persistidos em `src/logs/admin_events.jsonl`.

### Implementação atual de identidade
- Usuários são modelados por `EnterpriseUserRecord`, `EnterpriseUserCreate` e `EnterpriseUserUpdate` em `src/models/schemas.py`.
- Campos atuais de usuário:
  - `user_id`
  - `name`
  - `email`
  - `role`
  - `tenant_id`
  - `status`
  - `password_hash`
  - `password_salt`
  - timestamps derivados como `password_changed_at`, `status_changed_at`, `role_changed_at`
- Tenants são usados como escopo de workspace e controle de visibilidade.

### Implementação atual de autenticação
- Login: `POST /auth/login` em `src/api/main.py`.
- Logout: `POST /auth/logout`.
- Sessão atual: `GET /session` e `GET /auth/me`.
- Troca de tenant: `POST /auth/switch-tenant`.
- Recuperação atual: `POST /auth/recovery`, mas apenas registra pedido; não executa reset de senha.
- Sessão é server-side, emitida como `session_token` bearer.
- Sessão é buscada a partir do header `Authorization: Bearer <token>`.
- TTL atual: `SESSION_TTL_HOURS`, default `8`, em `src/core/config.py`.
- Sessões expiradas são podadas sob demanda em `src/services/enterprise_service.py`.
- Não há refresh/rotação explícita de sessão por request.

### Implementação atual de senhas
- Hashing em `src/services/admin_service.py`.
- Formato atual primário:
  - `$pbkdf2$<salt_hex>$<hash_hex>`
- Compatibilidade legada:
  - `$pbkdf2$<hash_hex>` com salt global histórico
  - `$2b$12$...` legado demo
- Usuários demo atuais:
  - `admin@demo.local`
  - `operator@demo.local`
  - `viewer@demo.local`
- Não existe endpoint formal para:
  - troca de senha autenticada
  - solicitação de reset com token
  - confirmação de reset com token

### Papéis e permissões atuais
- Papéis atuais de código:
  - `admin`
  - `operator`
  - `viewer`
- Implementação de autorização atual:
  - hierarquia simples por ordem em `ROLE_ORDER` dentro de `src/api/main.py`
  - permissões derivadas por role em `ROLE_PERMISSIONS` em `src/services/enterprise_service.py`
- Não existe modelo explícito persistido de:
  - permission catalog
  - role-permission mapping canônico
  - user overrides

### Implementação atual de auditoria
- Sucesso e falha de login geram `log_admin_event(...)`.
- Logout gera evento.
- CRUD de tenant e usuário gera evento.
- Mudança de role gera evento.
- Operações admin críticas de runtime/corpus geram evento.
- Não há log explícito e sistemático para acesso negado por guard.
- Não há trilha formal para:
  - change-password
  - request-password-reset
  - confirm-password-reset
  - revoke-session

## Onde Login/Auth/Users/Sessions Aparecem Hoje

### Backend
- `src/api/main.py`
  - guards `_require_authenticated_session`, `_require_min_role`, `_require_admin`, `_require_operator`, `_require_workspace_access`
  - rotas `/auth/*`, `/admin/*`, `/documents/*`, `/search`, `/query`, `/evaluation/*`, `/observability/*`
- `src/services/enterprise_service.py`
  - login/logout/session/tenant switch/recovery queue
- `src/services/admin_service.py`
  - CRUD de usuários e tenants
  - hashing/verificação de senha
  - auditoria administrativa
- `src/services/enterprise_store.py`
  - persistência JSON e append-only de eventos administrativos
- `src/models/schemas.py`
  - contratos de request/response

### Frontend
- `frontend/components/layout/enterprise-session-provider.tsx`
  - bootstrap da sessão
  - login/logout/switchTenant/recovery
  - persistência local da sessão
- `frontend/lib/api.ts`
  - cliente REST + injeção do bearer token
- `frontend/components/layout/app-shell.tsx`
  - redirecionamento para login e forbidden
  - controle de navegação por role
- `frontend/lib/navigation.ts`
  - matriz simples de acesso por role mínima
- `frontend/app/login/page.tsx`
  - login com defaults demo e seleção visual de role
- `frontend/app/recover-access/page.tsx`
  - recuperação apenas assistida/queued
- `frontend/app/admin/page.tsx`
  - CRUD de tenants/usuários e ações críticas admin

## Tabelas / Models / Rotas / Componentes Envolvidos

### Persistência real encontrada
- `src/data/enterprise/admin_state.json`
- `src/data/enterprise/session_state.json`
- `src/data/enterprise/recovery_state.json`
- `src/logs/admin_events.jsonl`

### Rotas atuais mais relevantes
- Públicas:
  - `POST /auth/login`
  - `POST /auth/recovery`
  - `GET /tenants`
- Sessão autenticada:
  - `GET /session`
  - `GET /auth/me`
  - `POST /auth/logout`
  - `POST /auth/switch-tenant`
  - `GET /documents`
  - `GET /documents/{document_id}`
  - `POST /documents/upload`
  - `POST /search`
  - `POST /query`
- Operator+:
  - `GET /evaluation/dataset`
  - `POST /evaluation/dataset`
  - `GET /queries/logs`
  - `GET /metrics`
  - `GET /observability/*`
  - `POST /evaluation/*`
  - `GET /corpus/audit`
  - `POST /corpus/repair/*`
- Admin:
  - `GET/POST/PATCH/DELETE /admin/tenants`
  - `GET/POST/PATCH/DELETE /admin/users`
  - `GET /admin/events`
  - `GET /admin/runtime`
  - `POST /admin/runtime/prune-index`
  - `POST /admin/runtime/cleanup-operational`
  - `GET /admin/alerts|slo|traces|audits|repairs`
  - `POST /admin/evaluation/run`
  - `POST /admin/corpus/*`

## Lacunas Encontradas

### Lacunas funcionais
- Não existe criação controlada do primeiro admin além do estado demo/default.
- Não existe bootstrap formal para produção interna.
- Não existe fluxo real de reset de senha com token.
- Não existe fluxo de troca de senha autenticada.
- Não existe listagem/revogação de sessões por usuário.
- Não existe separação real entre:
  - administração de acesso
  - administração operacional do RAG
  - auditoria

### Lacunas de autorização
- Modelo atual é hierárquico por role, não por permissão explícita.
- O papel `admin` atual acumula governança de acesso e governança operacional.
- Não existem papéis pedidos no objetivo:
  - `super_admin`
  - `admin_rag`
  - `auditor`
  - `operator`
  - `viewer`
- `POST /documents/upload` hoje exige apenas sessão + workspace; viewer autenticado consegue subir documento, o que conflita com menor privilégio.
- Não há auditoria explícita de acesso negado em todos os guards.

### Lacunas de segurança
- Token de sessão é armazenado no storage do frontend; não usa cookie HttpOnly.
- Frontend middleware Next.js está no-op; a proteção efetiva está no cliente e no backend.
- Não há rate limit de login.
- Não há política mínima formal de senha aplicada no backend.
- Não há contador/telemetria de falhas por identidade.
- Não há enumeração formal de eventos de segurança.

### Lacunas de UX interna
- Login atual é orientado a contas demo.
- Tela de recuperação não entrega reset real.
- Não existe UI mínima para:
  - alterar própria senha
  - resetar senha de outro usuário
  - revogar sessões

## Riscos de Regressão
- Quebrar compatibilidade com as contas demo atuais.
- Quebrar o shell frontend que assume `role` em `admin|operator|viewer`.
- Quebrar o acesso a chat, search e documents por alterar prematuramente o formato de `EnterpriseSession`.
- Quebrar sessões existentes se o payload persistido mudar sem migração tolerante.
- Quebrar testes existentes que dependem do fluxo atual de login e das roles antigas.
- Quebrar operações admin de runtime se a separação de papéis for feita sem mapeamento de permissões.

## Dependências Críticas
- `frontend/components/layout/enterprise-session-provider.tsx`
- `frontend/lib/api.ts`
- `frontend/lib/navigation.ts`
- `src/api/main.py`
- `src/services/enterprise_service.py`
- `src/services/admin_service.py`
- `src/services/enterprise_store.py`
- `src/models/schemas.py`
- suíte `src/tests/test_sprint5.py`
- suíte `src/tests/test_p0_closeout.py`
- suíte `src/tests/integration/test_tkt_010_non_leakage.py`

## Pontos Ambíguos
- O repositório fala em “quase pronto”, mas a camada de acesso persistente ainda é local/file-based, não relacional.
- O sistema atual usa tenant/workspace como boundary principal; o novo desenho precisa respeitar isso sem introduzir arquitetura paralela.
- A interface admin existente mistura governança de usuários e governança operacional do RAG; será necessário separar permissão sem quebrar a UX atual.

## Decisão de Estratégia Incremental
- Manter a arquitetura atual de persistência JSON nesta rodada, porque é o desenho real encontrado e já está integrado ao runtime e aos testes.
- Evoluir o schema de forma aditiva:
  - novos campos em usuários
  - catálogo de permissões
  - reset tokens
  - metadados de sessão
- Introduzir papéis canônicos novos com camada de compatibilidade para o papel legado `admin`.
- Adicionar endpoints novos sem remover abruptamente os atuais.
- Endurecer guards por permissão explícita, preservando checagens de workspace.

## Áreas que Não Devem Ser Quebradas
- `/search`
- `/query`
- `/documents`
- `/evaluation/*`
- `/observability/*`
- `/admin/runtime*`
- frontend shell principal
- indexação/ingestão/reparo do corpus
- contratos de telemetry e query logs

## Conclusão
O sistema já possui fundação utilizável de autenticação e RBAC, mas ainda em formato simplificado e com lacunas importantes em papéis, permissões, mudança/reset de senha, revogação de sessão e auditoria de segurança. A implementação deve endurecer a camada existente, não substituí-la por outra arquitetura.
