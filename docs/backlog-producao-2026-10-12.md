# Backlog proposto — RICK Intelligence em produção

**Data:** 12/10/2026. **Base inspecionada:** `48e383c25ca4af32aa7ffe7e2367360ca9742c58`. **Estado:** PROPOSTO, 56 tarefas, nenhuma implementação/execução de runtime iniciada por este documento. **Promoção:** NO-GO.

Fontes: [baseline de 12/10](<reports/baseline-producao-2026-10-12.md>), [backlog AUD07](<backlog-auditoria-2026-10-07.md>), [retomada de 09/10](<reports/retomada-2026-10-09.md>), [roadmap deste programa](<roadmap-producao-2026-10-12.md>) e contratos vigentes de [release](<architecture/release-integrity.md>), [autoridade](<architecture/promotion-authority.md>), [SLO](<operations/slo.md>) e [rollout](<../infrastructure/docker/rollout-policy.json>).

## Autoridade, status e escopo

- Este backlog é **especificação de trabalho proposto**, não um segundo ledger de execução. Todos os itens têm estado inicial de planejamento **PENDING / não adotado**. Ao iniciar a implementação, PROD12-002 deverá vincular/adotar os IDs no [backlog do controlador](<../.agent/backlog.json>) por procedimento aprovado; ele será o único owner de status, aceite e evidência. Este Markdown mantém contratos/dependências e aponta para o controlador; não manter dois status editáveis.
- IDs PROD12 não encerram AUD07/Q17/Q24/R27/AUD26/AUD03. A matriz de continuidade abaixo preserva os IDs antigos. Conclusões locais existentes são revalidadas no candidato novo, não automaticamente reimplementadas ou promovidas.
- `AUD12-A01…A13` significa achado de **12/10**, distinto dos A01…A20 da auditoria de 07/10. Papéis responsáveis são sugestões, não pessoas já designadas.
- **P0:** integridade/segurança reproduzida ou pré-condição obrigatória derrotada. **P1:** funcionalidade/confiabilidade/evidência necessária para promoção. **P2:** documentação/manutenção. Prioridade não elimina dependência nem transforma item obrigatório em opcional.
- Tamanho **P/M/G** é relativo: delimitado / múltiplas fronteiras / execução distribuída ou decisão incerta. Não é promessa de prazo; itens G são subdivididos em subtarefas após pré-condições conhecidas.
- **Obrig.=Sim** bloqueia conclusão do marco correspondente. **Obrig.=Não** é melhoria advisory e não autoriza enfraquecer gates existentes. PROD12-019 é o único advisory, para evitar uma reescrita ampla como pré-requisito artificial de produção.
- Aprovação do planejamento não autoriza automaticamente instalar, cobrar providers, alterar permissões do host, aplicar DDL, destruir volumes, publicar imagens, dar push/dispatch, usar dados pessoais ou implantar. Cada operação depende de autorização e ownership próprios.

### Aceite comum de qualquer tarefa

1. Preservar baseline e registrar SHA/tree/fingerprint, escopo, ambiente, versões, procedimento, exit code/resultado, hora UTC, hashes, artefatos, limitações, reviewer e próximo passo.
2. Bug confirmado: regressão rejeita o comportamento anterior e passa após correção, incluindo sucesso e falhas. Achado estático/condicional: primeiro reproduzir; se não confirmado, registrar resultado e disposição, não declarar uma correção fictícia.
3. Nenhum teste removido/skip introduzido para fabricar PASS; nenhuma redução dos floors/gates/controles. Probes que reproduzem defeito podem sair 0 sem aprovar o sistema.
4. Revisão independente para identidade, escopo, dados, worker, segurança e release. Builders não aprovam o próprio trabalho. Um revisor automatizado da sessão não satisfaz sozinho a autoridade humana de promoção.
5. `NOT_RUN`, `BLOCKED_EXTERNAL`, `FAIL`, `STALE`, skip e `no_data` permanecem não-PASS. Uma evidência anterior só é reutilizada quando o validador vigente permite e vínculo/frescor/ambiente continuam válidos.
6. Plano de rollback/roll-forward ou recuperação proporcional; preservar dados e histórico. Toda prova externa usa projeto/fixtures/credenciais autorizados e condições de aborto/teardown previamente definidas.
7. Mudança de candidato/configuração/topologia invalida as provas afetadas: retornar ao marco pertinente e repetir, não editar timestamps/checksums para reciclar aceite.

## Fila e dependências

Dependências numéricas usam o prefixo PROD12 e são **AND**; intervalos incluem todos os IDs. Preparação pode avançar antes, aceite não. Mapeamento PENDING é inicial de planejamento, não status do controlador.

| ID | Marco | Pri | Tam | Dono sugerido | Dependências | Obrig. | Origem |
|---|---|---|---|---|---|---|---|
| PROD12-001 | M0 | P0 | M | Lead/QA | — | Sim | baseline AUD12 |
| PROD12-002 | M0 | P0 | M | Lead/control plane | 001 | Sim | A06; continuidade AUD07-43 |
| PROD12-003 | M0 | P1 | M | QA/plataforma | 001 | Sim | cinco falhas ambientais |
| PROD12-004 | M0 | P0 | M | Produto/segurança/release | 001 | Sim | decisões atuais e autoridade |
| PROD12-005 | M0 | P1 | M | SRE/domínio/provider | 004 | Sim | SLO, RPO/RTO, corpus, custos |
| PROD12-006 | M0 | P1 | M | Operações/segurança | 004,005 | Sim | recursos/autorização externa |
| PROD12-007 | M1 | P0 | M | Identidade/API | 001 | Sim | AUD12-A01 |
| PROD12-008 | M1 | P0 | M | Worker | 001 | Sim | AUD12-A02 |
| PROD12-009 | M1 | P0 | M | Worker | 008 | Sim | AUD12-A03 |
| PROD12-010 | M1 | P0 | M | Worker/plataforma | 008,009 | Sim | A02/A03; teardown |
| PROD12-011 | M1 | P0 | M | API/segurança | 001,005 | Sim | AUD12-A04 |
| PROD12-012 | M1 | P1 | M | Identidade/segurança | 007,011 | Sim | AUD12-A05: spray |
| PROD12-013 | M1 | P1 | P | API/segurança | 012 | Sim | AUD12-A05: memória |
| PROD12-014 | M1 | P1 | M | Segurança/browser | 004,007 | Sim | CSRF condicional/A12 |
| PROD12-015 | M2 | P0 | M | Evidência/supply chain | 001,004 | Sim | AUD12-A13 |
| PROD12-016 | M2 | P1 | M | Plataforma/CI | 002,003,015 | Sim | A12; bootstrap |
| PROD12-017 | M2 | P1 | G | API/worker/qualidade | 007–014,016 | Sim | AUD12-A11: tipos |
| PROD12-018 | M2 | P1 | G | QA/API/web | 017,021–025 | Sim | AUD12-A11: cobertura |
| PROD12-019 | M2 | P2 | G | Arquitetura/domínios | 017,018 | Não | A11: concentração de módulos |
| PROD12-020 | M2 | P2 | M | Documentação/Lead | 014,016,021–025 | Sim | AUD12-A12 |
| PROD12-021 | M2 | P1 | M | Web/casos | 001,004 | Sim | AUD12-A07 |
| PROD12-022 | M2 | P1 | M | Web/chat/API | 001 | Sim | AUD12-A08 |
| PROD12-023 | M2 | P1 | P | Web/chat | 022 | Sim | AUD12-A09 |
| PROD12-024 | M2 | P1 | P | Web/documentos | 001 | Sim | AUD12-A10 |
| PROD12-025 | M2 | P1 | M | Web/acessibilidade | 021–024 | Sim | foco/resize e matriz visual |
| PROD12-026 | M2 | P0 | G | Integrador/QA/reviewer | 002,003,007–018,020–025 | Sim | AUD07-27; candidato local |
| PROD12-027 | M3 | P1 | G | SRE/segurança/DBA | 004–006,026 | Sim | topologia production-shaped |
| PROD12-028 | M3 | P0 | G | Release/supply chain | 016,026,027 | Sim | AUD07-39 |
| PROD12-029 | M3 | P0 | G | SRE/runtime | 006,027,028 | Sim | lab/readiness/autorização |
| PROD12-030 | M3 | P0 | G | DBA/worker | 029 | Sim | migrations/PostgreSQL |
| PROD12-031 | M3 | P1 | G | SRE/segurança | 012,029 | Sim | Redis e API A/B |
| PROD12-032 | M3 | P1 | G | Storage/retrieval | 029,030 | Sim | S3/Qdrant reais |
| PROD12-033 | M4 | P1 | G | Provider/RAG | 004–006,029 | Sim | provider/embeddings |
| PROD12-034 | M4 | P0 | G | Ingestão/QA | 030–033 | Sim | AUD07-28 |
| PROD12-035 | M4 | P0 | G | Identidade/segurança | 007,014,030,031,034 | Sim | AUD07-29/30 |
| PROD12-036 | M4 | P0 | G | Worker/DBA | 010,030,034 | Sim | AUD07-32 |
| PROD12-037 | M4 | P1 | G | Ingestão/segurança | 005,034,036 | Sim | AUD07-33 |
| PROD12-038 | M4 | P1 | G | RAG/domínio/dados | 005,033–035 | Sim | AUD07-31 |
| PROD12-039 | M4 | P0 | G | Segurança/evidência | 034–038 | Sim | negativos tenant/evidence/RAG |
| PROD12-040 | M4 | P1 | G | Casos/DBA/domínio | 004,021,030,035,039 | Sim | D04/persistência clínica |
| PROD12-041 | M4 | P1 | G | QA/web/acessibilidade | 021–025,034,035,038–040 | Sim | frontend real |
| PROD12-042 | M4 | P1 | G | Segurança independente | 035–041 | Sim | revisão/ataques autorizados |
| PROD12-043 | M5 | P1 | G | Observabilidade/SRE | 029,034–036,039 | Sim | AUD07-34 |
| PROD12-044 | M5 | P1 | G | Auditoria/DBA/SRE | 030,035,043 | Sim | audit/outbox/DLQ |
| PROD12-045 | M5 | P0 | G | Recovery/DBA/SRE | 032,036,040,043,044 | Sim | AUD07-35; rollback |
| PROD12-046 | M5 | P1 | G | Performance/SRE | 005,034,038,041,043,044 | Sim | AUD07-36 |
| PROD12-047 | M5 | P1 | G | Resiliência/SRE | 006,036,042,045,046 | Sim | AUD07-37 |
| PROD12-048 | M5 | P1 | G | SRE/performance | 046,047 | Sim | AUD07-38 |
| PROD12-049 | M5 | P1 | M | Operações/segurança/produto | 004,040,043–048 | Sim | on-call, privacidade, runbooks |
| PROD12-050 | M6 | P0 | G | CI/release/Lead | 026,028,034–049 | Sim | AUD07-40/43; frescor |
| PROD12-051 | M6 | P0 | G | Reviewers independentes | 050 | Sim | AUD07-41; 12 escopos |
| PROD12-052 | M6 | P0 | M | Signer/release independente | 050,051 | Sim | packet/seal/trust |
| PROD12-053 | M6 | P0 | M | D07/signer independente/release | 004,049,052 | Sim | AUD07-42; Go/No-Go e selo |
| PROD12-054 | M7 | P0 | G | Operador/release | 027,045,049,053 | Sim | canary autorizado |
| PROD12-055 | M7 | P1 | G | Operador/on-call/produto | 054 | Sim | expansão controlada/handoff |
| PROD12-056 | M7 | P1 | G | SRE/produto/segurança | 055 | Sim | acompanhamento real/SLO |

## M0 — Governança e baseline

### PROD12-001 — Preservar baseline e mapa de obrigações

**Entrega:** preservar relatório/probes/saídas da auditoria, hashes e os primeiros resultados falhos; materializar fixtures sintéticas e testes discriminantes em local aprovado. O [sumário da baseline](<reports/baseline-producao-2026-10-12.md>) não substitui logs/provas originais. Mapear achados, 26 dimensões e obrigações AUD07 à fila.

**Aceite/verificação:** toda origem tem tarefa/critério/owner e evidência; A01–A05 reproduzidos em harness isolado, A07–A10 tratados como estáticos até browser; resultado 7.713/6/221 preservado sem promoção. Nenhum encerramento automático de tarefa histórica. Hash do mapa/reproduções registrado.

### PROD12-002 — Recuperar plano de controle e adotar ownership único

**Entrega:** revisar [restaurador](<ci/restore_control_inputs.py>) e estado existente, recuperar/revincular run ao checkout por procedimento explícito, com backup e decisão; reconciliar convenções obsoletas de [planos do controlador](<../.agent/PLANS.md>) com a retirada dos legados. Adotar IDs/escopo/dependências propostos sem alterar o passado.

**Aceite/verificação:** caminho alternativo/clone limpo e retomada validam run/refs; candidato errado/run divergente continua rejeitado. `make control-inputs-check` e `make validate` passam quando os demais inputs aplicáveis estiverem íntegros. Histórico/assinaturas não reescritos; um owner de status. Não resolver A06 por simples busca/substituição de caminhos em ledgers.

### PROD12-003 — Obter executor compatível e diagnosticar cinco falhas ambientais

**Entrega:** declarar UID/GID, namespace, filesystem, sticky bit e capabilities exigidos pelos testes VPS; fornecer executor descartável compatível. Melhorar diagnóstico de precondições e de EINVAL quando necessário, sem relaxar guards de ownership/symlink/hardlink.

**Aceite/verificação:** reexecutar os cinco node IDs falhos da baseline em ambiente compatível e comprovar cenários positivos/negativos. Unsupported continua BLOCKED/NOT_RUN para esse gate, não PASS. Não chmod/chown de áreas do host ou privilégio extra sem autorização. Testes de segurança Linux têm evidência real, não só fixture simulada.

### PROD12-004 — Ratificar perfil do lançamento e autoridades

**Entrega:** documento datado com produto, tenants/capacidade, funcionalidades obrigatórias, owners/authority, regiões/dados/retention e limites. Confirmar escolhas existentes: [contas internas postgres-local-v1 e providers](<operations/vps-github-images.md#L337-L342>), [D04 intake amplo com revisão humana](<architecture/domain-decision-policy-2026-09-24.md#L3-L29>). A escolha não prova runtime ou segurança clínica.

**Aceite/verificação:** identidade, provider/modelo de chat, embeddings/dimensão, cases, política clínica, topologia, corpus/direitos e D07 têm owner e limites atuais. OIDC não é obrigatório só porque AUD07-30 usou esse título: executar o contrato da identidade aprovada; se IdP escolhido, implementar/revisar composição real separadamente. Não habilitar OIDC apenas por URLs, diagnóstico/prescrição autônomos ou módulo pessoal sem aprovação. Perfil limitado não dispensa gates atuais.

### PROD12-005 — Congelar budgets, carga, avaliação e aborto

**Entrega:** aprovar SLO/SLI, quotas de busca/login/recovery/provider, máximo de custo/tokens/contexto, limites parser, retenção/memória, dataset/splits/adjudicação, capacidade, duração soak e RPO/RTO. Reusar [pontos iniciais de SLO](<operations/slo.md#L48-L56>) e [canary/rollback](<../infrastructure/docker/rollout-policy.json>); não inventar resultados ou baixar targets.

**Aceite/verificação:** valores, owners, workload, janelas/amostras, incerteza, abort conditions e coleta definidos **antes** dos ensaios. Pontos iniciais ratificados ou proposta de alteração formalmente aprovada e rastreável. RPO/RTO/custo não definidos continuam bloqueadores. Não ajustar target após resultado ruim para obter aceite.

### PROD12-006 — Autorizar e provisionar inputs externos

**Entrega:** inventário seguro de daemon/projeto, namespaces/buckets/volumes, DNS/TLS, endpoints/roles, corpus sintético/autorizado, provider/account, registry/signer, reviewers e alert receiver; estimar custo/recursos. Separar autorizações lab, DDL, fault/restore, publication e produção.

**Aceite/verificação:** recursos exclusivos identificados, operador nomeado, acesso mínimo, teardown/backup/aborto aprovados; segredos por referência ao secret manager, não no documento. Detectar ausência como BLOCKED_EXTERNAL. Não adotar um serviço existente do host como laboratório por conveniência.

## M1 — Segurança e integridade críticas

Fontes principais: [adaptador PG](<../apps/api/src/services/postgres_identity.py>), [auth](<../apps/api/src/routes/auth.py>), [limiter](<../apps/api/src/core/rate_limit.py>), [search](<../apps/api/src/routes/search.py>), [CSRF](<../apps/api/src/core/csrf.py>), [runtime worker](<../apps/worker/runtime.py>) e [composição](<../apps/worker/deployment_composition.py>).

### PROD12-007 — Tornar logout honesto e revogação recuperável

**Entrega:** propagar erro tipado da revogação ao contrato HTTP, sem responder `signed_out` quando ela não foi confirmada; política de cookie/retry e auditoria de tentativa versus conclusão explícitas.

**Aceite/verificação:** storage indisponível não produz sucesso falso nem detalhe sensível; sucesso invalida token, falha preserva estado não confirmado e permite retry seguro. Regressão HTTP com falha injetada rejeita baseline; depois verificar PG/revogação real em 035. Não confundir apagar cookie com invalidar bearer copiado.

### PROD12-008 — Corrigir drain no shutdown repetido

**Entrega:** separar admissão fechada de parada concluída e recalcular relatório para ativos ainda executando. Não declarar `drained=True` com `active>0`.

**Aceite/verificação:** handler retido por Event: primeira e segunda chamadas com timeout mantêm indicação de trabalho não drenado; após término, relatório correto/idempotente. Timeout/deadline/cancel/logical_done e wait_for_idle exercitados sem sleeps frágeis. Regressão A02 falha antes/passa depois.

### PROD12-009 — Coordenar shutdown com claims em voo

**Entrega:** contabilizar/invalidar claims pendentes e tornar admissão de handler atômica com fechamento; definir devolução/reconciliação de lease adquirida depois do stop.

**Aceite/verificação:** claim suspenso por Event e shutdown concorrente não iniciam handler depois do fechamento; não há lease órfã/ACK indevido, deadlock ou excedente de concorrência. Regressão A03 rejeita baseline; perda de lease, cancel e erro de claim incluídos. Mesmo owner de 008, não dois writers de runtime.

### PROD12-010 — Impedir teardown de dependências ainda em uso

**Entrega:** composição só fecha stores/provider quando parada realmente concluída; reports inconsistentes são rejeitados e closers falhos podem ser tentados novamente sem double-close.

**Aceite/verificação:** recursos spies permanecem abertos durante ativo/claim/timeout; fechamento único após drain, shutdown repetido/cancel/SIGTERM simulado e closers com falha. Timeout é visível, nunca sucesso falso. SIGTERM/crash reais em 036.

### PROD12-011 — Limitar busca e concorrência antes do retrieval

**Entrega:** aplicar quota/rate limit por ator/tenant e política de concorrência/custo ratificada em 005; requests caros não iniciam embedding/store após negação. Preservar autorização, erros e compatibilidade HTTP.

**Aceite/verificação:** limiter negativo → 429 e zero chamadas retrieval/provider; backend do limiter indisponível → falha segura definida, sem fallback local em produção. Positivos, Retry-After, escopo e limites em body/top_k preservados; concorrência/cancel/timeout testados. Política compartilhada comprovada em 031/035/046.

### PROD12-012 — Bloquear spray com buckets independentes

**Entrega:** IP/rede confiável, conta e tenant têm proteções independentes conforme threat model, sem armazenar PII crua em labels/chaves; preservar neutralidade de recuperação e minimizar risco de lockout induzido.

**Aceite/verificação:** alternar emails no mesmo IP não contorna teto global aprovado; contas/tenants diferentes não compartilham bucket acidental; forwarded spoof ignorado sem proxy autorizado; paralelo/TTL/Redis unavailable fail-closed. Fake/distribuído separados; não afirmar proteção multi-replica pelo teste local.

### PROD12-013 — Limitar cardinalidade do limiter local

**Entrega:** bound de chaves/eventos, expiry global e comportamento de capacidade definido, com relógio injetável e contenção segura.

**Aceite/verificação:** carga de chaves arbitrárias não supera orçamento de memória/cardinalidade de 005; chaves expiradas removidas mesmo sem revisita; threads e capacidade/overflow testados. Nenhum bypass ao atingir limite; produção continua recusando limiter local.

### PROD12-014 — Verificar e endurecer contrato CSRF/origin

**Entrega:** reproduzir condições de cookie injection/subdomínio/CORS de forma isolada; documentar ameaça e política real. Se risco confirmado/aplicável, implementar defesa revisada (por exemplo vínculo verificável do nonce/origin), não presumir arquitetura sem teste.

**Aceite/verificação:** cookie/bearer precedence, origem autorizada/negada, nonce inválido/expirado/injetado, login/logout/reset e proxy cobertos. Se hipótese não reproduzida, registrar limites e parecer independente, não alegar exploit nem fake fix. Double-submit/configured token/origin condizem com documentação; sem reduzir restrições existentes.

## M2 — Produto e candidato local reproduzível

### PROD12-015 — Classificar snapshots e limpar inventário ativo

**Entrega:** aprovar destino/provenance dos 36 arquivos do snapshot runtime; preservar hashes/recuperabilidade fora do inventário de componentes ativos. Alinhar scanner/locks/SBOM/licenses por política explícita, não ampliar inventário para fingir que cópia histórica é app ativo.

**Aceite/verificação:** [teste de inventário](<../scripts/state_of_art/tests/test_frontend_supply_runtime.py#L208-L214>) passa em clone e checkout atual; snapshot recuperável por manifest/hash; componente novo não classificado, manifesto/lock ausente e segredo real continuam falhando. Zero apagamento de evidência/dados sem aprovação. A13 isolado e suíte global reexecutados.

### PROD12-016 — Bootstrap/toolchain e CI locais reproduzíveis

**Entrega:** instalação exclusiva de locks/hashes na toolchain declarada; detectar runtime efetivo Python/Node/npm e drift. Preservar pinagem de Actions e separação local/runtime/release; corrigir somente defeitos atuais demonstrados.

**Aceite/verificação:** clone limpo em caminho diferente instala e roda gates sem dependências do host/PYTHONPATH manual; versão errada falha com diagnóstico. CI local não cresce lixo versionável. [Toolchain](<../toolchain.json>) preservada até decisão formal de alteração. Não reabrir automaticamente retirada legada/namespace/fixtures AUD07 concluídas.

### PROD12-017 — Expandir tipos nos caminhos de maior risco

**Entrega:** ampliar mypy de contratos/autorização para seams de auth/identity/rate limit, worker/composição, jobs e adapters críticos; inventário de escopo e baseline explícitos. Tipar inputs/erros/relatórios novos sem blanket Any/ignore.

**Aceite/verificação:** 13 arquivos atuais continuam zero erros; novos caminhos críticos têm gate executável e teste negativo que insere erro conhecido. Novos erros bloqueiam; erros herdados inventariados por responsável/risco, sem excluir silenciosamente módulos. TypeScript continua aprovado. Cada expansão é uma subtarefa revisável, não migração massiva.

### PROD12-018 — Ampliar cobertura e regressões discriminantes

**Entrega:** cobrir wrapper HTTP, chat/paginação, documentos/retry, search/admin/collections/casos e ramos Python de falha/concorrência; registrar total elegível, incluído, excluído e branches. Reusar [sumário existente](<reports/coverage-2026-10-09.md>) sem anunciar subset como todo app.

**Aceite/verificação:** preservar floors atuais API 75%, worker 74%, web 85% e testes existentes; expansão do denominador tem plano/floor explícito antes da medição, sem baixar gate antigo. A01–A10 têm regressões pertinentes e bugs de estado/concorrência são detectados; testes não só toast/resultado positivo. Pacotes compartilhados recebem coverage própria, não entram magicamente no denominador API. Branches críticos não testados geram tarefa/risco visível.

### PROD12-019 — Reduzir concentração de módulos por seams (advisory)

**Entrega:** após fixes/contratos, refatorações pequenas de ingestion_service/runtime/postgres_jobs/provider/Qdrant por fronteira testável, sem alterar comportamento para reduzir linhas.

**Aceite/verificação:** contrato/diferencial/regressões preservados, ownership claro, redução de acoplamento demonstrada e nenhuma nova política duplicada. Não exigir número mágico de linhas. Pode continuar após primeira produção: se uma extração for necessária à correção/segurança, sua parte passa ao item obrigatório correspondente com decisão explícita, não como waiver de risco.

### PROD12-020 — Atualizar documentação e contratos observáveis

**Entrega:** corrigir CSRF, histórico/streaming já entregues, provider/identidade/D04 e localidades dos testes; garantir índice, comandos, autoria de estados e limites de runtime coerentes. Atualizar docs por decisão, preservar snapshots históricos.

**Aceite/verificação:** checker de links sem erros; exemplos confrontados com código/contratos; README não promete produção/AAA; nenhum plano antigo vira autoridade concorrente. Revisão de conteúdo, não apenas links. Backlog/roadmap/controlador apontam para owners e aceites corretos.

### PROD12-021 — Vincular rascunhos ao caso correto

**Entrega:** reproduzir A→B e decidir UX: rascunho por case_id ou limpar/confirmar ao trocar; cancelar/invalidar respostas antigas e estado de outra sessão.

**Aceite/verificação:** nota/decisão/feedback de A nunca enviados em B; troca/reload/unmount/resposta tardia/tenant/permissão testados em unit e browser com feature habilitada. Feature desativada não escreve dados. Backend continua autoritativo; não gerar recomendação clínica autônoma.

### PROD12-022 — Paginar conversas e turnos ponta a ponta

**Entrega:** expor cursor no [cliente HTTP](<../apps/web/lib/api.ts>) e [adapter](<../apps/web/components/chat/chat-adapter.ts>), consumir páginas no workspace com ordenação/dedup/abort e indicação de carregamento/truncamento.

**Aceite/verificação:** ≥51 conversas e ≥101 turnos acessíveis após reload/load-more; cursor inválido, página vazia, filtros, deep-link, falha intermediária, troca de escopo e respostas fora de ordem cobertos. Sem duplicação/inversão/perda visual silenciosa; servidor não amplia escopo pelo cursor.

### PROD12-023 — Exibir autorização e confiança verdadeiras

**Entrega:** selo/sugestões/composer dependem de confirmação de escopo/permissão, não apenas existência de sessão; 403/revogação eliminam sucesso e conteúdo pendente.

**Aceite/verificação:** acesso direto sem chat.query, 403 da API, falha/offline e mudança de grant mostram estado neutro/negado correto; nenhuma afirmação falsa de corpus autorizado. Positivo mantém legibilidade/foco; UI não substitui ACL backend.

### PROD12-024 — Atualizar catálogo depois de retry publicado

**Entrega:** tratar publicação de upload/reindex/retry pelo mesmo contrato de refresh sem misturar collection/workspace de operações antigas.

**Aceite/verificação:** retry publicado mostra documento real no catálogo, não só mensagem; pending/failed/cancelled não mostram publicação; mudança de sessão, unmount e requests antigos não sobrescrevem catálogo atual. Teste browser confirma estado e requisições.

### PROD12-025 — Resolver focos e validar acessibilidade local

**Entrega:** reproduzir drawer mobile→desktop e fechar/inativar trap conforme viewport; revisar foco/modal/teclado/leitores/labels/contraste/reduced-motion nas rotas corrigidas.

**Aceite/verificação:** 375/768/1440 px, largura estreita/zoom e navegação completa de teclado sem foco preso/oculto; resize/open/close/focus return testados. Axe sem violações relevantes nas superfícies obrigatórias e smoke manual com tecnologia assistiva. Hipótese não confirmada documentada; evidência visual nativa preservada. Prova contra API real em 041.

### PROD12-026 — Integrar e congelar candidato local

**Entrega:** incorporar itens obrigatórios locais, executar matriz completa num SHA limpo com revisão separada; mapear todos os skips externos e warnings com owner/next gate.

**Aceite/verificação:** `make ci`, `make api-test api-contract api-security api14-acl api16-full`, `make compose-static ops-static eval-retrieval-pack security-adversarial storage-test web-validate` e suíte ampliada passam para o escopo local obrigatório na toolchain/FS compatíveis. As seis falhas originais têm resultados novos/causas, não somem; 221 skips reclassificados por gate, não contados como runtime. Nenhum P0/local obrigatório aberto. AUD07-27 continua com transição explícita, não aprovação por este documento. Review crítica P0/segurança/dados/web e fonte/diff/hash archivados.

## M3 — Ambientes e serviços reais

Ativos existentes: [Dockerfiles/runbook](<../infrastructure/docker/RUNBOOK.md>), [deploy VPS](<operations/vps-github-images.md>), [Compose de referência](<../infrastructure/compose/compose.reference.yml>), [runtime](<architecture/production-runtime.md>) e [integridade de release](<architecture/release-integrity.md>). Reusar; não criar Kubernetes/multirregião como requisito sem decisão.

### PROD12-027 — Preparar topologia e hardening de staging/produção

**Entrega:** ratificar VPS/topologia/HA conforme perfil, DNS/TLS, firewall/network/egress, least privilege, volumes persistentes/quotas, secret manager/rotation, cookies/origins/proxies. Separar roles bootstrap, aplicação, readonly e migration; source/installer protegidos quando privilégio obrigatório.

**Aceite/verificação:** stores/console não públicos, TLS verificado sem bypass, aplicações não-root, credenciais bootstrap/DDL não no runtime, canais e backups segregados. Install/validate/preflight oficiais revisados com ownership. Same-origin e destino API do build web corretos. Single VPS não declarado HA; risco/capacidade avaliados e aceitos quando permitido pelos gates.

### PROD12-028 — Construir e verificar imagens imutáveis

**Entrega:** CI clean-SHA produz API/worker/web, digests, SBOM, provenance, scans/licenças/segredos e assinaturas verificáveis; registry retenção e trust chain revisados. Publicar somente com autorização.

**Aceite/verificação:** código/testes/build/scans correspondem aos digests usados no staging; **zero HIGH/CRITICAL inclusive unfixed**, conforme rollout vigente; imagem não-root e conteúdo/labels comprovados. Assinaturas e origem verificadas, não só tag. Aplicar scanners atuais; PASS antigo de dependência não vale para novo candidato. Reconstruir exige revalidar digests/provas afetadas.

### PROD12-029 — Subir lab production-shaped e atestar readiness

**Entrega:** inicializar projeto isolado aprovado, bootstrap/migrations e API/web/worker A/B/stores/OTel com probes e shutdown bounded. Gerar preflight por produtor autorizado, não pelo próprio gate consumidor.

**Aceite/verificação:** 11 serviços canônicos saudáveis, API/Web probes reais; run/commit/tree/fingerprint/config hash/ownership/expiry vinculados. Ausência/queda/stale preflight recusados. Teardown prova zero recursos descartáveis órfãos e preserva volumes não pertencentes ao lab. Lab loopback prova integração, não substitui autoridade production-runtime de ambiente production-shaped aprovado.

### PROD12-030 — Aplicar migrations e provar integridade PostgreSQL

**Entrega:** inventariar migrations atuais, scope preflight, locks/checksums/history, empty/prior/current data e política roll-forward. Aplicar DDL só no banco aprovado; reconciliar conflitos explicitamente.

**Aceite/verificação:** migrations/preflight reais, constraints cross-tenant/workspace/collection negativas, rollback transacional/ownership/queue/outbox/history e reapply idempotente. Não presumir seis migrations de documento histórico. `make ops-scope-preflight`, `make phase3-postgres-runtime` com inputs válidos e relatório; nenhuma reparação automática de dados incompatíveis.

### PROD12-031 — Provar Redis e buckets entre réplicas

**Entrega:** Redis auth/TLS/TTL/namespace, leases/reconnect/failover e duas APIs no mesmo backend de limites; zero process-local fallback.

**Aceite/verificação:** `make phase3-redis-runtime phase3-redis-multi-replica-runtime` com observações reais; troca de API não reinicia quota de search/login/recovery; outages/timeouts/expiração/renovação/stale owner não abrem acesso. Sem leak de chaves/PII e memória bounded. Requisitos de replicação equivalentes ao perfil, sem alegar HA não provada.

### PROD12-032 — Provar lifecycle S3/Qdrant

**Entrega:** PUT/HEAD/GET/DELETE/checksum/length/version/retention scoped no object store; schema/dimensão/filtros/coleção/alias/rebuild/delete/restore no Qdrant. Autoridade continua em fonte durável, não no vetor.

**Aceite/verificação:** `make phase3-object-qdrant-runtime`, wrong scope/checksum/version/object negativos, partial failure/restart/reconcile sem leak/órfão consultável. Retenção/delete/restore coerentes com dados autorizados e metadados, checksum e proveniência. Embedding dimension aprovada compatível com coleção.

## M4 — Qualidade, segurança e produto ponta a ponta

### PROD12-033 — Validar provider e embeddings reais com orçamento

**Entrega:** fechar lacunas do adapter selecionado e exercitar chat nativo OpenAI ou Anthropic, embeddings OpenAI independentes, SSE/cancel/tool/JSON/errors/circuit/deadline/retry e quotas aprovadas. Outro endpoint exige composição revisada.

**Aceite/verificação:** `make phase3-provider-runtime` contra serviço autorizado, modelos/dimensão/capabilities compatíveis; 429/500/timeout/truncamento/refusal/cancel não produzem conclusão aprovada falsa; limites de tokens/tempo/saída/custo observados. Nenhum dado fora do corpus permitido enviado, nenhuma cobrança fora do teto. Stub não prova provider real.

### PROD12-034 — Golden path durável com recuperação

**Entrega:** upload→objeto→fila→worker→parse/chunk/embed→vetor→verify/publish→retrieval→evidence→decision→resposta→histórico, incluindo delete/reindex/retry/cancel/restart e lineage.

**Aceite/verificação:** `make phase3-golden-runtime` / `make phase3-provider-rag-runtime` com stores/provider reais; uma publicação lógica por operação, source/chunk/checksum/version corretos, falha parcial não aparece como publicado; replays/outbox/objetos reconciliados. Audit e dados após restart consistentes; artefatos vinculados ao candidato e fixtures autorizadas.

### PROD12-035 — Identidade e isolamento reais entre réplicas

**Entrega:** provar política de identidade escolhida: login/logout/TTL/disable/reset/role-grant-workspace revocation, cookies/CSRF/CORS, buckets compartilhados e escopo em objetos/jobs/vetores/evidência/histórico/audit/browser.

**Aceite/verificação:** tenant A/B, token copiado depois de logout, falha do PG durante revogação e recuperação, grant retirado durante provider pendente e troca de API não vazam conteúdo/IDs/metadados; casos de timing com carga/metodologia aprovada. `make phase3-tenant-evidence-runtime` e harness identidade real. OIDC somente se escolhido e implementado: issuer/audience/JWKS rotation/membership/caches concretos, não configurados por aparência.

### PROD12-036 — Workers A/B, fencing e sinais reais

**Entrega:** dois processos concorrentes com PG/Redis reais, heartbeat/lease loss/stale version/duplicate delivery/DLQ/retry/replay; SIGTERM/kill/restart e shutdown corrigido em serviço.

**Aceite/verificação:** `make phase3-multi-worker-runtime`, nenhuma dupla publicação/ACK stale, nenhum handler após fechamento confirmado, drain/deadline honesto, claims em voo reconciliados e dependências fechadas somente após parada. Work recuperado/terminal após restart e dados/auditoria íntegros. Somente fault injection no lab aprovado.

### PROD12-037 — Arquivos hostis em isolamento efetivo

**Entrega:** corpus aprovado malformado/path traversal/archive/decompression/resource exhaustion no parser process runner e pipeline real; CPU/RAM/tempo/output/IPC/cleanup/egress bounded.

**Aceite/verificação:** `make phase3-file-security-runtime`; casos do gate vigente contidos e erros redigidos, nenhum processo/arquivo órfão, escape, deserialização insegura ou conteúdo malicioso publicado. Timeouts/cancel/kill reais demonstrados. Acrescentar riscos de formato autorizado sem reduzir corpus/thresholds existentes.

### PROD12-038 — Campanha RAG representativa e adjudicada

**Entrega:** corpus licenciado/revisado, estratos de dificuldade/ambiguidade/risco/idioma, splits e reserva, amostra e métricas ratificadas em 005; registrar versões de modelo/corpus/query/index.

**Aceite/verificação:** ranking, ACL leakage, citation support/completeness/precision/recall, unsupported claims/faithfulness e abstain/escalate avaliados com incerteza e adjudicação; holdout não usado para otimizar o próprio teste. Policy clínica mantém revisão humana; métricas sintéticas 1,0 de cinco casos não aprovam segurança/qualidade clínica. Corpus insuficiente → BLOCKED_EXTERNAL. Artefato de avaliação real reviewado e hash-bound.

### PROD12-039 — Evidência forjada e ataques RAG/tool

**Entrega:** forged/stale/wrong checksum/unknown chunk/revoked source, prompt/document/retrieval/tool injection, incomplete generation e contradiction entre decisão/citação, nos boundaries reais.

**Aceite/verificação:** tenant/evidence/adversarial corpus + integração real rejeitam entradas inválidas antes de publicação; apenas ANSWER com evidência válida pode gerar, ESCALATE/ABSTAIN não viram resposta clínica; JSON/SSE/fallback/history mantêm decisão/versão/provenance e provisional não parece final. Nenhuma instrução de documento substitui policy. Testar revogação entre retrieval, geração e persistência final.

### PROD12-040 — Persistência e aceite do módulo clínico/casos

**Entrega:** confirmar escopo D04 e feature flags do lançamento. Se cases habilitado, verificar/fechar adapter durável de produção para casos/reviews/feedback, tenant ACL, audit/idempotency, recovery e política de PII. SQLite/process-local de teste não basta. Modelo já escolhido de intake/revisão não concede aprovação clínica.

**Aceite/verificação:** registros e notas corretos após restart/restore, isolamento A/B, grants e idempotência, revisão humana obrigatória e ESCALATE antes de provider para requests clínicos. Owner de domínio/privacidade aprova dados/workflow/limites; não há diagnóstico/prescrição autônomos. Se módulo fora do perfil por decisão explícita, provar flags fechadas e impossibilidade de gravação/execução; registrar aceite **do perfil desativado**, não PASS de persistência inexistente nem dispensa de policy clínica mandatória.

### PROD12-041 — Browser API-backed e acessibilidade independentes

**Entrega:** browser no runtime aprovado, sem interceptar a fronteira que precisa de prova; login/casos/chat/history/search/fontes/upload/jobs/collections/admin/offline/403/worker/provider failures, conteúdo longo e estados vazios/loading/error.

**Aceite/verificação:** 375/768/1440, zoom/teclado/leitor de tela/contraste/reduced-motion/touch; axe e foco sem violação relevante, screenshots nativas + console/network + reviewer independente. A07–A10 reproduzidos/testados, paginação completa e rascunhos corretos. `make phase3-frontend-supply-runtime` para a prova exigida; `make web-validate`/fixtures locais não são substituto. Destino same-origin do build válido.

### PROD12-042 — Revisão de segurança externa escopada

**Entrega:** revisão/ataques autorizados de sessão/autorização, proxy/TLS/SSRF/origin, quotas/resource exhaustion, parser/upload, dados/telemetria/segredos, provider e ambiente/imagens; escopo e abortos definidos.

**Aceite/verificação:** findings classificados com reproduções/evidências/disposição; zero Critical/High antes do release, Medium somente com owner/mitigação/expiração e aceite permitido. Testar APIs públicas e deployment, não só scanner. Nenhum ataque ao host/terceiros/produção fora da autorização; parecer independente vinculado ao candidato.

## M5 — Operação, recuperação e capacidade

### PROD12-043 — Traces, métricas, SLO e alertas distribuídos

**Entrega:** exercitar collector/backend/dashboard/alert receiver com correlação Web/API/queue/worker/stores/provider/evidence/decision, cardinalidade/redaction/sampling/retention e owner on-call.

**Aceite/verificação:** `make phase3-observability-runtime`; traces reais correlacionados, nenhum segredo/conteúdo/PII em labels, collector indisponível não bloqueia transação, ausência é no_data; alarmes de latência/erro/lease/DLQ/readiness/backup chegam e recebem acknowledgement. Environment/window/amostra/release do SLI preservados; local/staging nunca copiados como produção.

### PROD12-044 — Auditoria durável e entrega/reconciliação

**Entrega:** verificar append/outbox/required audit de operações sensíveis, retries/DLQ/consumer dedup, retention/redaction/ACL e reconciliação sob indisponibilidade do sink.

**Aceite/verificação:** operação não é silenciosamente confirmada sem auditoria obrigatória; tentativas versus conclusão claras, reabertura/replay não perdem nem duplicam efeito lógico. Sink lento/falho não expõe payload nem trava indefinidamente; alertas de backlog/gaps executados. Audit persiste após crash e é consultável só no escopo autorizado. Prova em store/sink reais, não ring buffer.

### PROD12-045 — Restore integrado e ensaio de rollback/roll-forward

**Entrega:** backup consistente Postgres/objetos/vetores/Redis conforme necessidade, dados de casos/history/audit/outbox incluídos, restore isolado, reidratação/reconcile, imagens anteriores e compatibilidade migrations. Ensaiar rollback sob erro em staging antes do Go.

**Aceite/verificação:** `make phase3-restore-runtime`: counts/checksums/ACL/lineage/jobs/conversas/casos preservados, golden smoke funciona; RPO/RTO medidos contra 005, falhas/corrupção de backup detectadas. Rollback de imagem ≤300 s segundo policy existente ou roll-forward aprovado quando schema incompatível; não apagar volumes reais. Backups têm criptografia/acesso/retention e restore com operador/target/release/tempo.

### PROD12-046 — Capacidade, latência e custo representativos

**Entrega:** workloads de perfil real, incluindo distribuição payload/query/file/model, cold/warm e concorrência 1/10/50/100 conforme matriz vigente; registrar p50/p95/p99/throughput/error/CPU/RAM/disco/queues/custo e tamanho de amostra.

**Aceite/verificação:** `make phase3-performance`, budgets pré-aprovados atendidos; nenhuma medição de fixture usada como SLO. Identificar teto de admissão/quotas e headroom, comportamento em overload e degradado sem bypass, latência por família de rota/provider sem esconder tails/erros. Capacity/cost do perfil ratificados; se falhar, corrigir/retestar, não recortar workload conveniente.

### PROD12-047 — Chaos e recuperação controlados

**Entrega:** matriz de stop/kill/partition/slow/disk/dependency failures envolvendo worker/PG/Redis/Qdrant/S3/provider/collector no projeto autorizado, com limites e abortos.

**Aceite/verificação:** `make phase3-chaos`; nenhuma corrupção silenciosa/duplicate publication/cross-scope, recovery/deadline/retry/DLQ bounded, alertas e diagnósticos úteis; restore/roll-forward utilizado quando necessário. Safeguards preservam dados de outros projetos. Cada falha tem trigger, impacto, convergência e teste de reconciliação.

### PROD12-048 — Soak curto/estendido e limites de recursos

**Entrega:** executar duração/carga aprovadas em 005 após desempenho/chaos, observando growth de memória/FDs/processos/objetos/queues/telemetria, flaps e custo.

**Aceite/verificação:** `make phase3-soak`; sem crescimento ilimitado/retry storm/órfãos, budgets de disponibilidade/recursos/latência atendidos para a janela testada; critérios de início/fim/amostra/frescor preservados. Não mudar duração após ver leak, não truncar logs problemáticos; nenhum claim de 30 dias de produção pelo soak de staging.

### PROD12-049 — Runbooks, on-call e governança de dados

**Entrega:** runbooks de incidentes/restores/replays/rotations/migrations/deploy/rollback/indisponibilidade, escala de plantão e contato de incidente, retenção/export/delete/consentimento/acesso com privacidade/domínio. Realizar tabletop e teste de operador distinto do autor.

**Aceite/verificação:** destinatário de alertas responde e executa recovery; permissões/contatos, prioridades e procedimento de comunicação confirmados. Retenção/exclusão cobre fonte, jobs/history/cases/vetores/audit/backups e obrigações legais aplicáveis com decisão competente; informação clínica não vira aprovação regulatória por esse plano. Documentos executáveis e vinculados ao candidato, sem credenciais embutidas.

## M6 — Evidência, reviews, selo e Go/No-Go

### PROD12-050 — CI remoto e pacote fresco no candidato exato

**Entrega:** reexecutar lanes técnicas locais/remotas/runtime e verificações de integridade pré-review/pré-selo/pré-Go; reunir refs imutáveis para SHA/tree/fingerprint/config/digests únicos. Aplicar freshness policy e retestar o que venceu após testes longos. Não editar observation time para reciclar prova.

**Aceite/verificação:** `make triple-aaa-capability-matrix`, `make phase3-evidence` e validadores vigentes geram/verificam registros sem transformar failure em PASS. **Todos os gates técnicos deste estágio** passam e CI remoto é confirmado, não inferido do local. As lanes de autoridade `independent-reviews`, `sealed-packet` e `final-go-no-go` continuam legitimamente pendentes e bloqueiam promoção até 051–053; não exigir `--require-promotable` para encerrar 050. Dados errados/manifest missing/wrong-SHA/dirty/tampered recusados; objetos rehashed/retidos. Closure integral AUD07-43 fica condicionada a 053, não é concedida pelo aceite técnico de 050.

### PROD12-051 — Reviews independentes e scorecard tipado

**Entrega:** obter os 12 scopes vigentes: Architecture, Security, Runtime, Database, Distributed Systems, RAG, Observability, Recovery, Frontend, Accessibility, Supply Chain e Operations. Reviews frescos com tentativa de rejeição e independência reconhecida pela autoridade; checklist de 18 riscos.

**Aceite/verificação:** fontes e [constantes do motor](<../scripts/state_of_art/promotion_engine.py#L64-L124>) governam inventário; zero Critical/High, Medium com owner/aceite/mitigação/review/expiração; scorecard **26 dimensões tipadas**, overall derivado **≥96/100** conforme gate atual. Não converter as notas opinativas da auditoria para alcançar esse target. Reauditar A01–A13, obrigações antigas e riscos novos no artefato exato. Reviewer de outra árvore ou auto-review não aprova.

### PROD12-052 — Preparar packet e cadeia de confiança para selagem final

**Entrega:** release/signer prepara body imutável de CI/runtime/performance/chaos/soak/DR/frontend/supply chain, reviews e scorecard completos; valida schema/hash/frescor/trust store/key_id/retention e ensaia procedimento de selagem sem aprovar promoção. Chave privada permanece com autoridade independente.

**Aceite/verificação:** inventário/references/candidato/fingerprint/run/expiry corretos e testes de tampered/missing/wrong trust/key/signature/SHA discriminantes; ausência de decisão/selo reais continua não-promotable. **Não exigir `--require-promotable` para encerrar 052**. O body e seus hashes estão prontos para decisão humana; não preencher GO nem assinar como autoridade por conta do verificador. `command=None` não recebe executor que fabrica aceite. Selagem de promoção efetiva e validação total pertencem à transação de 053.

### PROD12-053 — Decisão humana, selagem e ratificação do release

**Entrega:** D07 e signer independente reconhecido pelo contrato realizam a transação final: (1) decisão humana datada sobre body/hash/candidato/escopo/riscos; (2) se GO, assinatura Ed25519 e retenção desse body com metadados/cadeia válidos; (3) validação integral do packet e ratificação humana dos bytes/digest exatos antes de instalação. Se NO-GO ou falha, devolver ao marco pertinente. Papéis podem coincidir somente quando o contrato de independência/autoridade permitir; builders/verificadores não obtêm poder de signer.

**Aceite/verificação:** `make phase3-evidence-verify`/`make triple-aaa-verify` ou invocações documentadas com sealed-packet/trust-store/inputs reais aprovam todos os gates, inclusive reviews/selo/final-go-no-go e requisito promotable; zero Critical/High, scorecard vigente e frescor preservados. GO é autorização externa registrada, **não inferida do exit code**. Selo/signatário/decision-authority atendem vínculos do motor; D07 ratifica packet/digests e autoriza escopo de instalação/canary/expansão explicitamente. Promoção continua NO-GO até conclusão desse evento; 054 nunca roda só porque o draft técnico passou.

## M7 — Primeira produção controlada e acompanhamento

### PROD12-054 — Implantar canary autorizado sem mudar o candidato

**Entrega:** operador instala somente digests aprovados, preserva anterior/volumes e aplica migration/preflight/config aprovados; começa com tenants/corpus/custo limitados ao perfil.

**Aceite/verificação:** política REC-33 vigente: ≥900 s e ≥100 requests, 5xx ≤1%, p95 ≤1500 ms, DLQ growth zero e readiness true; rollback ≤300 s ensaiado e trigger operável. Métricas/traces/alert receiver reais, smoke sintético/login/revoke/upload/consulta/casos quando habilitados; aborto automático/operacional se violar policy. Nenhum provider/scope extra ou evidência de staging copiada como PASS de SLO produção.

### PROD12-055 — Expandir tráfego e transferir operação

**Entrega:** após canary, expansão por estágios/amostra/janela aprovados (sem percentuais inventados), com limites de capacidade/gastos e responsáveis. Revisar health/quotas/privacy e rollback a cada estágio; handoff para plantão.

**Aceite/verificação:** stages documentados com decisão e observação; falha interrompe expansão/reverte conforme compatibilidade sem destruir dados. Acesso de usuários só no scope aprovado, on-call/backup/dead-letter/rotations ativos. Ambiente corresponde a digests/config aprovados. Maturidade limitada/single VPS descrita honestamente; escalar topologia exige nova prova/autoridade, não patch em produção sem release.

### PROD12-056 — Observar produção e revisar o primeiro ciclo operacional

**Entrega:** acompanhar SLIs de produção nas janelas vigentes (30 dias onde requerido, 24 h/10 min/per drill onde aplicável), incidentes, custos/capacidade/backup/restore/revogação e experiência de usuários; manutenção contínua e próximos ciclos.

**Aceite/verificação:** registros environment/release/candidate/window/amostra/hash completos e honestos, no_data até evidência suficiente; SLO breach abre ação/risco, não dashboard saudável por default. Review de 30 dias com owners, incidents/recovery, despesas reais, status de riscos, backlog de correção e decisão sobre escala. Esse acompanhamento não é prerequisite circular para autorizar canary: é obrigação pós-Go, nunca SLO de 30 dias afirmado antes de operar.

## Rastreabilidade de todos os achados de 12/10

| Achado | Tarefas |
|---|---|
| AUD12-A01 | 007,035,044 |
| AUD12-A02 | 008,010,036 |
| AUD12-A03 | 009,010,036 |
| AUD12-A04 | 011,031,035,046 |
| AUD12-A05 | 012,013,031,046,048 |
| AUD12-A06 | 002,003,016,026,050 |
| AUD12-A07 | 021,040,041 |
| AUD12-A08 | 022,041 |
| AUD12-A09 | 023,041 |
| AUD12-A10 | 024,034,041 |
| AUD12-A11 | 017,018,019,026 |
| AUD12-A12 | 014,016,020 |
| AUD12-A13 | 015,016,028,050 |

## Continuidade AUD07 — não duplicar nem apagar aceite

| Obrigação existente | Execução/aceite relacionado neste programa |
|---|---|
| AUD07-01–26,44–46 concluídas localmente | Preservar resultados; deltas atuais tratados em 002,003,015–020,026, sem repetir a retirada dos legados ou criar sete lanes vazias |
| AUD07-27 candidato integrado parcial | 026; aceite remoto/release em 050–053 |
| AUD07-28 golden path | 030–034 |
| AUD07-29 isolamento/revogação | 035,039,040 |
| AUD07-30 identidade/replicas | 004,031,035: prova da escolha atual; OIDC só se escolhido, implementado e revisado |
| AUD07-31 campanha RAG | 005,038,039 |
| AUD07-32 múltiplos workers | 008–010,036 |
| AUD07-33 arquivos hostis | 037 |
| AUD07-34 tracing/collector/alertas | 043,044 |
| AUD07-35 backup/restore | 045 |
| AUD07-36 capacidade/latência | 046 |
| AUD07-37 falhas/recovery | 047 |
| AUD07-38 soak | 048 |
| AUD07-39 release/imagens | 028,050 |
| AUD07-40 packet candidato | 050,052 |
| AUD07-41 reauditoria | 051 |
| AUD07-42 Go/No-Go | 053 |
| AUD07-43 gates CI/runtime/release pendentes | 002,003,015,016,026,050–053; nenhuma transição automática |

## Cobertura das 26 dimensões da auditoria

| Dimensão auditada | Tarefas principais |
|---|---|
| Documentação/rastreabilidade | 001,002,020,050 |
| Arquitetura/fronteiras | 010,017,019,026,027,051 |
| Manutenibilidade | 017–019 |
| API/contratos | 007,011–014,022,026,035 |
| Autenticação/sessões | 007,014,035 |
| Autorização/multitenancy | 012,035,039,040 |
| Controle de abuso | 011–014,031,042,046 |
| Ingestão/publicação | 024,030,034,036,037 |
| Worker/concorrência/shutdown | 008–010,036,047 |
| Integridade/migrations | 030,035,036,040,045 |
| Storage/arquivos | 032,037,045 |
| Retrieval/isolamento | 032,034,038,039 |
| Evidência/citação/abstenção | 033,038,039 |
| Providers/decisão | 004,005,033,038,039 |
| Casos/revisão humana | 021,040,041 |
| Frontend/estados | 021–025,041 |
| Acessibilidade/responsividade | 025,041,051 |
| Testes Python/regressão | 003,007–018,026,030–039 |
| Testes web/cobertura | 018,021–026,041 |
| Tipos | 017 |
| Dependências/supply chain | 015,016,028,042,050 |
| CI/reprodutibilidade | 002,003,016,026,028,050 |
| Observabilidade/audit | 043,044,049,056 |
| Deployment/prontidão | 027–029,049–055 |
| Backup/recovery | 045,047,049,056 |
| Performance/carga/chaos/soak | 005,046–048,054,056 |

Estas dimensões auditadas e as 26 dimensões **tipadas do motor de promoção** são rubricas diferentes; ambos os mapeamentos são obrigatórios e explícitos. Não usar a média de uma como substituto da outra.

## Primeira onda de execução proposta

1. 001 preserva a baseline; 002/003/004 podem avançar em paralelo com owners distintos.
2. Segurança local: 007 e 008→009→010 e 011, em superfícies separadas; 012/013 depois do contrato comum de limiter/auth. 007/012 compartilham auth e têm mesmo owner/serialização.
3. 015/016 restauram reprodutibilidade; 021 e 024 podem avançar independentes, 022→023 compartilham chat. 014 depende do perfil/threat model.
4. Integrar 017/018/020/025; 026 é a primeira demonstração completa, ainda **não produção**. Preparação de corpus/owners/budgets pode ocorrer em paralelo; execução externa aguarda 006 e os gates pertinentes.

Nenhuma tarefa está IMPLEMENTED/DONE por ter sido descrita aqui. Próximo passo: designar owners e aprovar a adoção/escopo da primeira onda, mantendo as autorizações externas separadas.
