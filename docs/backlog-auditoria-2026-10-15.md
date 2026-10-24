# Backlog de remediação e verificação — auditoria AUD15

**Data:** 15/10/2026 (America/Sao_Paulo). **Estado de publicação:** PROPOSTO. **Atualização posterior:** os 24 contratos foram adotados no [backlog canônico](<../.agent/backlog.json>) após o pedido humano de implementação; preparação/integração local em andamento, sem aceite automático. Este documento continua sendo especificação, não um segundo ledger de status. **Produto:** NO-GO.

Fontes: [relatório AUD15](<reports/relatorio-auditoria-2026-10-15.md>), [roadmap desta rodada](<roadmap-auditoria-2026-10-15.md>), [backlog PROD12](<backlog-producao-2026-10-12.md>) e [plano ativo](<../.agent/plans/producao-2026-10-12.md>). Este complemento especifica os novos gaps/revalidações; **não substitui** os contratos e dependências anteriores nem cria um segundo controlador.

## 1. Baseline e regras de execução

Baseline **histórica da auditoria**, não nova execução em 15/10 à tarde: HEAD `48e383c25ca4af32aa7ffe7e2367360ca9742c58` mais alterações locais. Nota 74,6/100; produção NO-GO. Passaram validação estática, lint, TypeScript, build, 115 testes web e 215 regressões focadas. Python ampliado: **7.658 passed, 278 failed, 221 skipped, 99 subtests passed**. Das falhas, 277 estão na lane VPS e uma no inventário Node. A causa ambiental principal foi diagnosticada; não se demonstrou que todas as 277 passariam em outro executor. Serviços externos, E2E atual, carga e restore integrado continuam sem prova nessa rodada.

- IDs **AUD15-T001…T024** são tarefas; **AUD15-01…13** são achados. Não confundir nem renumerar IDs PROD12/AUD07.
- O [estado do controlador](<../.agent/state.json>) e o [plano ativo](<../.agent/plans/producao-2026-10-12.md>) registram adoção anterior dos 56 contratos PROD12 em TODO, sem aceite. Portanto, não interpretar a redação original de planejamento de 12/10 como status atual de adoção. Os 24 IDs AUD15 foram posteriormente reconciliados no mesmo controlador, sem alterar os 92 itens anteriores; status de execução/aceite pertencem somente ao [backlog canônico](<../.agent/backlog.json>). O umbrella de preparação local é separado e não satisfaz dependências AND nem aceita essas tarefas por procuração.
- **P1:** segurança, dados, disponibilidade central ou evidência obrigatória antes da candidatura. **P2:** robustez, manutenção e fechamento complementar. Prioridade é distinta da severidade do relatório: nenhuma severidade foi elevada por conveniência.
- Tamanho **P/M/G:** pequeno delimitado / múltiplas fronteiras / grande ou dependente de ambiente/decisão. Não são dias. Donos são papéis sugeridos, não pessoas designadas.
- Dependências da tabela são **AND**, com prefixo AUD15-T. Elas governam aceite; preparação independente pode avançar antes. Um único writer por arquivo/recurso compartilhado, mesmo quando não há dependência funcional.
- Todos os 24 contratos têm **disposição obrigatória** para encerrar este complemento: corrigido e verificado, ou hipótese não confirmada com prova/revisão, ou encaminhamento explícito para contrato canônico sem declarar conclusão do produto. Risco não é aceito automaticamente; decisão material exige autoridade competente e não pode dispensar gates congelados.
- **Histórico de autoridade:** o pedido de publicação autorizava apenas planejamento. O pedido humano posterior “implementa todo o conteudo dos planos” autoriza implementação reversível e reconciliação local, registradas no [plano ativo](<../.agent/plans/producao-2026-10-12.md>) e na [barra AUD15 congelada](<reports/evidence/aud15-implementation-20261015/quality-bar.md>). Isso não fornece D01–05/07, serviços/segredos/providers pagos, DDL real, push/deploy/promoção ou autorização para mudar permissões do host; essas fronteiras conservam gates próprios.

### Definition of Done comum

1. Registrar candidato (SHA + estado/tree/fingerprint), configuração, ambiente/toolchain, procedimento, resultado/exit, timestamp UTC, artefatos/hashes, limitações e reviewer.
2. Defeito reproduzido: teste deve rejeitar a versão defeituosa e aprovar a corrigida. Um probe que sai 0 ao confirmar o bug **não** é regressão verde do produto; inverter suas expectativas para o contrato desejado.
3. Achado estático: reproduzir primeiro. Se não confirmado, preservar tentativa e justificar disposição revisada; não inventar correção ou bypass.
4. Cobrir sucesso, erro, callback tardio, concorrência/escopo relevantes; revisão independente para identidade, isolamento, dados e release. Nenhum skip/exclusão/floor reduzido para fabricar PASS.
5. Não tratar NOT_RUN, STALE, BLOCKED_EXTERNAL, no_data ou skip como PASS. Counts 115/215/7.658 são referências históricas, **não metas congeladas de quantidade**; mudanças de coleta exigem inventário e justificativa.
6. Preservar patches existentes, logs falhos e evidência histórica. Provas ignoradas pelo Git precisam de retenção aprovada; ausências são registradas, nunca reconstruídas como execução original.

## 2. Fila priorizada e dependências

| ID | Marco | Pri | Tam | Entrega | Dono sugerido | Dependências |
|---|---|---|---|---|---|---|
| AUD15-T001 | M0 | P1 | M | Candidato, evidências e reconciliação com PROD12 | Lead/QA | — |
| AUD15-T002 | M0 | P1 | M | Toolchain reproduzível | Plataforma/CI | 001 |
| AUD15-T003 | M0 | P1 | G | Executor VPS compatível e diagnóstico das 277 falhas | Plataforma/segurança | 001 |
| AUD15-T004 | M0 | P1 | M | Classificação dos 221 skips | QA/runtime | 001 |
| AUD15-T005 | M0 | P1 | M | Inventário Node coerente | Supply chain/CI | 001 |
| AUD15-T006 | M1 | P1 | M | Logout OIDC com efeito/resultado honestos | Identidade/API | 001 |
| AUD15-T007 | M1 | P1 | M | Distinguir indisponibilidade de ausência OIDC | Identidade/API | 006 |
| AUD15-T008 | M1 | P1 | M | Quota antes de trabalho caro no reset | API/segurança | 001 |
| AUD15-T009 | M2 | P1 | M | Identidade sem bloqueio síncrono do event loop | API/plataforma | 006,007,008 |
| AUD15-T010 | M1 | P1 | M | Revalidação de sessão entre abas | Web/identidade | 001 |
| AUD15-T011 | M1 | P1 | M | Preservar pergunta e idempotência offline | Web/chat | 001 |
| AUD15-T012 | M1 | P1 | P | Preservar draft de caso após submit | Web/casos | 001 |
| AUD15-T013 | M2 | P2 | P | Paginar todos os casos | Web/casos | 012 |
| AUD15-T014 | M2 | P2 | M | Recuperação verdadeira após 403 | Web/chat/identidade | 010,011 |
| AUD15-T015 | M2 | P2 | M | Validar respostas HTTP de sucesso | Web/contratos | 010 |
| AUD15-T016 | M2 | P2 | M | Retomar acompanhamento do mesmo job | Web/documentos | 015 |
| AUD15-T017 | M2 | P2 | P | Preservar exceções no contexto OTel | Observabilidade/worker | 001 |
| AUD15-T018 | M2 | P2 | M | Acessibilidade e foco nas transições corrigidas | Web/acessibilidade | 010,011,012,013,014,016 |
| AUD15-T019 | M2 | P2 | M | Tipagem ampliada nas fronteiras de risco | API/worker/web | 009,015,017 |
| AUD15-T020 | M2 | P2 | M | Cobertura com denominador explícito e cenários novos | QA/API/web | 009,010,011,012,013,014,015,016,017,018,019 |
| AUD15-T021 | M2 | P2 | P | Documentação alinhada ao comportamento | Documentação/Lead | 002,005,006,007,008,009,010,011,012,013,014,015,016,017,018,019,020 |
| AUD15-T022 | M3 | P1 | G | E2E local atual com testes de isolamento e recuperação | QA/browser | 002,006,007,008,009,010,011,012,013,014,015,016,018 |
| AUD15-T023 | M3 | P1 | G | Candidato local integrado e revisão independente | Integrador/QA | 002,003,004,005,006,007,008,009,010,011,012,013,014,015,016,017,018,019,020,021,022 |
| AUD15-T024 | M0 | P1 | M | Reconciliar contratos externos, recursos e autoridades | Lead/SRE/produto | 001 |

## 3. Contratos de entrega e aceite

### AUD15-T001 — Preservar e reconciliar baseline

**Entrega:** preservar o relatório/logs/probes disponíveis e seu vínculo à árvore auditada; comparar com o candidato de execução e mapear itens novos, extensões de PROD12 e revalidações de patches já existentes. Não sobrescrever provas históricas.

**Aceite:** inventário com hashes/disponibilidade, alterações de candidato explícitas e cada um dos 13 achados mapeado. Ausências de logs originais de outras datas continuam registradas. Proposta de adoção/vínculo revisada, sem duas tarefas reivindicando o mesmo aceite, sem editar controlador neste pedido.

### AUD15-T002 — Fixar ambiente de verificação

**Entrega:** executar em Python/Node/npm compatíveis com o [contrato de toolchain](<../toolchain.json>), usando locks e runner existentes; registrar versões efetivas, não apenas pins declarados.

**Aceite:** bootstrap reproduzível em checkout controlado, dependências consistentes, lint/typecheck/build aprovados nesse ambiente. Qualquer mudança de versão passa por decisão técnica explícita, não alteração silenciosa do contrato para coincidir com o host.

### AUD15-T003 — Diagnosticar e reexecutar lane VPS

**Entrega:** listar os 277 node IDs falhos, agrupar causas e pré-condições UID/GID, sticky bit, namespaces e capabilities; disponibilizar executor descartável compatível por autorização própria. Reutilizar PROD12-003, ampliando a baseline de falhas a reconciliar.

**Aceite:** reexecutar a lane inteira e os negativos em Linux representativo; cada falha tem causa e resolução ou bloqueio concreto. A barreira ambiental diagnosticada não encerra todas as falhas por inferência. Sem chmod/chown do host, remoção de guards, mocking de DAC apresentado como prova real, ou skip convertido em verde.

### AUD15-T004 — Dar destino verificável aos skips

**Entrega:** matriz dos 221 skips observados, por node ID, motivo, pré-condição, ambiente/owner e gate obrigatório; atualizar a coleta no candidato novo.

**Aceite:** todo skip obrigatório de runtime vinculado a PROD12 e reexecutado no ambiente adequado antes de seu gate; inaplicabilidade somente com perfil ratificado e prova de feature fechada. Não exigir artificialmente zero skips de testes genuinamente não aplicáveis, nem ocultar obrigação externa.

### AUD15-T005 — Corrigir inventário Node — AUD15-08

**Entrega:** decidir política explícita de snapshots versionados e inventário de componentes; corrigir a origem da discrepância, preservando evidência histórica e componentes executáveis legítimos.

**Aceite:** teste de inventário isolado e suíte relevante aprovados; negativos detectam manifesto extra legítimo não catalogado e componente canônico ausente. Não resolver removendo assertion ou ignorando indiscriminadamente diretórios executáveis. Vínculo: PROD12-015.

### AUD15-T006 — Logout federado honesto — AUD15-01

**Entrega:** definir a autoridade da sessão local/federada e a capacidade do adapter/broker; implementar revogação suportada ou recusa explícita de confirmação não suportada. Não trocar o perfil postgres-local-v1 por OIDC sem decisão: tratar também o adapter disponível/injetável.

**Aceite:** saída confirmada invalida a autoridade relevante sob o contrato aprovado; sem suporte/timeout/falha não há falso `signed_out` nem `completed`. Regressão JWT local rejeita a baseline; testes protegem o logout nativo já corrigido. Persistir decisão sobre alcance do access token versus sessão do broker, sem prometer revogar JWT stateless sem mecanismo.

### AUD15-T007 — Indisponibilidade não é ausência — AUD15-06

**Entrega:** distinguir credencial inválida/expirada, membership negada e falha de consulta à autoridade; propagar indisponibilidade em envelope seguro.

**Aceite:** outage de resolver retorna erro de disponibilidade, não 200 de logout/401 por ausência inventada; token inválido continua negado. Recuperar resolver não pode desmentir uma saída anteriormente confirmada. Sem vazamento de detalhe ou redução de fail-closed. Mesmo owner de T006.

### AUD15-T008 — Limitar confirmação de reset — AUD15-02

**Entrega:** quota antes de KDF e transação de consumo; definir chaves/budgets e reduzir custo de token inválido sem enumeração nem quebra da transação single-use.

**Aceite:** limiter negativo exige **zero hash e zero consume**, falha do limiter é segura, requests permitidos usam quotas corretas e tokens não vazam nas chaves/logs; sucesso, expiração, replay e corrida single-use exercitados. Números de quota exigem política aprovada, não defaults inventados para obter PASS.

### AUD15-T009 — Não bloquear o loop — AUD15-07

**Entrega:** adapter async ou offload bounded para identidade/KDF/DB, com deadline, admissão, cancelamento e encerramento definidos; evitar apenas deslocar fila ilimitada para threads.

**Aceite:** dependência artificialmente lenta não bloqueia request independente no mesmo processo; orçamento de espera/concorrência e saturação verificados. Login/lookup/erro não perdem escopo, tracing ou consistência da sessão. Benchmark deve registrar workload, não extrapolar uma chamada para capacidade real.

### AUD15-T010 — Autoridade de sessão entre abas — AUD15-05

**Entrega:** primeiro reproduzir multiaba A→logout/login B; sincronizar invalidação/troca e revalidar autoridade ao retomar antes de mostrar privado ou admitir mutações. Não persistir credenciais em broadcasts/storage.

**Aceite:** aba antiga não continua apresentando contexto A e submetendo ação como B; testes cobrem revogação, foco/visibility, API 401, indisponibilidade, logout falho e respostas antigas. Prova browser multi-page direcionada nesta tarefa e revalidação integrada em T022; não declarar bypass ACL que a auditoria não comprovou.

### AUD15-T011 — Pergunta recuperável offline — AUD15-03

**Entrega:** preservar texto e identidade/chave de retry ao abortar por perda de rede, mantendo descarte de resposta tardia e separação de sessão.

**Aceite:** deferred send → offline → online mantém pergunta recuperável e retry idempotente; no backend pode haver resultado desconhecido, então reconciliação não duplica turno. Callback tardio não publica resposta, conteúdo não atravessa identidade e offline não se confunde com permissão revogada.

### AUD15-T012 — Preservar criação de caso — AUD15-04

**Entrega:** bloquear edição explicitamente durante POST ou usar revisão de draft para limpar somente os dados efetivamente enviados.

**Aceite:** enviar A e editar B enquanto pendente não apaga B silenciosamente; submit duplicado é excluído, erro permite recuperação e troca de sessão descarta callbacks. Manter requisitos de revisão/feedback que já possuem regressões.

### AUD15-T013 — Paginação completa de casos — AUD15-09

**Entrega:** reproduzir cenário com 51 casos; consumir paginação/total e apresentar parcialidade verdadeira, sem multiplicar coleta sem limite.

**Aceite:** 51º caso acessível, sem duplicação; falha da próxima página preserva os itens anteriores; respostas tardias não alargam tenant/workspace/owner. Criar caso e atualizar lista não quebra cursor/offset.

### AUD15-T014 — Recuperar após 403 sem afrouxar autoridade — AUD15-10

**Entrega:** substituir retry inoperante por revalidação/autenticação explícita conforme contrato; alinhar specs de 403/offline ao comportamento aprovado.

**Aceite:** 403 não libera envio por tentativa cega; após autoridade revalidada e permissão restaurada a ação volta a funcionar. Diferenciar history.read de chat.query conforme política backend; se negado, UI permanece honesta. Testes antigos não são simplesmente removidos para ocultar falha.

### AUD15-T015 — Validar sucesso HTTP — AUD15-12

**Entrega:** schemas/guards runtime nos envelopes consumidos, começando por sessão e documentos; rejeitar HTML/JSON inválido/campos ausentes com erro de contrato recuperável. Diferenciar endpoints legitimamente sem corpo.

**Aceite:** 200 malformado não vira catálogo vazio nem sessão válida; erro seguro preserva request-id e suporta retry. Schemas válidos continuam aceitos; SSE mantém parser próprio e contratos de abort/terminal.

### AUD15-T016 — Retomar o mesmo job — AUD15-11

**Entrega:** ação controlada de consultar/retomar acompanhamento, com budget/backoff e identificação do job sem reenvio do arquivo; distinguir timeout do polling de falha do job.

**Aceite:** timeout→published e 503→published convergem; não duplica upload/retry, não anuncia sucesso antecipado, permite cancelar acompanhamento e invalida callbacks de outro escopo. Definir recuperação após remount sem reter dados sensíveis indevidamente.

### AUD15-T017 — Exceção original no OTel — AUD15-13

**Entrega:** separar entrada/cleanup do contexto das exceções lançadas pelo corpo, sem segundo yield após throw.

**Aceite:** mesma exceção original preservada; falhas de attach/detach e corpo sem erro cobertas, sem `generator didn't stop after throw()`. Proteger resultado do worker atual; não apresentar o bug do utilitário como perda de job demonstrada.

### AUD15-T018 — Semântica acessível e foco

**Entrega:** definir modalidade do drawer, interação com o fundo e restauração de foco; rever teclado, live regions, erro/loading e transições afetadas pelos fixes.

**Aceite:** árvore acessível e navegação de teclado coerentes em mobile/tablet/desktop, sem foco preso/invisível; testes automáticos mais avaliação assistiva proporcional com evidência em T022. Nenhum PASS WCAG global derivado só de axe ou labels.

### AUD15-T019 — Tipagem gradual por risco

**Entrega:** ampliar tipagem nas fronteiras alteradas de identidade, transporte, worker/telemetria e adapters, com lista explícita de arquivos e baseline de dívida; preservar contratos canônicos.

**Aceite:** typecheck passa, novas fronteiras não dependem de Any/cast indiscriminado para silenciar erro; documentar o denominador Python além dos 13 arquivos da auditoria. Não impor reescrita de todo monorepo como dependência artificial.

### AUD15-T020 — Cobertura e testes discriminantes

**Entrega:** incluir chat workspace, transporte e documentos no denominador relevante, além das suites novas; medir API/worker alterados, identificar ramos críticos e inventariar cenários dos 13 achados.

**Aceite:** todos os invariantes corrigidos têm negativos que rejeitam baseline; relatório informa arquivos/linhas/branches e exclusões, sem anunciar 92,57% como cobertura global. Não baixar floors vigentes; ampliação incompatível exige melhoria de testes e decisão de escopo explícita, não exclusão para obter verde.

### AUD15-T021 — Docs sem drift

**Entrega:** alinhar CSRF, histórico/streaming, logout federado, toolchain, erros e procedimentos de recuperação; ligar provas novas sem atualizar timestamps históricos.

**Aceite:** `make docs-check` e diff check aprovam; exemplos refletem implementação validada, NOT_RUN externo e limitações permanecem visíveis; não promover produto pela nota nem reescrever relatório AUD15.

### AUD15-T022 — E2E local atual

**Entrega:** ensaio browser aprovado para identidade multiaba, offline durante envio, 403/revalidação, criação/paginação de casos, resposta malformada e retomada de job; matriz mobile/tablet/desktop e acessibilidade. Fixtures sintéticas e backend controlado devem ser explicitados.

**Aceite:** build servido e versão do browser identificados, cenários positivos/negativos passam com console/rede/artefatos revisados; nenhum teste depende de política antiga contraditória. Mocks, API real e autoridade externa são classes distintas. Iniciar servidor/portas só na rodada autorizada, sem substituir a GUI existente; E2E local não fecha PROD12-041 real.

### AUD15-T023 — Gate local integrado

**Entrega:** repetir gates canônicos e suite ampliada no candidato único, revalidar os patches já observados e obter crítica independente das fronteiras corrigidas.

**Aceite:** validação, lint, tipos, build, regressões/API/worker/web e inventário aprovados; lane VPS aprovada no executor compatível; skips classificados sem obrigação obrigatória ausente. Counts/coleção e mudanças justificados. Reviewer verifica negativos de identidade/draft/isolamento. Candidato integrado e evidência suficiente para fechar gaps locais, mas **não** GO de produção; obrigações históricas de PROD12-026 continuam exigindo seu próprio aceite.

### AUD15-T024 — Recursos, perfil e mapa externo

**Entrega:** reconciliar PROD12-004/005/006 e 027–056 com a auditoria nova: perfil postgres-local-v1/D04 já registrado, uso ou exposição efetiva de OIDC, direitos do corpus, ambientes, namespaces, custos, SLO, RPO/RTO, janela de testes e pessoas com poder de aborto/promoção. Manter contratos existentes, sem inventar novas autorizações.

**Aceite:** cada lacuna externa tem ID canônico, owner proposto, pré-condição, gate, evidência requerida e autoridade pendente; preparação pode acabar com bloqueios explícitos, mas nenhum gate externo é considerado cumprido. Proposta revisada de vínculo T023→PROD12-026/050 e novos gaps antes de canary; nenhuma edição de dependências do controlador neste pedido.

## 4. Rastreabilidade dos 13 achados

| Achado | Tarefa principal | Relação com trabalho anterior |
|---|---|---|
| AUD15-01 | T006 | Complementa PROD12-007/035: a correção nativa não prova logout OIDC |
| AUD15-02 | T008 | Amplia PROD12-012: confirmação de reset não coberta por quotas das outras rotas |
| AUD15-03 | T011 | Complementa PROD12-022/023: paginação/selo não provam preservação offline |
| AUD15-04 | T012 | Complementa PROD12-021: draft de create difere de review/feedback |
| AUD15-05 | T010 | Complementa PROD12-025/035/041; exige reprodução multiaba |
| AUD15-06 | T007 | Complementa PROD12-007/035; ausência não equivale a outage |
| AUD15-07 | T009 | Alimenta PROD12-017/046; scheduling local precede carga real |
| AUD15-08 | T005 | Reutiliza PROD12-015; falha de inventário permanece aberta |
| AUD15-09 | T013 | Complementa PROD12-021/041; reproduzir 51 casos |
| AUD15-10 | T014 | Complementa PROD12-023/025/041; manter fail-closed |
| AUD15-11 | T016 | Complementa PROD12-024/041; refresh após publicação não prova retomada |
| AUD15-12 | T015 | Complementa PROD12-018/041; cast TS não valida resposta HTTP |
| AUD15-13 | T017 | Complementa PROD12-043; utilitário local versus tracing distribuído |

T001 deve reconciliar os vínculos, não marcar automaticamente essas tarefas históricas como novas, concluídas ou aceitas. PROD12-008–013/021–024 com melhorias observadas são **revalidações**, não convites a reimplementar o que já passou.

## 5. Backlog externo mantido por referência, sem duplicação de IDs

As dependências AND e os aceites detalhados do [backlog PROD12](<backlog-producao-2026-10-12.md>) continuam valendo; os intervalos abaixo agrupam trabalho, não dispensam predecessores anteriores a 027.

| Frente pendente | IDs canônicos | Evidência necessária / saída |
|---|---|---|
| Ambiente, recursos, perfil e budgets | PROD12-004–006,027 | Autorização, owners, dados sintéticos, topologia, budgets/SLO/DR e condições de aborto |
| Imagens, supply e lab | PROD12-028–029 | Digests testados, SBOM/scans/provenance/assinaturas conforme policy; lab autorizado e preflight |
| PostgreSQL, Redis, S3/Qdrant e migrations | PROD12-030–032 | Aplicação/recovery em destino descartável, saúde, ACL, persistência e fail-closed reais |
| Provider, golden path, identidade e worker | PROD12-033–036 | Upload→fila→publicação→retrieval; revogação/tenant; workers A/B, lease/fencing e sinais reais |
| Corpus hostil, RAG e domínio | PROD12-037–040 | Parsers hostis isolados, corpus licenciado/representativo, métricas/abstenção, casos e revisão humana |
| Browser real e segurança independente | PROD12-041–042 | E2E API-backed multiaba, responsivo/acessível, dados/serviços reais autorizados e negativos de isolamento |
| Observabilidade e auditoria | PROD12-043–044 | Traces API→worker→stores, alertas entregues, outbox/DLQ, audit durável e detecção de falhas |
| Restore integrado | PROD12-045 | Restaurar stores/conversas/audit em ambiente isolado; integridade e tenant pós-restore, RPO/RTO medidos e rollback/roll-forward |
| Carga, chaos, soak e operação | PROD12-046–049 | Workloads aprovados, p95/p99/erros/custo, crash/degradação/recuperação, estabilidade e handoff; métricas reais |
| Candidato, reviews, packet e Go/No-Go | PROD12-050–053 | Frescor/vínculo, reviews e policy congelada; autoridade D07 e selo válido, sem aprovação pelo próprio builder |
| Canary, expansão e acompanhamento | PROD12-054–056 | Só após autorização; aborto/reversão, expansão controlada e janela real de SLIs, não SLO presumido |

## 6. Cobertura das 26 dimensões da auditoria

| Dimensões | Contratos que produzem a nova evidência |
|---|---|
| 1 arquitetura; 2 contratos | T005,015,019,023; PROD12-026/050 |
| 3 autenticação; 4 tenant; 5 abuso; 6 auditoria | T006–010,014,015,022,023; PROD12-035/039/042/044 |
| 7 dados; 8 ingestão; 9 worker; 10 providers | T023 revalida local; PROD12-030–037/040/045 |
| 11 retrieval; 12 qualidade IA | PROD12-033/038/039, reconciliados em T024 |
| 13 UX; 14 integração web; 15 acessibilidade | T010–016,018,022; PROD12-041/042 |
| 16 testes; 17 cobertura; 18 tipagem | T003,004,019,020,022,023 |
| 19 lint; 20 build; 21 CI/supply | T002,005,023; PROD12-028/050 |
| 22 documentação; 23 reprodutibilidade | T001–005,021,023 |
| 24 observabilidade; 25 restore; 26 produção | T017,024; PROD12-043–056 |

**Primeira ação proposta:** T001 — preservar a baseline e reconciliar os IDs; em seguida T006, T008, T010, T011 e T012 em frentes coordenadas, enquanto plataforma resolve T002/T003/T005. Nenhuma data de produção ou nova nota é prometida por este backlog.
