# 0024 — Operação do Corpus e Reindex

## Objetivo

Definir a convenção operacional única para corpus, chunks e reindex após a liberação do Gate F0.

---

## Fonte de Verdade Operacional

### Diretórios canônicos

- corpus ativo: `src/data/documents/{workspace_id}/`
- corpus arquivado: `src/data/documents-ARCHIVED/{workspace_id}/`
- dataset operacional: `src/data/{workspace_id}/dataset.json`
- logs: `src/logs/`

### Convenção de arquivos do corpus ativo

Cada documento persistido no corpus canônico deve existir como:

- `{document_id}_raw.json`
- `{document_id}_chunks.json`

Exemplo no workspace `default`:

- `src/data/documents/default/7f91fdbd-a4e3-4f24-84e3-6edaa802955b_raw.json`
- `src/data/documents/default/7f91fdbd-a4e3-4f24-84e3-6edaa802955b_chunks.json`

### O que não é corpus ativo

- `src/data/documents-ARCHIVED/` não participa de ingestão nem de busca
- `src/data/default/` contém artefatos de suporte da fase, não o corpus vetorial ativo
- scripts de bootstrap podem ler `src/data/default/politicas_fluxpay.md` somente como fallback de inicialização; o fluxo operativo normal deve partir do `raw.json` canônico já persistido

---

## Quando Usar Reindex

Use reindex quando ocorrer um destes cenários:

- drift entre disco e Qdrant
- alteração no algoritmo de chunking
- correção estrutural em metadata persistida
- reconstrução de ambiente local
- limpeza de corpus canônico seguida de reimportação

Não use reindex para upload normal de documentos. Upload regular deve continuar pelo endpoint `/documents/upload`.

---

## Fluxo Operacional Recomendado

### 1. Inspecionar o corpus canônico

```bash
find src/data/documents/default -maxdepth 1 -type f | sort
```

Verifique:

- quais `document_id`s estão ativos
- se cada documento tem par `_raw.json` + `_chunks.json`

### 2. Rebuild local de chunks sem tocar no Qdrant

Use quando quiser apenas regenerar chunks em disco.

```bash
cd src
python3 scripts/reindex_corpus.py default --local-only
```

Efeito:

- lê todos os `*_raw.json` do workspace
- recalcula os chunks
- sobrescreve apenas os `*_chunks.json`
- não escreve embeddings nem pontos no Qdrant
- deriva os documentos a partir do corpus canônico já persistido, não do markdown solto

### 3. Reindex completo com Qdrant

Use quando precisar restaurar `Qdrant = disco`.

```bash
cd src
source .env
python3 scripts/reindex_corpus.py default
```

Pré-requisitos:

- Qdrant acessível
- `OPENAI_API_KEY` configurada

Efeito:

- recria a collection por padrão
- regenera chunks a partir dos `*_raw.json`
- recalcula embeddings
- reindexa todos os chunks do workspace
- executa verificação final de contagem

### 4. Reindex sem recriar a collection

Use só quando quiser preservar a collection existente.

```bash
cd src
source .env
python3 scripts/reindex_corpus.py default --skip-recreate
```

### 5. Reindex sem verificação final

Use apenas em troubleshooting controlado.

```bash
cd src
source .env
python3 scripts/reindex_corpus.py default --skip-verify
```

---

## Como Validar `Qdrant = disco`

### Validação mínima

1. contar chunks no diretório canônico
2. consultar a collection ativa
3. comparar pontos, IDs únicos e documentos do workspace

### Exemplo de leitura esperada

```text
disco: 7 chunks
qdrant: 7 pontos
unique ids: 7
documents: 1
```

Se os números divergirem:

1. confirmar se o workspace usado na verificação é o mesmo da ingestão
2. confirmar se há arquivos indevidos no diretório canônico
3. rodar reindex completo
4. reexecutar os testes de consistência

---

## Tratamento de Drift de Corpus

### Se houver duplicatas acidentais

Mover para o diretório arquivado:

```bash
mv src/data/documents/default/<arquivo> src/data/documents-ARCHIVED/default/
```

Depois:

```bash
cd src
source .env
python3 scripts/reindex_corpus.py default
```

### Regra operacional

O diretório `src/data/documents/default/` deve conter apenas o corpus ativo.

Se um arquivo não deve participar da busca:

- não pode permanecer no diretório canônico
- deve ser arquivado ou removido do fluxo ativo

---

## Comandos de Verificação Rápida

### Suíte principal

```bash
pytest -q
```

### Health check da API

```bash
curl http://localhost:8000/health
```

### Metadata do documento canônico

```bash
curl "http://localhost:8000/documents/7f91fdbd-a4e3-4f24-84e3-6edaa802955b?workspace_id=default"
```

### Métricas agregadas

```bash
curl "http://localhost:8000/metrics?days=7"
```

---

## Critério de Operação Correta

O estado operacional é considerado correto quando:

1. o corpus ativo está apenas em `src/data/documents/{workspace_id}/`
2. cada documento ativo possui `_raw.json` e `_chunks.json`
3. `pytest -q` está verde
4. a collection ativa reflete o corpus canônico
5. a documentação e o runtime apontam para o mesmo diretório operacional

---

## Próximo Passo

Usar este runbook como base para os itens pós-gate de hardening e operabilidade.
