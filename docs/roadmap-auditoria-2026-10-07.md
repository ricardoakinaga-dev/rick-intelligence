# Roadmap de remediação RICK Intelligence

**Data:** 07/10/2026. **Estado:** planejamento proposto a partir da auditoria de 07/10/2026;
**M0 e M1 concluídos** (AUD07-01–14: A02/A03 fechados e discriminados, A04 coberto pela
política default-deny de rotas, A16 fail-closed no wrapper de resiliência) — ver
[`fix-gates-1.md`](reports/evidence/auditoria-2026-10-07/fix-gates-1.md),
[`fix-gates-2.md`](reports/evidence/auditoria-2026-10-07/fix-gates-2.md),
[`route-policy.md`](reports/evidence/auditoria-2026-10-07/route-policy.md) e
[`resilience-fail-closed.md`](reports/evidence/auditoria-2026-10-07/resilience-fail-closed.md).
**M2 em curso** — AUD07-15, AUD07-17, AUD07-18 e AUD07-19 concluídas: ver
[`npm-supply-chain.md`](reports/evidence/auditoria-2026-10-07/npm-supply-chain.md),
[`python-typecheck.md`](reports/evidence/auditoria-2026-10-07/python-typecheck.md),
[`evidence-destination.md`](reports/evidence/auditoria-2026-10-07/evidence-destination.md)
(evidência de 1,86 GB → 411 ficheiros/≈3,5 MB na árvore, resto na bolsa *content-addressed*) e
[`untracked-hygiene.md`](reports/evidence/auditoria-2026-10-07/untracked-hygiene.md)
(`git status` 241 → 238 `??` com `.opencode/` e `.agent/*.lock` ignorados — a regra `uv.lock`
foi revertida por ser artefacto de verificação; checkout limpo = 0 linhas; `make ci`/`make test`
= 0 crescimento; regressão `scripts/phase11/test_untracked_hygiene.py`; E4 prova que, com os
inputs de CI trackeados, um checkout novo dá `make validate` = 0).
**AUD07-43 em curso** — as 7 falhas de CI do checkout novo (run `37768041811`, 08/10/2026)
foram remediadas e confirmadas no push `4d2ac2c`: phase-1.3, phase-1.3.1, phase-1.4 e
phase-1.5 verdes; PHASE3 `--verify` permanece vermelho **por decisão de 08/10/2026
(deixar vermelho e registar)**, `State of Art / release integrity` segue vermelho por
evidência de runtime não vinculada (pré-existente desde 10/09) e `phase-1.6` está em
diagnóstico — sem alteração de gates — ver
[`ci-lanes-remediation.md`](reports/evidence/auditoria-2026-10-07/ci-lanes-remediation.md).
**Baseline:** 64,2/100 em 26 áreas, 20 achados (A01–A20); prontidão `NO-GO`.

Este roadmap organiza o caminho do checkout atual até um candidato promovível a produção. A
primeira entrega é um candidato local em que os cinco gates vermelhos
(`validate`, `lint`, `test-fast`, `api-security`, `build`) voltam a passar e os dois defeitos
reproduzidos (A02, A03) têm regressões discriminantes. A entrega final depende de execução real
sobre serviços externos, evidência operacional selada e decisão de promoção vinculada ao
candidato.

O [backlog desta rodada](backlog-auditoria-2026-10-07.md) detalha **43 tarefas AUD07** com
dependências e critérios de aceite. O [relatório da auditoria](reports/relatorio-auditoria-2026-10-07.md)
preserva notas, achados A01–A20, comandos, exit codes e limites. Este planejamento não altera os
estados de execução em `.agent/` nem inicia as correções.

## Ponto de partida

O corte auditado tem HEAD `b52f32c` com **889 mudanças pendentes** (219 modificados, 439
apagados, 231 não rastreados, `+23.745/−3.532`). Nenhuma evidência pode ser vinculada a um
candidato identificável até que essa árvore seja selada — por isso AUD07-01 precede todo o
resto.

A matriz local rendeu **≈ 7.175 testes verdes** em oito lanes e **339 testes de navegador**,
com 92,14% de linhas no web. Ao mesmo tempo, cinco gates obrigatórios estão vermelhos por
motivos distintos e conhecidos: legados ausentes (A01), artefato de build obsoleto (A05),
registro de política incompleto (A04), testes apontando para caminhos apagados (A06) e
bootstrap irreproduzível (A08). Corrigir esses cinco é a condição mínima para qualquer
candidatura.

O relatório registrou 20 achados: 7 de prioridade P0, 11 de P1 e 2 de P2. A02 e A03 foram
reproduzidos ao vivo nesta rodada e têm precedência sobre qualquer trabalho de expansão.

## Etapas e entregas

| Marco | Resultado esperado | Tarefas | Condição de saída |
|---|---|---|---|
| **M0 Baseline selada e gates verdes locais** | Candidato identificável com `validate`, `lint`, `test-fast`, `api-security` e `build` passando | AUD07-01–09 | `make ci` retorna 0 em checkout limpo; reproduções A02/A03 preservadas com hash |
| **M1 Defeitos de integridade e autorização** | Idempotência e lifecycle de coleção têm regressões que rejeitam a baseline; toda rota está na política default-deny; `production_safe` defaulta sem probe | AUD07-10–14 | A02, A03, A04 e A16 corrigidos com testes que falham antes e passam depois; `make api-security` verde |
| **M2 Confiabilidade da toolchain** | Bootstrap reproduzível, type-checker Python, dependências sem alerta, árvore limpa, lanes de CI verdes | AUD07-15–21, 43 | Checkout novo instala só dos locks e roda as suites sem `PYTHONPATH` manual; `npm audit` 0 HIGH; `git status` limpo; os 7 workflows do run de referência passam |
| **M3 Documentação e testes coerentes** | README/índice refletem o checkout; lanes raiz materializadas; skips classificados | AUD07-22–26 | 0 links quebrados em primário/plans/reports; inventário de skips com gate |
| **M4 Candidato integrado local** | Todas as suites locais, contrato, build e navegador executam juntas no candidato | AUD07-27 | `make ci`, `make api16-full`, `make web-validate` verdes no mesmo SHA |
| **M5 Integração com serviços reais** | PostgreSQL, Redis, Qdrant, object-storage e provider exercitados de ponta a ponta | AUD07-28–33 | Golden path, isolamento multi-tenant, revogação e publicação comprovados com teardown |
| **M6 Operação, performance e recuperação** | Restauração, capacidade, falhas e soak medidos contra budgets definidos antes | AUD07-34–38 | RPO/RTO, p50/p95/p99, chaos e soak dentro dos budgets aprovados |
| **M7 Evidência, reauditoria e promoção** | Release deriva de evidência atual, selada e vinculada ao candidato | AUD07-39–42 | Pacote de promoção gerado, reauditoria concluída e Go/No-Go explícito |

## Sequência e trabalho em paralelo

A sequência de aceite é **M0 → M1/M2/M3 → M4 → M5 → M6 → M7**. M1, M2 e M3 podem avançar em
paralelo depois que AUD07-01 selar a baseline; M4 exige a integração deles.

| Frente | Pode começar | Coordenação necessária |
|---|---|---|
| Reconciliação legados (A01) | Imediatamente após AUD07-01 | Toca README, `check_boundaries.py`, Makefile e 5 workflows; um único integrador |
| Idempotência e lifecycle (A02/A03) | Imediatamente após AUD07-01 | Compartilham `chat_service`/`retrieval_service`; não executar alterações concorrentes no mesmo arquivo |
| Política de rotas (A04) | Imediatamente após AUD07-01 | `routes/__init__.py` e `routes/knowledge.py`; independente das outras frentes |
| Toolchain e CI (A08/A09/A10) | Imediatamente após AUD07-01 | Locks e workflows; preservar pinagem por SHA e `--require-hashes` |
| Higiene e versionamento (A11/A12) | Imediatamente após AUD07-01 | Pode bloquear commits das outras frentes; resolver primeiro |
| Documentação (A13) | Após decisão sobre legados | Depende de AUD07-02/03 para não reescrever duas vezes |
| Integração real (A15) | Após M4 | Requer endpoints, credenciais, dados permitidos e teardown autorizados |
| Qualidade de IA (A14) | Após M4 | Requer corpus autorizado, direitos e adjudicação |

As dependências explícitas do backlog prevalecem sobre o paralelismo sugerido aqui.

## Gates de passagem

### G1 Correção local

Cada bug precisa de reprodução que falha na baseline e passa após a correção, com os resultados
originais preservados. Casos positivos, compatibilidade e isolamento continuam funcionando. Uma
revisão separada confere os P0; a conclusão de quem implementou não substitui essa revisão.

### G2 Candidato reproduzível

CI e suites executam no checkout limpo do candidato, com dependências instaladas dos locks e sem
pacotes extras do host. Todos os gates obrigatórios retornam sucesso. Os skips são classificados;
os obrigatórios para o gate seguinte executam. Cobertura informa denominador e exclusões.

### G3 Integração autorizada

Identificar endpoints, credenciais, dados permitidos, limites de recurso e teardown antes da
execução. Exercer tenant A/B, revogação, reinício, replay, falha de provider e publicação
concorrente nos serviços reais. Resultados locais anteriores não substituem essa prova.

### G4 Operação comprovada

Definir budgets de RPO/RTO, latência, erros, memória e duração **antes** dos ensaios. Medir
restore e capacidade com a mesma versão e topologia. Ausência de amostras permanece `no_data`;
falha ou ausência de artefato não vira `PASS`.

### G5 Promoção

CI, evidências de runtime, imagens, scans, assinaturas e pareceres identificam o mesmo candidato
e seus digests. A nota média pode ser recalculada na reauditoria; **não é condição suficiente
para promover**. Um gate obrigatório `NOT_RUN`, `BLOCKED_EXTERNAL`, `STALE` ou falho mantém
`NO-GO`.

## Dependências externas e decisões

| Dependência | Tarefas afetadas | Preparação possível agora |
|---|---|---|
| Decisão sobre os três componentes legados | AUD07-02, 03, 04 | Levantar o que ainda é consumido e o que é só documentação |
| PostgreSQL, Redis, Qdrant, S3 e provider de teste | AUD07-28–33 | Preparar harnesses, namespaces descartáveis e negativos |
| Corpus representativo, direitos e revisão de domínio | AUD07-31 | Definir desenho da avaliação, splits e campos de proveniência |
| IdP/OIDC externo e múltiplas réplicas | AUD07-30 | Definir escopo de revogação e janelas de cache |
| Collector, alert routing e ensaios de falha | AUD07-34–38 | Definir sinais, budgets, carga e condições de aborto |
| Registry, assinatura, revisão e autoridade de promoção | AUD07-39–42 | Preparar manifesto e pacote sem declarar promoção |

Consultar os [bloqueadores externos](reports/external-evidence-blockers.md) e o
[runbook de release](operations/release-readiness.md). A existência desses documentos não
comprova que a dependência já esteja disponível.

## Priorização e estimativa

Executar primeiro **AUD07-01** (selar baseline) e, em paralelo, os P0 de gates vermelhos
(**AUD07-02, 05, 06, 07, 08**) e de integridade (**AUD07-10, 11, 12**). Em seguida fechar as
frentes de toolchain e documentação que sustentam o M2/M3. Integração real (M5) só começa depois
de M4 verde.

O backlog usa tamanhos relativos P/M/G. **Não há calendário prometido**: faltam capacidade da
equipe, ambiente e decisões externas. Após AUD07-01, o responsável pelo projeto pode distribuir
as tarefas em ciclos conforme disponibilidade e resultados.

## Primeira entrega

1. **AUD07-01** — selar a baseline e preservar as reproduções de A02/A03.
2. Em paralelo: **AUD07-05/06/07/08** (gates verdes) e **AUD07-10/11/12** (defeitos P0).
3. Integrar num único candidato e executar **AUD07-27** antes de buscar qualquer evidência de
   runtime.
