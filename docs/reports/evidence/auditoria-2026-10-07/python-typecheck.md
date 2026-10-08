# Evidência de correção — type checking gradual em Python (AUD07-17)

**Data:** 2026-10-08. **Candidato:** worktree de `/home/ricardo/rick-intelligence`,
`HEAD = b52f32c141916a2ea3af1a6b913bd91f380606e0`. **Achado de origem:** A11
("não há nenhum type-checker Python em uso").

## 1. Problema

`make typecheck` só compilava `apps/web` (TypeScript) e fazia `compileall` em
`scripts`/`packages` — verificação de sintaxe, não de tipos. `pip-audit` e os
testes de contrato não detectam atribuições/assinaturas inconsistentes.

## 2. O que mudou

| Peça | Arquivo | Papel |
|---|---|---|
| Ferramenta | `requirements/test.in` + `requirements/test.lock` | `mypy==2.4.0` (+ `ast-serialize`, `librt`, `mypy-extensions`, `pathspec`); regenerado com o comando do próprio cabeçalho (`uv pip compile --generate-hashes --python-version 3.12`). **Nenhum pin existente mudou**: diff = 5 adições, `pip install --require-hashes --only-binary=:all: --dry-run -r requirements/test.lock` exit 0 |
| Cobertura explícita | `mypy.ini` | `files` = `packages/contracts/src`, `packages/authorization/src`; `warn_unused_ignores`, `no_implicit_optional` |
| Baseline versionada | `docs/baselines/mypy-baseline.txt` | limite de erros por diretório (0/0), com regras comentadas |
| Enforcer | `scripts/phase11/typecheck_baseline.py` | roda mypy com a config canônica, atribui erros ao diretório do baseline (prefixo mais longo), **falha acima** do limite, **avisa abaixo** (para rebaixar, nunca inflar) |
| Gate | `scripts/phase11/runner.py::mode_typecheck` | terceiro caso do `make typecheck` (e portanto do `make ci`) |
| Testes | `scripts/phase11/test_typecheck_baseline.py` | 8 testes: parser, atribuição de prefixo, erro novo falha, limite respeitado, aviso de rebaixe, diretório ausente |

### Correções de código para o baseline nascer em 0

- **13 × `Literal[CONST]`**: mypy rejeita `Literal[variável]` mesmo com
  `Final`. Constantes marcadas `: Final` e o valor literal inlinado na
  anotação (`contract_version: Literal["provider-contract-v1"] =
  PROVIDER_CONTRACT_VERSION`) — valor e validação Pydantic idênticos.
- **`permissions_for_role`**: `overrides: dict | None` → `Mapping[str, object] | None`
  (a implementação já delega a `normalize_permission_overrides(overrides: object | None)`;
  o call site passa o resultado de `isinstance(..., Mapping)`).
- **`policy.py:150`**: `# type: ignore[union-attr]` removido — `warn_unused_ignores`
  provou que o mypy atual não precisa dele (narrowing por `hasattr`).

## 3. Discriminação

| Experimento | Mudança | Resultado |
|---|---|---|
| [`exp-a17.txt`](discrimination/exp-a17.txt) | `_AUD07_17_PROBE: int = "…"` anexado a `packages/contracts/src/rick_contracts/locking.py` | `make typecheck` **exit 2**: `error: Incompatible types … [assignment]` + `FAIL: packages/contracts/src: 1 erro(s) mypy, baseline aceita 0` |
| [`control-a17.txt`](discrimination/control-a17.txt) | probe removido (restauração byte a byte) | `make typecheck` **exit 0**, `PASS: … packages/contracts/src=0/0, packages/authorization/src=0/0` |

Um erro tipado novo em pacote coberto derruba o gate; a restauração o devolve ao verde —
a diferença é só o arquivo.

## 4. Gates

| Gate | exit | Resultado |
|---|---|---|
| `make typecheck` | 0 | web tsc, `compileall` e **mypy baseline** |
| `make validate` | 0 | boundaries, toolchain, workflow, control-plane |
| `make test` | 0 | 614+103, 17, 1704+18, 734, **480** (era 472; +8 novos) |
| `make ci` | 0 | validate + test-fast + lint + **typecheck** + build |

## 5. Limites

- Cobertura inicial deliberadamente estreita (contratos e autorização). Ampliar é
  alterar `files` no `mypy.ini` **e** acrescentar a linha no baseline — as duas
  alterações são visíveis em revisão; remover um pacote também.
- O limite do baseline é **0** nos dois pacotes: ele não absorve dívida, só torna
  explícita a cobertura. Um limite > 0 exige comentário na própria linha.
- mypy indexa por **nome de módulo**: um fixture (ou módulo renomeado) reaproveitado
  pode reportar o caminho gravado no `.mypy_cache`. Os testes usam nomes únicos por
  execução; no repositório os caminhos são estáveis.
- `mypy` só é executado pelo `make typecheck`/`make ci`; os workflows do GitHub não
  rodam esse alvo (mantêm os lanes atuais) — o lock foi atualizado mesmo assim para
  que instalação canônica e local converjam.
