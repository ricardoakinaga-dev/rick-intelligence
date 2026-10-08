# Roadmap de remediação RICK Intelligence

**Data:** 03/10/2026. **Estado:** planejamento proposto a partir da auditoria de 02–03/10/2026. **Baseline:** 76/100, 29 áreas e 24 achados; prontidão `NO-GO`.

Este roadmap organiza a correção dos defeitos de autorização, publicação de dados, geração, interface e CI encontrados na auditoria. A primeira entrega é um candidato local com regressões que rejeitam os cenários reproduzidos. A entrega final depende de integração real, recuperação comprovada e decisão de promoção vinculada ao candidato.

O [backlog desta rodada](backlog-auditoria-2026-10-03.md) detalha 36 tarefas com dependências e critérios de aceite. O [snapshot da auditoria](reports/evidence/auditoria-2026-10-03/scorecard.json) preserva notas, achados A01–A24, fontes e limitações. Este planejamento não altera os estados de execução em `.agent/` nem inicia as correções.

## Ponto de partida

O corte auditado tinha HEAD `b52f32c141916a2ea3af1a6b913bd91f380606e0` e alterações locais. As notas se referem a essa árvore, incluindo arquivos não commitados; repetir a identificação antes da implementação é obrigatório.

A matriz principal teve 2.070 testes Python aprovados, 79 pulados e uma falha. Os testes de domínio e tooling exigiram dependências adicionais ausentes do lock canônico. O frontend passou lint, typecheck e quatro testes unitários; a cobertura apresentada se limita a três helpers. Testes verdes não rejeitaram os novos cenários adversariais de autorização e integridade.

O relatório registrou 13 achados de gravidade alta, nove médios, um baixo e um condicional. A03 depende do adapter OIDC/resolver selecionado; A06 demonstrou o efeito destrutivo no store em memória; A10 demonstra exposição no cliente, sem provar bypass do backend. A24 comprova feedback por outro proprietário, mas sua classificação depende da política de colaboração. Esses limites devem acompanhar as regressões e a revisão.

## Etapas e entregas

| Marco | Resultado esperado | Tarefas | Condição de saída |
|---|---|---|---|
| **M0 Baseline e documentação** | Um candidato identificável, reproduções preservadas e referências acessíveis | AUD03-01, AUD03-25 | Hashes, comandos, primeiros resultados e mapa A01–A24 registrados; links do pacote resolvem |
| **M1 Autorização e auditoria** | Revogação permanece negativa; membership e grants controlam cada ação; mutações obrigatórias têm trilha durável | AUD03-02–07, AUD03-13 | Negativos dos achados A01–A03, A09, A14 e A17 passam; política A24 definida ou módulo clínico permanece fechado |
| **M2 Integridade de publicação** | Uma tentativa antiga não desfaz outra; IDs são inequívocos; catálogo e tombstones preservam seu ciclo de vida | AUD03-08–12 | Interleavings A04/A05, colisão A06, coleção arquivada A07 e tombstone A16 têm regressões discriminantes |
| **M3 Geração e interface** | Respostas só são aprovadas com término válido; permissão revogada retira dados; streams e teclado respeitam estados terminais | AUD03-14–20 | Reproduções de provider, wildcard, caso tardio, SSE, foco e SLO inválida são rejeitadas; testes cobrem componentes e parser |
| **M4 CI e regressão integrada local** | Checkout novo executa os checks necessários com ambiente declarado, sem histórias locais implícitas | AUD03-21–24, AUD03-26 | FAST/UNIT/tooling e web passam no candidato limpo; dependências completas; fixtures incorretas falham nos checkers |
| **M5 Integração e qualidade real** | Identidade, stores, fila, worker, provider e browser funcionam juntos com isolamento demonstrado | AUD03-27–30 | Inventário instalado, golden path, negativos multi-tenant e campanha autorizada têm provas atuais |
| **M6 Operação e recuperação** | Falhas são detectadas; dados são recuperáveis; capacidade e comportamento prolongado são medidos | AUD03-31–35 | Collector/alertas, restore, RPO/RTO, carga, chaos e soak cumprem budgets definidos antes dos ensaios |
| **M7 Reauditoria e promoção** | Release deriva de evidência atual e autoridade verificável | AUD03-36 | Mesmo candidato em CI/runtime/imagens, nenhuma falha alta sem resolução aceita e decisão Go/No-Go registrada |

## Sequência e trabalho em paralelo

A sequência de aceite é **M0 → M1/M2/M3 → M4 → M5 → M6 → M7**. O aceite de M4 depende da integração das correções locais. As correções de bootstrap e dependências do CI podem começar logo após M0 para sustentar os testes das outras frentes.

| Frente | Pode começar | Coordenação necessária |
|---|---|---|
| Identidade, grants e auditoria | Após a identificação da baseline | Sequenciar mudanças no mesmo provider, política e rotas; alinhar transações/outbox antes de implementar AUD03-06 |
| Ingestão e knowledge | Após a identificação da baseline | AUD03-08/09/11 compartilham pipeline; um responsável integra as alterações. IDs novos exigem contrato de compatibilidade |
| Provider e evidência | Após a identificação da baseline | AUD03-15 integra a semântica de wildcard definida em AUD03-02/04 |
| Interface | Após a identificação da baseline | AUD03-16–18 têm arquivos distintos; integrar sessão, parser e componentes antes da matriz AUD03-20/26 |
| CI e checkers | Após a identificação da baseline | Mudanças de workflow/locks e regras de controle têm um integrador; preservar a autoridade e o histórico dos gates |
| Inventário read-only instalado | Quando existir o escopo externo aplicável | Pode antecipar M5; não aplicar migrations nem alterar dados durante AUD03-27 |

As dependências explícitas do backlog prevalecem sobre o paralelismo sugerido aqui. Não executar duas alterações concorrentes no mesmo arquivo ou recurso mutável.

## Gates de passagem

### G1 Correção local

Cada bug precisa de reprodução que falha na baseline e passa após a correção. Preservar casos positivos, compatibilidade e isolamento. Uma revisão deve conferir o comportamento público ou a fronteira efetivamente afetada; mocks isolados não encerram um bug que dependa da integração dos adapters.

### G2 Candidato reproduzível

Executar CI e suites no checkout limpo da versão integrada, com dependências instaladas dos locks e sem pacotes extras do host. Todos os checks obrigatórios devem retornar sucesso. Os 79 casos pulados da baseline precisam ser classificados; os obrigatórios para o gate seguinte deverão executar. Cobertura deve informar denominador e exclusões.

### G3 Integração autorizada

Identificar endpoints, credenciais, dados permitidos, limites de recurso e teardown antes da execução. Exercer tenant A/B, revogação, reinício, replay, falha de provider e publicação concorrente nos serviços reais. Resultados locais anteriores não substituem essa prova.

### G4 Operação comprovada

Definir budgets de RPO/RTO, latência, erros, memória e duração antes dos ensaios. Medir restore e capacidade com a mesma versão e topologia. Ausência de amostras permanece `no_data`; falha ou ausência de artefato não vira PASS.

### G5 Promoção

CI, evidências de runtime, imagens, scans, assinaturas e pareceres devem identificar o mesmo candidato e seus digests. A nota média pode ser recalculada na reauditoria; não é condição suficiente para promover. A autoridade de release decide Go/No-Go com riscos residuais e responsável por recuperação explícitos.

## Dependências externas e decisões

| Dependência | Tarefas afetadas | Preparação possível agora |
|---|---|---|
| Política de feedback por outro proprietário | AUD03-07; gate clínico de AUD03-26/30 | Documentar a decisão pendente e preservar o comportamento fechado por padrão |
| História de migrations e escopo de dados instalados | AUD03-10/27/28 | Preparar inventário read-only e compatibilidade de IDs em fixtures |
| Lab, IdP, PostgreSQL, Redis, Qdrant, S3 e provider | AUD03-28/30 | Preparar harnesses, namespaces descartáveis e negativos |
| Corpus representativo, direitos e revisão de domínio | AUD03-29 | Definir desenho da avaliação, splits e campos de provenance |
| Collector, alert routing e ensaios de falha/recuperação | AUD03-31–35 | Definir sinais, budgets, carga e condições de aborto |
| Registry, assinatura, revisão e autoridade de promoção | AUD03-36 | Preparar manifesto e pacote sem declarar promoção |

Consultar os [bloqueadores externos](reports/external-evidence-blockers.md), o [runbook de release](operations/release-readiness.md) e o [procedimento de upgrade](operations/migration-upgrade-2026-09-24.md). As referências orientam o trabalho; sua existência não comprova que a dependência já esteja disponível.

## Priorização e estimativa

Executar primeiro os P0 de autorização e integridade, preservando privacidade na interface e validação de término do provider. Desbloquear CI em paralelo. Em seguida fechar os P1 de paridade, contratos negativos, observabilidade local e cobertura. Os P2 documentais podem avançar junto de M0.

O backlog usa tamanhos relativos P/M/G. Não há calendário prometido: faltam capacidade da equipe, ambiente e decisões externas. Após M0, o responsável pelo projeto pode distribuir as tarefas em ciclos conforme disponibilidade e resultados. O prazo dos marcos externos começa a ser estimável quando suas dependências estiverem confirmadas.

## Primeira entrega

Começar por **AUD03-01**, preservar os cenários e iniciar **AUD03-02/03/04** e **AUD03-08/10/11** em frentes coordenadas, com **AUD03-21/22** sustentando CI. AUD03-14 e AUD03-16 podem avançar em arquivos independentes. Reunir essas correções num candidato para AUD03-26 antes de buscar aceite de runtime.
