# Diagnóstico (não concluída) — basenames de teste duplicados (AUD07-16)

**Data:** 2026-10-07/08. **Candidato:** worktree de `/home/ricardo/rick-intelligence`,
`HEAD = b52f32c141916a2ea3af1a6b913bd91f380606e0`. **Achado de origem:** A07.
**Estado:** diagnóstico completo, correção **revertida** — a tarefa segue `Planejada`.

## 1. Problema (reproduzido)

`packages/*/tests/` não tem `__init__.py`, então o modo `prepend` do pytest registra cada arquivo
pelo **basename**. Dois pares repetem nome e a execução única morre na coleta:

| Basename | Ocorrências |
|---|---|
| `test_provider.py` | `packages/identity/tests/` × `packages/providers/tests/` |
| `test_aud03_postgres_live.py` | `packages/identity/tests/` × `packages/knowledge/tests/` |

[`discrimination/exp-a07.txt`](discrimination/exp-a07.txt):
`pytest --collect-only packages` ⇒ **exit 2**, `2 errors during collection`, 3280 coletados.

## 2. O que foi tentado e por que foi revertido

Renomear os dois arquivos **identity** resolve a colisão (validado: invocação única
`pytest packages` ⇒ exit 0 com **3295 passed, 119 skipped** e `make test` por pacote ⇒ exit 0,
[`discrimination/control-a07.txt`](discrimination/control-a07.txt)) — mas derruba `make validate`:

```
[FAIL] BACKLOG_EVIDENCE_REF: Q17-01.A.evidence_refs[100] ... packages/identity/tests/test_provider.py
[FAIL] VERIFY_ARTIFACT_REF:  VER-...-20260925.artifacts[7] ... (7 refs no total)
```

O control-plane exige que cada referência de `.agent/backlog.json` e `.agent/verification.jsonl`
resolva no worktree (ou no histórico *retired component*). Editar esses artefatos para apontar
para o nome novo violaria o contrato append-only de histórico; a cópia `providers` não pode ser
renomeada porque
`scripts/state_of_art/generate_release_evidence.py:151` referencia o caminho dela.

Os arquivos voltaram aos nomes originais (`git mv` reverso + `packages/identity/README.md`
revertido) e `make validate` voltou a **exit 0**.

## 3. Rota pendente (para a próxima execução)

1. `--import-mode=importlib` em um `pytest.ini`/config escopado (o próprio
   `packages/identity/README.md` já usa esse modo num comando) — validando lane a lane, porque
   muda como `conftest` é importado (`from conftest import login_as` em `apps/api/tests`);
   ou
2. cadeia `__init__.py` em `tests/` + `<pkg>/` + `packages/` para nomes de módulo únicos
   (`packages.identity.tests.test_provider`), validando `test_import_boundary` e
   `dependency-boundaries`.

**Discriminação já pronta:** restaurar qualquer um dos dois basenames ⇒ exit 2 na coleta.
