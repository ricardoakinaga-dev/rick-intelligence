# Backlog de remediação RICK Intelligence

**Data:** 03/10/2026. **Estado:** 36 tarefas propostas; implementação não iniciada por este pacote. **Origem:** auditoria de 02–03/10/2026, 76/100, 29 áreas, 24 achados e prontidão `NO-GO`.

Este backlog traduz os achados A01–A24 em correções verificáveis e acrescenta o trabalho de integração, operação e promoção ainda sem prova. O [roadmap](roadmap-auditoria-2026-10-03.md) define a sequência dos marcos. O [snapshot de origem](reports/evidence/auditoria-2026-10-03/scorecard.json) preserva observações, notas e limites; seus caminhos `/tmp` são referências históricas de execução e precisam ser arquivados em AUD03-01.

Os IDs AUD03 pertencem a este planejamento. Eles não encerram nem substituem tarefas Q17/Q24/R27/AUD26, os ledgers em `.agent/` ou gates de promoção. Conclusão local e validação externa terão registros distintos.

## Convenções de execução

- **P0:** defeito de autorização, privacidade ou integridade, ou impedimento essencial à validação do candidato. Priorizar antes de ampliar exposição.
- **P1:** confiabilidade, compatibilidade, testes ou prova operacional necessária para o respectivo gate.
- **P2:** documentação e manutenção sem alteração de comportamento.
- **Tamanho P:** alteração delimitada e teste focado. **M:** vários componentes ou contratos. **G:** concorrência, compatibilidade de dados ou execução distribuída. São estimativas relativas propostas.
- **Planejada:** trabalho local ainda não iniciado. **Dependência externa:** execução depende de ambiente, dados, política ou autoridade descrita. A disponibilidade deve ser reconferida antes de executar.
- Os responsáveis são papéis sugeridos, não designações de pessoas. Registrar ownership antes de alterações paralelas.

Uma tarefa só recebe aceite quando cumprir os critérios, preservar o primeiro resultado da baseline e apresentar candidato/hash, comando completo, exit code, resultado, artefatos e limites. Criar regressões que rejeitem o comportamento incorreto. Não enfraquecer thresholds, pinar Actions novamente por tag, remover gates ou marcar casos como ignorados para obter sucesso.

## Fila de tarefas

| ID | Marco | Prioridade | Entrega | Tamanho | Dependências | Estado |
|---|---|---|---|---|---|---|
| AUD03-01 | M0 | P1 | Identificar candidato e preservar reproduções | M | — | Planejada |
| AUD03-02 | M1 | P0 | Preservar negação após retirar último grant | M | 01 | Planejada |
| AUD03-03 | M1 | P0 | Exigir grant na mutação de coleção | P | 02 | Planejada |
| AUD03-04 | M1 | P0 | Validar membership OIDC ativa e completa | M | 01 | Planejada |
| AUD03-05 | M1 | P1 | Rejeitar snapshot moderno malformado | M | 04 | Planejada |
| AUD03-06 | M1 | P0 | Vincular auditoria obrigatória às mutações | G | 01 | Planejada |
| AUD03-07 | M1 | P1 | Definir limite de feedback em caso de terceiro | M | 01 | Dependência externa |
| AUD03-08 | M2 | P0 | Impedir compensação por tentativa antiga | G | 01 | Planejada |
| AUD03-09 | M2 | P0 | Tornar consistente a saída do guard de publicação | M | 08 | Planejada |
| AUD03-10 | M2 | P0 | Eliminar colisão de IDs com compatibilidade | G | 01 | Planejada |
| AUD03-11 | M2 | P0 | Preservar coleção arquivada e catálogo | M | 08 | Planejada |
| AUD03-12 | M2 | P1 | Impedir ressurreição de tombstone em memória | P | 10 | Planejada |
| AUD03-13 | M1 | P1 | Negar escopo vazio antes de embed e search | P | 02 | Planejada |
| AUD03-14 | M3 | P0 | Rejeitar provider sem término válido | P | 01 | Planejada |
| AUD03-15 | M3 | P1 | Respeitar wildcard na revalidação de evidência | P | 02, 04, 14 | Planejada |
| AUD03-16 | M3 | P0 | Descartar resposta privada após revogação | M | 01 | Planejada |
| AUD03-17 | M3 | P1 | Encerrar SSE e cancelar consumo em falha | M | 14 | Planejada |
| AUD03-18 | M3 | P1 | Conter foco em diálogo ocupado | P | 01 | Planejada |
| AUD03-19 | M3 | P1 | Rejeitar SLI e threshold inválidos | P | 01 | Planejada |
| AUD03-20 | M3 | P1 | Cobrir parser, sessão e componentes web | M | 15–18 | Planejada |
| AUD03-21 | M4 | P0 | Validar controle em checkout novo | G | 01 | Planejada |
| AUD03-22 | M4 | P0 | Completar dependências da CI nos locks | M | 01 | Planejada |
| AUD03-23 | M4 | P1 | Corrigir regressão de Action pinada por SHA | P | 22 | Planejada |
| AUD03-24 | M4 | P1 | Tornar checkers de CI e TypeScript discriminantes | M | 21–23 | Planejada |
| AUD03-25 | M0 | P2 | Corrigir referências documentais quebradas | P | 01 | Planejada |
| AUD03-26 | M4 | P1 | Validar candidato integrado local | G | 02–25; 07 condicional | Planejada |
| AUD03-27 | M5 | P1 | Inventariar migrations e compatibilidade instalada | M | 01 | Dependência externa |
| AUD03-28 | M5 | P0 | Provar golden path e publicação com serviços reais | G | 26, 27 | Dependência externa |
| AUD03-29 | M5 | P1 | Executar campanha RAG representativa | G | 28 | Dependência externa |
| AUD03-30 | M5 | P0 | Provar revogação e isolamento com IdP e réplicas | G | 26, 28; 07 condicional | Dependência externa |
| AUD03-31 | M6 | P1 | Provar collector, alertas e sinais distribuídos | G | 19, 28 | Dependência externa |
| AUD03-32 | M6 | P0 | Medir restore e reconciliação por tenant | G | 27, 28 | Dependência externa |
| AUD03-33 | M6 | P1 | Medir capacidade e latência representativas | G | 28, 31 | Dependência externa |
| AUD03-34 | M6 | P1 | Ensaiar falhas e recuperação controladas | G | 28, 31, 32 | Dependência externa |
| AUD03-35 | M6 | P1 | Executar soak com limites de recursos | G | 33, 34 | Dependência externa |
| AUD03-36 | M7 | P0 | Reauditar e decidir promoção do candidato | G | 26–35 | Dependência externa |

As dependências abreviadas usam o prefixo AUD03. Intervalos incluem todos os IDs indicados. AUD03-07 é condição dos gates clínicos somente quando o módulo estiver habilitado; manter as duas flags fechadas preserva o limite durante as demais validações, sem declarar a política resolvida.

## Aceite comum

1. A reprodução relevante distingue baseline incorreta e candidato correto; os resultados originais ficam preservados.
2. O caso positivo continua funcionando, com compatibilidade e escopo explícitos.
3. Testes negativos incluem revogação, exceção, cancelamento, estado vazio e concorrência quando aplicáveis.
4. Não há escrita fora do escopo autorizado nem alteração de histories/checksums para encobrir divergência.
5. Evidências identificam a árvore exata. `NOT_RUN`, `BLOCKED_EXTERNAL`, `STALE` e falha não contam como aprovação.
6. Revisão separada confere os P0 e mudanças de identidade, dados, auditoria ou promoção. A conclusão de quem implementou não substitui essa revisão.

## Baseline e documentação

### AUD03-01 Identificar candidato e preservar reproduções

**Responsável sugerido:** integração e qualidade. **Origem:** corte completo da auditoria.

Registrar HEAD, diff, hashes dos arquivos não commitados e dependências. Preservar os scripts/logs adversariais de segurança, ingestão e frontend antes de alterar o código; sanitizar dados e registrar o ambiente usado. O snapshot incluído neste pacote é um registro histórico e não substitui a repetição da baseline.

**Aceite:** cada A01–A24 possui fonte e procedimento recuperável; baselines de coleta/CI e limites dos mocks estão registrados; a árvore do usuário está preservada. O primeiro candidato de correção pode ser distinguido por hash. Evidências novas têm destino durável sob `docs/reports/evidence/` ou referência CI recuperável.

### AUD03-25 Corrigir referências documentais quebradas

**Responsável sugerido:** documentação e integração. **Origem:** A23.

Reconciliar os destinos em `docs/plans/phase-3-runtime-evidence-production-promotion.md`, `docs/reports/relatorio-auditoria-local-2026-10-01-base.md` e `docs/progress/phase-1.1-report.md`. Identificar documentos históricos e os destinos atuais sem reescrever decisões antigas.

**Aceite:** links locais resolvem, incluindo sintaxe de linha; o índice aponta para o pacote vigente quando este for incorporado como referência atual; arquivo inexistente não é recriado como evidência fictícia.

## Autorização e auditoria

### AUD03-02 Preservar negação após retirar último grant

**Responsável sugerido:** identidade e autorização. **Origem:** A01. **Fonte:** `packages/authorization/src/rick_authorization/policy.py`.

Distinguir grants omitidos de lista explicitamente vazia. Remover o último grant não pode restaurar `*` nem `rag_phase0`. Revisar derivação, persistência, login e refresh para conservar essa distinção.

**Aceite:** gestor e veterinário com zero grants continuam sem coleções no próximo login/refresh; wildcard explícito e grants válidos continuam funcionando; importação legacy tem regra específica e não reexpande um snapshot moderno. Testar memória e adapters persistentes, incluindo retirada de grant e tentativa de consulta.

### AUD03-03 Exigir grant na mutação de coleção

**Responsável sugerido:** API e autorização. **Origem:** A02. **Fonte:** `apps/api/src/routes/knowledge.py`.

Aplicar o collection scope aos handlers de edição e archive, além da permissão de papel. Conferir os outros handlers administrativos de coleção que usam a mesma fronteira.

**Aceite:** gestor autorizado apenas em `allowed` não edita nem arquiva `secret`; nada é alterado na coleção negada. Grant específico e wildcard autorizado permitem operações corretas. Executar negativos pela rota HTTP e conferir persistência e auditoria.

### AUD03-04 Validar membership OIDC ativa e completa

**Responsável sugerido:** identidade. **Origem:** A03. **Fonte:** `packages/identity/src/rick_identity/oidc.py`.

Exigir estado ativo e identidade/tenant/workspace/papel obtidos da autoridade de membership. Registros incompletos ou desativados devem ser negados; claims não completam privilégios omitidos pela autoridade.

**Aceite:** tokens válidos com membership disabled/inactive, incompleta ou divergente resultam sessão anônima/negação; claims `PLATFORM_ADMIN` e workspace estrangeiro não ganham autoridade. Membership ativa correta continua autenticando. Documentar o contrato do resolver e validar cada adapter composto.

### AUD03-05 Rejeitar snapshot moderno malformado

**Responsável sugerido:** identidade e stores. **Origem:** A14. **Fonte:** `packages/identity/src/rick_identity/provider.py` e `postgres.py`.

Restringir migração aos estados realmente legacy. Snapshot moderno sem `permissions`, versão incompatível ou campo inválido deve falhar fechada.

**Aceite:** o caso `AUTHORITATIVE` v1 sem permissões é negado e não recebe defaults do papel; permissões vazias permanecem negativas; migração legacy legítima persiste uma vez e não muda silenciosamente nas leituras seguintes.

### AUD03-06 Vincular auditoria obrigatória às mutações

**Responsável sugerido:** API e persistência. **Origem:** A09. **Fontes:** `apps/api/src/routes/sessions.py`, `knowledge.py` e fronteiras de audit/outbox.

Definir a unidade atômica de revogação, delete/reindex e outras mutações sensíveis. Usar a autoridade persistente/outbox apropriada para que falha na gravação obrigatória não seja reportada apenas depois do efeito comprometido. Um intent isolado precisa ter resultado/reconciliação rastreáveis.

**Aceite:** falha de gravação obrigatória não deixa uma mutação efetivada sem trilha; exceção durante a operação registra desfecho consistente; replay/idempotência não duplica efeitos. Exercitar stores reais em memória/local e fixtures transacionais, preservando distinção entre commit do audit e entrega posterior do sink. Prova PostgreSQL integrada pertence também a AUD03-28.

### AUD03-07 Definir limite de feedback em caso de terceiro

**Responsável sugerido:** produto/domínio e autorização. **Origem:** A24, condicional. **Fonte:** `apps/api/src/routes/cases.py`.

Decidir se veterinários podem enviar feedback sobre casos de outros proprietários no mesmo workspace, e qual permissão específica autoriza isso. A reprodução atual prova o comportamento, não resolve a política.

**Aceite:** decisão de owner-only ou colaboração explícita documentada e aplicada em rotas/stores; negativos cruzam owner, tenant e workspace; feedback permitido tem ator e trilha. Enquanto a decisão faltar, conservar o módulo fechado por padrão e não declarar aceite clínico.

### AUD03-13 Negar escopo vazio antes de embed e search

**Responsável sugerido:** retrieval. **Origem:** A17. **Fonte:** `packages/retrieval/src/rick_retrieval/pipeline.py`.

Encerrar consulta sem coleções permitidas antes de qualquer embed ou backend search.

**Aceite:** contadores de adapters ficam em zero quando `allowed_collection_ids=[]`; nenhuma query é enviada ao provider; resultado comunica negação/ausência conforme contrato. Coleção permitida e wildcard válido preservam ranking e proveniência.

## Integridade de publicação

### AUD03-08 Impedir compensação por tentativa antiga

**Responsável sugerido:** ingestão, jobs e knowledge. **Origem:** A04. **Fonte:** `packages/ingestion/src/rick_ingestion/pipeline.py`.

Vincular escritas de documento/chunks/vetores e compensação à tentativa/versão que possui a operação. O fence da fila deve proteger também os efeitos do pipeline, não somente ACK. Definir o contrato entre stores antes de alterar os adapters.

**Aceite:** suspender A, perder sua posse, publicar com B e retomar A não remove nenhum dado de B; documento e vetores permanecem publicados e íntegros. Testar cancelamento, falha e retry com barreiras determinísticas, incluindo compensação após escrita parcial. Prova distribuída com PostgreSQL/Qdrant será exigida em AUD03-28.

### AUD03-09 Tornar consistente a saída do guard de publicação

**Responsável sugerido:** worker e ingestão. **Origem:** A05. **Fontes:** `apps/worker/external_ingestion.py` e pipeline.

Alinhar o commit da publicação e a verificação de lease. Uma exceção na saída do guard não pode deixar o job publicado e seus dados apagados, nem tentar uma transição terminal inválida.

**Aceite:** perda de lease na entrada, antes do commit e na saída mantém estado de job/documento/vetores coerente; não ocorre `published → failed` inválido; resultado indica o desfecho real e não compensa publicação pertencente a outra tentativa.

### AUD03-10 Eliminar colisão de IDs com compatibilidade

**Responsável sugerido:** knowledge e arquitetura de dados. **Origem:** A06. **Fonte:** `packages/knowledge/src/rick_knowledge/identity.py`.

Definir encoding de identidade inequívoco e versionado, preservando determinismo. A compatibilidade dos IDs existentes exige inventário/mapeamento e plano de migração; não recalcular IDs persistidos ou referências de citações silenciosamente.

**Aceite:** `default/tenant:t:w` e `t/w` nunca recebem o mesmo ID com coleção/bytes iguais; variações de separadores e scope têm testes; IDs repetidos no mesmo scope continuam estáveis. Fixtures antigas preservam leitura/referências ou migram por procedimento explícito e verificável. Aplicação em dados instalados depende de AUD03-27 e do plano aprovado de compatibilidade.

### AUD03-11 Preservar coleção arquivada e catálogo

**Responsável sugerido:** ingestão e knowledge. **Origem:** A07. **Fonte:** pipeline e adapters de catálogo.

Separar criação de coleção inexistente de ingestão numa coleção existente. A ingestão não deve reabrir coleção arquivada nem substituir título, descrição, versão ou retention metadata.

**Aceite:** tentativa em coleção arquivada é negada sem mudar catálogo; ingestão numa coleção ativa conserva campos existentes; criação concorrente não sobrescreve catalogação revisada. Reativação, quando autorizada, passa por operação explícita auditada.

### AUD03-12 Impedir ressurreição de tombstone em memória

**Responsável sugerido:** knowledge. **Origem:** A16. **Fonte:** `packages/knowledge/src/rick_knowledge/store.py`.

Aplicar ao store em memória o contrato terminal de exclusão existente nos adapters persistentes.

**Aceite:** delete seguido de upsert published do mesmo ID é rejeitado em memória/SQLite/PostgreSQL; nenhum chunk ou vetor torna o tombstone visível. A matriz de contrato verifica paridade, inclusive operações de manutenção expressamente suportadas.

## Geração e interface

### AUD03-14 Rejeitar provider sem término válido

**Responsável sugerido:** providers e Professor. **Origem:** A08. **Fonte:** `packages/providers/src/rick_providers/client.py`.

Eliminar o default `stop` quando a resposta omitir o sinal de término. Preservar a distinção entre conclusão, truncamento, tool call e resposta malformada.

**Aceite:** resposta HTTP 200 sem `finish_reason`, com valor null/inválido ou conteúdo incompleto recebe erro tipado e nunca `APPROVED_EVIDENCE`; JSON e streaming cumprem o mesmo contrato; término válido continua aprovando quando os outros gates passam.

### AUD03-15 Respeitar wildcard na revalidação de evidência

**Responsável sugerido:** evidência e autorização. **Origem:** A15. **Fonte:** `apps/api/src/services/professor_backend.py`.

Usar a semântica canônica de permissão na revalidação em vez de exigir a string literal `chat.query`.

**Aceite:** wildcard autorizado e `chat.query` explícito dão o mesmo resultado para evidência idêntica; lista vazia/negada e scope revogado continuam rejeitando; a revalidação não reexpande permissões retiradas.

### AUD03-16 Descartar resposta privada após revogação

**Responsável sugerido:** frontend e sessão. **Origem:** A10. **Fontes:** `case-workspace.tsx`, `app-shell.tsx` e session provider.

Cancelar ou invalidar requisições antigas quando identidade, scope ou permissões mudarem. Limpar dados privados e impedir que respostas tardias de list/detail/mutation restaurem a view.

**Aceite:** remover `cases.read` com list/detail pendentes mantém a restrição após todas as respostas; dados antigos não aparecem no DOM, estado ou ações. Mudanças de tenant/workspace e logout recebem a mesma proteção. Backend continua revalidando autorização independentemente do cliente.

### AUD03-17 Encerrar SSE e cancelar consumo em falha

**Responsável sugerido:** frontend e contratos de chat. **Origem:** A18. **Fonte:** `apps/web/lib/api.ts`.

Tratar completion/DONE/error/abort como estados explícitos. Eventos posteriores ao terminal não alteram a resposta aceita. Cancelar o reader/stream quando o processamento falhar ou for abortado.

**Aceite:** completion → DONE → nova completion conserva a resposta válida ou rejeita o fluxo conforme política documentada, sem aceitar substituição; erro/abort cancela o stream e libera recursos. Testar frames divididos, conclusão ausente, EOF e eventos inválidos.

### AUD03-18 Conter foco em diálogo ocupado

**Responsável sugerido:** frontend e acessibilidade. **Origem:** A19. **Fonte:** `apps/web/components/ui.tsx`.

Manter foco no diálogo quando seus controles ficarem disabled, com um destino focável apropriado e anúncio do estado ocupado.

**Aceite:** Tab/Shift+Tab não escapam durante busy; foco é restaurado ao fechar; Escape segue a política de operação; teclado e semântica de modal são verificados no browser.

### AUD03-19 Rejeitar SLI e threshold inválidos

**Responsável sugerido:** observabilidade. **Origem:** A20. **Fonte:** `packages/observability/src/rick_observability/slo.py`.

Validar finitude, sinal, contagens e budgets antes da decisão. Definir a resposta de erro/ausência de dado para entradas inválidas.

**Aceite:** NaN, infinidades, latência negativa e threshold inválido nunca produzem `healthy`; amostra zero permanece `no_data`; valores válidos dentro/fora do budget continuam healthy/breach; bool não é aceito como contagem numérica legítima.

### AUD03-20 Cobrir parser sessão e componentes web

**Responsável sugerido:** frontend e qualidade. **Origem:** A22.

Adicionar testes comportamentais para parser, sessão e componentes afetados. Reportar cobertura desses caminhos e conservar o denominador explícito; não usar os três helpers como substituto da garantia da aplicação.

**Aceite:** retirar os fixes de AUD03-16/17/18 faz os respectivos testes falharem; permissão, loading/erro/retry, cancelamento e foco são exercitados. CI executa esses testes; build e matriz browser validam as interações complementares em AUD03-26.

## CI e validação integrada local

### AUD03-21 Validar controle em checkout novo

**Responsável sugerido:** CI e integração. **Origem:** A11. **Fontes:** `docs/ci/check_control_plane.py`, validators e workflows.

Definir os inputs persistentes do controle e sua restauração verificável num runner novo. Preservar decisões/histórias e checksums; arquivos ignorados existentes no host não podem ser pré-condição implícita. Não criar aprovação vazia para preencher arquivos faltantes.

**Aceite:** checkout limpo do candidato com o procedimento declarado executa `make validate`; runner não usa diretórios locais prévios; input ausente/corrompido ainda falha. Histórico de auditoria mantém proveniência e autoridade, com política de versionamento ou recuperação explícita.

### AUD03-22 Completar dependências da CI nos locks

**Responsável sugerido:** toolchain e CI. **Origem:** A12. **Fontes:** `requirements/*.in`, `*.lock`, `Makefile` e `.github/workflows/quality.yml`.

Cobrir PyYAML, qdrant-client e imports transitivos efetivamente usados por cada lane. Regenerar locks por seu processo, com hashes e compatibilidade; separar legacy diferencial se necessário sem omitir a cobertura exigida.

**Aceite:** ambiente novo instalado somente dos locks declarados coleta e executa infraestrutura, domínio, migrations/jobs/storage e gates de tooling; `pip check` passa; nenhuma instalação supplemental manual é necessária. Fixtures missing-dependency falham e a lane correspondente fica explícita.

### AUD03-23 Corrigir regressão de Action pinada por SHA

**Responsável sugerido:** qualidade e release. **Origem:** A13. **Fonte:** `scripts/state_of_art/tests/test_generate_release_evidence.py`.

Atualizar a assertion para validar o pin imutável e os downloads obrigatórios do workflow atual.

**Aceite:** teste passa com o SHA revisado e falha com tag mutável, download ausente ou artefato errado; preservar `actions/download-artifact` pinada por commit. A suíte `scripts/state_of_art/tests` passa no ambiente canônico.

### AUD03-24 Tornar checkers de CI e TypeScript discriminantes

**Responsável sugerido:** arquitetura e CI. **Origem:** A21. **Fontes:** `scripts/phase15/check_boundaries.py` e `scripts/phase11/check_canonical_ci.py`.

Verificar imports TypeScript/TSX relevantes e comandos de steps executáveis, sem aceitar ocorrência apenas em comentário. Preservar exceções explícitas de adapters e migrations.

**Aceite:** import direto proibido do legado em TS/TSX é rejeitado; comando obrigatório comentado não satisfaz a regra; arquivo/texto irrelevante não cria falso PASS. Fixtures corretas continuam passando e os checkers executam no CI.

### AUD03-26 Validar candidato integrado local

**Responsável sugerido:** integração e revisão independente. **Origem:** todos os defeitos locais corrigidos.

Integrar as mudanças, identificar candidato limpo e repetir API/packages/worker/infra/tooling, locks, lint/typecheck/build, contrato HTTP e browser a 375/768/1440. Exercer falha, retry, revogação, upload, chat e administração. Registrar quais rotas usam fixtures e quais usam API real.

**Aceite:** nenhum P0 local pendente; suites obrigatórias sem falhas; todos os achados locais possuem regressão e revisão. Screenshots, console/network, teclado e acessibilidade correspondem ao build final. Os testes opt-in externos continuam classificados, sem serem contabilizados como PASS. AUD03-07 resolvido para fluxo clínico habilitado, ou flags permanecem fechadas e o aceite exclui esse fluxo explicitamente.

## Integração e qualidade real

### AUD03-27 Inventariar migrations e compatibilidade instalada

**Responsável sugerido:** dados e operação. **Origem:** lacuna de evidência instalada.

Usar o escopo read-only aplicável para obter versões/checksums, constraints e referências de IDs em snapshot identificado. Confrontar com o procedimento de upgrade e a compatibilidade proposta em AUD03-10.

**Aceite:** inventário completo e redigido, origem/snapshot identificados e incompatibilidades documentadas; nenhuma migration, repair ou backfill é aplicada nesta tarefa. Aplicação posterior só ocorre com backup e plano específico, conforme [preflight 0008](operations/0008-scope-migration-preflight.md).

### AUD03-28 Provar golden path e publicação com serviços reais

**Responsável sugerido:** runtime, ingestão e qualidade. **Origem:** integração pendente e A04–A07/A09.

Executar API → objeto → fila → worker → vetores → retrieval → evidência → resposta, com PostgreSQL/Redis/Qdrant/S3/provider em ambiente identificado. Exercer workers A/B, reinício, perda de lease, retry, delete/reindex e isolamento A/B.

**Aceite:** uma publicação válida por operação; tentativa antiga não altera vencedor; estados, checksums e referências permanecem coerentes após falhas; audit obrigatório é persistido; negativos não vazam dados. Artefatos reais, limites e teardown vinculados ao candidato, sem usar mocks como substituto.

### AUD03-29 Executar campanha RAG representativa

**Responsável sugerido:** retrieval, avaliação e domínio. **Origem:** qualidade real não executada.

Usar corpus autorizado, provado como representativo e versionado, provider identificado e splits de treino/calibração/reserva. Aprovar limiares, riscos e adjudicação antes de medir; estratificar por dificuldade, ambiguidade e risco.

**Aceite:** amostra suficiente segundo desenho aprovado; métricas de ranking, vazamento ACL, suporte de citações, completude, unsupported claims e faithfulness com incerteza/proveniência; positivos e negativos revisados. Corpus insuficiente ou provider não executado mantém campanha bloqueada; os cinco fixtures sintéticos não substituem esta tarefa.

### AUD03-30 Provar revogação e isolamento com IdP e réplicas

**Responsável sugerido:** segurança e runtime. **Origem:** prova externa de identidade, tenancy e privacidade.

Exercer membership desativada, retirada de grants, troca de workspace, revogação de sessões e buckets de rate limit em mais de uma instância. Cruzar objeto, job, catálogo, vetor, evidência, histórico e browser.

**Aceite:** operações posteriores à revogação são negadas de forma consistente nas réplicas; scopes cruzados não retornam conteúdo/metadados; conteúdo privado pendente não reaparece na UI. IdP/adapters e política de timing/caches estão identificados; fluxo clínico respeita a decisão AUD03-07 se habilitado.

## Operação e promoção

### AUD03-31 Provar collector alertas e sinais distribuídos

**Responsável sugerido:** observabilidade e operação.

Observar tracing, métricas e alert routing através do runtime real. Comparar sinais de réplicas e exercitar collector indisponível e ausência de amostras.

**Aceite:** trace relaciona request/job/provider; labels e payloads permanecem redigidos/bounded; alertas chegam ao destino configurado; ausência de coleta produz no_data/alarme correspondente e não interfere na transação. Registrar ambiente e janela para cada SLO.

### AUD03-32 Medir restore e reconciliação por tenant

**Responsável sugerido:** dados e operação.

Executar backup e restore somente em ambiente descartável identificado, com o alcance de destruição/restauração confirmado. Reconstruir read models e comparar dados, grants, conversas, auditoria, objetos e vetores.

**Aceite:** checksums, contagens e relações reconciliados, isolamento preservado e RPO/RTO medidos contra budgets previamente definidos. Guardar backup verificável, alvo e teardown. Arquivo de dump íntegro sozinho não aprova restore.

### AUD03-33 Medir capacidade e latência representativas

**Responsável sugerido:** performance e operação.

Definir workload, concorrência, limites, topology e critérios antes de medir API/worker/web/provider. Separar latência local de serviço e custo de provider.

**Aceite:** p50/p95/p99, throughput, erros, CPU/memória, filas e custo por cenário; budgets cumprem os objetivos aprovados ou limitação fica explícita. Registrar tamanho da amostra, warm/cold, recursos e versão, sem substituir medidas por fixtures.

### AUD03-34 Ensaiar falhas e recuperação controladas

**Responsável sugerido:** runtime e operação.

Planejar quedas, timeout/429, particionamento, reconexão e reinícios dos componentes dentro dos limites acordados. Definir interrupção do ensaio e recuperação antes da injeção.

**Aceite:** retries/budgets continuam bounded; não há dupla publicação, corrupção ou retry storm; indisponibilidade aparece como erro/degradação correta; recuperação e alertas funcionam; o replay preserva idempotência e tenant scope.

### AUD03-35 Executar soak com limites de recursos

**Responsável sugerido:** confiabilidade e operação.

Após carga e falhas controladas, sustentar o workload pela janela aprovada e acompanhar memória, threads, conexões, filas, storage, redaction e retenção.

**Aceite:** ausência de crescimento indevido além dos budgets, taxas de erro/latência aceitáveis e dados íntegros após a janela. Execução tem duração, volume, condições de aborto e observações suficientes; processo curto sem carga não é soak.

### AUD03-36 Reauditar e decidir promoção do candidato

**Responsável sugerido:** integração, revisores e autoridade de release.

Reavaliar as 29 áreas, verificar os gates obrigatórios, executar CI sobre o candidato exato e selar pacote com imagens/digests, scans atuais, assinaturas, evidências de operação e revisão independente. Preparar canary/rollback conforme runbook.

**Aceite:** candidato e imagens coincidem com a evidência; pacote não pode ser autopromovido por declaração; findings altos estão resolvidos ou tratados pela autoridade aplicável sem mascarar gate falho; riscos residuais e recuperação têm responsáveis. Go/No-Go é explícito. Gate ausente/falho/stale mantém `NO-GO`, independentemente da nota média.

## Rastreabilidade dos achados

| Achado | Tarefa de correção |
|---|---|
| A01 Último grant volta a defaults | AUD03-02 |
| A02 Mutação de coleção ignora grants | AUD03-03 |
| A03 Membership OIDC inativa/incompleta | AUD03-04 |
| A04 Compensação de tentativa antiga | AUD03-08 |
| A05 Guard deixa publicação incoerente | AUD03-09 |
| A06 Colisão de ID entre scopes | AUD03-10 |
| A07 Ingestão reabre/apaga catálogo | AUD03-11 |
| A08 Provider inventa término | AUD03-14 |
| A09 Mutação antecede audit obrigatório | AUD03-06 |
| A10 Casos privados reaparecem na UI | AUD03-16 |
| A11 CI depende de arquivos ignorados | AUD03-21 |
| A12 Locks faltam dependências | AUD03-22 |
| A13 Teste stale exige tag de Action | AUD03-23 |
| A14 Snapshot moderno recebe defaults | AUD03-05 |
| A15 Wildcard é rejeitado na publicação | AUD03-15 |
| A16 Tombstone ressuscita em memória | AUD03-12 |
| A17 Escopo vazio chama embed/search | AUD03-13 |
| A18 Parser aceita pós-terminal/não cancela | AUD03-17 |
| A19 Foco escapa no diálogo busy | AUD03-18 |
| A20 SLI inválida é healthy | AUD03-19 |
| A21 Checkers aceitam fixtures incorretas | AUD03-24 |
| A22 Cobertura web omite comportamentos | AUD03-20 |
| A23 Destinos documentais quebrados | AUD03-25 |
| A24 Feedback por outro proprietário | AUD03-07 |

AUD03-01 preserva a baseline; AUD03-26 integra as regressões; AUD03-27–36 tratam as lacunas externas e a promoção. O roteiro não promete disponibilidade desses recursos nem execução por meio deste documento.
