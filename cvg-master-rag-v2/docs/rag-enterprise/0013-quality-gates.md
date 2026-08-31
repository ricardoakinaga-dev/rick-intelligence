# 0013 — Quality Gates

## Objetivo

Definir gates objetivos e binários entre fases.

Nesta versão, os gates cobrem:

- qualidade técnica do motor
- maturidade operacional
- maturidade de produto
- maturidade enterprise

---

## Visão Geral dos Gates

```
GATE F0 ──────────────► GATE F1 ──────────────► GATE F2 ──────────────► GATE F3
  │                      │                       │                      │
  ▼                      ▼                       ▼                      ▼
Motor estável       Operação            Frontend              Plataforma
dataset real        profissional        robusto               multiempresa
observabilidade     painel técnico      chat + painéis        RBAC + governança
mínima              e métricas          experiência premium   SLA + auditoria
```

---

## GATE F0 — Foundation / Validation

### Definição

O sistema Fase 0 é considerado válido para avançar se TODOS os critérios abaixo forem verdadeiros:

#### A. Infraestrutura (Obrigatório)

- [ ] Upload de PDF funciona e retorna document_id
- [ ] Upload de DOCX funciona e retorna document_id
- [ ] Upload de MD funciona e retorna document_id
- [ ] Upload de TXT funciona e retorna document_id
- [ ] Parsing de PDF extrai texto (spot-check em 3 arquivos)
- [ ] Parsing de DOCX extrai texto corretamente
- [ ] Chunking recursive gera chunks de ~1000 caracteres
- [ ] Chunking recursive respeita overlap de 200
- [ ] Embeddings são gerados via OpenAI
- [ ] Vetores densos são indexados no Qdrant
- [ ] Vetores esparsos (BM25) são indexados no Qdrant
- [ ] Busca híbrida retorna resultados com scores RRF

#### B. Retrieval Quality (Obrigatório)

- [ ] Dataset de 20+ perguntas reais foi criado
- [ ] Cada pergunta tem document_id e trecho_esperado
- [ ] Retrieval foi executado para todas as 20+ perguntas
- [ ] Hit Rate top-5 >= 60% (mínimo 12/20)
- [ ] Se hit_rate < 60%: falha documentada com análise

#### C. Answer Quality (Obrigatório)

- [ ] Resposta é gerada para cada query do dataset
- [ ] Low confidence é marcado corretamente (sem falsos negativos)
- [ ] Respostas sem contexto adequado são marcadas
- [ ] Latência média < 5 segundos por query

#### D. Observabilidade (Obrigatório)

- [ ] Todas as queries são logadas com timestamp, query, scores, latency
- [ ] Métricas básicas disponíveis: hit_rate, avg_latency, avg_score
- [ ] Falhas de parse são logadas com razão

#### E. Documentação (Obrigatório)

- [ ] README com instruções de setup e run
- [ ] Endpoints documentados (input/output/erros)
- [ ] Contrato de chunk schema definido
- [ ] Contrato de search result definido

### Critério Binário

```
IF (A AND B AND C AND D AND E):
    → GATE F0 APROVADO
ELSE:
    → GATE F0 REPROVADO
    → Listar TODAS as falhas
    → Criar plano de correção
    → Executar correções
    → Testar novamente
```

---

## GATE F1 — RAG Profissional

### Pré-requisito

- GATE F0 aprovado
- Fase 0 em produção (mesmo simples) sem falhas críticas
- Dataset expandido para 30+ perguntas

### Definição

Considerar a Fase 1 encerrada se TODOS os critérios forem cumpridos:

#### A. Baseline Estável

- [ ] Fase 0 continua funcionando sem falhas críticas
- [ ] Dataset expandido: 30+ perguntas reais
- [ ] Hit rate baseline (RRF-only) documentado

#### B. Telemetria

- [ ] Logs de query em formato estruturado (JSON Lines)
- [ ] Script de agregação de métricas funcionando
- [ ] Métricas disponíveis: hit_rate_top1, top3, top5, avg_latency, avg_score, low_confidence_rate
- [ ] Low confidence rate é trackeado

#### C. Reranking (se implementado)

- [ ] Cohere rerank-3 integrado e funcionando
- [ ] Comparação RRF-only vs RRF+rerank executada
- [ ] Decisão documentada: reranking mantido ou removido
- [ ] Se mantido: gain documentado (> 5pp justificado)

#### D. Avaliação

- [ ] LLM Judge integrado para triagem
- [ ] Processo de revisão humana definido e executado
- [ ] 100% das respostas com judge_score < 0.70 revisadas por humano
- [ ] Padrões de falha identificados e documentados

#### E. Tuning

- [ ] chunk_size testado em 4 variações (500, 750, 1000, 1500)
- [ ] overlap testado em 3 variações (100, 200, 300)
- [ ] Melhores configurações documentadas
- [ ] Impacto de parâmetros compreendido e registrado

#### F. Melhoria vs Baseline

- [ ] Hit rate top-5 >= 75% OU
- [ ] Melhoria >= 15pp vs F0 baseline

#### G. Operação Visual Inicial

- [ ] Existe interface web técnica ou operacional mínima
- [ ] Documentos podem ser inspecionados visualmente
- [ ] Busca pode ser testada sem depender só de `curl`
- [ ] Métricas operacionais estão visíveis em interface ou painel simples

---

## GATE F2 — RAG Premium

### Pré-requisito

- GATE F1 aprovado
- Dados suficientes para identificar padrões (ex: docs longos performam pior)
- Time entende onde estão as limitações do baseline

### Definição

Considerar a Fase 2 encerrada se TODOS os critérios forem cumpridos:

#### A. Estratégias Testadas

- [ ] Semantic chunking testado em 5+ documentos longos
- [ ] Decisão documentada: adotar ou não adotar
- [ ] Se adotado: em quais tipos de documento aplica (definido por evidência)
- [ ] Page-by-page testado (se jurídicos disponíveis)
- [ ] Agentic chunking testado (se necessário)

#### B. Benchmark Controlado

- [ ] 3-5 perguntas testadas em 4+ estratégias
- [ ] Análise manual dos resultados (não só judge)
- [ ] Estratégia vencedora identificada com justificativa clara
- [ ] Resultados não baseados apenas em LLM Judge

#### C. HyDE (se implementado)

- [ ] Testado com threshold < 0.85
- [ ] Comparação: híbrida vs híbrida+HyDE em 10+ queries
- [ ] Gain documentado (deve ser > 10pp para manter)
- [ ] Custo por query estimado e justificado

#### D. Citações e Grounding

- [ ] Formato de citação definido e implementado
- [ ] Citation coverage rate medido (target: > 80%)
- [ ] Low groundedness tratado e logado

#### E. Melhoria vs F1

- [ ] Hit rate top-5 >= 80% OU melhoria >= 5pp vs F1
- [ ] Estratégias premium justificadas com dados reais

#### F. Produto Premium

- [ ] Frontend robusto funcional
- [ ] Chat web operacional
- [ ] Painel de documentos funcional
- [ ] Tela de busca com evidências visíveis
- [ ] Dashboard operacional funcional
- [ ] Produto utilizável sem depender da interface técnica
- [ ] Checklist formal do gate visual executado (`0029-checklist-do-gate-visual-da-fase-2.md`)

---

## GATE F3 — RAG Enterprise

### Pré-requisito

- GATE F2 aprovado
- 1+ tenant usando em produção com sucesso
- Evidência de mercado querendo a solução

### Definição

Considerar a Fase 3 encerrada se TODOS os critérios forem cumpridos:

#### A. Multitenancy

- [ ] 3+ tenants ativos simultaneamente
- [ ] Isolamento verificado: tenant A não vê dados de tenant B
- [ ] Collection separada por workspace (ou filtro verificado)
- [ ] Queries nunca vazam entre tenants
- [ ] Onboarding de novo tenant funcional

#### B. Admin Panel

- [ ] CRUD de empresas funcionando
- [ ] Upload de documentos via UI funcional
- [ ] Métricas visíveis para operador
- [ ] Config de agente aplicável e efetiva
- [ ] Logs de conversa acessíveis

#### C. Segurança

- [ ] Auth implementado (Supabase ou equivalente)
- [ ] Roles: admin, operator, viewer testadas
- [ ] Logs de auditoria funcionando (quem fez o quê, quando)
- [ ] Dados isolados por tenant

#### D. SLA

- [ ] Uptime >= 99% (medido por 7 dias consecutivos)
- [ ] p99_latency < 3s em queries normais
- [ ] error_rate < 2%
- [ ] Health check endpoint funcional

#### E. Observabilidade

- [ ] Dashboard de métricas acessível
- [ ] Alertas configurados: uptime < 99%, latência > 5s, error_rate > 5%
- [ ] Logs de sistema disponíveis para debugging
- [ ] Tracing de queries (request_id → query → retrieval → answer)

#### F. Frontend Enterprise Final

- [ ] Login e navegação por perfil funcionando
- [ ] Painel administrativo completo
- [ ] Dashboard executivo funcional
- [ ] Operação multiempresa acessível por interface visual
- [ ] A experiência final é compatível com uso comercial por usuários não técnicos

---

## Checklist de Gate

```
GATE F0:
  [ ] A. Infraestrutura (12 itens)
  [ ] B. Retrieval Quality (4 itens)
  [ ] C. Answer Quality (4 itens)
  [ ] D. Observabilidade (3 itens)
  [ ] E. Documentação (5 itens)

GATE F1:
  [ ] A. Baseline Estável (3 itens)
  [ ] B. Telemetria (4 itens)
  [ ] C. Reranking (4 itens)
  [ ] D. Avaliação (4 itens)
  [ ] E. Tuning (4 itens)
  [ ] F. Melhoria vs Baseline (2 itens)

GATE F2:
  [ ] A. Estratégias Testadas (5 itens)
  [ ] B. Benchmark Controlado (4 itens)
  [ ] C. HyDE (4 itens)
  [ ] D. Citações e Grounding (3 itens)
  [ ] E. Melhoria vs F1 (2 itens)

GATE F3:
  [ ] A. Multitenancy (5 itens)
  [ ] B. Admin Panel (5 itens)
  [ ] C. Segurança (4 itens)
  [ ] D. SLA (4 itens)
  [ ] E. Observabilidade (4 itens)
```

---

## Notas Importantes

1. **Gate não aprovado = não avança.** Não existe "aprovar com ressalvas". Todas as falhas precisam ser corrigidas.

2. **Evidência > intuição.** Se um critério não pode ser provado com dados, não está aprovado.

3. **Teste manual é válido.** Não precisa de automação para validar gates iniciais. Teste manual spot-check é aceitável.

4. **Logs são evidência.** Se está logado, aconteceu. Se não está logado, não aconteceu.

---

## Próximo Passo

Ir para `0014-riscos-custos-e-decisoes.md` — riscos, custos e decisões.
