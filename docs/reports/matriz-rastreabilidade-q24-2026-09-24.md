# Rastreabilidade Q24 → controle canônico

Checkpoint de recuperação: 2026-09-25T06:53:03Z.

Esta matriz registra escopo e responsáveis de integração. O estado de execução continua exclusivamente no [backlog canônico](../../.agent/backlog.json); nenhum status histórico é transferido por equivalência de IDs.

Os 33 critérios completos de entrega, aceite, prova e recuperação permanecem no [catálogo Q24](../backlog-qualidade-2026-09-24.md). As dez famílias A24 e as 26 áreas estão vinculadas nas tabelas da seção 9 desse catálogo. As barras [Gauntlet](../../.gauntlet/bar.json) e [fase 3](current-triple-aaa-quality-bar-v1.json) permanecem inalteradas.

| Tarefa | Resultado | Referências Q17 de origem | Responsável canônico pela integração/evidência |
|---|---|---|---|
| Q24-01 | Preservar o candidato e reconciliar Q17/Q24 | Q17-01.A, Q17-02.A | Q17-01.A |
| Q24-02 | Fixar aceitação, cobertura e responsabilidades | Q17-01.B, Q17-02.A, Q17-26.A | REC-M0, Q17-26.A |
| Q24-03 | Atualizar dependências da API de forma compatível | Q17-05.B, Q17-25.C | SA-SECURITY-TENANT-LOCAL, Q17-26.A |
| Q24-04 | Unificar a coleção exibida e enviada no upload | Q17-16.A | Q17-16.A |
| Q24-05 | Preservar fontes binárias no retry | Q17-06.A, Q17-16.A | Q17-16.A, Q17-06.B |
| Q24-06 | Corrigir o contrato impossível do pacote de avaliação RAG | Q17-14.A | Q17-14.A |
| Q24-07 | Definir atualização de banco sem reescrever histórico | Q17-19.A | Q17-19.A |
| Q24-08 | Tornar explícitos e limitados os modos de telemetria | Q17-23.A | Q17-23.A |
| Q24-09 | Integrar regressões e tipagem reais ao fluxo local/CI | Q17-06.B, Q17-26.A | Q17-26.A |
| Q24-10 | Construir laboratório isolado e observar readiness | Q17-18.A, Q17-20.A, Q17-21.A | Q17-18.A, PH3-2-LAB-READINESS |
| Q24-11 | Provar instalação, upgrade e bootstrap persistente | Q17-07.B, Q17-19.A, Q17-22.B | Q17-19.A, PH3-2-LAB-READINESS |
| Q24-12 | Validar provider real e orçamento de chamadas | Q17-13.A | Q17-13.A |
| Q24-13 | Especificar e implementar classificação de risco/intenção | Q17-11.A | Q17-11.A |
| Q24-14 | Conectar as ações de decisão ao caminho da API | Q17-11.B, Q17-12.B | Q17-11.A, Q17-12.A |
| Q24-15 | Completar fontes, publicação final e equivalência do chat | Q17-06.B, Q17-10.A, Q17-12.A, Q17-15.A | Q17-12.A, Q17-15.A |
| Q24-16 | Demonstrar o fluxo inicial completo | Q17-08.C, Q17-18.B | Q17-18.A, SA-INGESTION-APP-LIFECYCLE, Q17-16.A |
| Q24-17 | Disponibilizar schema e indexação sparse no caminho HTTP | Q17-08.B, Q17-09.A | Q17-09.A, Q17-08.A |
| Q24-18 | Conectar busca híbrida HTTP e fallback explícito | Q17-09.A | Q17-09.A |
| Q24-19 | Garantir consistência entre mutação e auditoria | Q17-17.A | Q17-17.A |
| Q24-20 | Consumir e reconciliar pendências administrativas | Q17-17.A | Q17-17.A |
| Q24-21 | Validar sessões, permissões e isolamento completo | Q17-03.A, Q17-04.A, Q17-05.A | SA-SECURITY-TENANT-LOCAL |
| Q24-22 | Provar concorrência, fencing e retomada de workers/Redis | Q17-19.B, Q17-20.A, Q17-21.A | Q17-20.A |
| Q24-23 | Completar integridade, reindexação e contratos dos stores | Q17-07.A, Q17-08.A, Q17-22.A | Q17-22.A, Q17-08.A |
| Q24-24 | Observar o fluxo e testar alertas operacionais | Q17-23.B | Q17-23.A, SA-OBSERVABILITY |
| Q24-25 | Completar UX de documentos, chat e administração | Q17-15.B, Q17-16.B, Q17-17.B, Q17-26.C | Q17-16.A, SA-VISUAL, Q17-15.A, Q17-17.A |
| Q24-26 | Avaliar RAG em corpus representativo e autorizado | Q17-14.B | Q17-14.A |
| Q24-27 | Conectar evidências reais aos verificadores de release | Q17-25.A, Q17-26.B | Q17-26.A |
| Q24-28 | Restaurar o conjunto e medir RPO/RTO | Q17-24.A | SA-EXTERNAL |
| Q24-29 | Medir capacidade, latência e custo | Q17-24.B | SA-EXTERNAL |
| Q24-30 | Executar caos e estabilidade prolongada | Q17-24.C | SA-EXTERNAL |
| Q24-31 | Preparar documentação, inventário e artefatos do candidato | Q17-01.C, Q17-02.B, Q17-25.C | REC-M0, Q17-26.A |
| Q24-32 | Revisar de forma independente e reauditar as 26 áreas | Q17-25.D, Q17-26.D | REC-M0, Q17-26.A |
| Q24-33 | Validar o pacote final e obter decisão de promoção | Q17-25.D | SA-EXTERNAL, Q17-26.A |

## Contratos de execução nesta onda

O Lead integra dependências, HTTP multipart, interface, regressões e os cinco controles canônicos. Kepler recebe o caminho de migração e seus testes; Wegener recebe Decision/Professor e os testes correspondentes; Hooke recebe retrieval HTTP, ingestão externa e testes conectados. Nenhum builder pode escrever `.agent/`, `.gauntlet/` ou aceitar a própria entrega. Os escopos exatos foram transmitidos aos agentes e os resultados serão inspecionados antes de integração.

Q24-03/Q24-09/Q24-27/Q24-31–33 ampliam o alcance de entrega além do fechamento histórico PH3-1-CI-RELEASE-CLOSURE. O trabalho novo é acompanhado em Q17-26.A e REC-M0; o DONE histórico de PH3-1 não aprova o novo candidato. Q24-19 e Q24-20 são incrementos distintos do mesmo dono Q17-17.A: atomicidade primeiro, consumidor depois. C1–C12 rejeitaram somente snapshots exatos. C10 encontrou lookup de sessão sem workspace; C11 encontrou reset durável tenant-only e uma violação do inventário de leitura. C12 exige escopo exato antes de reset global e passou API 743, PostgreSQL 108 e mutações administrativas 15. A revisão independente C12 rejeitou somente esse snapshot por corrida entre PATCH esparso e recuperação; C13 corrigiu o lock e a regressão PostgreSQL real passou; C13 foi aceito nos 11 critérios locais; a reconciliação integrada do consumidor outbox Q24-19/20 permanece aberta. A aceitação integrada permanece aberta.

Dados sintéticos locais e recursos descartáveis identificados são usados apenas no escopo reversível de implementação. Aprovação clínica, corpus representativo, limites operacionais finais, assinatura e implantação continuam dependentes das decisões aplicáveis D01–D05/D07. Disponibilidade do Docker não comprova prontidão completa.

## Continuidade

Reexecutar o check correspondente depois de qualquer mudança que afete seu escopo. Conservar resultados negativos e não somar suítes sobrepostas como testes únicos. Rever a independência e a origem de cada evidência antes de encerrar uma tarefa.
