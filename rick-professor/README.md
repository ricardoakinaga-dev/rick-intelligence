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
| `API_KEY` | sim para os endpoints OpenAI | - | Chave Bearer exigida; sem valor, o acesso é negado em qualquer ambiente |
| `TELEGRAM_WEBHOOK_SECRET_TOKEN` | sim para o webhook | - | Secret configurado no webhook do Telegram; sem valor, o endpoint permanece indisponível |
| `TELEGRAM_UPDATE_TTL_SECONDS` | não | `86400` | Janela de idempotência por `update_id` no Redis |
| `TELEGRAM_IDEMPOTENCY_TIMEOUT_MS` | não | `3000` | Timeout para reservar um `update_id`; falha fechada se o Redis não responder |
| `PORT` | não | `3000` | Porta do serviço |
| `LOG_LEVEL` | não | `info` | Nível de log |
| `PUBLIC_MODEL_NAME` | não | `rick-professor` | Nome retornado em `/v1/models` |
| `QDRANT_URL` | não | `http://rickvet-rag-qdrant:6333` | URL do Qdrant |
| `QDRANT_COLLECTION` | não | `rag_phase0` | Collection física usada na busca |
| `QDRANT_SCORE_THRESHOLD` | não | `0` | Threshold opcional do Qdrant |
| `QDRANT_WORKSPACE_ID` | não | `default` | Workspace confiável aplicado ao filtro de busca |
| `QDRANT_ALLOWED_COLLECTION_IDS` | não | `rag_phase0` | IDs de collection permitidos, separados por vírgula |
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
  -e API_KEY=<configure-an-openai-secret> \
  -e TELEGRAM_WEBHOOK_SECRET_TOKEN=<configure-a-telegram-secret> \
  -e QDRANT_URL=http://qdrant:6333 \
  -e QDRANT_COLLECTION=rag_phase0 \
  -e REDIS_URL=redis://redis:6379 \
  -e REDIS_LOCKER_URL=http://redis-locker:3000 \
  rick-professor
```

## Endpoints principais
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /webhook/telegram` (exige `X-Telegram-Bot-Api-Secret-Token`)
- `GET /health` (liveness, não exige autenticação)
- `GET /healthz` (readiness incluindo Qdrant)

## Healthcheck do container
O Dockerfile valida o serviço consultando `GET /health`, que é uma rota de liveness pública. `/v1/models` continua protegido pela `API_KEY`.

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
- API Key: o mesmo valor configurado no servidor em `API_KEY`

O modo de desenvolvimento também exige `API_KEY`; não existe bypass implícito quando a variável está ausente. O comando `npm test` define chaves literais exclusivas do teste (`test-only-*`) para manter a autenticação explícita e isolada.

## Webhook do Telegram
Configure no Telegram um `secret_token` e forneça o mesmo valor em `TELEGRAM_WEBHOOK_SECRET_TOKEN`. O serviço compara o header `X-Telegram-Bot-Api-Secret-Token` em tempo constante e grava cada `update_id` no Redis com TTL para evitar reprocessamento de entregas repetidas. Se o secret não estiver configurado ou o Redis estiver indisponível, o update não é processado.

## Observações
- O diretório `dist/` não é versionado; ele é gerado no build.
- O `.env` local não é versionado.
