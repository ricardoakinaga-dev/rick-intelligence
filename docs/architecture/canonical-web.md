# Web canônica — State of Art slice

Status: `VERIFY / CYCLE5 WEB LOCAL ESCOPADO; PRODUTO COMPLETO ABERTO` em 2026-09-07. Este documento descreve o
caller root que já foi implementado e separa explicitamente o que ainda exige
o spine durável/live.

## Tese de produto

O produto é um workbench clínico de evidência: superfícies calmas e legíveis,
contraste legível, teal reservado para ação/estado e a sequência
`resposta → fonte → confiança` como hierarquia central. A densidade operacional
vem de informação útil, não de decoração.

## Ownership e fronteira

`apps/web/**` é o único caller visual canônico desta fase. A UI preservada em
`cvg-master-rag-v2/frontend/**` continua intacta e fala o contrato legado; não
há imports cruzados entre as duas superfícies.

O cliente root consome apenas:

- `/api/v1/auth/login`, `/api/v1/auth/me` e `/api/v1/auth/logout`;
- `/api/v1/documents`, upload, exclusão e reindexação de documentos;
- `/api/v1/collections` e jobs de ingestão, incluindo retry e cancelamento;
- `/api/v1/chat` e `/api/v1/search`;
- `/api/v1/admin/health` e `/api/v1/admin/audit` para leitura administrativa;
- `/health/ready` para o sinal de runtime.

Em desenvolvimento, o browser permanece same-origin: o Next encaminha
`/api/*` e `/health/*` para `RICK_API_INTERNAL_URL`. Isso evita perder cookies
`SameSite=Lax` quando a origem visual e a API usam nomes de host diferentes.
`NEXT_PUBLIC_API_BASE_URL` é uma exceção explícita para uma implantação que já
possua CORS restritivo, cookie seguro e política de origem revisada.

No build de produção, `RICK_API_INTERNAL_URL` precisa estar definido ao executar
`npm run build`: os destinos são gravados em `.next/routes-manifest.json`.
Definir outro valor apenas em `npm run start` não substitui esses destinos.
Uma verificação local reproduziu login501 quando o build apontava para8000 e
a API de teste estava em8001; o trace e o manifesto identificaram a divergência.
Confira o destino gerado antes da integração e use o endereço autorizado da API
no build. Essa configuração não autoriza acesso a um serviço de produção.

## Superfícies e estados

| Rota | Estado entregue | Próximo limite |
| --- | --- | --- |
| `/login` | credencial, erro redigido, foco visível, retorno para `next` | recuperação de conta durável |
| `/app` | pergunta como ação principal; documentos e disponibilidade independentes; vazio/403/erro distintos | critérios externos e aceite do produto completo |
| `/app/documents` | catálogo, filtros, upload, jobs, retry/reindex/delete confirmados pelo servidor; proteção contra resposta de coleção antiga | validação externa da persistência e recuperação |
| `/app/search` | consulta, coleção, limite inteiro, histórico da URL, trechos e metadados; invalidação de resposta antiga | matriz visual, conteúdo longo e testes independentes |
| `/app/chat` | pergunta, loading, resposta, citações, incerteza e clipboard | histórico persistido e streaming na interface |
| `/admin` | guarda por permissões efetivas, saúde e auditoria independentes; estados anteriores limpos na atualização | operações administrativas adicionais exigem contratos próprios |

O papel é exibido somente depois de resolvido pelo servidor. O controle de
permissão do backend é autoritativo; a guarda da UI existe para impedir que
uma navegação direta produza uma superfície enganosa.

Revisão REC de 08/09/2026: [matriz de personas](rec-personas.md). A shell usa
`session.permissions`; campo vazio/ausente não recupera acesso pelo papel.
Catálogo somente leitura não mostra mutações; saúde/auditoria só são solicitadas
quando cada permissão existe. Novas evidências ficam em `artifacts/rec-m0-v4/`,
sem reutilizar as aprovações históricas abaixo como aprovação deste código.

## Sistema visual e acessibilidade

Os tokens vivem em `apps/web/app/globals.css`: canvas claro, rail escuro,
teal para ação/saúde, âmbar para atenção e vermelho para falha. A shell tem
skip link, `:focus-visible`, navegação mobile, `prefers-reduced-motion`,
breakpoints de 375, 768 e 1440 px, e estados explícitos de loading/empty/error/
forbidden/success.

Critérios visuais desta fase:

1. nenhum estado de erro deve parecer sucesso;
2. fonte/corpus/escopo aparecem antes de confiança implícita;
3. todos os controles principais têm nome acessível e alcançável por teclado;
4. o layout não depende de tabela larga ou scroll horizontal em 375 px;
5. a interface conserva hierarquia e affordance em 768 e 1440 px.

## Evidência atual

O ciclo1 está preservado em [visual-state-quality.md](visual-state-quality.md)
como histórico. O contrato de benchmark mantém a meta95 e exige crítica
independente; o pacote corrente Cycle4, descrito abaixo, atribuiu scores
independentes à superfície web. Os estados403 da visão geral foram
inspecionados nos três viewports e não tiveram violações na varredura axe local;
isso não certifica toda a aplicação nem substitui avaliação manual WCAG AA.

Executado no ciclo1 (logs brutos em `.gauntlet-state-of-art/evidence/visual-cycle-1/`):

```text
npm run lint       PASS
npm run typecheck  PASS
npm run build      PASS
npm run test:e2e   PASS — 87 testes, 6 skips existentes; desenvolvimento e produção
```

O browser real foi usado para login against o root API local e para gerar
screenshots em `artifacts/visual/state-of-art/`. A evidência é local e não
prova disponibilidade de OpenAI, Qdrant, Redis, fila durável, object storage,
deploy, restart recovery ou operação multi-instância.

## Inspeção de fontes no chat — ciclo2 verificado localmente

Quando a resposta contém citações, o link “Consultar fontes” aparece antes do
texto e leva o foco ao título das fontes. Cada fonte usa `details/summary`
nativos para revelar documento, coleção, trecho, páginas inicial/final e código
de integridade exatamente como recebidos. Valores ausentes ficam explícitos;
não são criadas URLs de documento nem presumida validação de integridade.
Um link permite voltar ao início da resposta. A apresentação não modifica a
política de evidência nem os limites de sessão. Evidência desta implementação
parcial está no registro `VER-SA-VISUAL-CHAT-SOURCES`; a regressão corrente está
no registro `VER-SA-VISUAL-CYCLE2-COPY-RECOVERY`. A aprovação visual independente
atual está no registro `VER-SA-VISUAL-CYCLE4-REVIEWS`; ela é escopada à web.

## Leitura de resultados da busca — ciclo2 verificado localmente

A busca mantém consulta, coleção e limite no contrato existente. Coleção e
limite ficam em filtros expansíveis, com os valores resumidos antes da abertura;
uma falha de validação nativa reabre o campo para correção. O link “Ler trecho
selecionado” leva ao leitor, e a escolha de um resultado move o foco para seu
texto completo sem outra requisição. “Voltar aos resultados” restaura o foco
ao item selecionado. A prévia compacta não substitui nem corta o texto do leitor.
No desktop, o leitor tem mais largura que a lista; em telas menores, a sequência
continua em uma coluna. Identificadores recebidos permanecem visíveis após o
texto, sem inferir validade de um código de integridade. Verificação parcial:
`VER-SA-VISUAL-SEARCH-READING` e no pacote corrente
`evidence/visual-cycle2-current/`. A implementação está verde na matriz local;
a aprovação independente atual está registrada no gate Cycle4, mas permanece
escopada à superfície web e não certifica o produto inteiro.

## Apresentação de papel, estado e recuperação — ciclo2

Papéis e estados operacionais são traduzidos apenas na camada de apresentação:
`PLATFORM_ADMIN`, `KNOWLEDGE_MANAGER` e `VETERINARIAN` aparecem como nomes
humanos, enquanto IDs, chaves de sessão, contratos da API e a autorização do
servidor permanecem intactos. A visibilidade de Administração é um espelho
defensivo do papel canônico; não concede acesso.

O acesso negado a `/admin` mantém o breadcrumb da rota, informa “Acesso
restrito.” e oferece retorno explícito para `/app`. Um `403` de uma sessão
administrativa mantém a falha verdadeira, a ação de tentar novamente e o
retorno à visão geral. Estados de saúde usam “Disponível”, “Com limitações”,
“Indisponível” ou “Não confirmado” conforme a resposta recebida; ausência de
resposta não vira sucesso.

Na tela de login, organização, identidade e recuperação são descritas em
português, e o campo `tenant_id` continua sendo enviado com o mesmo contrato.
O botão de ação permanece alcançável no primeiro viewport mobile. Esses
comportamentos são cobertos por `tests/copy-recovery.spec.ts` em 375, 768 e
1440 px.

## Pacote corrente de verificação local — Cycle5 final

O build local de produção foi regenerado após o hardening de escopo e o estado
de readiness degradada. A execução vigente de `make web-validate` passou
`234/234`, sem skip planejado ou executável, falha inesperada ou flaky. A matriz
inclui `custom-workbench-degraded` em mobile, tablet e desktop, estados de
recuperação antes/depois, foco de teclado, 320 CSS px, estresse tipográfico e
reflow de viewport efetivo equivalente a 200%; seus
renders/JSONs estão em
`.gauntlet-state-of-art/evidence/visual-cycle5-current/production-test-results/`.
Os 18 registros de performance preservam LCP `≤2500 ms` e CLS `≤0,1`; o resumo
vigente registra máximo observado de LCP `692 ms` e CLS `0,0245569`, sob
condições locais sintéticas. Os valores anteriores de `920 ms` e `620 ms` ficam
tratados como observações históricas e não como evidência vigente.

Os JSONs vigentes da matriz registram `prefers_reduced_motion=true` e não têm
violações ou incompletudes axe. O pacote atual contém 141 PNGs e 141 JSONs,
incluindo artefatos de reflow, escala, foco e recuperação. O manifesto/packet histórico Cycle4 permanece
preservado; o pacote corrente de renders e performance está em
`.gauntlet-state-of-art/evidence/visual-cycle5-current/`. O gate
`.agent/gates/state-of-art-visual-cycle4-verified.json` registra duas aprovações
cegas históricas: Dalton `97/100` e Kuhn `95,52/100`, ambos HIGH e sem
Critical/High; elas não foram reutilizadas como aprovação do Cycle5.

O Cycle3 histórico foi rejeitado por lacunas de rastreabilidade/performance e
skips; essas decisões permanecem preservadas. O Cycle4 fechou parte dessas
lacunas com evidência durável de LCP/CLS, reduced-motion, focus trap protegido
contra refoco tardio, harness de produção determinístico e erro de chat
compacto. A regressão atual acrescenta a distinção honesta de readiness
degradada e executa as três larguras antes cobertas apenas por plano. Qualquer
aprovação visual anterior continua escopada ao snapshot que ela nomeia; não é
aprovação de performance de campo nem do produto completo.

## Gate de promoção

O gate Cycle4 aprova somente a superfície web canônica e sua evidência local.
Este slice não é promoção de produção enquanto os critérios
`SA-DURABILITY`, `SA-OPERATIONS`, `SA-OBSERVABILITY`, `SA-SECURITY`,
`SA-PERFORMANCE` e a cobertura completa `SA-WEB/SA-VISUAL` do quality bar não
tiverem evidência fresca. Continuam faltando runtime externo autorizado,
corpus aprovado, durabilidade/restore/soak, multi-instância, observabilidade,
performance de API/worker, deployment/rollback e aceitação final independente.
A ausência de trace bruto tab-a-tab e de integrações externas continua
explícita. O caller está pronto para integrar esses contratos; ele não deve
mascarar a ausência deles.
