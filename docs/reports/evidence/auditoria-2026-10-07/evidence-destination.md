# AUD07-18 — Destino versionável para a evidência de 1,86 GB

**Tarefa:** AUD07-18 (M2, P1, tamanho M) · **Origem:** A11 · **Data:** 08/10/2026
**Política (única fonte):** [`docs/reports/evidence/README.md`](../README.md)
**Ferramenta:** [`scripts/phase11/evidence_store.py`](../../../../scripts/phase11/evidence_store.py)
**Discriminação:** [`evidence-store-ab.txt`](discrimination/evidence-store-ab.txt),
[`evidence-store-integrity.txt`](discrimination/evidence-store-integrity.txt),
[`evidence-store-gitignore.txt`](discrimination/evidence-store-gitignore.txt)

## 1. Aceite e resultado

| Aceite | Resultado |
|---|---|
| Política documentada e aplicada | `docs/reports/evidence/README.md` (regras, comandos, limites) + `evidence_store.py`; `check` corre no `make validate` e no `make ci` |
| `docs/reports/evidence/` deixa de ser 1,86 GB untracked | **50 351 ficheiros / 1,86 GB → 411 ficheiros / 3 625 941 bytes (≈3,5 MB)**; os 411 estão **staged**, incluindo os 248 `*.log` que a regra `*.log` do `.gitignore` escondia (exceção `!docs/reports/evidence/**/*.log` + gate) |
| Cada evidência citada continua recuperável por hash | Citações **absolutas** (325) presentes; **45 ficheiros citados repostos** com hash verificado contra a bolsa; **0 links de evidência quebrados** em `docs/**/*.md` |
| Nada é apagado sem substituto verificável | 0 remoções; tudo foi **movido** para a bolsa *content-addressed* com linha no manifesto — com a ressalva do incidente na §4 |

## 2. Medição inicial

```
$ find docs/reports/evidence -type f | wc -l   →  50351
$ du -sh docs/reports/evidence                 →  1,8G   (≈1,86 GB em bytes)
```

Por conjunto: `production-2026-10-04` 40 143 ficheiros / 1,4 GB (quase todo
`baseline-projection/` — `node_modules`, `.venv`, `.next`, `dist`),
`implementation-aud03-2026-10-03` 6 952 / 151 MB, `implementation-q24-2026-09-24` 3 209 /
198 MB, `implementation-aud03-2026-10-04` 19, restantes conjuntos. **Nenhum ficheiro da
árvore era rastreado** (`git status` mostrava `?? docs/reports/evidence/`).

Conjunto de retenção (337 ficheiros / 1,84 MB) medido antes de mexer: 310 referências em
`.agent/*`, 233 em `docs/ci/control-inputs/*` (verificados por hash por
`restore_control_inputs.py --check`), 31 em `docs/**/*.md`, 0 em `scripts/**`.

## 3. Regra aplicada

Fica e é versionado: (1) **evidência citada** — normalizada das três formas de citação usadas
no repositório (`docs/reports/evidence/…`, `reports/evidence/…`, `evidence/…`,
`../reports/evidence/…`); (2) conjuntos **`auditoria-*`**; (3) ficheiros de texto na **raiz**
da pasta (a própria política e sumários, < 1 MB).

Tudo o resto vai para `artifacts/evidence-store/<sha[:2]>/<sha256>` (gitignored), com
inventário em `artifacts/evidence-store/MANIFEST.tsv` ancorado pelo hash gravado em
`docs/reports/evidence/STORE-SUMMARY.json` (versionado).

Um ficheiro mantido mas **ignorado pelo git** (a regra `*.log` da raiz apanhava 248 deles)
não estava em lado nenhum fora do *worktree*: nem versionado, nem na bolsa. Corrigido com a
exceção `!docs/reports/evidence/**/*.log` no `.gitignore` e com um teste do `check`
(`evidência mantida ignorada pelo git`, via `git check-ignore --no-index`).

Estado final (2026-10-08T05:58:33Z):

| Métrica | Valor |
|---|---|
| Ficheiros mantidos | 411 (3 625 941 bytes) |
| *Blobs* na bolsa | 34 117 (1 324 752 664 bytes) |
| Linhas no manifesto | 35 843 (5 942 132 bytes) |
| `manifest_sha256` | `40582dcc8ab99dc8c17b7f6b2ba4ffcc5bfdc05b42909a4f95fa28b91e855f9d` |
| Linhas sem caminho (`-`) | 30 200 |

Comandos executados nesta ordem:

```
python3 scripts/phase11/evidence_store.py apply    # classifica e move (crash-safe)
python3 scripts/phase11/evidence_store.py relink   # fecha o inventário
python3 scripts/phase11/evidence_store.py check    # PASS
python3 scripts/phase11/evidence_store.py verify   # PASS (34 117 hashes recomputados, 5 s)
```

## 4. Incidente na execução e correção

O **primeiro** `apply` parou com `PermissionError` num diretório só-leitura
(`production-2026-10-04/identity-replica30/identity30-review-packet/evidence`, `dr-xr-xr-x`)
**antes** de gravar o manifesto: 45 943 ficheiros já estavam na bolsa sem o mapeamento
caminho→hash. Nenhum conteúdo se perdeu (o movimento é um *rename*; os *blobs* continuam íntegros
e verificáveis — §5), mas o **caminho original** dessas linhas não é recuperável.

Correções aplicadas à ferramenta:

1. `ensure_writable`/`move_entry` — repara o diretório de origem só-leitura e re-tenta;
2. manifesto gravado de forma **crash-safe** e chaveado por `(caminho, hash)` (as linhas `-`
   partilham caminho e eram colapsadas num dicionário indexado só por caminho);
3. subcomando **`relink`** — fecha o inventário: recupera caminhos a partir dos pares
   `(path, sha256)` de inventários sobreviventes e regista o resto como `original_path = -`.

Com o `relink`, **1 594 caminhos** foram recuperados (q24, `.gauntlet/state.json`,
`docs/ci/control-inputs`, JSON de evidência mantidos); restam **30 200 linhas `-`**.

**Evidência citada afetada e repostagem:** 33 citações em forma relativa (28 em
`implementation-aud03-2026-10-03`, 1 em `…-10-04`, 5 em `production-2026-10-04`) apontavam para
ficheiros movidos na interrupção sem linha no manifesto. Os 33 foram **repostos com hash
verificado**: 32 a partir de uma cópia local de referência de trabalho
(`/tmp/opencode/clean-checkout`), cada cópia comprovada contra um *blob* existente na bolsa, e o
`novel-final.log` — que não tinha cópia local — **recuperado da própria bolsa** pela hash
registada no `archive-manifest.json` do pacote. Mais 6 ficheiros irmãos citados apenas pelo
`review.md` do pacote `identity30-review-output` foram repostos pela mesma rota, somando **39
ficheiros**. Depois da repostagem não resta nenhum link de evidência quebrado em `docs/**/*.md`.

O pacote só ficou completo porque o detetor de citações passou a contar os links de um
**ficheiro já mantido dentro da pasta** (§7 da política): `review.md` é citado por relatório,
mas os seus próprios links (`review.json`, `independent-check.py`, …) não eram apanhados pelos
padrões normais — sem a segunda passagem o `apply` voltava a mover parte de um conjunto citado.

As restantes **738** citações relativas sem ficheiro na árvore são links históricos a material
anterior a esta política; reportam-se como aviso, não falham o gate. As citações **absolutas** —
as que os gates usam — estão todas satisfeitas. As **30 200 linhas `-`** do manifesto continuam
a significar conteúdo íntegro na bolsa sem mapeamento caminho→hash: nenhum dos 39 repostos
dependeu desse mapeamento perdido — as rotas da §8 da política exigem caminho conhecido ou hash
registada.

Para os três diretórios citados que ficaram só com a política foram criadas páginas-ponte
(citadas pelo `docs/INDEX.md`, portanto mantidas):
`implementation-aud03-2026-10-03/README.md`, `…/ci-restore/README.md`, `…/runtime/README.md`.
Outros 6 ficheiros citados por link relativo já tinham sido repostos antes, via `restore`,
incluindo `production-2026-10-04/{identity-replica30,integration-dedup17,
joint-restore18,observability31-closed,runtime24-historical}.json` e o
`recovery-manifest.json` do q24 (total geral com esses: 45 ficheiros repostos).

## 5. Discriminação (reverter ⇒ falha, restaurar ⇒ verde)

| Sonda | Espera | Observado |
|---|---|---|
| A1 material bruto reinserido em `production-2026-10-04/probe-a1/` | `check` exit 1 | exit 1, `arquivo fora da política` |
| A2 sonda removida | `check` exit 0 | exit 0 |
| B1 `MANIFEST.tsv` alterado | `check` exit 1 | exit 1, `manifest_sha256` divergente |
| B2 manifesto reposto | `check` exit 0 | exit 0 |
| C1 maior *blob* corrompido | `verify` exit 1 | exit 1, `hash divergente` |
| C2 *blob* reposto | `verify` exit 0 | exit 0 |
| C3 após o reparo | `check` exit 0 | exit 0 |
| D1 exceção `!docs/reports/evidence/**/*.log` removida do `.gitignore` | `check` exit 1 | exit 1, `evidência mantida ignorada pelo git` |
| D2 exceção reposta | `check` exit 0 | exit 0 |

As sondas A/B/C foram **reexecutadas** depois da alteração ao detetor de citações (2.ª passagem
da §3) e deram o mesmo resultado: A1=1, A2=0, B1=1, B2=0, C1=1, C2=0, C3=0. A sonda D (exceção
ao `.gitignore`) é nova: D1=1, D2=0. Transcrições em [`discrimination/`](discrimination/).

## 6. Gates

```
make validate  → exit 0  (inclui "evidence store policy (AUD07-18)" → PASS)
make test      → exit 0  (614+103, 17, 1704+18, 734, 494 = 14 testes de evidência)
make ci        → exit 0  (validate + test-fast + lint + typecheck + build)
```

`scripts/phase11/test_evidence_store.py` — 14 testes que montam um repositório mínimo em
diretório temporário (política de retenção, `apply`, pacote de revisão mantido com irmãos
citados, mantido escondido pelo `.gitignore`, `check` nas quatro falhas, `restore`, `relink` com
e sem inventário, `verify`). Rodam no `make test` e no `make ci`.

Como a linha nova do `Makefile` executa um *script* Python, o fixture de
`test_check_canonical_ci.py` passou a incluir `scripts/phase11/evidence_store.py` na lista de
fontes executadas pelas receitas — é o contrato do `check_canonical_ci` (uma receita só executa
fontes que o fixture copia).

## 7. Limites conhecidos

- A bolsa é **gitignored**: num *clone* novo só a política e o sumário estão presentes; o
  `check` valida então a política e avisa (`NOT_AVAILABLE`) que a cobertura da bolsa só corre
  localmente. Sem publicação externa (artefacto de CI ou armazenamento com referência
  imutável), a bolsa é o único sítio com o conteúdo — fazer cópia de segurança.
- O `check` imprime `AVISO: 738 citação(ões) em forma relativa sem arquivo na árvore`: são os
  links históricos da §4 (eram 771 antes da repostagem), não falham o gate de propósito.
- As referências de `.gauntlet/state.json` (3 226 caminhos) apontam para material na bolsa; o
  `gauntlet_state.py validate` não as verifica (`artifacts.jsonl` está vazio), mas um *run* que
  precise delas deve `restore` primeiro.
- `docs/ci/prove_control_restore.py` e `snapshot_control_inputs.py` leem histórico desta pasta:
  corra `restore` antes.

## 8. Estado do *worktree* e próximo passo

`git status --porcelain` ao fechar a tarefa: **414 staged** (412 desta pasta + `.gitignore` +
documentação da remediação), **241 não rastreadas** (docs 68, apps 67, packages 64, scripts 24,
infrastructure 12, resto), 439 remoções e 239 modificações por consolidar. A evidência já não
contribui para as não rastreadas — era um único `?? docs/reports/evidence/` que escondia 50 351
ficheiros.

**Próximo passo:** AUD07-19 — política de artefatos não rastreados e limpeza da árvore (M2),
sobre as 241 entradas não rastreadas que restam e sobre as remoções/modificações pendentes.
