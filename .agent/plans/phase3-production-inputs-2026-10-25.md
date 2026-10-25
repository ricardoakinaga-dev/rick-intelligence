# Phase 3 — inputs de produção e CI do candidato

## Contrato desta continuação

Baseline confirmada limpa em `a8a83ca5ce1781302ffb2a72fac9fe8de398de10`.
O pedido autoriza trabalhar nos bloqueios; não constitui revisão independente,
aprovação de corpus, política clínica ou decisão GO. O controlador AUD15 e seus
ledgers históricos permanecem preservados. O relatório desta unidade fica em
`docs/reports/evidence/prd26-2026-10-24/production-inputs-closure.md`.

## Descobertas confirmadas

- GitHub público: `ricardoakinaga-dev/rick-intelligence`; main remoto em
  `c6fb3f0ae8e485960d3d54c2a3294ce476e2781d`, 44 commits atrás do candidato.
- Nenhum commit/run remoto de a8a83ca; nenhuma variável ou secret de Actions.
  Inspeção feita pelos nomes, sem solicitar/exibir valores de segredo.
- Propostas VPS TLS/auth e workflow GHCR já existem, mas exigem arquivos e
  políticas independentes. Não preencher essas aprovações pelo builder.
- Corpus AUD24 existente foi rejeitado como representativo; não reutilizá-lo
  como corpus aprovado nem registrar métricas tautológicas como suporte semântico.
- O gate Redis e seu fault harness não encaminham CA/cert/key ao RedisSettings,
  apesar de a biblioteca suportá-los. Isso impede validar uma CA privada real.

## Autoridade recebida

Após preparar diff/bundle e inspeção limitada de 385 blobs novos, o usuário
respondeu **“Autorizar branch público e CI”** para publicar o candidato no branch
`phase3/a8a83ca-candidate` e executar `quality.yml`. Isso não autoriza promoção
de main, publicação de imagens ou implantação. Os artefatos de revisão ficam
em `.runtime/phase-3/unblock-a8a83ca/`.

## Trabalho e aceite

- [x] Publicar o SHA exato no branch autorizado, disparar quality e inspecionar
  conclusão/artefatos reais; falha remota continua falha e não vira PASS local.
- [x] Encaminhar referências de CA/cert/key sem permitir desativar verificação.
- [x] Exercitar Redis real isolado com TLS/mTLS, senha, leases, limite e circuito;
  rejeitar CA errada, hostname errado, cliente sem certificado, senha errada e
  downgrade plaintext. Chaves apenas em diretório privado ignorado.
- [ ] Regressões, relatório e inventário de pendências atualizados.

O probe TLS é diagnóstico de laboratório com CA própria, nunca aprovação da
CA/custos/topologia/identidade de produção. A promoção inteira permanece NO-GO
até haver corpus/avaliador, políticas de produção, CI aprovado, revisão e GO reais.

## Recuperação

O nome/label da instância TLS deve carregar o run ID; cleanup só remove recursos
com o label exato. A pilha dev compartilhada não é pausada. Preservar resultados
anteriores e a identidade a8a83ca dos dados remotos; código novo ainda requer novo
candidato/CI após revisão. Não disparar publish-images sem políticas revisadas.

## Progresso verificado em 25/10

Branch publicado; quality 40212544954 no SHA a8a83ca terminou FAIL real.
O CI revelou três defeitos adicionais: links ignorados em clones, classificador
de permissão confundindo filtragem e negação, e dependências vulneráveis.
Escopo incorporado: preservar originais e converter links locais em texto;
separar filtragem de eventos da exigência da rota sem relaxar testes; atualizar
locks com hashes e auditar sem exclusões.

Verificado: 182 testes de segurança; 75 focados; 17 de regressão TLS; 266 web;
make validate, compose-static, typecheck, web-build; auditorias test/runtime/npm
com zero vulnerabilidades; trace real API/worker após atualização OTel PASS.
TLS com proveniência fac0aebf030a428a PASS, cleanup PASS, source DIRTY (antes
do commit), produção false. API coverage ampliada ainda em execução.
Correções devem ser commitadas no mesmo branch candidato e um novo CI deve ser
disparado; não importar a falha a8 como sucesso do novo SHA.
