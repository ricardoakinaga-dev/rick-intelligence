# Plano executivo de atualizações e melhorias — RICK Intelligence

**Data-base:** 24/09/2026. **Versão:** PE24-v1, com checkpoint local em 25/09/2026. Além de Q24-19/Q24-20, avançaram fatias locais de Q24-03, Q24-05, Q24-06, Q24-08, Q24-21 e Q24-25; Q24-26 agora separa métricas/intervalos por identidade de modelo/corpus ou tipo de caso negativo e rótulos declarados. A campanha real permanece `NOT_RUN`/`BLOCKED`; marcos integrados, operacionais e de promoção permanecem abertos.

Documentos complementares: [roadmap](roadmap-qualidade-2026-09-24.md) e [backlog executável](backlog-qualidade-2026-09-24.md). Base: [reauditoria de 24/09/2026](relatorio-auditoria-2026-09-24.md), [evidências preservadas](reports/evidence/auditoria-2026-09-24/manifest.json) e [planejamento anterior](plans/plano-executivo-qualidade-2026-09-17.md).

## 1. Objetivo e resultado esperado

Transformar a implementação atual em um produto utilizável e verificável: receber um documento na coleção correta, processá-lo com integridade, recuperar fontes autorizadas, gerar uma resposta quando a política permitir, apresentar citações e preservar o histórico. O mesmo conjunto deve suportar falhas, reinícios, atualização de banco e recuperação de dados com evidência de funcionamento.

A estratégia é corrigir os defeitos que impedem esse fluxo, demonstrá-lo cedo em ambiente isolado e completar as capacidades distribuídas antes da promoção. A arquitetura existente será aproveitada; a auditoria não justifica uma reescrita geral.

O programa possui **33 tarefas propostas**, distribuídas em **seis marcos, M0–M5**, com cobertura dos dez achados A24 e das 26 áreas avaliadas. A quantidade de tarefas não representa progresso concluído nem esforço uniforme.

## 2. Ponto de partida

| Aspecto | Evidência de referência | Implicação para o plano |
|---|---|---|
| Avaliação técnica | Nota 72/100, ante 70/100 em 17/09 | Melhorar comportamento e evidência; não perseguir uma média como substituto da prontidão. |
| Candidato inspecionado | HEAD `b52f32c141916a2ea3af1a6b913bd91f380606e0`, incluindo alterações locais não commitadas | Preservar e reconciliar o trabalho existente antes de qualquer integração. |
| Regressões | 1.693 execuções aprovadas, com sobreposição entre suítes | Aproveitar as correções verificadas e identificar cada suíte; não anunciar testes únicos ou cobertura integral. |
| Falhas reproduzidas | Upload inicial com coleção vazia e avaliação RAG reprovada | Manter as reproduções como critérios de encerramento das respectivas tarefas. |
| Bloqueio funcional | Decision fixa risco/intenção desconhecidos no caminho canônico | Implementar política de domínio; não liberar respostas classificando tudo como baixo risco. |
| Operação | Stack distribuída, restauração e provider real não comprovados na rodada | Criar evidência operacional própria, vinculada ao candidato e ao ambiente corretos. |

Fonte desses resultados: [relatório da auditoria, seções 1, 3 e 5](relatorio-auditoria-2026-09-24.md). São resultados daquela auditoria, não uma nova execução de testes neste planejamento. A resposta do Docker fora do sandbox não comprova disponibilidade de todos os serviços nem autorização de implantação.

## 3. Escopo e entregas

| Frente | Resultado de negócio/engenharia | Tarefas principais |
|---|---|---|
| Segurança e previsibilidade | Dependências compatíveis, upload íntegro, avaliação coerente, verificação local reproduzível | Q24-03 a Q24-09 |
| Uso completo inicial | Documento → fila → worker → índice → resposta autorizada → citações → histórico em serviços reais de teste | Q24-10 a Q24-16 |
| Completude funcional | Busca híbrida HTTP, auditoria reconciliável, isolamento e reindexação consistentes, interface utilizável | Q24-17 a Q24-26 |
| Entrega e operação | Evidências consumidas pela CI, recuperação comprovada, capacidade e estabilidade medidas | Q24-27 a Q24-30 |
| Encerramento | Manuais e artefatos do candidato, revisão independente, reauditoria e decisão de promoção | Q24-31 a Q24-33 |

M0, com Q24-01 e Q24-02, organiza a execução e os critérios. As correções já verificadas de batching, citações, contratos, metadados SSE, shutdown e entrega padrão de eventos serão preservadas e revalidadas, conforme a seção 4 da auditoria.

Ficam fora desta etapa documental: alterações no código do produto, migrações, chamadas a providers, criação de infraestrutura, commits, push e implantação. O plano não acrescenta novos módulos de produto, troca de framework ou remoção dos três sistemas legados. Novos defeitos encontrados na execução deverão receber evidência e prioridade próprias.

## 4. Sequenciamento executivo

**M0 — Organizar o candidato.** Conferir alterações existentes, relacionar Q24 aos itens Q17 e aos controles canônicos, explicitar responsáveis e fontes de aceite.

**M1 — Corrigir os fundamentos.** Atualizar dependências, corrigir coleção de upload e retry binário, resolver o contrato de avaliação RAG, preparar a estratégia de migração, limitar a telemetria e integrar os checks locais à CI.

**M2 — Demonstrar o primeiro fluxo real.** Construir o laboratório isolado, testar persistência e provider, conectar decisão/evidências e executar o fluxo completo inicial. A demonstração pode usar o retrieval dense atual, identificado como tal; não encerra a exigência de busca híbrida.

**M3 — Fechar integração e qualidade.** Conectar sparse/dense no HTTP canônico, concluir auditoria administrativa, isolamento, concorrência, ingestão, telemetria, experiência web, avaliação representativa e contratos de evidência de release.

**M4 — Provar recuperação e capacidade.** Restaurar o conjunto, medir cargas e executar falhas e estabilidade prolongada no ambiente autorizado.

**M5 — Preparar e julgar o candidato.** Consolidar documentação, inventário de dependências, artefatos e revisão. Reavaliar as 26 áreas e consumir evidências reais nos gates de promoção. Implantação é uma decisão operacional posterior, não um efeito automático de uma nota.

As dependências exatas pertencem ao [backlog](backlog-qualidade-2026-09-24.md). O [roadmap](roadmap-qualidade-2026-09-24.md) especifica demonstrações, paralelismo e critérios de saída. Preparações de um marco podem começar antes do encerramento integral do anterior quando as dependências da tarefa permitirem.

## 5. Critérios de sucesso

| Dimensão | Condição de encerramento | Evidência exigida |
|---|---|---|
| Uso básico | Upload padrão/alternativo e retry preservam destino, bytes e origem; consulta permitida chega a resposta fundamentada | Testes na API e no navegador, além do fluxo integrado Q24-16. |
| Decisão e fontes | Todas as ações previstas possuem caminhos exercitados; fonte inválida, revogada ou sem suporte não recebe aprovação indevida | Matriz de decisão, validação antes da publicação e avaliação com referências rotuladas. |
| Segurança | Achados críticos/altos aplicáveis encerrados, escopos isolados e dependências verificadas no ambiente final | Regressões negativas, inventário resolvido, varreduras e revisão do candidato. |
| Durabilidade | Instalação e upgrade suportados, pendências administrativas reconciliadas e replays sem efeitos duplicados | Ensaios com banco/worker reais, interrupção e reinício, reconciliação de objetos e índices. |
| Operação | Recuperação, limites de capacidade, alertas e estabilidade atendem contratos previamente definidos | Logs, métricas, RPO/RTO medidos, carga, caos e soak nos limites aprovados. |
| Entrega | Todos os critérios obrigatórios têm resultados atuais e verificáveis; nenhuma etapa obrigatória falha, ausente ou bloqueada | CI, hashes, candidato identificado, revisão independente e pacote final validado. |

Continuam vigentes os [14 critérios do programa](../.gauntlet/bar.json), o [adendo de qualidade da fase 3](reports/current-triple-aaa-quality-bar-v1.json) e seus contratos. Este plano não altera essas barras, seus limiares nem os gates históricos. O score gerencial de 26 áreas não é o score oficial de promoção. Nenhuma nota final ou selo AAA é prometido antecipadamente.

Para A24-04, a incompatibilidade matemática do pacote RAG deve ser resolvida por uma especificação versionada e justificada. A versão antiga e sua falha permanecem como histórico; reduzir exigências ou modificar respostas de referência apenas para obter PASS não encerra o achado.

## 6. Responsáveis e recursos

| Papel proposto | Responsabilidade | Recursos a confirmar na execução |
|---|---|---|
| Lead de engenharia | Contratos, ordem das tarefas, integração e reconciliação Q17/Q24 | Capacidade de implementação, revisão e um responsável por arquivos compartilhados. |
| Backend e segurança | API, dependências, sessões, auditoria e idempotência | Ambiente de dependências isolado, banco de teste e ferramentas de verificação. |
| Plataforma RAG | Ingestão, retrieval, Evidence, Decision e Professor | Provider/embeddings autorizados e corpus com direitos de uso definidos. |
| Frontend e design | Estados da interface, upload/retry, acessibilidade e integração com a API | Navegador de teste e ambiente web alinhado à API. |
| Dados e operações | Laboratório, migrações, filas, observabilidade e recuperação | Recursos descartáveis isolados, backup separado e acesso operacional delimitado. |
| QA e release | Regressões, evidências e critérios de promoção | CI com permissões limitadas e auditor/revisor distinto do implementador quando exigido. |
| Responsável de domínio e autoridade de release | Política de risco, corpus e decisões operacionais | Pessoas efetivamente designadas; nenhum aceite é presumido. |

Os papéis não representam uma equipe já contratada. Com uma pessoa, executar as frentes na ordem de dependência; com várias, usar escopos separados. Ferramentas de IA podem auxiliar implementação e revisão, mas uma autoavaliação não deve ser registrada como revisão independente.

Não há neste plano orçamento monetário, modelo de provider ou calendário comprometido. O esforço é relativo no backlog. Custos de infraestrutura, armazenamento, chamadas e revisão deverão ter limites identificados antes dos ensaios que os consumam. Ajustar concorrência da execução à capacidade disponível, preservando os workloads obrigatórios existentes até uma decisão explícita de escopo.

## 7. Decisões que condicionam a execução

As referências D01–D07 vêm do [plano anterior](plans/plano-executivo-qualidade-2026-09-17.md) e do [estado canônico](../.agent/state.json). Seu estado deve ser conferido ao iniciar cada tarefa; decisões já válidas não devem ser solicitadas novamente.

| Referência | Decisão necessária | Parte que depende dela |
|---|---|---|
| D01 | Dados de teste, tenants, isolamento e retenção | Uso de dados nos ensaios integrados; não impede escrever testes herméticos. |
| D02 | Ambiente, credenciais, bootstrap, TLS e confiança dos artefatos | Inicialização do laboratório, testes externos e preparação operacional. |
| D03 | Provider/modelo/endpoint, custo e interrupção | Chamadas reais e medições dependentes do modelo. |
| D04 | Política de domínio, corpus, direitos de uso, rótulos e limiares | Aceite da classificação de risco e da avaliação representativa. O desenho técnico pode avançar sem inventar aceite clínico. |
| D05 | SLO, RPO/RTO, cargas, amostras e janelas | Julgamento de desempenho, recuperação, alertas e estabilidade. |
| D06 | Reconciliação da execução com o catálogo Q17 | Consultar a autoridade histórica e o pedido vigente; não recriar uma autorização geral ou substituir o trabalho já existente. |
| D07 | Revisão final, assinatura e eventual implantação | Promoção/implantação; não bloqueia preparação de um candidato revisável. |

Essas decisões delimitam ações concretas. A ausência de uma decisão de provider, por exemplo, não é motivo para interromper correções locais de upload já autorizadas em uma etapa de implementação.

## 8. Governança sem duplicação de estado

Este documento define objetivos e direção; o roadmap define marcos; o backlog Q24 define escopo, dependências e aceite propostos. O [backlog canônico](../.agent/backlog.json), o [plano ativo](../.agent/plans/phase-3-runtime-evidence-production-promotion.md) e os ledgers continuam donos do estado real de execução.

Na ativação de uma tarefa, reutilizar o item Q17 correspondente sempre que representar o mesmo resultado. Criar apenas as subtarefas ausentes, preservando IDs e evidências anteriores. Uma correção com prova local deve receber apenas a validação pendente, não ser refeita por aparecer em um novo documento. Q24 não marca automaticamente nenhum Q17 como concluído.

Por entrega: reproduzir ou confirmar o achado, especificar o comportamento esperado, implementar a menor mudança coerente, executar teste discriminante e regressões, revisar, registrar evidências e só então atualizar o estado. Falhas estáticas refutadas devem ser reclassificadas com evidência, sem alterações artificiais no produto.

## 9. Riscos e recuperação

| Risco | Medida prevista |
|---|---|
| Perder alterações locais ou testar apenas HEAD antigo | Q24-01 inventaria arquivos, diffs e hashes; preservar trabalho de terceiros e preparar candidato que inclua as mudanças realmente avaliadas. |
| Mudança de dependências quebrar contratos | Q24-03 combina resolução compatível, regressões HTTP e inspeção da imagem; rollback de código/dependências revisado, sem degradar proteções. |
| Migração nova não ser alcançada por erro de checksum antigo | Q24-07 define caminhos por estado de instalação; Q24-11 comprova cada caminho antes de qualquer atualização operacional. |
| Liberar respostas sem política ou fontes suficientes | Q24-13 a Q24-15 exercitam decisões positivas e negativas, com revalidação de fontes e classificação conservadora de desconhecidos. |
| Mock ser confundido com integração | Q24-16 e as campanhas posteriores exigem serviços reais e identificam claramente as partes simuladas. |
| Testes pressionarem dados, recursos ou orçamento incorretos | Identificar projeto/endpoints/dados e limites antes de cada campanha; interromper no limite configurado. |
| Evidência antiga aprovar novo candidato | Q24-27 e Q24-32 verificam vínculo, frescor, integridade e impactos de mudanças posteriores. |

Após interrupção, consultar estado e evidência mais recentes, verificar efeitos já ocorridos e retomar o primeiro teste pendente. Reversões de código atingem apenas alterações próprias; mudanças persistentes exigem plano de restore ou roll-forward testado. Nunca limpar volumes, apagar logs de migração ou descartar arquivos para fabricar um candidato limpo.

## 10. Próxima ação de implementação

Q24-01/Q24-02 foram reconciliadas com o controle Q17 e a implementação local avançou pelos contratos de upload, autorização/chat, decisão/publicação, ingestão, retrieval híbrido, migrações e auditoria administrativa durável. C1–C12 rejeitaram snapshots exatos. C11 encontrou reset durável sem escopo workspace; C12 exige membership exata antes de alterar credenciais globais e passou API 743, mutações administrativas 15, PostgreSQL 108 e lint/typecheck. A revisão independente rejeitou o snapshot C12: um PATCH administrativo esparso pode restaurar senha antiga após a recuperação; C13 já serializa as gravações integrais e a regressão PostgreSQL real passa; API 743, PostgreSQL 109 e mutações administrativas 15 passam. A revisão independente aceitou C13 no escopo local, com 11 critérios aprovados e a corrida PostgreSQL corrigida. A reconciliação do consumidor outbox e do worker integrado permanece aberta. Os gates de domínio, operações, integração e promoção continuam abertos; não há DONE de Q17 nem autorização de produção neste checkpoint.

**Limite deste plano:** ele define direção, ordem e critérios propostos. O estado efetivo pertence ao [backlog canônico](../.agent/backlog.json), ao [plano ativo](../.agent/plans/phase-3-runtime-evidence-production-promotion.md) e aos ledgers; nenhuma tarefa recebe PASS ou DONE só pela criação ou atualização destes documentos.

**Continuidade local em 25/09:** Q24-03 atualizou Starlette/Uvicorn e manteve FastAPI no release vigente; o lock contém 45 pacotes hash-pinned, passou audit PyPI/OSV, `pip check` e 749 testes API em ambiente Python 3.12. Os cinco workflows de instalação direta estão alinhados, incluindo o pin explícito de `python-multipart` no phase-1.5. A imagem e seu inventário continuam pendentes de D02; há um aviso conhecido de depreciação no TestClient/HTTPX. Q24-05 reenvia os mesmos bytes DOCX sintéticos no retry e valida checksum e escopo; o adaptador de parser não prova extração real e retenção/reload depende de D01. Em Q24-26, métricas e intervalos separam pares modelo/corpus positivos e tipos de expectativa negativos dentro dos rótulos `risk`/`ambiguity`; IDs escapam os componentes e o teste de colisão passou. O harness e pack passaram 18 e 15 testes. A primeira crítica permaneceu `INVALID` por mutação de bytecode; uma segunda revisão independente válida foi `CONDITIONAL PASS` e seus dois achados foram corrigidos. A revisão final do snapshot atualizado aguarda conclusão. Campanha, retenção, integração, gates operacionais e decisões externas permanecem abertas; veja o [manifesto deste checkpoint](reports/evidence/implementation-q24-2026-09-24/verification-q24-03-runtime-deps-q24-26-strata-identity-20260925T1938Z/manifest.json).
