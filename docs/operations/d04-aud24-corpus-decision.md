# D04 AUD24 — decisão de corpus para o pack RAG representativo

**Data:** 24/10/2026. **Estado:** `PROPOSTO / AGUARDANDO REVISÃO DE DOMÍNIO`. **Não é aprovação clínica, de release ou de produção.**
**Decisão humana registrada:** o usuário autorizou o caminho **corpus sintético público + revisão de domínio** para AUD24-044.

## 1. O que será avaliado

O pack mede o comportamento do pipeline de retrieval/citação/abstenção, não a qualidade clínica de um modelo. Cada caso deve conter: pergunta, escopo autorizado, resultados recuperados, citações, claims, suporte e latência observada.

## 2. Proposta de corpus

| Campo | Proposta |
|---|---|
| Origem | cenários **sintéticos** redigidos para o produto, sem dados de pacientes, sem PII, sem reprodução de diretriz proprietária |
| Tamanho mínimo | 12 casos: 4 positivos de ranking, 3 negativos/abstenção, 2 ACL cross-tenant, 2 citação/claim não suportado, 1 limite/latência |
| Idioma | português, com termos técnicos veterinários revisados |
| Licença | conteúdo do repositório, sem licença de terceiros; qualquer fonte externa futura exige licença e atribuição |
| Retenção | versionado no Git; nenhum dado pessoal |
| Labels | relevância, citação esperada, suporte do claim e decisão de abstenção definidos pelo revisor de domínio |
| Thresholds propostos | hit@3 ≥ 0,90; ACL leakage = 0; citation precision ≥ 0,95; citation recall ≥ 0,90; unsupported claim ≤ 0,05; latência apenas descritiva, não SLO |

## 3. O que o revisor de domínio precisa aprovar

1. Casos e termos clínicos são plausíveis e não induzem conduta insegura.
2. Labels de relevância/citação/abstenção estão corretos.
3. Thresholds são adequados ao risco e ao objetivo do pack.
4. Limitações e linguagem de “não é aconselhamento clínico” estão explícitas.

**Nome do revisor:** ____________________  **Data:** __________  **Assinatura/registro:** ____________________

## 4. O que a engenharia fará após a assinatura

- criar `docs/evaluation/packs/aud24-synthetic-v1/` com os 12 casos e manifest;
- rodar `make eval-retrieval-pack` e registrar métricas/limitações;
- manter o pack como evidência local, sem alegar corpus representativo de produção;
- vincular a aprovação ao ID AUD24-044.

## 5. Estado atual

Um candidato de 12 casos foi criado em `docs/evaluation/packs/aud24-synthetic-v1/`, mas o **agente revisor o REJEITOU** como representativo: corpus sem texto, checksums/fontes inválidos, casos clonados, abstenção/ACL não exercitadas e thresholds divergentes do D04.

O pack pode ser usado apenas como **smoke de schema/harness**. AUD24-044 permanece `BLOCKED_EXTERNAL`; a aprovação exigida é humana/de domínio ou uma emenda formal que delegue escopo ao agente. Evidência: [revisão do agente](../reports/evidence/auditoria-2026-10-24/rag-pack-review-agent-20261024.md).
