# 0001 — Visão Geral e Objetivos

## Objetivo

Estabelecer a visão geral do programa como uma jornada até uma versão final **Enterprise Premium**, combinando:

- motor RAG forte
- interface técnica funcional no presente
- frontend robusto no futuro
- experiência premium de uso
- plataforma enterprise completa

---

## Leitura Executiva

O projeto não deve ser lido apenas como “backend com Swagger”.

Ele deve ser entendido em duas camadas:

### 1. Estado atual

Hoje já existe:

- motor RAG funcional
- operação técnica real
- API REST
- retrieval híbrido
- avaliação e métricas mínimas

### 2. Destino do produto

O destino final do programa é:

- produto web robusto
- chat web
- painéis operacionais
- painel administrativo
- camada enterprise com multitenancy, RBAC e governança

---

## Problema que a documentação resolve

A documentação existe para impedir dois erros:

1. tratar o sistema atual como produto final quando ele ainda é predominantemente técnico
2. tratar o produto final como algo puramente conceitual, sem trilha clara de evolução

---

## Linha Mestra do Programa

```text
FASE 0 ──────► FASE 1 ──────► FASE 2 ──────► FASE 3
Foundation     Operação        Produto         Plataforma
Validation     Profissional    Premium         Enterprise
   │               │               │               │
   ▼               ▼               ▼               ▼
Motor           Painel          Frontend        Multitenancy
técnico         técnico         robusto         + governança
validado        inicial         + chat web      + admin completo
```

---

## Princípios de Governança

1. **Document-first**: decisões importantes precisam estar refletidas na documentação
2. **Fases claras**: cada fase tem escopo, objetivo e tipo de interface dominante
3. **Dataset real**: a qualidade técnica depende de validação com dados reais
4. **Separação clara**: ingestion quality ≠ retrieval quality ≠ answer quality ≠ product quality
5. **Produto gradual**: a interface visual cresce por fases, sem prometer frontend final antes da hora
6. **Escalabilidade justificada**: a arquitetura cresce quando houver necessidade real
7. **Visão final explícita**: o produto final enterprise premium precisa estar descrito desde já

---

## Definições Importantes

| Termo | Significado |
|---|---|
| **Ingestion Quality** | Taxa de extração bem-sucedida por tipo de arquivo |
| **Retrieval Quality** | Hit rate top-k em perguntas reais sobre documentos reais |
| **Answer Quality** | Groundedness e citação da resposta sobre o contexto recuperado |
| **Product Quality** | Clareza da experiência, operação visual e usabilidade do sistema |
| **Gate** | Critério objetivo de saída de fase |
| **Dataset Real** | Perguntas feitas por usuários reais sobre documentos reais |

---

## Estrutura Normativa Principal

Os documentos mais importantes desta pasta são:

- `0003-estrategia-de-fases.md`
- `0005-fase-1-rag-profissional.md`
- `0006-fase-2-rag-premium.md`
- `0007-fase-3-rag-enterprise.md`
- `0008-arquitetura-alvo-e-arquitetura-atual.md`
- `0013-quality-gates.md`
- `0015-roadmap-executivo.md`
- `0016-backlog-priorizado.md`
- `0020-master-execution-log.md`
- `0025-visao-final-enterprise-premium.md`
- `0026-mapa-de-aderencia-ao-guia.md`

---

## Métricas de Sucesso da Documentação

- 0 ambiguidade entre interface técnica atual e interface final futura
- 0 conflito entre roadmap, fases e backlog
- visão final de produto coerente com frontend robusto e plataforma enterprise
- gates definidos para qualidade técnica e evolução de produto

---

## Próximo Passo

Ir para `0003-estrategia-de-fases.md`.
