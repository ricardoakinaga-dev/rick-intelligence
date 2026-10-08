# Roadmap — fechamento de qualidade RICK Intelligence

Data: 2026-09-17. Versão RM17-v1. Estado: **PROPOSTO; IMPLEMENTAÇÃO NÃO INICIADA POR ESTE PACOTE**.

## Contrato

Este roadmap ordena o [backlog Q17](backlog-qualidade-2026-09-17.md), subordinado ao [plano executivo PE17](plano-executivo-qualidade-2026-09-17.md) e às autoridades existentes nele listadas. Fonte: [auditoria de 26 itens](../reports/relatorio-auditoria-2026-09-17.md), candidato `b52f32c`.

M0–M7 são marcos de execução propostos, não novos gates de promoção. Os IDs Q17 identificam os itens desta auditoria, não as dimensões do scorecard oficial. A correspondência integral às 64 seções e aos gates vigentes é saída obrigatória de M0.

Cada tarefa do backlog tem subtarefas com dependências específicas; a ordem de aceitação integrada dos marcos é conservadora. Implementação local pode avançar antes do aceite runtime do marco anterior se não depende dele, mas não pode herdar um PASS fictício. Bloqueio externo não impede correções locais independentes.

## Sequência e estimativa relativa

```text
M0 Fundamentos de execução e rastreabilidade
 └─ M1 Ambiente inicializável e migração segura
     └─ M2 Autoridade de dados e ingestão ponta a ponta
         └─ M3 Inteligência fundamentada e políticas reais
             └─ M4 Experiência completa e acessível
                 └─ M5 Operação, recuperação e capacidade
                     └─ M6 Entrega reproduzível e cadeia de confiança
                         └─ M7 Revalidação integral e decisão de promoção
```

Tamanho relativo: S = mudança delimitada em uma fronteira; M = várias fronteiras com testes; L = campanha integrada; XL = campanha com janelas externas e revisão de domínio. Não representa dias, promessa de prazo ou orçamento. Lead converte em calendário somente depois de conhecer equipe, ambiente, corpus e decisões D01–D07 do plano. Incerteza runtime alta até M1; qualidade clínica até M3; janelas operacionais até M5.

| Marco | Porte | Dependência de aceite | Resultado observável | Principais subtarefas |
|---|---|---|---|---|
| M0 | M | D06 | Escopo rastreado, contracts revisados e testes que detectam os achados | Q17-01.A/B, 02.A/B, 06.A, 26.A |
| M1 | L | M0; D01/D02 para live | Imagens inicializam em lab isolado; banco vazio e legado migram; worker observado | Q17-18.A/B, 19.A/B, 20.A, 21.A, 23.A |
| M2 | L | M1 | Upload → objeto → job → worker → índice com integridade e sem publicação indevida | Q17-07.A/B, 08.A/B/C, 20.B, 21.B, 22.A/B |
| M3 | XL | M2; D03/D04 para provider/corpus | Consulta autorizada produz resposta citada ou decisão conservadora adequada | Q17-03.A/B, 04.A/B, 05.A/B, 06.B, 09.A/B, 10.A/B, 11.A/B, 12.A/B, 13.A/B, 14.A/B |
| M4 | L | M3 | Usuário completa chat, documentos e administração com API real e recuperação acessível | Q17-15.A/B, 16.A/B, 17.A/B/C, 26.C |
| M5 | XL | M4; D05 e autoridade de drill | Traces, alertas, restore e workloads/falhas reais cumprem metas congeladas | Q17-23.B, 24.A/B/C |
| M6 | L | M5 | CI cobre produto e evidência; imagens verificadas; decisões válidas são consumidas sem bypass | Q17-25.A/B/C, 26.B |
| M7 | L | M6; D07 | Novo candidato reavaliado, pacote fresco revisado/selado e Go/No-Go explícito | Q17-01.C, 02.C, 25.D, 26.D |

Em M1–M6, antecipar desenvolvimento de harness e CI local de Q17-25/26 assim que suas dependências permitirem; M6 é aceite integrado, não primeira execução de CI. Analogamente, revisão de política, tokens, auth e corpus pode começar em M0; sua aprovação conectada fica em M3/M4.

## M0 — Tornar o trabalho executável

Entrada: D06 permite iniciar construção; preservar alterações existentes, ler instruções aplicáveis e capturar HEAD. Deduplicar tarefas contra `.agent/backlog.json`; vincular Q17 a subtarefas canônicas sem mudar retroativamente resultados.

Entregas: mapa dos 26 itens, 64 seções e 26 dimensões oficiais; dono por contrato; inventário dos casos obrigatórios do prompt; decisões D01–D07 com status/owner; tests known-bad para principais achados e contrato de serialização JSON/SSE/histórico. A regra mais forte entre exigência vigente e implementação de promoção prevalece até decisão explícita.

Saída: nenhum item ou requisito órfão; nenhum ciclo de dependência; baseline discriminante preservado. Achado refutado exige evidência e nova disposição, nunca apagar histórico. Nenhum runtime é aprovado em M0.

## M1 — Ambiente que realmente inicia

Entrada: escopo de lab, secrets, TLS, imagem, daemon e dados aprovados. Sem modificar permissões do host, adotar serviços alheios ou chamar provider pago como teste de prontidão.

Entregas: corrigir factory/variáveis API, configuração Prometheus, healthcheck do processo worker, orçamento de shutdown, migração legada e limites de consultas; observar Redis TLS conforme ambiente. Instrumentação limitada deve sobreviver a sink lento antes de submeter o sistema à carga.

Demonstração: construir e iniciar as imagens no daemon autorizado; readiness/liveness distinguem falhas; migrar base vazia e base com jobs legados; parar/reiniciar somente recursos próprios. `make compose-static` e `make ops-static` continuam necessários, mas não bastam.

Saída: `P0-LAB` e provas iniciais de `P0-DURABILITY` pertinentes passam no escopo observado; runtime ainda não prova produto completo. Sem daemon: `BLOCKED_EXTERNAL`, mantendo correções locais verificáveis.

## M2 — Publicação íntegra e recuperável

Entregas: equivalência de tombstones, batching de embeddings, reindexação por versão de modelo, checksums obrigatórios, bootstrap convergente, Worker A/B e buckets Redis compartilhados. Especificar primeiro a fronteira de transação/outbox/fencing e os casos de rollback.

Demonstração: dois tenants sintéticos, arquivo maior que 256 chunks, reingestão idempotente, exclusão terminal e mudança de embedding; job e objeto reconciliados após falha. Fixture de provider determinístico é permitida para diagnóstico local, mas golden-path/provider live mantém gate separado.

Saída: nenhuma duplicação ou publicação por owner obsoleto nos casos declarados; oito pontos de crash worker e doze falhas de ingestão cobertos e rastreados; checksums e linhagem conferidos em autoridade e projeção. Gate file-security usa corpus de regressão controlado em worker isolado autorizado, sem atacar terceiros.

## M3 — Resposta fundamentada, isolamento e decisão

Entregas: dense+sparse no adapter conectado, fallback explícito, validação pós-geração, política real de risco/intenção, recusa de aprovação sem suporte, orçamentos preventivos, contratos uniformes, auth/CSRF e permissões explicitados.

Demonstração: consulta com fontes válidas, pergunta ambígua, fonte revogada durante geração, ausência de evidência, provider indisponível e conteúdo não suportado. Observar saídas ANSWER/RETRIEVE_AGAIN/CLARIFY/ABSTAIN/ESCALATE nas situações aprovadas, sem colapsar todas em NO_EVIDENCE. Validar isolamento via API e stores com identidades sintéticas.

Avaliação: implementar MRR/nDCG/ganho de reranker/relevância/abstenção faltantes; thresholds por grupo antes dos resultados; corpus autorizado com divisão de calibração/aceitação e revisão qualificada. Nenhum resultado sintético vira atestado clínico.

Saída: `P1-TENANT-EVIDENCE` e `P1-RAG-PROVIDER` com observações adequadas; D04 ausente bloqueia aceite de domínio, não permite fixar risco LOW por conveniência.

## M4 — Produto utilizável e confiável

Entregas: metadados JSON/SSE/histórico equivalentes; paginação; destino de upload explícito; retry binário; jobs longos retomáveis; auditoria consistente; idempotência por intenção e falhas administrativas isoladas.

Demonstração: fluxos web completos contra API real, sem interceptar a fronteira principal por respostas fabricadas. Testes mockados permanecem como complemento de estados raros. Capturar todos os estados/viewports definidos no plano, incluindo 403, rede interrompida, conteúdo longo e sessão expirada.

Saída: nenhuma tarefa primária quebrada; WCAG AA nos critérios aplicáveis comprovados, navegação assistiva e teclado inspecionados; pacote visual ≥95 com confiança HIGH e crítica independente. Sem browser/render: `NOT_RUN`, jamais aprovação visual por lint/build.

## M5 — Operação e recuperação comprovadas

Entregas: exporter real, correlação API→queue→worker→retrieval→provider, alertas observados, cardinalidade limitada, restore de serviços e reconstrução da projeção. Campanhas de carga, treze faults chaos/cinco invariantes e dois perfis soak conforme requisito.

Demonstração: `seed → backup → destroy → restore → rebuild → verify` somente na cópia isolada autorizada; medir RPO/RTO; verificar identidades, ACL, jobs, attempts, outbox, audit, objetos, checksums e linhagem. Cinco workloads em concorrência 1/10/50/100 com p50/p95/p99, erros, throughput, CPU/RAM e custos.

Saída: objetivos e budgets aprovados em D05 antes da campanha, sem reduzir depois dos resultados. Se capacidade 100 não for viável no hardware, registrar falha/limite e decisão de capacidade, não omitir o caso. Staging e produção mantêm registros distintos; observação de 30 dias não é fabricada por soak curto.

## M6 — Pipeline capaz de provar e rejeitar

Entregas: CI inclui web canônica e pacotes Python, testes novos, verificadores conhecidos bons/ruins, lab aprovado e artefatos immutable; SBOM, licença, secrets/dependências/imagens, non-root/read-only/capabilities/resources/health e assinaturas.

Corrigir as etapas sem comando do orquestrador por ingestão de observações verificadas e identidade de aprovador, não por PASS fixo ou execução de aprovação humana automática. Resolver a ordem CI/runtime/autoridade para que não exija um pacote impossível antes de coletar seus inputs.

Saída: pacote válido autorizado pode ser processado e inválido é rejeitado; origem de reviews e decisão humana conferida; gates atuais não removidos. Não basta provar que o verificador sempre retorna NO-GO.

## M7 — Revalidar e decidir, sem promessa automática

Preparar candidato limpo autorizado, reler o mapa e as revisões. Executar novamente todas as lanes obrigatórias, preservar falhas e vincular logs sanitizados a commit/tree/digests/run/ambiente. Matriz oficial com 26 dimensões, média ≥96, zero Critical/High e todos os gates obrigatórios PASS. Provas de frontend, RAG, runtime e recuperação devem corresponder ao mesmo candidato e às janelas aceitas.

Críticos frescos por escopo, review final distinto de builders/revisores anteriores, checagem de imutabilidade, signatário autorizado e Go/No-Go explícito. `make triple-aaa-verify` deve refletir o conjunto válido; saída 2 é bloqueio externo, 1 falha e 0 apenas quando todas as condições obrigatórias forem atendidas. Verificar também JSON: saída GNU Make não substitui status detalhado.

Saídas possíveis: **TRIPLE_AAA demonstrado no escopo aprovado** ou **NO-GO com lacunas, owner e próxima ação**. Aceite deste roadmap não promete resultado, prazo, certificação clínica ou implantação automática.

## Paralelismo e pontos de sincronização

- Lead detém schema compartilhado, contratos SSE, estado e integração; builders não editam esses arquivos simultaneamente.
- Lane dados/runtime: Q17-18/19/20/21/22; lane RAG: Q17-07/08/09/10/11/12/13/14; lane experiência: Q17-03/04/05/06/15/16/17; QA/release transversal Q17-23/24/25/26. As lanes são responsabilidades, não permissão para ignorar conflitos.
- `external_composition.py` e `professor_backend.py` exigem sequência de owner, não escrita paralela. UI espera contrato estável de retry/SSE antes de integrar; design brief e fixtures podem anteceder.
- A cada marco, integração e crítica independente antes de aceitar o seguinte. Builder retorna IMPLEMENTED, jamais autoaprovação.

## Interrupção, reversão e retomada

Interromper por requisito material ambíguo, autorização ausente, fonte de evidência inválida, quebra de integridade ou risco fora do lab. Registrar candidato, efeito parcial, artefatos, tarefa, autoridade e próximo teste no controle canônico quando ativo. Manter evidência de falhas. Teardown somente próprio, sem remoção automática de volumes/evidências. Migration aplicada exige estratégia Q17-19; alterações irreversíveis de dados não têm "git revert" como recuperação.

Estado inicial de todos os marcos: PLANEJADO; gates de produto não executados por esta entrega. Próxima ação de construção: D06 → Q17-01.A → Q17-02.A/Q17-26.A.
