# 0031 — Checklist do Gate da Fase 3

## Objetivo

Registrar a validação formal necessária para decidir se a **Fase 3 — Enterprise Platform** pode ser considerada concluída.

Este documento não presume aprovação.

Ele existe para:

- consolidar a evidência da trilha enterprise
- separar o que já está pronto do que ainda é gap real
- evitar declarar o gate sem validação ponta a ponta

---

## Estado de partida

Leitura atual do código e da documentação:

- `frontend/` é o app canônico validado da Fase 2
- `Sprint G1` da Fase 3 já possui implementação material no código ativo
- `0030-backlog-por-sprint-da-fase-3.md` define a trilha executável da fase
- `0007-fase-3-rag-enterprise.md` define o escopo e o gate conceitual

---

## Evidência mínima exigida

Antes de decidir o gate da Fase 3, deve existir evidência reproduzível para:

1. frontend enterprise completo instalando e buildando
2. backend principal verde
3. autenticação e navegação por perfil operáveis
4. multitenancy operável pela UI
5. admin panel operável pela UI
6. observabilidade enterprise operável pela UI
7. auditoria e governança operáveis pela UI
8. plataforma comercialmente demonstrável sem depender de Swagger para a rotina principal

---

## Checklist do Gate

### A. Frontend Enterprise

- [x] login e recuperação de acesso funcionam
- [x] navegação por perfil funciona
- [x] selector de tenant/workspace funciona
- [x] painel administrativo existe
- [ ] dashboard executivo existe

### B. Multitenancy

- [ ] 3+ tenants ativos simultaneamente
- [ ] isolamento entre tenants verificado
- [ ] queries não vazam entre tenants
- [ ] onboarding de novo tenant funcional
- [ ] branding por tenant funcional

### C. RBAC e Segurança

- [ ] autenticação forte implementada
- [ ] roles admin/operator/viewer testadas
- [ ] autorização por role aplicada em endpoints centrais
- [ ] logs administrativos funcionando
- [ ] políticas de retenção e isolamento definidas

### D. Operação Enterprise

- [ ] CRUD de empresas/workspaces funcionando
- [ ] métricas por tenant visíveis
- [ ] alertas configurados
- [ ] tracing mínimo de queries funcional
- [ ] logs de sistema acessíveis para debugging

### E. Auditoria e Governança

- [ ] trilha de auditoria funcionando
- [ ] quem fez o quê e quando está registrado
- [ ] eventos administrativos acessíveis
- [ ] workflows de aprovação funcionam

### F. Qualidade de Serviço

- [ ] uptime >= 99% em janela de validação definida
- [ ] p99_latency < 3s em queries normais
- [ ] error_rate < 2%
- [ ] health check funcional

### G. Produto Comercial

- [ ] experiência final compatível com usuários não técnicos
- [ ] plataforma demonstrável como produto enterprise
- [ ] operação principal executável sem interface técnica

---

## Matriz de Decisão

### Aprovado

Marcar **Fase 3 concluída** somente se:

- todos os itens bloqueantes acima estiverem validados
- os gaps restantes forem claramente de evolução futura
- a rotina principal puder ser feita pela UI

### Não aprovado

Marcar **nova rodada corretiva necessária** se qualquer um destes pontos permanecer:

- multitenancy sem isolamento real
- RBAC incompleto ou inconsistente
- observabilidade insuficiente para operação
- dependência forte de Swagger para rotina diária
- base paralela ainda confundindo a fonte de verdade

---

## Campos para preenchimento da execução real

### Data da validação

- `2026-04-16`

### Responsável

- `Codex`

### Evidência executada

- `0030-backlog-por-sprint-da-fase-3.md` criado como trilha executável
- `0007-fase-3-rag-enterprise.md` atualizado para apontar para o backlog
- `0015-roadmap-executivo.md`, `0016-backlog-priorizado.md`, `0025-visao-final-enterprise-premium.md` e `0026-mapa-de-aderencia-ao-guia.md` alinhados à transição F2 → F3
- `GET /session`, `POST /auth/login`, `POST /auth/logout`, `POST /auth/recovery` e `GET /tenants` implementados
- `GET /auth/me` implementado
- `frontend/app/login/page.tsx`, `frontend/app/onboarding/page.tsx`, `frontend/app/recover-access/page.tsx`, `frontend/app/admin/page.tsx` e `frontend/app/forbidden/page.tsx` criados
- `frontend/app/admin/page.tsx` agora opera CRUD de tenants e usuários com drawer de formulário
- `frontend/components/layout/app-shell.tsx` agora expõe seletor de tenant e logout
- `frontend/components/layout/enterprise-session-provider.tsx` mantém sessão local, troca de tenant, recuperação e evita race entre bootstrap anônimo e login
- backend agora valida cabeçalhos enterprise para role e workspace em rotas sensíveis
- `pnpm -C frontend exec tsc --noEmit`, `pnpm -C frontend lint` e `pnpm -C frontend build` passaram na base enterprise atual
- `pnpm -C frontend test:smoke` passou com `5 passed`
- `pytest -q` em `src` passou com `48 passed, 3 skipped`

### Decisão final

- [ ] Fase 3 concluída
- [x] Nova rodada corretiva necessária

### Observações

- o gate da Fase 3 ainda não foi executado por completo
- o G1 foi implementado e validado por evidência automatizada
- a fase continua aberta porque G2-G4 ainda não possuem a evidência completa de multitenancy, RBAC forte, operação e governança enterprise
- a Fase 2 segue fechada e validada
- o workspace `playwright-ui` é apenas resíduo controlado do smoke test da Fase 2
