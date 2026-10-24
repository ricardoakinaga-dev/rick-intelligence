# Escopo executável — primeira onda AUD24 (M0)

**Data:** 24/10/2026. **Estado:** `EXECUTADO LOCALMENTE` — G0 PASS; evidência em [implementation-stage1](../reports/evidence/auditoria-2026-10-24/implementation-stage1.md). **Não é aceite de produto.**
**Decisão de entrada:** [ADR-024](<../architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md>) ratificado (AUD24-D1, A+ em duas etapas).
**Baseline:** [auditoria AUD24](<../reports/relatorio-auditoria-2026-10-24.md>), HEAD `48e383c`, worktree com alterações não commitadas do usuário.
**Contratos desta onda:** AUD24-001 (preservar baseline), AUD24-002 (contrato do B01 — concluído pelo ADR-024), AUD24-003 (reconciliar IDs). Nenhum código de produção é alterado nesta onda.

## 1. Pré-condições

1. Autorização humana para **adotar** AUD24-001/003 no controlador; sem isso, este documento é apenas um runbook.
2. Confirmar que o worktree atual é o candidato a preservar (109 entradas no momento da auditoria; conferir o número atual).
3. Confirmar que ninguém está editando os mesmos arquivos durante a captura (um writer).
4. Diretório de saída ignorado pelo Git: `.runtime/auditoria-2026-10-24/`.
5. Nenhum `git reset`, `git checkout -- .`, `git clean`, commit, push ou alteração de DAC.

## 2. AUD24-001 — Preservar baseline

### Objetivo

Produzir um manifesto verificável do worktree e provar que ele pode ser reconstruído byte a byte, sem tocar no estado atual.

### Procedimento

```bash
ROOT="$(pwd)"
OUT="$ROOT/.runtime/auditoria-2026-10-24"
mkdir -p "$OUT"
git rev-parse HEAD > "$OUT/head.txt"
git status --porcelain=v1 > "$OUT/status-before.txt"
git diff --binary > "$OUT/tracked.patch"
git diff --stat > "$OUT/tracked.stat"
git ls-files -z | xargs -0 sha256sum > "$OUT/hashes-tracked.txt"
git ls-files --others --exclude-standard -z | xargs -0 -r sha256sum > "$OUT/hashes-untracked.txt"
git ls-files --others --exclude-standard > "$OUT/untracked.txt"
```

**Restauração em diretório isolado:**

```bash
RESTORE="$OUT/restore"
rm -rf "$RESTORE"
git worktree add --detach "$RESTORE" HEAD
git -C "$RESTORE" apply --binary "$OUT/tracked.patch"
# copiar os não rastreados para o mesmo caminho relativo
while IFS= read -r f; do mkdir -p "$RESTORE/$(dirname "$f")"; cp -p "$ROOT/$f" "$RESTORE/$f"; done < "$OUT/untracked.txt"
```

Ao final, remover o worktree temporário: `git worktree remove --force "$RESTORE"`.

**Conferência:**

- `( cd "$RESTORE" && sha256sum -c "$OUT/hashes-tracked.txt" && sha256sum -c "$OUT/hashes-untracked.txt" )`.
- Comparar contagem de entradas e hashes do patch.
- Comparar `git status` do original com a lista de arquivos restaurados; nenhum arquivo do usuário pode faltar.
- Gerar `manifest.json` com schema, HEAD, branch, timestamp UTC, contagens, SHA-256 do patch e das listas, e resultado da restauração.

### Aceite

- Manifesto reproduzível e verificável.
- Restauração em diretório isolado produz os mesmos bytes para todos os arquivos rastreados e não rastreados listados.
- Nenhum arquivo do worktree original foi removido/alterado.
- `restore-report.json` registra `PASS`/`FAIL`, comandos e limitações.

### Evidência

`manifest.json`, `tracked.patch`, `hashes-*.txt`, `restore-report.json`, `status-before.txt`, `README.md` com o procedimento e hashes.

## 3. AUD24-002 — Contrato do B01

**Status:** concluído pela decisão humana e pelo [ADR-024](<../architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md>). Não há código nesta onda.

**Registro de aceite:** ADR-024, seção 2 (A+ em duas etapas), seção 3 (máquina de estados), seção 4 (ordenação/HTTP), seção 6 (reconciliador) e seção 10 (matriz de testes).

**Pendência antes de M1:** converter o ADR em especificação de implementação para AUD24-012 (schema, transições, API do reconciliador). Isso pertence à segunda onda, não a este runbook.

## 4. AUD24-003 — Reconciliar AUD24 ↔ AUD15 ↔ PROD12

### Objetivo

Provar que os 29 contratos novos não duplicam IDs, não reivindicam aceites existentes e cobrem os 12 achados.

### Procedimento

1. Extrair a lista de IDs AUD24 do backlog e a lista de achados do relatório.
2. Construir `reconciliation.md` com: achado → contrato primário → contratos secundários → marco → gate → ID herdado (quando houver).
3. Verificar por script que:
   - todo achado AUD24-01…12 tem exatamente um contrato primário;
   - todo contrato AUD24-001…045 aparece uma vez;
   - nenhum ID AUD15/PROD12 foi renumerado;
   - as heranças PROD12 apontam para IDs existentes.
4. Rodar `make docs-check`, `docs/ci/check_control_plane.py` e `git diff --check`.
5. Registrar `PASS`/`FAIL` e limitações.

### Aceite

- Matriz completa e sem duplicidade.
- 12/12 achados cobertos; 29/29 contratos mapeados.
- Nenhum status/aceite anterior alterado.
- Checks verdes.

### Evidência

`reconciliation.md`, `ids.json` (ou equivalente), saída dos checks.

## 5. Gate G0

| Critério | Evidência |
|---|---|
| Baseline reproduzível e nenhum arquivo perdido | `restore-report.json` PASS |
| Decisão do B01 ratificada | ADR-024 |
| IDs reconciliados, sem duplicação | `reconciliation.md` + checks |
| Quality bar/comandos congelados | este documento + plano AUD24 |
| Nenhuma alteração de código de produção | `git diff` restrito a docs/runtime |

**G0 só fecha quando os quatro primeiros itens estiverem com evidência atual.** Caso contrário, permanece `BLOCKED`.

## 6. Fora de escopo desta onda

- Implementar AUD24-012, 010/011 ou qualquer correção de identidade.
- Editar `apps/`, `packages/`, `infrastructure/` ou testes de produto.
- Commitar, fazer push, abrir PR ou promover.
- Executar serviços externos, DDL real, provider pago ou browser.
- Alterar `.agent/backlog.json` sem autorização de adoção.

## 7. Handoff para a segunda onda

Após G0:

1. Adotar AUD24-012 no controlador e detalhar o schema/máquina de estados do ADR-024.
2. Implementar a etapa 1 (semântica + unicidade + ordem) e atualizar o teste B01 para o novo contrato.
3. Implementar a etapa 2 (tabela + projeção + reconciliador) e rodar crash/concorrência.
4. Só então abrir AUD24-010/011 e AUD24-030.

## 8. Limitações

- O runbook não foi executado nesta preparação; os comandos são a especificação, não um PASS.
- O manifesto precisa ser gerado no momento da adoção; contagens mudam se o worktree mudar.
- A restauração em `restore/` é uma prova local; não substitui backup externo/versionamento.
- A decisão AUD24-D1 não autoriza produção; o ADR é local/reversível.
