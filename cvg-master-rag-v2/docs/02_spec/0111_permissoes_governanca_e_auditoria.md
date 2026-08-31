# 0111 — Permissões, Governança e Auditoria

## Papéis (Roles)

### Admin
**Permissões:**
- CRUD de tenants
- CRUD de usuários
- Visualização de métricas
- Acesso a auditoria

**Não pode:**
- Delete tenant with active users

---

### Operator
**Permissões:**
- Upload de documentos
- Queries (search, query)
- Visualização de documentos e chunks

**Não pode:**
- CRUD de tenants/users
- Acesso a métricas agregadas

---

### Viewer
**Permissões:**
- Queries (search, query)
- Visualização básica

**Não pode:**
- Upload de documentos
- CRUD admin

---

## Escopos

| Escopo | Admin | Operator | Viewer |
|---|---|---|---|
| documents:upload | ✅ | ✅ | ❌ |
| documents:read | ✅ | ✅ | ✅ |
| search:execute | ✅ | ✅ | ✅ |
| query:execute | ✅ | ✅ | ✅ |
| metrics:read | ✅ | ✅ | ❌ |
| audit:read | ✅ | ❌ | ❌ |
| tenants:create | ✅ | ❌ | ❌ |
| tenants:update | ✅ | ❌ | ❌ |
| tenants:delete | ✅ | ❌ | ❌ |
| users:create | ✅ | ❌ | ❌ |
| users:update | ✅ | ❌ | ❌ |
| users:delete | ✅ | ❌ | ❌ |

---

## Trilha de Auditoria

### Eventos Auditados

| Evento | Quem | Quando | O que |
|---|---|---|---|
| login | System | Login attempt | User, IP, result |
| logout | System | Logout | Session, user |
| create_tenant | Admin | Tenant created | Admin, tenant_id, name |
| update_tenant | Admin | Tenant updated | Admin, tenant_id, changes |
| delete_tenant | Admin | Tenant deleted | Admin, tenant_id (blocked if active) |
| create_user | Admin | User created | Admin, user_id, email, role |
| update_user | Admin | User updated | Admin, user_id, changes |
| delete_user | Admin | User deleted | Admin, user_id |

---

## Eventos Sensíveis

### Log sempre obrigatório para:
- Criação de admin
- Remoção de tenant
- Alteração de role
- Tentativas de login falhas

---

## Segregação de Responsabilidades

### Princípio: 4 eyes
- Operações admin requerem role admin
- Operator não pode promover a admin
- Viewer não pode criar outros viewers

### Princípio: Least Privilege
- Cada role tem mínimo de permissões necessárias
- Roles não são acumulativas (admin != operator + viewer)

---

## Política de Aprovação Humana

### Requer aprovação manual:
- Remoção de tenant com dados ativos
- Alteração de role admin → operator/viewer

### Não requer aprovação:
- Criação de tenant/user
- Upload de documentos
- Queries

---

## Próximo Passo

Avançar para 0112_integracoes_externas.md