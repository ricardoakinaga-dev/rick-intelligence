# Reanálise do programa e prioridades de construção — 08/09/2026

**Revisão:** `66781cbe96c10786bbf9b9150ee4798df62fdba6`.

**Método:** inspeção atual de código, configuração, contratos e testes; comparação com os dois relatórios existentes.

**Resultado:** base técnica local funcional; produto incompleto; **NO-GO para produção**.

## 1. Correções à análise anterior

O relatório comparativo anterior atribuiu 83/100 à implementação local e 52/100 à produção sem explicitar cálculo ou peso. Essas notas são avaliações históricas, não percentuais de conclusão. A reanálise usa critérios explícitos abaixo e considera também os fluxos de produto descritos no [relatório de funcionamento](relatorio-auditoria-funcionamento-2026-09-08.md).

O timeout anterior não comprova defeito do worker ou da API. Nesta rodada, `timeout 60s make api16-root` encerrou com código 124 no sandbox. Um teste mínimo de health, com faulthandler após 10 segundos, mostrou espera em `TestClient.__enter__ → AnyIO BlockingPortal`, antes da execução da rota. Fora do sandbox, a mesma suíte API passou: **358 passed, 221 warnings, 15,31 s**, código 0. Há evidência de sensibilidade ao ambiente de execução; a causa interna exata permanece por investigar. Não é justificável alterar código de negócio para contornar isso sem reprodução discriminante.

Também não basta configurar `RICK_API_CHAT_BACKEND=professor`: o factory seleciona provider determinístico por padrão em test/dev/local quando `RICK_PROVIDER` está vazio. Além disso, o factory local monta retrieval com embeddings hash. Provar uma chamada real de chat não prova embeddings reais nem qualidade RAG.

## 2. Evidência desta rodada

| Verificação | Resultado e alcance |
|---|---|
| `make api16-domain storage-test` | 104 testes de knowledge/ingestion/retrieval + 9 de storage passaram; código 0 |
| `timeout -k 5s 90s make api16-root`, fora do sandbox | 358 testes passaram; código 0; 221 avisos de depreciação |
| API no sandbox | timeout 124; trace localiza espera no harness TestClient/AnyIO |
| Fonte web/admin/chat/configuração | inspecionada diretamente nesta rodada |
| 234 testes browser e inspeção de renders | relatados na auditoria de funcionamento; não reexecutados nem reinspecionados nesta rodada |
| Modelo, Qdrant, Redis, Postgres, IdP, broker e object storage externos | não exercitados nesta rodada |
| Segurança completa, aceite clínico e produção | não certificados por estes checks |

Não foram realizadas chamadas pagas, implantação ou mudanças de implementação. Os testes aprovados somam **471 execuções** nas três superfícies indicadas, sem somar contagens históricas.

## 3. Notas com critério explícito

Cada item recebe quatro parcelas de 0–25: **C** = código/contrato presente; **U** = fluxo utilizável pelo destinatário; **V** = evidência de verificação; **O** = integração operacional/durabilidade. Escala por parcela: 0 ausente; 5 referência ou fragmento; 10 parcial; 15 substancial com lacunas; 20 forte no escopo local; 25 completo no escopo aplicável. São julgamentos de engenharia, não medições de segurança ou qualidade clínica.

| Item | C | U | V | O | Total /100 | Justificativa |
|---|---:|---:|---:|---:|---:|---|
| Arquitetura e contratos | 25 | 20 | 20 | 15 | **80** | Separação root/packages e contratos locais; composição externa pendente. |
| Configuração do modelo | 10 | 5 | 10 | 5 | **30** | Exemplo de ambiente diverge do root; professor local pode ser determinístico. |
| Super Admin | 10 | 5 | 15 | 5 | **35** | Listar/criar usuários na API; UI, edição e gestão completa ausentes. |
| Identidade e recuperação | 15 | 10 | 20 | 5 | **50** | Sessão local implementada; reset incompleto e IdP externo não verificado. |
| Autorização e navegação | 20 | 10 | 20 | 5 | **55** | ACL server-side; navegação ainda mostra catálogo ao papel clínico. |
| Console RAG | 15 | 10 | 15 | 5 | **45** | Ciclo de documentos parcial; gestão de coleções/configuração/avaliação incompleta. |
| Ingestão e documentos | 20 | 20 | 20 | 5 | **65** | Pipeline e lifecycle locais; durabilidade externa pendente. |
| Retrieval e qualidade | 20 | 15 | 20 | 5 | **60** | Mecanismos de busca implementados; qualidade semântica não demonstrada. |
| Professor e geração real | 20 | 10 | 15 | 0 | **45** | Provider/orquestração existem; caminho real completo não exercitado. |
| Conversas e histórico | 10 | 5 | 15 | 0 | **30** | Histórico bounded em memória; UI e memória multi-turn ausentes. |
| Streaming | 10 | 5 | 15 | 0 | **30** | SSE envia resposta já concluída; web força stream=false. |
| Persistência e worker | 15 | 10 | 20 | 5 | **50** | Primitivas SQLite/local; composição distribuída ausente. |
| Auditoria e observabilidade | 20 | 10 | 15 | 5 | **50** | Audit/telemetria locais; exportação, retenção e alertas externos pendentes. |
| Web e experiência | 20 | 10 | 15 | 5 | **50** | Superfícies implementadas; workflows por persona incompletos. |
| Testes e evidência | 25 | 15 | 20 | 5 | **65** | Regressão API atual verde; E2E contém interceptações e faltam integrações live. |
| Operação e release | 10 | 5 | 10 | 0 | **25** | Referências e gates existem; restore, carga e rollout não demonstrados. |

Média simples dos 16 itens: **47,8/100** (arredondada de 47,8125). Ela mede aderência ao produto completo com a rubrica acima; não é diretamente comparável a 83/100 de construção local. Nenhuma média permite ignorar requisitos obrigatórios ausentes.

## 4. Achados atuais e rastreabilidade

| ID | Evidência de código | Consequência | Backlog |
|---|---|---|---|
| A01 | [config.py](../../apps/api/src/core/config.py), [.env.example](../../.env.example), [factory](../../apps/api/src/app.py) | `LLM_*` do exemplo não corresponde a `EXTERNAL_CHAT_API_KEY`, `OPENAI_*`, `RICK_API_CHAT_BACKEND` e `RICK_PROVIDER` do root; preenchimento do exemplo não assegura provider real | REC-03, REC-21 |
| A02 | [admin.py](../../apps/api/src/routes/admin.py), [cliente web](../../apps/web/lib/api.ts), [admin web](../../apps/web/app/admin/page.tsx) | API parcial de usuários sem UI; sessões administrativas sempre retornam lista vazia; lista de roles é fixa | REC-10–13 |
| A03 | [auth.py](../../apps/api/src/routes/auth.py) | Solicitação responde queued; confirmação de reset sempre falha. Resposta neutra pode proteger contra enumeração, mas não constitui recuperação implementada | REC-13 |
| A04 | [shell](../../apps/web/components/app-shell.tsx) | Papel clínico recebe navegação Documentos apesar da restrição de catálogo; guarda visual não substitui ACL | REC-04 |
| A05 | [knowledge.py](../../apps/api/src/routes/knowledge.py), [documentos](../../apps/web/app/app/documents/page.tsx) | Ciclo local de documentos existe; coleções têm listagem, sem console completo de gestão, avaliação e configuração | REC-14–16 |
| A06 | [chat_service.py](../../apps/api/src/services/chat_service.py) | `stream_events` aguarda `chat()` terminar antes de fatiar a resposta em blocos de 120 caracteres. SSE existe; geração incremental pelo provider não está entregue | REC-25 |
| A07 | [chat_history.py](../../apps/api/src/services/chat_history.py), [orquestração](../../packages/professor/src/rick_professor/orchestration.py), [chat web](../../apps/web/app/app/chat/page.tsx) | Histórico é read model em memória; backend recebe mensagem atual e ID, sem recuperação de turnos anteriores no serviço. Histórico de consulta não é memória conversacional | REC-23–26 |
| A08 | [factory](../../apps/api/src/app.py), [migration](../../infrastructure/migrations/0001_control_plane.sql) | Produção exige componentes injetados; migration atual cobre bookkeeping/jobs, não schema completo de produto | REC-06–09, REC-17–20 |
| A09 | [Playwright](../../apps/web/playwright.config.ts), [testes web](../../apps/web/tests) | API pode ser reaproveitada; vários cenários interceptam HTTP. Quantidade de testes não prova integração integral | REC-01, REC-28 |
| A10 | [operação](../operations/release-readiness.md) | Backup, restore, rollout e alertas são referências sem execução live demonstrada | REC-29–34 |
| A11 | planos COR anteriores | `COR-068` dependia de “todos P0”, incluindo a decisão posterior; faltavam dono/local de alteração e administração funcional detalhada | novo DAG REC no backlog |

## 5. Interpretação de produto

Manter `apps/web + apps/api` como linha canônica é coerente com a arquitetura existente. Dois frontends preservados durante migração não são, isoladamente, um defeito. A lacuna é não transferir capacidades necessárias ao produto root. Legado deve servir como referência de comportamento/adapter até equivalência explícita; sua remoção não é requisito desta correção.

As primeiras entregas visíveis devem permitir: administrador gerir usuários e sessões; gestor RAG gerir coleções e publicação; usuário retomar uma conversa com fontes autorizadas e geração real. O suporte clínico completo e a equivalência de recursos com OpenWebUI precisam de escopo aprovado; não foram presumidos como funcionalidades já entregues.

O plano anterior concentrava esforço em infraestrutura, deixando usuários, sessões e gestão RAG subespecificados. A revisão combina entregas por persona com persistência desde as primeiras fatias. Preparar ambientes e tomar decisões pode ocorrer em paralelo à validação local.

## 6. Plano resultante e limites

- [Plano executivo revisado](../plans/plano-executivo-correcoes-2026-09-08.md)
- [Roadmap revisado](../plans/roadmap-correcoes-2026-09-08.md)
- [Backlog revisado](../plans/backlog-correcoes-2026-09-08.md)

Este documento é a nova síntese da rodada e preserva os relatórios anteriores como evidência histórica. Não há aprovação visual independente nova nem avaliação semântica live. As notas refletem inspeção e evidência disponível, com esses limites.

## 7. Verificação do planejamento

Os quatro documentos desta revisão foram verificados quanto a links locais, IDs e dependências. Resultado: 35 tarefas únicas, dependências existentes, nenhum ciclo, 16 somas de pontuação corretas e nenhum link local ausente. Houve uma revisão de consistência pelo próprio autor; ela não constitui parecer independente do produto.
