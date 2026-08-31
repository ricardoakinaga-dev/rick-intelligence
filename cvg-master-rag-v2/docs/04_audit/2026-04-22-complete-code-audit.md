# AUDIT REPORT — CVG RAG Enterprise Premium

Data: 2026-04-22
Escopo: leitura integral da pasta `docs/` como fonte de verdade documental e auditoria minuciosa do código em `src/`, `frontend/`, CI e testes.
Base normativa principal: `docs/00_discovery/*`, `docs/01_prd/*`, `docs/02_spec/*`, complementada por `AGENTS.md`, runtime/backlog/log e relatórios de build/audit existentes.

## Evidências executadas
- Leitura do inventário completo de `docs/`.
- Leitura direta de documentos mestres: `0009_discovery_master.md`, `0020_prd_master.md`, `0120_spec_master.md`, `99_runtime_state.md`, `20_master_execution_log.md`, `30_backlog_master.md`, `0207-auth-access-final-report.md`.
- Inspeção manual de código crítico: `src/api/main.py`, `src/services/vector_service.py`, `src/services/search_service.py`, `src/services/admin_service.py`, `src/core/config.py`, `frontend/lib/api.ts`, `frontend/app/admin/page.tsx`, `frontend/package.json`, `.github/workflows/ci.yaml`.
- Gates executados:
  - `pytest -q` em `src/`
  - `npm run build` em `frontend/`
  - `pnpm exec tsc --noEmit` em `frontend/`
  - `pnpm exec playwright test` em `frontend/`

## Métricas objetivas
- Arquivos analisados (extensões principais): 818
- LOC aproximado: 107686
- Arquivos Python: 446
- Arquivos frontend TS/TSX: 28
- Arquivos de teste detectados: 13

## Resultado dos gates
- Python tests: FAIL
  - 211 passed
  - 17 skipped
  - 4 failed
- Frontend build: PASS
- Frontend typecheck: PASS
- Frontend smoke/Playwright: FAIL
  - 5 passed
  - 1 failed
- Frontend unit test script: inexistente em `frontend/package.json`

## Falhas concretas encontradas
1. `pytest` falhou em metadata de `document_filename` no retrieval e nas citações.
2. `pytest` falhou em autorização inconsistente entre `/observability/*` e `/admin/*`.
3. `pytest` falhou porque `/admin/alerts` aceitou `operator`, contrariando o contrato esperado pelo teste.
4. Playwright falhou no fluxo de busca porque a evidência esperada (`30 dias corridos`) não apareceu na UI.
5. `frontend/package.json` não expõe script `test`, o que enfraquece o gate padrão de qualidade.
6. `src/core/config.py` contém linha corrompida para `OPENAI_API_KEY` (`OPENAI_API_KEY=os.get...EY", "")`), sinal claro de defeito de código/configuração.

## Notas por item analisado (0-100)

### 1. Aderência à documentação canônica — 82/100
Pontos fortes:
- O repositório tem trilha documental extensa e bem organizada em discovery, PRD, SPEC, BUILD e AUDIT.
- O código efetivamente implementa grande parte do escopo central: ingestão, retrieval híbrido, query RAG, auth, admin e observabilidade.

Débitos:
- A SPEC master ainda descreve sessão server-side in-memory, mas a documentação mais recente de auth hardening indica persistência JSON; há evolução real, porém com narrativa parcialmente divergente entre documentos.
- O contrato de autorização observado em testes não está consistente no runtime atual.

### 2. Documentação e governança CVG — 90/100
Pontos fortes:
- Excelente densidade documental.
- Estado, backlog e execution log existem e estão estruturados.
- Há rastreabilidade forte entre docs e entregas.

Débitos:
- O backlog master contém itens e débitos técnicos antigos que já não refletem plenamente o estado atual do sistema.
- Há muita documentação histórica; a fonte normativa existe, mas a sobrecarga documental aumenta risco de divergência.

### 3. Arquitetura e design — 84/100
Pontos fortes:
- Modular monolith coerente com a SPEC.
- Separação razoável entre API, services, models, telemetry e frontend.
- Pipeline de retrieval/query tem evolução visível e heurísticas adicionais relevantes.

Débitos:
- `src/api/main.py` está muito grande e concentra responsabilidades demais.
- Há acoplamento operacional alto entre autorização, telemetria, runtime admin e endpoints de negócio.
- O modelo de permissão parece ter crescido mais rápido que a decomposição arquitetural.

### 4. Implementação de domínio RAG — 86/100
Pontos fortes:
- Ingestão, chunking, retrieval híbrido, groundedness e query expansion/retry mostram maturidade acima da média.
- Há tratamento para fallback local, deduplicação, reranking e recuperação crosslingual.

Débitos:
- Os testes quebrados de `document_filename` mostram regressão em um detalhe funcional importante para evidência e UX.
- Parte do comportamento depende de heurísticas crescentes, o que aumenta complexidade de manutenção.

### 5. API e contratos — 76/100
Pontos fortes:
- Cobertura de endpoints é ampla.
- Há contratos para auth, admin, observabilidade, corpus audit/repair e query/search.

Débitos:
- Há divergência concreta entre contrato esperado e comportamento real em autorização administrativa.
- Endpoints retornam 500 embrulhando 403 em alguns casos, o que quebra semântica HTTP e contrato de erro.
- A consistência entre `/observability/*` e `/admin/*` está frágil.

### 6. Segurança e autenticação — 74/100
Pontos fortes:
- Há RBAC/permissions reais, sessão autenticada, revogação, reset, trilha de auditoria e endurecimento recente.
- O modelo de permissões por role está mais maduro que o PRD inicial.

Débitos críticos:
- O frontend ainda usa bearer token em storage, explicitamente reconhecido como limitação.
- Há inconsistência de enforcement em endpoints administrativos/observability.
- CORS global aberto (`allow_origins=["*"]`) é inadequado para cenário enterprise real.
- A linha corrompida de `OPENAI_API_KEY` em config reduz confiança operacional.

### 7. Multi-tenant e isolamento — 83/100
Pontos fortes:
- O código mostra preocupação explícita com `workspace_id`, tenant e guards.
- Há testes e documentação dedicados a isolamento.

Débitos:
- Como há falhas de autorização em superfícies admin/observability, o isolamento administrativo ainda inspira cautela.
- O score permanece alto, mas não máximo, porque os contratos de acesso não estão totalmente estáveis.

### 8. Persistência e integridade de dados — 78/100
Pontos fortes:
- Há registry de documentos, logs JSONL, audit/repair e serviços de integridade.
- A abordagem file-based está bem documentada e foi mantida com compatibilidade.

Débitos:
- O uso intensivo de JSON/file-based em auth/admin/session continua sendo solução pragmática, não robusta para escala enterprise.
- Há risco operacional por ausência de banco transacional para superfícies administrativas e de sessão.
- Divergência entre SPEC antiga e implementação atual merece normalização documental.

### 9. Observabilidade — 81/100
Pontos fortes:
- Há tracing, SLI/SLO, health, runtime summary, alerts e logs especializados.
- O projeto demonstra cultura de observabilidade superior ao normal em projetos desse porte.

Débitos:
- O enforcement de acesso em observability está inconsistente.
- Parte das rotas administrativas de observabilidade não respeita claramente a fronteira entre leitura operacional e governança.
- Quando 403 vira 500, a experiência operacional degrada.

### 10. Testes automatizados — 73/100
Pontos fortes:
- Suite Python volumosa e valiosa: 211 testes passando mesmo com regressões abertas.
- Há smoke E2E com Playwright e gates específicos.

Débitos:
- 4 falhas reais no backend e 1 falha real no smoke UI impedem nota alta.
- `frontend/package.json` não possui script `test`, enfraquecendo padrão de automação.
- Há indicativos de fragilidade em contratos de autorização e evidência visual.

### 11. Frontend e UX operacional — 80/100
Pontos fortes:
- Frontend compila, typechecka e cobre páginas críticas.
- A tela admin é rica e mostra maturidade operacional.

Débitos:
- `app/admin/page.tsx` é grande e complexa.
- Há warning de variável não usada (`canManageRuntime`).
- Um teste de busca falha exatamente na evidência visível, o que é problema de UX funcional e confiança.

### 12. Infraestrutura e DevOps — 77/100
Pontos fortes:
- Existe CI em GitHub Actions com typecheck, smoke, lint e build.
- O pipeline cobre backend e frontend em pontos importantes.

Débitos:
- CI usa `pnpm exec next lint`, mas o build local já acusou warning de configuração do plugin Next no ESLint.
- Requisitos Python pinam `qdrant-client==1.7.4`, enquanto o histórico documental já reporta incompatibilidade com o ambiente atual; isso é dívida operacional clara.
- Falta gate único consolidado que reflita exatamente o runtime real aprovado.

### 13. Qualidade de código e manutenibilidade — 75/100
Pontos fortes:
- Nomes e organização geral são compreensíveis.
- Há esforço de documentação inline e testes ao redor de funcionalidades complexas.

Débitos:
- Arquivos centrais grandes demais (`src/api/main.py`, `frontend/app/admin/page.tsx`, `src/tests/test_sprint5.py`).
- Complexidade ciclomática e crescimento de condicionais tornam regressões mais prováveis.
- A linha corrompida em `src/core/config.py` é um sinal de higiene insuficiente.

### 14. Prontidão enterprise real — 71/100
Pontos fortes:
- O projeto tem base muito sólida para um RAG enterprise em evolução.
- Governança e trilha documental estão acima da média.

Débitos:
- Ainda não está em estado “enterprise premium plenamente comprovado” porque há regressões abertas em teste, inconsistência de autorização, dívida em secrets/session storage e persistência administrativa simplificada.

## Score geral ponderado
79/100

## Principais achados críticos
1. Segurança/contrato: autorização inconsistente entre superfícies admin e observability.
2. Qualidade funcional: regressão em `document_filename` quebra retrieval/citações e provavelmente a UX da busca.
3. Qualidade operacional: um endpoint transforma erro de autorização esperado em 500.
4. Configuração: `src/core/config.py` contém linha corrompida de API key.
5. DevEx/CI: ausência de script frontend `test` e dependência Python historicamente incompatível.

## Recomendações priorizadas

### P0
1. Corrigir imediatamente `document_filename` no pipeline retrieval → query → citations.
2. Corrigir guards de `/admin/alerts`, `/admin/audits`, `/admin/repairs` e `/observability/*` para alinhar contrato e testes.
3. Garantir que erros de permissão retornem 403 em vez de 500 encapsulado.
4. Corrigir `src/core/config.py` e validar bootstrap/config por teste automatizado.
5. Fazer a suíte voltar para verde: `pytest -q` e `pnpm exec playwright test`.

### P1
6. Adicionar script `test` no frontend e padronizar gates locais/CI.
7. Revisar `requirements.txt` para resolver incompatibilidade de `qdrant-client` com o ambiente real.
8. Restringir CORS para ambientes permitidos.
9. Reduzir acoplamento de `src/api/main.py` extraindo routers/dependencies por domínio.

### P2
10. Migrar bearer token em storage para cookie HttpOnly quando viável.
11. Refatorar `frontend/app/admin/page.tsx` em subcomponentes.
12. Consolidar documentação normativa para remover divergência entre SPEC antiga e auth hardening atual.

## Conclusão
O projeto é forte, ambicioso e muito acima de um protótipo casual. A documentação é robusta, a arquitetura base é coerente e o domínio RAG está bem trabalhado. Porém, a auditoria real do código e dos gates mostra que o estado atual não sustenta a nota implícita de 96/100 presente em partes da documentação operacional. A fotografia objetiva desta rodada é 79/100: base excelente, mas ainda com regressões abertas, inconsistências de autorização e algumas dívidas estruturais importantes para um posicionamento enterprise premium pleno.
