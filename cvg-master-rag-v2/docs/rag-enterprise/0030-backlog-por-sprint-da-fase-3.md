# 0030 — Backlog por Sprint da Fase 3

## Objetivo

Transformar a Fase 3 em backlog executável por sprint, com itens claros para:

- frontend enterprise
- backend enterprise
- segurança e governança
- observabilidade e QA

Este documento complementa o `0007-fase-3-rag-enterprise.md`.

---

## Como usar este backlog

Cada sprint deve produzir:

- capacidade utilizável
- integração real com backend
- estados de erro e loading minimamente tratados
- evidência demonstrável
- critério de aceite verificável

Regra de execução:

1. fechar frontend e contrato da sprint juntos
2. não deixar autenticação, RBAC ou tenancy para depois se a tela depender deles
3. não aprovar sprint apenas com mock visual
4. registrar gaps reais no execution log

### Estado atual da implementação

Leitura honesta do código em `2026-04-16`:

- `frontend/` continua sendo o frontend canônico validado da Fase 2
- `Sprint G1` já tem implementação material no código ativo
- a fundação enterprise agora expõe sessão, tenants e login local no backend e no shell
- `Sprint G2` já começou a sair do papel com o painel `/admin` e o CRUD inicial de tenants e usuários
- o backend agora também recusa acesso admin sem role adequada e bloqueia workspace fora do tenant ativo
- o `Sprint G1` foi validado com `pnpm -C frontend exec tsc --noEmit`, `pnpm -C frontend lint`, `pnpm -C frontend build`, `pnpm -C frontend test:smoke` e `pytest -q`
- os sprints `G3-G4` seguem como backlog pendente
- o workspace `playwright-ui` existe apenas como artefato de smoke test da Fase 2

---

## Sprint G1 - Fundacao Enterprise

### Resultado esperado

Existir uma base enterprise mínima pronta para autenticação, tenancy e navegação por perfil.

### Backlog de frontend

- criar rota de login
- criar fluxo de recuperação de acesso
- criar estado de onboarding
- criar navegação por perfil
- preparar shell com seletor de tenant
- preparar fallback visual para sessão expirada

### Backlog de backend

- definir contrato de autenticação
- definir contrato de sessão
- definir contrato de tenant/workspace ativo
- definir contrato de perfil/role
- expor metadata mínima de usuário autenticado

### Backlog de segurança e governança

- escolher provedor de auth ou mecanismo interno
- definir roles iniciais:
  - admin
  - operator
  - viewer
- definir política de acesso por role
- definir isolamento lógico base por tenant

### Backlog de UX e conteúdo

- definir microcopy de login e recuperação
- definir empty state para usuário sem tenant ativo
- definir mensagens para acesso negado e sessão expirada

### Backlog de QA

- validar login bem-sucedido
- validar logout
- validar sessão expirada
- validar navegação por role
- validar troca de tenant sem recarregar a app

### Critério de aceite

- usuário entra no produto com identidade real
- a navegação respeita o contexto do usuário
- a base visual não depende de Swagger para acesso

### Implementado nesta rodada

- contrato de sessão enterprise com `GET /session`, `POST /auth/login`, `POST /auth/logout`, `POST /auth/recovery` e `GET /tenants`
- `GET /auth/me` adicionado para introspecção explícita da identidade autenticada
- shell global com seletor de tenant, role badge e logout
- rotas `login`, `recover-access` e `onboarding`
- rota `forbidden` e guardas de navegação por role
- persistência local da sessão enterprise no frontend
- bootstrap de sessão anônima por padrão, com invalidação segura do bootstrap durante login/logout
- páginas principais usando o workspace ativo do contexto enterprise
- smoke test do frontend agora autentica pela UI, usa backend isolado em `8010` e valida `admin`, upload, busca, chat e responsividade

### Evidência de validação do G1

- `pnpm -C frontend exec tsc --noEmit` passou
- `pnpm -C frontend lint` passou
- `pnpm -C frontend build` passou
- `pnpm -C frontend test:smoke` passou com `5 passed`
- `pytest -q` em `src` passou com `48 passed, 3 skipped`

### Status

`CONCLUÍDO`

### Implementado nesta rodada (Sprint G2 inicial)

- painel `/admin` com CRUD operacional para tenants e usuários
- criação, edição e remoção de tenants via UI
- criação, edição e remoção de usuários via UI
- drawer de formulário com feedback de erro e refresh após mutações
- proteção visual do tenant bootstrap contra remoção

---

## Sprint G2 - Multitenancy e Admin Core

### Resultado esperado

Operador e admin conseguem separar, administrar e auditar tenants/workspaces de forma clara.

### Backlog de frontend

- criar painel administrativo
- criar lista de tenants/workspaces
- criar detalhe de tenant
- criar cadastro e edição de tenant
- criar gestão de usuários
- criar gestão de permissões
- criar tela de configurações do agente
- criar tela de thresholds e parâmetros

### Backlog de backend

- expor CRUD de tenants/workspaces
- expor CRUD de usuários
- expor associação usuário-role-tenant
- expor persistência de configurações por tenant
- expor limites e quotas por tenant, se aplicável

### Backlog de segurança e governança

- implementar RBAC real em endpoints centrais
- garantir isolamento entre tenants
- registrar eventos administrativos
- garantir trilha de auditoria por ação

### Backlog de UX e conteúdo

- definir microcopy do painel admin
- definir empty state de tenants vazios
- definir mensagens para permissões insuficientes

### Backlog de QA

- validar CRUD de tenants
- validar CRUD de usuários
- validar alteração de role
- validar isolamento entre tenants
- validar auditoria de ações administrativas

### Critério de aceite

- admin consegue operar a base multiempresa pela interface
- os dados ficam isolados por tenant
- permissões deixam de ser implícitas

---

## Sprint G3 - Observabilidade e Operacao Enterprise

### Resultado esperado

A plataforma passa a ser operável com leitura executiva, alertas e rastreabilidade.

### Backlog de frontend

- criar dashboard executivo
- criar dashboard por tenant
- criar visao de KPIs de uso
- criar visao de KPIs de qualidade
- criar visao de KPIs de ingestao
- criar visao de KPIs de custo
- criar visao de alertas

### Backlog de backend

- expor métricas por tenant
- expor séries temporais básicas
- expor alertas e status de saúde
- expor tracing mínimo por request
- expor eventos administrativos para auditoria

### Backlog de observabilidade

- definir alertas de uptime
- definir alertas de latência
- definir alertas de erro
- definir retenção e acesso a logs
- definir correlação de request_id

### Backlog de UX e conteúdo

- definir visual dos KPIs
- definir copy dos estados de alerta
- definir leitura consolidada para usuários não técnicos

### Backlog de QA

- validar dashboard executivo
- validar visao por tenant
- validar alertas
- validar tracing de ponta a ponta

### Critério de aceite

- operador entende a saúde da plataforma sem ler logs crus
- os tenants aparecem de forma consistente nos dashboards
- alertas e tracing ajudam operação real

---

## Sprint G4 - Release Enterprise e Hardenings Finais

### Resultado esperado

Concluir a Fase 3 como plataforma comercialmente demonstrável.

### Backlog de frontend

- polir navegação por perfil
- polir estados de erro e vazio
- reforçar consistência visual
- fechar responsividade desktop/tablet/mobile
- revisar acessibilidade mínima

### Backlog de backend

- congelar contratos enterprise mínimos
- registrar endpoints complementares que ficam para evolução futura
- validar limites de performance e estabilidade

### Backlog de segurança e compliance

- validar políticas de retenção
- validar logs administrativos
- validar isolamento entre tenants
- validar autorização por role

### Backlog de QA

- smoke test ponta a ponta da plataforma
- validação visual final
- validação de isolamento e RBAC
- validação de observabilidade e auditoria

### Critério de aceite

- a plataforma pode ser demonstrada como enterprise real
- os gaps remanescentes são de evolução, não de fundamento
- a Fase 3 pode ser fechada com evidência

---

## Dependências de Backend por Tema

| Tema | Backend obrigatório | Backend recomendado |
|---|---|---|
| Auth e acesso | login, sessão, recuperação | SSO no futuro |
| Tenancy | tenants/workspaces, role mapping | billing/quotas |
| Admin core | CRUD de usuários e tenants | políticas avançadas |
| Observabilidade | métricas, logs, tracing | alertas e dashboards |
| Compliance | auditoria, retenção, isolamento | exportação de trilha |

---

## Definicao de Pronto da Fase 3

A Fase 3 é considerada pronta quando:

1. existe frontend enterprise completo
2. autenticação e navegação por perfil funcionam
3. multitenancy funcional
4. RBAC funcional
5. painel administrativo real existe
6. observabilidade enterprise existe
7. auditoria e governança funcionam
8. a plataforma é demonstrável como produto comercial

---

## Proximo Passo

Executar `Sprint G1` e usar `0031-checklist-do-gate-da-fase-3.md` para registrar a validação formal conforme a implementação avançar.
