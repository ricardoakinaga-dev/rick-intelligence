# 0018 — Plano de Validação com Dataset Real

## Objetivo

Estabelecer processo rigoroso para criar, manter e usar dataset real de validação. Dataset real é a base de todas as decisões de progresso entre fases.

---

## Princípio Fundamental

```
╔════════════════════════════════════════════════════════════╗
║  SEM DATASET REAL, NENHUMA DECISÃO DE GATE É VÁLIDA.      ║
║                                                             ║
║  Perguntas sintéticas são ajuda. Não são verdade.         ║
╚════════════════════════════════════════════════════════════╝
```

---

## 1. O Que É Dataset Real

### Definição

Dataset real consiste de:

| Campo | Descrição | Exemplo |
|---|---|---|
| `pergunta` | Texto da pergunta feita por usuário real | "Qual o prazo para reembolso?" |
| `document_id` | ID do documento que contém a resposta | "doc-001" |
| `trecho_esperado` | Trecho exato do documento que responde | "O prazo para reembolso é de 30 dias..." |
| `resposta_esperada` | Resumo do que deveria ser dito | "30 dias corridos" |
| `dificuldade` | Easy / Medium / Hard | "easy" |
| `categoria` | Tipo de pergunta | "procedimento" |
| `contexto` | Quem perguntou, quando, por quê | "Cliente via chat, perguntou sobre política" |

### O Que NÃO É Dataset Real

- ❌ Perguntas geradas por LLM sozinho
- ❌ Perguntas inventadas sem documento fonte
- ❌ "Creo que o usuário perguntaria..."
- ❌ Perguntas de benchmarks públicos que não existem nos documentos do cliente

---

## 2. Como Criar Dataset Real

### Passo 1: Coletar Perguntas Reais

```
Fontes de perguntas reais (prioridade):
1. Histórico de conversas de suporte/atendimento (se disponível)
2. Entrevista com time de negócio: "Que perguntas seus clientes fazem?"
3. Documentos de FAQ existentes
4. Entrevista com clientes: "Que informações você busca?"
```

### Passo 2: Mapear para Documentos

```
Para cada pergunta coletada:
1. Identificar qual documento contém a resposta
2. Localizar trecho exato que responde
3. Criar entrada no dataset com todos os campos
```

### Passo 3: Validar with Domain Expert

```
Cada pergunta do dataset precisa ser validada por alguém que conhece o domínio:
- "Essa pergunta faz sentido no contexto?"
- "A resposta esperada está correta?"
- "Esse é um caso real, não artificial?"
```

### Passo 4: Classificar Dificuldade

```python
def classify_difficulty(question, expected_chunk):
    # Easy: resposta explícita, único trecho, sem ambiguidade
    # Medium: resposta está presente, mas requer contexto
    # Hard: resposta parcialmente presente, ou múltiplas interpretações
```

---

## 3. Tamanho Mínimo do Dataset

| Fase | Mínimo | Recomendado | Quando expandir |
|---|---|---|---|
| F0 | 20 perguntas | 30 perguntas | Se documentos mudarem significativamente |
| F1 | 30 perguntas | 50 perguntas | Se novo tipo de documento aparecer |
| F2 | 50 perguntas | 80 perguntas | Se mudança de estratégia exigir |
| F3 | 80 perguntas | 100+ perguntas | Se novo tenant trouxer novos casos |

---

## 4. Estrutura do Dataset

```json
{
  "dataset_id": "cliente_x_fase0",
  "version": "1.0",
  "created_at": "2024-03-15",
  "created_by": "nome@empresa.com",
  "documentos_cobertos": ["doc_001", "doc_002", "doc_003"],
  "total_perguntas": 30,
  "por_dificuldade": {
    "easy": 12,
    "medium": 12,
    "hard": 6
  },
  "por_categoria": {
    "fato": 10,
    "procedimento": 12,
    "política": 5,
    "detalhes": 3
  },
  "questions": [
    {
      "id": 1,
      "pergunta": "Qual o prazo para reembolso?",
      "document_id": "doc_001",
      "documento_nome": "Política de Reembolso.pdf",
      "trecho_esperado": "O prazo para solicitação de reembolso é de 30 dias corridos após a purchase.",
      "resposta_esperada": "30 dias corridos",
      "dificuldade": "easy",
      "categoria": "procedimento",
      "contexto": "Cliente via chat de suporte",
      "validado_por": "nome@empresa.com",
      "data_validacao": "2024-03-15"
    }
  ]
}
```

---

## 5. Manutenção do Dataset

### Regra: Dataset não é estático

- Adicionar perguntas quando falhas surgirem em produção
- Remover perguntas se documento não existir mais
- Atualizar trechos_esperados se documentos mudarem
- Re-classificar dificuldade se novos padrões surgirem

### Frequência de Atualização

| Evento | Ação |
|---|---|
| Nova falha em produção (pergunta não respondida) | Adicionar pergunta ao dataset |
| Documento atualizado | Verificar se perguntas ainda são válidas |
| Novo tipo de documento | Expandir dataset para cobrir |
| Nova categoria de perguntas | Adicionar categoria ao dataset |

---

## 6. Validação de Retrieval com Dataset

### Como testar retrieval

```python
def evaluate_retrieval(dataset, search_service):
    results = []
    for question in dataset.questions:
        retrieved_chunks = search_service.search(
            query=question.pergunta,
            workspace_id=question.workspace_id,
            top_k=5
        )
        hit_top5 = any(
            chunk.document_id == question.document_id
            for chunk in retrieved_chunks
        )
        results.append({
            "question_id": question.id,
            "retrieved_docs": [c.document_id for c in retrieved_chunks],
            "expected_doc": question.document_id,
            "hit_top5": hit_top5
        })
    return aggregate_hit_rate(results)
```

### Métricas Calculadas

```python
{
    "hit_rate_top1": 0.xx,  # Documento correto é o #1
    "hit_rate_top3": 0.xx,  # Documento correto está no top-3
    "hit_rate_top5": 0.xx,  # Documento correto está no top-5
    "avg_score_top1": 0.xx,  # Score do primeiro resultado
    "by_difficulty": {...},  # Hit rate por dificuldade
    "by_category": {...}     # Hit rate por categoria
}
```

---

## 7. Dataset de Exemplo (Placeholder)

```json
{
  "dataset_id": "placeholder_phase0",
  "version": "0.1",
  "note": "Este dataset é placeholder. Substituir por dados reais antes de iniciar Fase 0.",
  "questions": [
    {
      "id": 1,
      "pergunta": "PLACEHOLDER: Qual a pergunta real?",
      "document_id": "doc-placeholder",
      "trecho_esperado": "PLACEHOLDER: Trecho que contém a resposta",
      "resposta_esperada": "PLACEHOLDER: Resumo do que应该 ser dito",
      "dificuldade": "medium",
      "categoria": "procedimento"
    }
  ]
}
```

**⚠️ ATENÇÃO:** O sistema NÃO deve prosseguir para Gate F0 sem dataset real substituindo o placeholder.

---

## 8. Validação de Gate com Dataset

### Gate F0

```
Critério: hit_rate_top5 >= 60% no dataset real de 20+ perguntas

Teste:
  1. Executar retrieval para todas as perguntas do dataset
  2. Calcular hit_rate_top5
  3. Se >= 60%: GATE APROVADO
  4. Se < 60%: GATE REPROVADO → analisar falhas → ajustar → testar novamente
```

### Gate F1

```
Critério: hit_rate_top5 >= 75% OU +15pp vs baseline

Teste:
  1. Medir hit_rate com configuração atual
  2. Comparar com hit_rate F0 baseline
  3. Se melhoria >= 15pp: GATE APROVADO
  4. Se não: analisar onde está o problema
```

### Gate F2

```
Critério: Estratégia premium vence com significância

Teste:
  1. Rodar benchmark controlado (3-5 perguntas, 4 estratégias)
  2. Análise manual: qual estratégia ganha onde e por quê
  3. Se estratégia premium > baseline com > 10pp: GATE APROVADO
  4. Se não: não adotar premium, manter baseline
```

---

## 9. Checklist de Dataset

### Antes de Iniciar Fase 0

- [ ] Dataset criado com mínimo 20 perguntas reais
- [ ] Cada pergunta tem document_id válido
- [ ] Cada pergunta tem trecho_esperado
- [ ] Revisão humana confirmou que perguntas fazem sentido
- [ ] Dataset exportado em JSON no formato definido

### Durante Fase 0

- [ ] Retrieval testado com 100% das perguntas
- [ ] Falhas documentadas com razão
- [ ] Perguntas que não podem ser respondidas identificadas

### Entre Fases

- [ ] Dataset expandido para novo mínimo
- [ ] Novas perguntas adicionadas de falhas reais
- [ ] Validação de gate usa dataset atualizado

---

## Próximo Passo

Ir para `0019-observabilidade-e-metricas.md` — observabilidade e métricas.