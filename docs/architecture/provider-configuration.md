# Configuração efetiva do provider — REC-03

O processo da API lê variáveis de ambiente. Copiar `.env.example` para `.env`
não carrega esse arquivo automaticamente no Python; exporte valores por seu
launcher/gerenciador de secrets. Não coloque credenciais na linha de comando.

| Canônica root | Alias aceito |
|---|---|
| LLM_PROVIDER | RICK_PROVIDER |
| LLM_BASE_URL | OPENAI_BASE_URL |
| LLM_API_KEY | EXTERNAL_CHAT_API_KEY |
| LLM_MODEL | OPENAI_CHAT_MODEL |
| EMBEDDING_MODEL | OPENAI_EMBEDDING_MODEL |
| EMBEDDING_DIMENSION | OPENAI_EMBEDDING_DIMENSIONS |

Valor vazio é placeholder não configurado. Dois valores não vazios diferentes
falham no startup, sem ecoar valores. `openai-compatible` e `openai_compatible`
são equivalentes. Não existe precedência silenciosa sobre configuração conflitante.

`RICK_API_CHAT_BACKEND=stub` é o default hermético. Para o Professor local,
selecione `professor`; provider vazio seleciona `deterministic` em local/dev/test.
Para geração externa, selecione explicitamente `openai` ou `openai-compatible`,
configure endpoint/modelo e injete a chave. `RICK_API_USE_LEGACY=1` seleciona
rollback legado explicitamente; falhas nele não caem silenciosamente no stub.

OpenAI e Anthropic foram indicados pelo usuário; Anthropic ainda requer adapter
próprio e não deve ser tratado como endpoint OpenAI-compatible. Não são feitas
chamadas reais sem teto de custo, credencial e corpus autorizado.

`GET /api/v1/admin/system` exige `runtime.manage`; `runtime` informa composição
factory/injected, backend/provider ativos e configuração de credencial como
booleano. Não expõe URLs/chaves nem declara verificação de produção. Componentes
injetados são `externally_managed`, não inferidos a partir do nome configurado.
O factory ainda usa embedding hash local para retrieval: configurar o modelo de
embedding não torna o índice semântico. REC-18 possui aceite separado.

API e frontend antigos toleram o campo adicional de sessão; frontend novo com
API antiga fica sem ações até receber permissões, por segurança. Fazer rollout
da API primeiro. Para rollback de código, preservar dados; M0 não migra storage.
