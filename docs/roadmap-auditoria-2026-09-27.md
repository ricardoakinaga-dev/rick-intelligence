# Roadmap de melhorias — RICK Intelligence (auditoria 27/09/2026)

**Data-base:** 27/09/2026. **Versão:** RM27-v1. **Origem:** [relatório de auditoria geral](reports/relatorio-auditoria-geral-2026-09-27.md) (nota 79/100).

**Documento complementar:** [backlog executável](backlog-auditoria-2026-09-27.md).

## 1. Contexto e objetivo

A auditoria de 27/09 confirmou que **7 dos 10 achados A24 foram resolvidos** no código, com regressões dirigidas. O que separa a nota atual (79) da prontidão para produção (meta AAA ≥96) deixou de ser qualidade de código local e passou a ser: (a) **evidência operacional distribuída real**, (b) **autoridade externa conectada**, e (c) **política de domínio clínico** (D04).

O objetivo deste roadmap é transformar o `STATE_OF_ART_CANDIDATE` em um candidato revisável com runtime comprovado, sem fabricar evidência, sem substituir decisões humanas por automação e sem reduzir exigências para obter aprovação.

## 2. Princípios (inalterados)

1. Um gate `NOT_RUN`, `BLOCKED_EXTERNAL` ou falho mantém o candidato abaixo de promoção.
2. Prova unitária/hermética não substitui prova integrada distribuída.
3. Nenhuma nota substitui um gate obrigatório ou uma autoridade humana.
4. Evidência antiga não aprova novo candidato; cada entrega vincula candidato, commit/tree, ambiente e hash.
5. As decisões D01–D07 condicionam apenas o efeito dependente; preparação local pode avançar.

## 3. Sequência de entregas (marcos)

| Marco | Objetivo | Saída esperada |
|---|---|---|
| **M1 — Hardening e higiene** | Fechar débitos de segurança/qualidade de fácil escopo e eliminar inconsistências | Candidato mais limpo, sem achados P1 triviais abertos |
| **M2 — Fechar A24-09 (autoridade)** | Conectar ou explicitar os executores dos gates finais de promoção | Trilha de promoção rastreável até autoridade real |
| **M3 — Prova operacional (A24-10)** | Executar o fluxo ponta-a-ponta em ambiente descartável aprovado | upload → fila → worker → índice → resposta → citações → histórico, com falhas/restart |
| **M4 — Medição de operação** | RPO/RTO, capacidade, caos e soak medidos | Números reais, não alvos declarados |
| **M5 — Domínio e promoção** | Política de domínio clínico (D04) + revisão independente + reauditoria | Decisão documentada de promoção |

## 4. Detalhamento por marco

### M1 — Hardening e higiene
Corrige os achados *não-operacionais* da auditoria, todos de escopo local:

- **CSRF com nonce por sessão** (substituir token estático/vazio em produção).
- **Credencial scoped no bootstrap do MinIO** (separar do root).
- **Eliminar duplicação de código** (`ConfirmDialog`, `errorMessage`).
- **Pin de ações GitHub** nas workflows `phase-*.yml` (alinhar ao `quality.yml`).
- **Reconciliar `toolchain.json`** com versões reais do compose (Qdrant/Redis).
- **Explicitar `retrieval_mode`** na composição (não depender de default).

**Demonstração:** os débitos listados na seção 4 da auditoria ficam fechados com evidência; nenhum gate externo é tocado.

### M2 — Fechar A24-09 (autoridade)
As três lanes `lab-readiness`, `independent-reviews`, `production-runtime` estão com `command=None` (`triple_aaa_verify.py:513,541,544`). Duas saídas legítimas:

1. **Conectar** produtores/consumidores reais (comando que lê observação real, identidade de revisor vinculada, runtime aprovado).
2. **Explicitar** que são decisões humanas externas e documentar o processo e a evidência aceita.

**Critério:** nenhuma lane declarada sem comando permanece ambígua; cada uma tem dono, fonte de aceite e evidência vinculada ao candidato. Não transformar bloqueio em aprovação sintética.

### M3 — Prova operacional (A24-10 + resíduo A24-06)
Em ambiente descartável aprovado (D01, D02, D03):

- Executar o **fluxo golden completo**: upload → objeto → job durável → worker → parse → chunk → embed → Qdrant → publish → retrieval → evidence → Professor → decision → resposta citada → histórico.
- Exercitar **reconciliação do outbox administrativo** sob falha de sink e restart (fecha A24-06 ponta-a-ponta).
- Registrar cada transição, lineage, idempotência e recuperação.

### M4 — Medição de operação (A24-10)
Com D05 definido, medir de fato:

- **Restore:** RPO/RTO reais (seed → backup → destroy → restore → verify).
- **Capacidade:** p50/p95/p99, throughput, latência de primeiro token, fila, memória (1/10/50/100 concorrência).
- **Caos/soak:** faults injetados com invariantes verificados + janela de estabilidade.

**Critério:** números medidos substituem alvos declarados; falha de recuperação reabre as tarefas causais.

### M5 — Domínio e promoção
- **D04:** substituir o `NonClinicalRequestPolicy` (allowlist técnico) por uma política de domínio revisada, sem liberar respostas indevidamente.
- **Revisão independente** do candidato completo (revisor distinto do implementador).
- **Reauditoria** das 26 áreas e recálculo da nota.
- **Decisão de promoção** documentada e rastreável.

## 5. Caminho crítico e paralelismo

| Frente | Pode avançar em paralelo | Exige serialização |
|---|---|---|
| Hardening (M1) | Todos os itens são independentes entre si | — |
| Autoridade (M2) | Especificar processo enquanto M1 roda | Consumo final depende de autoridade real |
| Operação (M3) | Preparar harness | Execução depende de D01/D02/D03 |
| Medição (M4) | Preparar workloads | Depende de M3 + D05 |
| Domínio (M5) | Especificar política em paralelo | Revisão/promoção depois de M3/M4 |

**Caminho crítico:** M1 → M3 (fluxo real) → M4 (medição) → M5 (revisão/promoção). M2 pode ser especificado em paralelo desde o início.

## 6. Critérios de sucesso

| Dimensão | Condição |
|---|---|
| Segurança | Zero achado crítico/alto aplicável aberto; dependências e CSRF verificados no ambiente final |
| Uso básico | fluxo ponta-a-ponta real com citações e histórico verificáveis |
| Operação | RPO/RTO, capacidade, caos e soak medidos com limites acordados |
| Entrega | gates obrigatórios com evidência atual; revisão independente; decisão rastreável |

## 7. Riscos e recuperação

- **Evidência antiga aprovar candidato novo** → vincular cada entrega a commit/tree/hash.
- **Mock confundido com integração** → exigir serviços reais e identificar partes simuladas.
- **Liberar resposta sem política** → manter fallback conservador até D04 decidido.
- **Interrupção** → observar efeito já ocorrido antes de repetir upload/migração/mutação/publicação.

**Limite deste documento:** define direção e ordem. O estado real permanece no controle canônico (`.agent/`, `.gauntlet/`); a atualização deste roadmap não encerra tarefa nem autoriza promoção.
