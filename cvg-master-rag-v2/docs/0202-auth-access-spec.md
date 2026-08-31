# 0202 — Auth Access SPEC

## Arquitetura da Solução

### Princípio
Endurecer a camada existente de auth/acesso sem trocar a arquitetura principal do sistema.

### Componentes
- `src/services/admin_service.py`
  - catálogo de papéis e permissões
  - CRUD de usuários
  - operações de senha e governança
- `src/services/enterprise_service.py`
  - login/logout
  - sessão atual
  - revogação/listagem de sessões
  - reset token flow
- `src/services/enterprise_store.py`
  - persistência JSON tolerante a migração
- `src/api/main.py`
  - endpoints auth/admin
  - guards por sessão, workspace, role e permissão
- frontend session provider / admin / login / recovery
  - refletindo novos contratos sem quebrar o shell atual

## Fluxos

### Login
1. Usuário envia `email + password + tenant_id`.
2. Backend normaliza identidade.
3. Backend valida:
   - usuário existe
   - status ativo
   - senha válida
   - tenant permitido
4. Backend cria sessão server-side com TTL.
5. Backend retorna `EnterpriseSession` com:
   - role canônica
   - permissões efetivas
   - tenant ativo
6. Evento auditado:
   - `auth.login`
   - ou `auth.login_failed`

### Logout
1. Cliente envia bearer token.
2. Backend remove a sessão persistida.
3. Evento auditado:
   - `auth.logout`

### Troca de senha autenticada
1. Usuário autenticado envia:
   - senha atual
   - nova senha
2. Backend valida senha atual e política mínima.
3. Backend atualiza hash/salt/timestamps.
4. Backend revoga sessões anteriores do usuário, preservando opcionalmente a sessão corrente apenas se configurado; nesta rodada, revogar todas e exigir novo login.
5. Evento auditado:
   - `auth.change_password`

### Reset de senha
1. Solicitação:
   - `POST /auth/request-password-reset`
   - sempre responde com mensagem neutra
2. Backend cria token random, armazena apenas hash do token e TTL.
3. Confirmação:
   - `POST /auth/confirm-password-reset`
   - token + nova senha
4. Backend valida token, expiração e uso.
5. Backend troca senha, marca token como consumido e revoga sessões.
6. Eventos auditados:
   - `auth.password_reset_requested`
   - `auth.password_reset_confirmed`
   - `auth.password_reset_invalid_token`

### Revogação de sessão
1. Super admin consulta sessões de um usuário.
2. Super admin revoga sessão específica ou todas.
3. Evento auditado:
   - `auth.session_revoked`

## Modelo de Sessão
- Persistência continua server-side em JSON local.
- Estrutura da sessão evolui para incluir:
  - `session_token`
  - `user_id`
  - `tenant_id`
  - `role`
  - `permissions`
  - `created_at`
  - `last_seen_at`
  - `expires_at`
  - `revoked_at`
  - `revoked_reason`
  - `ip`
  - `user_agent`
- Sessão inválida quando:
  - expirada
  - revogada
  - usuário desativado
  - senha alterada após a emissão
  - role/permissões mudadas após a emissão

## Estratégia de Hashing de Senha
- Manter compatibilidade de leitura com:
  - `$2b$...` legado demo
  - `$pbkdf2$<hash>` legado intermediário
- Novo padrão de escrita:
  - PBKDF2-SHA256
  - salt aleatório por usuário
  - formato `$pbkdf2$<salt_hex>$<hash_hex>`
- Política mínima de senha:
  - tamanho mínimo 12
  - deve conter pelo menos duas classes entre: maiúscula, minúscula, número, símbolo
  - rejeitar igual ao e-mail
  - rejeitar igual à senha anterior imediata quando houver histórico disponível; nesta rodada, sem histórico completo, validar apenas contra a senha atual

## Estratégia de Autorização

### Papéis canônicos
- `super_admin`
- `admin_rag`
- `auditor`
- `operator`
- `viewer`

### Compatibilidade
- `admin` legado será normalizado para `super_admin`.

### Catálogo inicial de permissões
- `users.manage`
- `users.read`
- `roles.manage`
- `passwords.reset`
- `sessions.revoke`
- `sources.manage`
- `documents.read`
- `documents.upload`
- `documents.delete`
- `chunks.delete`
- `search.execute`
- `query.execute`
- `ingestion.run`
- `reindex.run`
- `audit.read`
- `audit.export`
- `observability.read`
- `settings.sensitive.manage`

### Mapeamento inicial
- `super_admin`
  - todas as permissões
- `admin_rag`
  - `sources.manage`
  - `documents.read`
  - `documents.upload`
  - `search.execute`
  - `query.execute`
  - `ingestion.run`
  - `reindex.run`
  - `audit.read`
  - `observability.read`
- `auditor`
  - `documents.read`
  - `search.execute`
  - `query.execute`
  - `audit.read`
  - `observability.read`
- `operator`
  - `documents.read`
  - `documents.upload`
  - `search.execute`
  - `query.execute`
  - `ingestion.run`
- `viewer`
  - `documents.read`
  - `search.execute`
  - `query.execute`

## Middleware / Guards / Policies
- Manter:
  - sessão autenticada
  - workspace ativo permitido
- Adicionar:
  - `require_permission(permission)`
  - auditoria de acesso negado
  - normalização de role legada
- Estratégia:
  - rotas sensíveis passam a ser protegidas por permissão explícita
  - workspace check continua obrigatório quando aplicável

## Tabelas e Colunas Encontradas / Schema Evolutivo

### Persistência atual
- Não há banco relacional/migrações SQL no módulo de acesso atual.
- O storage real é JSON.

### Estruturas a evoluir

#### users
- manter:
  - `user_id`, `name`, `email`, `tenant_id`, `status`
- adicionar:
  - `role` canônica
  - `permission_overrides`
  - `must_change_password`
  - `created_at`
  - `updated_at`
  - `deactivated_at`
  - `role_changed_at`

#### sessions
- manter:
  - `session_token`, `user_id`, `tenant_id`, `created_at`, `expires_at`
- adicionar:
  - `last_seen_at`
  - `revoked_at`
  - `revoked_reason`
  - `ip`
  - `user_agent`
  - `role_snapshot`
  - `permissions_snapshot`

#### password_reset_tokens
- novo conjunto lógico em `recovery_state.json` ou arquivo dedicado evolutivo:
  - `reset_id`
  - `user_id`
  - `email`
  - `token_hash`
  - `tenant_id`
  - `created_at`
  - `expires_at`
  - `used_at`
  - `requested_by`

#### audit_log
- manter `admin_events.jsonl`
- padronizar novas ações de segurança no mesmo trilho append-only

## Contratos de API

### Novos endpoints
- `POST /auth/change-password`
- `POST /auth/request-password-reset`
- `POST /auth/confirm-password-reset`
- `GET /auth/sessions`
- `POST /auth/sessions/revoke`
- `POST /admin/users/{user_id}/reset-password`

### Compatibilidade
- manter:
  - `POST /auth/recovery`
  - como fallback assistido/humano

## Impactos no Frontend
- Tipos de role e permissões precisam ser expandidos.
- Navegação não pode depender só de hierarquia simples.
- Login deve parar de sugerir que a role é escolhida no frontend; a role real vem do backend.
- Tela admin deve:
  - exibir role canônica
  - permitir reset/desativação conforme permissão
  - ocultar ações proibidas
- Deve existir UX mínima para:
  - trocar própria senha
  - solicitar reset

## Impactos no Backend
- `src/api/main.py`
  - novos guards e endpoints
  - proteção explícita nas rotas críticas
- `src/services/admin_service.py`
  - role mapping, permission catalog, password policy, reset helpers
- `src/services/enterprise_service.py`
  - sessões, reset token flow, change-password, revogação
- `src/models/schemas.py`
  - novos contratos

## Impactos no Banco / Persistência
- Não haverá introdução de banco novo nesta rodada.
- Haverá migração aditiva do schema JSON existente ao carregar/salvar estado.

## Impactos nos Workers
- Nenhum worker de RAG deve mudar de arquitetura.
- Apenas as superfícies de acionamento de ingestão/reindexação receberão guard por permissão.

## Trilha de Auditoria

### Eventos mínimos obrigatórios
- `auth.login`
- `auth.login_failed`
- `auth.logout`
- `auth.change_password`
- `auth.password_reset_requested`
- `auth.password_reset_confirmed`
- `auth.password_reset_invalid_token`
- `auth.session_revoked`
- `auth.access_denied`
- `user.create`
- `user.update`
- `user.deactivate`
- `user.role_change`
- `user.password_reset_admin`
- `documents.upload`
- `ingestion.run`
- `reindex.run`
- `documents.delete`
- `chunks.delete`
- `audit.export`
- `settings.sensitive.update`

### Sanitização
- Nunca registrar:
  - senha
  - token puro
  - hash completo de recuperação

## Estratégia de Rollback
- Novos campos são opcionais e aditivos.
- Roles legadas continuam legíveis.
- Novos endpoints podem ser retirados sem quebrar `/auth/login`, `/auth/logout`, `/auth/me`.
- Guards novos serão introduzidos em pontos críticos preservando o workspace check atual.
