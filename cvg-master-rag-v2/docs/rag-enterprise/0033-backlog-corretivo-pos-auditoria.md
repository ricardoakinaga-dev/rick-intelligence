# 0033 — Backlog Corretivo Pos-Auditoria (Atualizado 2026-04-17)

## Objetivo

Transformar a auditoria registrada em `0038-relatorio-de-auditoria-tecnica-2026-04-17.md` em backlog executável, priorizado e verificável.

**Nota geral auditoria: 87/100**

---

## Blocker Real: Dataset Não Existe

A auditoria identificou que **o dataset de avaliação real não existe no repo**. Sem ele, nenhum gate pode ser verificado — nem F0, F1, F2 ou F3.

Este é o blocker mais crítico do programa e deve ser tratado como **P0 absoluto**, antes de todas as outras correções.

---

## Regra de Execução

1. dataset real vem primeiro — sem ele, gates não são verificáveis
2. fechar auth demo antes de declarar plataforma enterprise
3. isolamento multi-tenant deve ser provado por teste
4. não usar métricas infladas como critério de gate
5. cada item deve terminar com evidência reproduzível

---

## Backlog P0 — Dataset (CRÍTICO)

### P0-DATASET — Criar Dataset Real de Avaliação

**Objetivo**

O sistema precisa de 20+ perguntas reais para que qualquer gate seja verificável.

**Entregas**

- criar `src/data/default/dataset.json` com 20+ perguntas
- schema validado contra Pydantic
- múltiplos documentos fonte (não apenas 1)
- balanceamento por categoria e dificuldade
- baseline de hit_rate >= 60% registrado

**Critério de aceite**

- `GET /evaluation/dataset` retorna 20+ perguntas
- hit_rate top-5 >= 60% no baseline
- schema valida sem erros
- dataset cobre corpus real mais amplo

**Nota-alvo**

- elevar `Dataset e avaliação auditável` de `60` para `>= 80`

---

## Backlog P0 — Segurança (do plano anterior)

### P0.1 Autenticacao real e sessao confiavel

**Objetivo**

Substituir o modelo atual baseado em cabecalhos do cliente por autenticacao real com sessao resolvida no servidor.

**Entregas**

- implementar identidade autenticada real no backend
- remover dependencia de `X-Enterprise-*` como fonte primaria de identidade
- expor sessao autenticada derivada do servidor
- invalidar sessao corretamente em logout e expiracao

**Criterio de aceite**

- nenhum endpoint central depende de role ou tenant vindos diretamente do cliente
- `GET /session` retorna identidade resolvida pelo servidor
- testes cobrem login valido, sessao expirada e tentativa de spoofing

**Nota-alvo**

- elevar `Seguranca e RBAC` de `82` para `>= 90`

### P0.2 RBAC server-side de verdade

**Objetivo**

Fazer a autorizacao nascer de membership persistida e aplicada no backend.

**Entregas**

- persistir usuario, tenant, role e memberships
- aplicar verificacao de role nos endpoints centrais
- separar permissoes de `admin`, `operator` e `viewer`
- registrar negativas de acesso relevantes

**Criterio de aceite**

- troca de role muda comportamento de endpoints
- usuarios sem permissao recebem bloqueio consistente
- cobertura automatizada para rotas administrativas

### P0.3 Persistencia administrativa e trilha de auditoria

**Objetivo**

Sair de store em memoria e ter operacao administrativa duravel e auditavel.

**Entregas**

- persistir tenants e usuarios em storage duravel
- persistir memberships por tenant
- criar tabela ou storage de eventos administrativos
- registrar ator, acao, alvo, tenant, timestamp e request_id

**Criterio de aceite**

- criar, editar e remover tenant ou usuario sobrevive a restart
- eventos administrativos ficam consultaveis

### P0.4 Multitenancy com isolamento provado

**Objetivo**

Tornar o isolamento por tenant verificavel e nao apenas implicito.

**Entregas**

- revisar todos os pontos de acesso a documentos, queries, auditoria e metricas
- garantir filtro server-side por tenant em fluxos centrais
- criar testes de nao-vazamento entre tenants
- provar 3 tenants ativos simultaneamente

**Criterio de aceite**

- nao ha leitura cruzada de documentos, logs ou queries entre tenants
- smoke e testes backend cobrem isolamento

---

## Backlog P1

Itens de maturidade alta que devem fechar a Fase 3 com padrao enterprise real.

### P1.1 Observabilidade F3 completa

**Objetivo**

Fechar o contrato de `0019-observabilidade-e-metricas.md`.

**Entregas**

- adicionar `request_id` ponta a ponta
- padronizar logs com campos estruturados minimos
- expor metricas por tenant
- preparar tracing minimo de query

**Nota-alvo**

- elevar `Observabilidade e metricas` de `95` para `>= 98`

### P1.2 Alertas e SLA operacional

**Objetivo**

Sair de monitoramento passivo para operacao com sinais de falha e meta de servico.

**Entregas**

- definir SLI e SLO basicos
- calcular `uptime`, `p99_latency` e `error_rate`
- adicionar alertas minimos para falha de saude e degradacao de busca

**Nota-alvo**

- elevar `SLA, alertas e tracing` de `24` para `>= 75`

### P1.3 Dashboard executivo de verdade

**Objetivo**

Levar o dashboard de uma leitura operacional para uma leitura executiva enterprise.

**Entregas**

- incluir KPIs de uso, qualidade, latencia e operacao por tenant
- destacar alertas e regressao de qualidade
- separar visoes de admin global e operador local

### P1.4 Fechar disciplina de qualidade e reproducao

**Objetivo**

Fazer build, typecheck e smoke se comportarem como evidencias confiaveis de release.

**Entregas**

- remover dependencia fragil de `.next/types` no typecheck
- parametrizar portas do smoke test
- fazer `pytest` encerrar com output conclusivo
- documentar pipeline minima de validacao

**Nota-alvo**

- elevar `Qualidade de engenharia e reprodutibilidade` de `58` para `>= 80`

---

## Backlog P2

Itens de acabamento e ampliacao apos o fechamento dos bloqueios.

### P2.1 Reranking (Cohere) ou documentar justificativa

### P2.2 HyDE ou remover do roadmap

### P2.3 Semantic chunking ou justificativa

### P2.4 Branding e onboarding por tenant

### P2.5 Workflow de aprovacao e governanca

### P2.6 Politicas e retencao

---

## Sequencia Recomendada

### Antes de Tudo

- **P0-DATASET** — criar dataset real (blocker de todos os gates)

### Sprint H1 - Auth e sessao confiavel

- P0.1
- P0.2

### Sprint H2 - Persistencia e auditoria administrativa

- P0.3
- parte de P0.4

### Sprint H3 - Isolamento multi-tenant comprovado

- concluir P0.4
- testes de nao-vazamento

### Sprint H4 - Avaliacao honesta e calibracao

- ja com dataset real criado

### Sprint H5 - Observabilidade e operacao enterprise

- P1.1
- P1.2
- P1.3

### Sprint H6 - Qualidade de release e fechamento do gate

- P1.4
- reauditoria do gate F3

---

## Evidencia Minima para Encerrar a Rodada Corretiva

Antes de reavaliar qualquer gate, deve existir evidencia reproduzivel para:

1. **dataset real de 20+ perguntas funcionando**
2. autenticacao real funcionando sem confiar em cabecalhos do cliente
3. RBAC aplicado no backend com memberships persistidas
4. tenants, usuarios e eventos administrativos persistidos
5. isolamento entre tenants coberto por testes
6. `lint`, `build`, `typecheck`, `smoke` e `pytest` verdes de forma repetivel

---

## Meta da Rodada

Meta executiva:

- levar a nota geral de `87` para `>= 92`
- ** remover o blocker de dataset que impede qualquer gate**
- reabrir a decisao do gate apenas com evidencia limpa
- ter dataset real, auth real e isolamento provado
