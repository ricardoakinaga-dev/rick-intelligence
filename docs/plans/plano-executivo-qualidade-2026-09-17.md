# Plano executivo — fechamento de qualidade RICK Intelligence

Data: 2026-09-17. Versão: PE17-v1. Estado: **PROPOSTO PARA EXECUÇÃO; PRODUTO NÃO PROMOVIDO**.

## 1. Objetivo, entregáveis e limite de autorização

Transformar os achados dos 26 itens da [auditoria preservada](../reports/relatorio-auditoria-2026-09-17.md) em correções verificadas e capacidade operacional demonstrada, visando `STATE_OF_ART → AAA → TRIPLE_AAA` conforme as regras efetivas do repositório.

Esta entrega cria somente relatório, plano executivo, roadmap e backlog. Não inicia implementação, contratação, instalação, serviços, uso de dados reais, gasto em providers, commit, publicação ou deployment. A execução do programa descrito abaixo é uma etapa posterior a ser iniciada explicitamente. Qualidade clínica e aprovação de release dependem de autoridades externas.

**Compromisso de entrega:** não declarar concluído ou Triplo AAA enquanto qualquer condição obrigatória estiver pendente, falha, bloqueada, desatualizada ou sem revisão. Não é possível garantir antecipadamente a nota, ausência absoluta de defeitos ou superioridade sobre o mercado. State of Art/Triplo AAA são classificações internas verificáveis; uma alegação comparativa pública exige benchmark externo separado.

Entregáveis relacionados:

- [Relatório de auditoria](../reports/relatorio-auditoria-2026-09-17.md): cópia da resposta entregue, mantida como snapshot; referências `arquivo:linha` pertencem a `b52f32c`.
- Este plano: objetivo, política de aceite, papéis, riscos e recuperação.
- [Roadmap](roadmap-qualidade-2026-09-17.md): sequência, dependências entre marcos e demonstrações.
- [Backlog](backlog-qualidade-2026-09-17.md): registro detalhado dos trabalhos propostos, testes e dependências.

## 2. Baseline e interpretação correta

Código de referência: `b52f32c141916a2ea3af1a6b913bd91f380606e0`. Na entrada desta etapa, nenhum arquivo rastreado estava alterado; `.opencode/` já era não rastreado e será preservado.

A auditoria anterior atribuiu 70/100, com 1.017 execuções locais de testes aprovadas, contando sobreposição entre suites. Não são cobertura medida, qualidade clínica, prova runtime ou evidência fresca após futuras alterações. Os achados são estáticos até que cada implementação capture reprodução discriminante. A cópia do relatório preserva essas distinções e não recebe resultados de trabalhos posteriores.

Há duas famílias de problemas:

1. **Internos:** composição API, SQL legado, lifecycle worker, citações, metadados SSE, lotes de embedding, seleção de coleção, retry binário, auditoria administrativa e verificadores incompletos.
2. **Dependentes de ambiente/autoridade:** serviços descartáveis, TLS, provider autorizado, corpus licenciado, medição de carga/recuperação, review visual, assinatura e promoção humana.

Resolver somente acesso ao Docker não fecha os internos. Resolver somente código não comprova os externos.

## 3. Fontes de verdade e reconciliação obrigatória

Este pacote é uma **decomposição suplementar**, não um novo controlador nem uma substituição silenciosa dos planos existentes.

| Conteúdo | Autoridade mantida | Relação com PE17 |
|---|---|---|
| Requisitos atuais amplos | [Prompt de 2026-09-10](../prompts/triple-aaa-runtime-closure-2026-09-10.txt), 64 seções | Q17-02 reconcilia todas as seções; os 26 itens não as substituem |
| Quality bar | [current-triple-aaa-quality-bar-v1.json](../reports/current-triple-aaa-quality-bar-v1.json) | Preservar critérios; sua referência ao prompt anterior é drift a reconciliar, não autorização para enfraquecer |
| Plano ativo e progresso | `.agent/state.json`, `.agent/plans/phase-3-runtime-evidence-production-promotion.md`, `.agent/backlog.json` | Nenhum ponteiro/status é alterado nesta entrega |
| Histórico e limitações | [Auditoria runtime](../reports/triple-aaa-runtime-closure-current-audit.md), [plano predecessor](phase-3-triple-aaa-closure.md) | Preservar hashes, decisões e resultados anteriores |
| Promoção executável | `scripts/state_of_art/promotion_engine.py`, `release_integrity.py`, `triple_aaa_verify.py` | Sem reduzir requisitos do motor para obter PASS |
| Parecer de promoção | [Pacote final existente](../reports/rick-intelligence-triple-aaa-final-promotion.md) | Continua NO-GO até evidência nova |
| Metas operacionais | [SLO](../operations/slo.md), [DR](../operations/disaster-recovery.md) | Alvos não equivalem a observações |

A auditoria tem 26 itens, mas **eles não são as 26 dimensões do scorecard de promoção**. Não reutilizar automaticamente notas ou números entre esses namespaces. Q17-02 produz mapeamento explícito requisito → item Q17 → dimensão oficial → gate → evidência; Q17-25 verifica a completude na promoção.

Na futura ativação, Q17-01 reconcilia o HEAD e as tarefas existentes (`PH3-2-LAB-READINESS`, `PH2-P0-02-POSTGRES-ADAPTER`, `PH2-P0-03-REAL-WORKER-RUNTIME`, `SA-EXTERNAL`, `SA-VISUAL`, `REC-M0`). Atribuir subtarefas Q17 ao item canônico adequado ou criar IDs aprovados sem duplicar trabalho. Estado de execução passa a ser escrito apenas no backlog canônico; este catálogo permanece referência de escopo. Não reabrir como "não implementado" tudo que já tem fechamento local; revalidar a garantia afetada pelo novo achado.

## 4. Arquitetura alvo e estratégia

Preservar `apps → packages → contracts/shared`, migração por adapters e legado protegido. Sem reescrita geral, remoção do legado ou troca de framework como atalhos de qualidade.

Fluxo a demonstrar cedo: navegador → sessão/escopo → upload → objeto íntegro → job PostgreSQL → Worker A/B → parsing isolado → embeddings em lotes → publicação/projeção Qdrant → busca autorizada → Evidence/Decision → geração com citações → SSE/histórico coerentes → auditoria/trace.

PostgreSQL e objetos verificados mantêm autoridade persistente; Qdrant é projeção reconstruível. Distinguir atomicidade no banco de efeitos externos e publicar somente sob fencing válido. Especificar reconciliação/outbox antes de alterar publicação, identidade ou auditoria. Não chamar de exatamente-uma-vez um fluxo com apenas deduplicação parcial.

## 5. Barra de aceite congelada para os documentos

Barra DP17-v1, congelada antes da escrita. Todos os critérios são obrigatórios. Não é a barra de aprovação do produto.

| ID | Fonte / prioridade | Critério rejeitável | Verificação / limitação |
|---|---|---|---|
| DP17-1 | USER / P0 | Cópia contém os 26 itens, notas, ressalvas, achados e resultados da resposta original, sem reescrita histórica | Comparação textual e contagem; transcript é fonte, não execução nova |
| DP17-2 | USER / P0 | Cada item possui criação/correção/implementação ou justificativa de não aplicação, testes, evidência, owner funcional e dependências | Inspeção dos 26 épicos no backlog; não prova código |
| DP17-3 | DERIVED / P0 | DAG acíclico, marcos executáveis, nenhuma aprovação runtime depende apenas de mock ou documento | Validação de IDs e revisão cruzada plano/roadmap/backlog |
| DP17-4 | REPO / P0 | Preserva autoridades, requisitos prévios e separa scorecard oficial da auditoria | Conferência das fontes acima e tarefa de reconciliação |
| DP17-5 | USER + REPO / P0 | Triplo AAA exige gates reais, zero Critical/High, evidências atuais e autoridade; nenhuma garantia antecipada | Revisão independente do contrato de aceite |
| DP17-6 | USER + REPO / P1 | Plano visual cobre identidade, estados, acessibilidade, três viewports, render e críticos independentes | Inspeção do brief e Q17-15/16/17/26; visual continua NOT_RUN |
| DP17-7 | REPO / P0 | Apenas os quatro documentos solicitados são adicionados; código/histórico/controle/legado preservados | Git diff/status, hashes dos quatro documentos antes/depois da crítica |

Escopo Gauntlet desta sessão: construção material documental, não campanha multi-round de produto. Lead escreve; scouts consultivos não aprovam; crítico final fresco I1 julga os arquivos. Sem novo `.gauntlet/` ou alteração do run existente. Envelope: até quatro agentes, profundidade um, até uma hora; parar com handoff se faltar evidência, não fabricar aprovação.

## 6. Condições para entregar o produto como Triplo AAA

O contrato de promoção existente é obrigatório. A política executável é mais restritiva que algumas descrições antigas e não será reduzida para compatibilização.

- `STATE_OF_ART`: satisfazer o conjunto efetivo do motor, incluindo serviços live, frontend/acessibilidade, supply chain e file-security quando exigidos.
- `AAA`: acrescentar restore, performance e revisões independentes conforme o motor.
- `TRIPLE_AAA`: acrescentar chaos, soak, production-runtime, pacote selado e decisão Go/No-Go.
- Scorecard oficial: exatamente as 26 dimensões oficiais, média derivada ≥96/100. É necessário, mas insuficiente: zero Critical e zero High abertos; Medium apenas com owner, mitigação, aceite, prazo e revalidação.
- Qualidade visual: ≥95/100 na rubrica aplicável, identidade preservada, confiança HIGH, estados/viewports reais, nenhuma barreira essencial de acessibilidade e review independente. Nota visual não substitui scorecard oficial.
- Evidências vinculadas a commit/tree, artefato/digest, ambiente, run, procedimento, código de saída, timestamps, reviewer e limitações. Respeitar frescor de 24h e tolerância futura de 5min do verificador atual. Longos testes/SLOs exigem política explícita de janela e checkpoint; nunca falsificar a data de uma observação antiga.
- O conjunto requerido deve retornar PASS no candidato exato. `NOT_RUN`, `BLOCKED_EXTERNAL`, `STALE`, `INVALID`, falha local ou serviço apenas configurado impedem promoção.
- Tests/build/lint/typecheck, isolamento entre tenants, migração com dados legados, publicação segura, providers/corpus autorizados, DR, SLO, supply chain e review final devem ter provas no limite real correspondente.

Preservar as matrizes do prompt: oito lanes CI, oito pontos de crash worker, doze falhas de ingestão, cinco métricas de citações, treze faults de chaos e cinco invariantes, dois perfis de soak, cinco workloads em concorrência 1/10/50/100, doze escopos de review e dezoito checks finais. Q17-02 inventaria os casos individualmente; não os substituir por um teste agregado ou contagem sem semântica.

SLOs iniciais existentes: API ≥99,9% e chat ≥99% em 30 dias, retrieval p95 ≤1,5s em 30 dias, ingestão ≥99% em 24h, durabilidade 100% por drill, suporte de citações ≥99% no conjunto aprovado; DR RPO ≤15min e RTO ≤60min. D05 confirma carga, hardware, janelas e budgets antes de medir. Sem amostra: `no_data`. Evidência staging nunca vira produção por renomeação. Não esperar 30 dias e tentar selar todos os artefatos como se tivessem sido gerados juntos: resolver a compatibilidade de janelas no contrato antes de executar a campanha.

## 7. Direção de design e experiência

Modo: planejamento sobre produto existente; render, contraste e aprovação visual **NOT_RUN**. Público observado: veterinários em consulta a evidências e operadores/administradores de conhecimento. Meio: componentes HTML/CSS e tokens existentes, sem geração raster necessária.

Tese: **bancada veterinária de evidências**, com ordem pergunta → resposta → fontes → incerteza; operação administrativa com ordem ação → alvo/escopo → resultado confirmado → auditoria. Preservar rail escuro, canvas claro, teal funcional, tokens e tipografia atuais (`apps/web/app/globals.css`), componentes de `apps/web/components/ui.tsx` e organização do chat. Mudança de marca ou promessa clínica requer aceite humano.

Q17-15/16/17 especificam telas e estados; Q17-26 é dono do pacote visual transversal. Exigir screenshots nativas em 375×812, 768×1024 e 1440×1000, zoom/texto 200%, reflow a 320 CSS px, teclado, leitor de tela, foco/restauração, reduced motion, mensagens de erro associadas, contraste WCAG AA medido e alvos preferenciais 44×44px. Sem aprovação por código ou screenshot redimensionada. Medir todos os pares viewport/estado relevantes, não somente a homepage.

Estados obrigatórios: carregamento, vazio, sessão expirada, 403, erro de rede, sucesso, resposta fraca/sem evidência, SSE provisório/interrompido, cancelamento pendente, job longo, retry, conflito idempotente, listas longas e metadados extensos. Não anunciar cada token SSE para tecnologia assistiva; anunciar transições úteis. Proibir falso percentual, sucesso sem confirmação e diferenciação somente por cor.

Crítica visual material: dois avaliadores frescos com comparação cega de artefatos renderizados, referência atual preservada e rubrica congelada; adjudicador novo somente se houver discordância material. Aprovação do plano de design não aprova o visual construído.

## 8. Organização, decisões e recursos

| Responsabilidade | Owner funcional proposto | Limite |
|---|---|---|
| Contratos compartilhados, integração, deduplicação do backlog | Lead de engenharia | Único escritor do controle canônico quando a execução for ativada |
| Auth, API, auditoria, contratos | Backend/security | Não delegar mudanças concorrentes nos mesmos arquivos de contrato |
| Knowledge, ingestão, retrieval, Evidence/Decision/Professor | Plataforma RAG | Política clínica não é decidida pelo implementador |
| PostgreSQL, Redis, storage, worker, SLO/DR | Dados/SRE | Somente endpoints isolados explicitamente autorizados |
| UI, design system, estados e acessibilidade | Frontend/design | Preservar marca e conteúdo; validar no browser |
| Testes, CI, supply chain, packet | QA/release | Builder não assina sua própria aprovação |
| Juízo de domínio e Go/No-Go | Humano qualificado e release authority | Identidades ainda não designadas |

Owners são papéis, não pessoas contratadas ou disponíveis. Não há prazo/calendário ou orçamento de provider aprovado. Estimativas de esforço no roadmap são relativas, para ordenação; M0 deverá convertê-las em calendário com capacidade e orçamento reais.

Decisões pendentes:

- **D01:** dados sintéticos/tenants/isolamento e retenção aprovados; dono de dados.
- **D02:** daemon descartável, secrets, identidade bootstrap, TLS/topologia e trust store; operador/security.
- **D03:** provider/modelo/endpoints, custo máximo, limites e política de interrupção; titular da conta.
- **D04:** corpus/licenças, risco clínico/intenção, gold labels, thresholds por grupo e revisão veterinária; responsável de domínio.
- **D05:** ambiente/carga/amostra/janelas, SLO/DR, soak curto/estendido, alertas e compatibilidade de frescor; SRE/release.
- **D06:** ativar execução e reconciliar catálogo Q17 com backlog canônico; usuário/Lead.
- **D07:** autorização separada para promoção, assinatura e eventual implantação/canário; release authority. Risco residual alto não é dispensa silenciosa do selo Triplo AAA.

## 9. Execução, validação e recuperação

Ordem detalhada no roadmap: M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7. Pode haver implementação local paralela antecipada quando as dependências da subtarefa estiverem satisfeitas; aceite integrado respeita a ordem. Arquivos acoplados em `external_composition.py`, `professor_backend.py`, contratos, CI e estado têm owner único por onda.

Por subtarefa: inspecionar HEAD/instruções → reproduzir comportamento ou capturar baseline → especificar contrato → menor correção coerente → teste focado → regressão → crítico fresco → reteste → evidência → atualização canônica. Achado estático não confirmado deve ser reclassificado com prova, não "corrigido" à força. Novas implementações começam com critérios de aceitação e teste que detecte ausência, não teste de um detalhe arbitrário.

Comandos locais existentes, após inspeção de efeitos: `make validate`, `make lint`, `make typecheck`, `make api16-domain`, `make api16-worker`, `make api16-root`, `make api15-contracts`, `make api15-provider`, `make api15-lock`, `make api15-professor`, `make storage-test`, `make jobs-test`, `make eval-retrieval-pack`, `make compose-static`, `make ops-static`; web requer também `make web-lint`, `make web-typecheck`, `make web-build`, `make web-e2e`. Raiz lint/typecheck não é garantia de cobertura da web canônica nem tipagem Python completa. Q17-26 amplia checks sem enfraquecer os atuais.

Runtime somente após D01–D05 aplicáveis: targets `make phase3-postgres-runtime`, `make phase3-multi-worker-runtime`, `make phase3-redis-runtime`, `make phase3-redis-multi-replica-runtime`, `make phase3-object-qdrant-runtime`, `make phase3-golden-runtime`, `make phase3-provider-rag-runtime`, `make phase3-tenant-evidence-runtime`, `make phase3-observability-runtime`, `make phase3-restore-runtime`, `make phase3-file-security-runtime`, `make phase3-performance`, `make phase3-chaos`, `make phase3-soak`, `make phase3-frontend-supply-runtime` e `make triple-aaa-verify`. Alguns dependem de harness/autoridade ainda não completos; comandos existentes não são promessa de PASS. Casos novos do backlog exigem implementação de testes, não nomes de comandos fictícios.

Recuperação após interrupção: ler estado/plano/backlog canônicos, conferir git/serviços/propriedade dos recursos e hashes; não reutilizar PASS de outro candidato. Registrar último efeito confirmado, trabalho parcial e próximo teste. No código, rollback de mudança revisada ou roll-forward conforme contrato; no banco, não editar migration aplicada nem apagar ledger de checksum: Q17-19 decide reparo seguro por estado real da instalação. Recuperação destrutiva apenas em cópia aprovada. Não executar reset, limpeza, teardown de serviços alheios nem remover `.opencode/` para obter checkout limpo. Preparar candidato limpo separado somente com autorização e commits explicitamente solicitados.

## 10. Riscos e fechamento

| Risco | Controle | Bloqueia |
|---|---|---|
| Aprovação por nota ou histórico | Gates same-candidate + negativos known-bad + assinatura independente | M7 |
| Suposta integração com serviços simulados | Separação unit/contract/live; dados e observações do serviço real | M1–M7 conforme tarefa |
| Fonte revogada/citação sem apoio | Validação pré/pós-geração e apresentação conservadora | M3/M4 |
| Duplicação/perda em migração e publicação | Fixture legada, fencing, outbox, replay e restore real | M1/M2/M5 |
| Custos ou dados não autorizados | D01–D04 e orçamento finito | Campanhas live |
| Pipeline não consegue consumir aprovação válida | Casos known-good autorizados e known-bad sem autoaprovação | M6/M7 |
| Crescimento de escopo/documentação concorrente | Um owner canônico, mapeamento Q17, congelamento por marco | M0 |

Progresso inicial: relatório original existente; pacote documental em elaboração; **nenhuma subtarefa de produto Q17 executada nesta entrega**. Resultado da revisão documental será comunicado separadamente e não altera o NO-GO do programa.

Primeira ação da futura construção: D06 e Q17-01.A, reconciliar o catálogo com o controle atual e registrar o candidato; em seguida Q17-02.A e Q17-26.A estabelecem rastreabilidade e testes que rejeitam os achados. Não começar por mais um selo ou por retoque cosmético.
