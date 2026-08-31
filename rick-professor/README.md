# rick-professor

Serviço RAG compatível com endpoint estilo OpenAI para respostas clínicas veterinárias.

## O que faz
- recebe mensagens em `/v1/chat/completions`
- busca evidências no Qdrant
- usa Redis e `modulo-redis-locker` para controle de concorrência
- retorna respostas estruturadas baseadas em RAG

## Dependências externas
- OpenAI API
- Qdrant
- Redis
- `modulo-redis-locker`

## Variáveis de ambiente
| Variável | Obrigatória | Padrão | Descrição |
|---|---:|---|---|
| `OPENAI_API_KEY` | sim | - | Chave da OpenAI |
| `PORT` | não | `3000` | Porta do serviço |
| `LOG_LEVEL` | não | `info` | Nível de log |
| `PUBLIC_MODEL_NAME` | não | `rick-professor` | Nome retornado em `/v1/models` |
| `QDRANT_URL` | não | `http://rickvet-rag-qdrant:6333` | URL do Qdrant |
| `QDRANT_COLLECTION` | não | `rickvet_documents` | Collection usada na busca |
| `QDRANT_SCORE_THRESHOLD` | não | `0` | Threshold opcional do Qdrant |
| `REDIS_URL` | não | `redis://rick-professor-redis:6379` | Redis para memória/conversa |
| `REDIS_LOCKER_URL` | não | `http://n8n-redis-locker:3000` | URL do serviço de lock |
| `MODEL_PREPROCESSOR` | não | `gpt-4o-mini` | Modelo de pré-processamento |
| `MODEL_PLANNER` | não | `gpt-4o` | Modelo planner |
| `MODEL_AGENT` | não | `gpt-4o` | Modelo principal |
| `MODEL_FALLBACK` | não | `gpt-4o-mini` | Modelo fallback |

## Build
```bash
docker build -t rick-professor .
```

## Run
```bash
docker run -d \
  --name rick-professor \
  -p 3020:3000 \
  -e OPENAI_API_KEY=sk-xxxx \
  -e QDRANT_URL=http://qdrant:6333 \
  -e QDRANT_COLLECTION=rickvet_documents \
  -e REDIS_URL=redis://redis:6379 \
  -e REDIS_LOCKER_URL=http://redis-locker:3000 \
  rick-professor
```

## Endpoints principais
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /webhook` (fluxos integrados)

## Healthcheck do container
O Dockerfile valida o serviço consultando `GET /v1/models`.

## Deploy completo
Este repositório inclui um stack de exemplo para subir:
- Redis
- Qdrant
- modulo-redis-locker
- rick-professor
- modulo-rag-indexer

Arquivos:
- `deploy/docker-compose.example.yml`
- `deploy/.env.example`

### Como usar
1. Clone os 3 repositórios como pastas irmãs:
   - `modulo-redis-locker`
   - `rick-professor`
   - `modulo-rag-indexer`
2. Entre em `rick-professor/deploy`
3. Copie o arquivo de ambiente:
   ```bash
   cp .env.example .env
   ```
4. Ajuste os valores sensíveis
5. Suba a stack:
   ```bash
   docker compose -f docker-compose.example.yml --env-file .env up -d --build
   ```

## Open WebUI
Para integrar com Open WebUI, use:
- Base URL: `http://rick-professor:3000/v1`
- API Key: qualquer valor definido no Open WebUI para o provider

## Observações
- O diretório `dist/` não é versionado; ele é gerado no build.
- O `.env` local não é versionado.
