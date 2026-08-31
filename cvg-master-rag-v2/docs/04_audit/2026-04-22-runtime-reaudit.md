# RUNTIME RE-AUDIT REPORT — CVG RAG Enterprise Premium

Data: 2026-04-22
Escopo: reexecutar gates reais de backend, frontend, integrações HTTP e smoke UI para validar o estado operacional atual do programa.

## Evidências executadas
- `pnpm lint` em `frontend/`
- `pnpm build` em `frontend/`
- `pnpm exec tsc --noEmit` em `frontend/`
- `pytest --collect-only -q` em `src/`
- `pytest -q` em `src/` fora do sandbox
- `pnpm test:smoke` em `frontend/` fora do sandbox
- reprodução manual do endpoint `/queries/logs`

## Resultado factual da rodada
- `pnpm lint`: PASS com 1 warning
  - `frontend/app/admin/page.tsx:100` — `canManageRuntime` declarado e não usado
- `pnpm build`: PASS
- `pnpm exec tsc --noEmit`: PASS
- `pytest --collect-only -q`: PASS
  - `232` testes coletados
- `pytest -q` fora do sandbox: FAIL
  - `214 passed`
  - `17 skipped`
  - `1 failed`
- `pnpm test:smoke` fora do sandbox: FAIL
  - `5 passed`
  - `1 failed`

## Bloqueio de ambiente observado
Dentro do sandbox do agente, processos que precisam abrir socket local falham com `PermissionError: [Errno 1] Operation not permitted`.

Impacto:
- `uvicorn` local não sobe no sandbox
- `python -m http.server` não sobe no sandbox
- o smoke Playwright não consegue validar runtime real no sandbox
- requisições com `TestClient` ficam presas no primeiro request dentro do sandbox, mas funcionam fora do sandbox

Conclusão:
- a validação de runtime real desta rodada foi executada fora do sandbox

## Falha backend confirmada
Suíte:
- `src/tests/test_sprint5.py::TestListEndpoints::test_query_logs_list_normalizes_legacy_rows_without_chunks_count`

Sintoma no run completo:
- resposta `401` em `GET /queries/logs?workspace_id=default&limit=5&offset=0`

Diagnóstico:
- a falha não é determinística isoladamente
- a mesma reprodução do endpoint, executada separadamente, respondeu `200`
- a suíte isolada `pytest -q tests/test_sprint5.py::TestListEndpoints` passou com `4 passed`

Leitura técnica:
- há poluição de estado ou fragilidade de isolamento na trilha de autenticação/sessão entre testes
- o bug está no comportamento do runtime sob ordem real de execução, não no contrato nominal do endpoint

## Falha frontend/smoke confirmada
Teste:
- `frontend/tests/phase2-gate.spec.ts:49`
- cenário `documentos executa upload web pela UI`

Sintoma:
- a UI não exibiu `Documento enviado` após clicar em `Enviar`
- o snapshot final mostra a aplicação na tela de login, não na tela de documentos

Leitura técnica:
- o problema não é boot de servidor
- backend e frontend subiram corretamente fora do sandbox
- há quebra funcional no fluxo autenticado de upload, provavelmente envolvendo sessão ou redirecionamento durante o pós-upload

## Integrações avaliadas
- Backend HTTP real: parcialmente funcional
  - `/health`, login, busca e chat passaram indiretamente pelo smoke
- Frontend + backend: parcialmente funcional
  - rotas principais renderizam
  - busca e chat funcionam
  - troca de tenant básica funciona
  - upload via UI permanece quebrado
- Sessão enterprise: funcional com instabilidade
  - login e troca de tenant passam em smoke
  - existe evidência de fragilidade de sessão em teste completo backend e no fluxo de upload da UI

## Conclusão operacional
Não há evidência suficiente para afirmar que "tudo está funcionando".

Estado real desta rodada:
- frontend builda, linta e typechecka
- backend quase fecha verde, mas ainda há 1 falha real em execução completa
- smoke real ainda falha no fluxo de upload autenticado

## Próximo passo recomendado
P0 corretivo:
1. estabilizar a trilha de sessão/autorização que faz `GET /queries/logs` falhar no run completo
2. corrigir o fluxo de upload autenticado na UI até o smoke voltar para `6/6`
3. reexecutar `pytest -q` e `pnpm test:smoke` fora do sandbox para confirmar fechamento real
