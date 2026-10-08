# Evidência de correção — supply chain npm (AUD07-15)

**Data:** 2026-10-07. **Candidato:** worktree de `/home/ricardo/rick-intelligence`,
`HEAD = b52f32c141916a2ea3af1a6b913bd91f380606e0`. **Achado de origem:** A10 (2 HIGH no npm).
**Continuação:** [`fix-gates-1.md`](fix-gates-1.md), [`fix-gates-2.md`](fix-gates-2.md),
[`route-policy.md`](route-policy.md), [`resilience-fail-closed.md`](resilience-fail-closed.md).

## 1. Problema

| Pacote | Faixa vulnerável | Advisory | Onde entra |
|---|---|---|---|
| `sharp` | `< 0.35.5` | CVE-2026-96889 / GHSA-wq5f-xc86-pv6w (librsvg) | transitive de `next@15.5.25` |
| `source-map-js` | `1.0.0 – 1.2.1` | GHSA-68fv-2mgg-jv7q (DoS por offsets de source map) | transitive de `postcss@8.5.28` e `magicast@0.5.5` |

Ambos já existiam corrigidos no registro (`sharp 0.35.5`, `source-map-js 1.2.2`), mas o
`package-lock.json` fixava as versões vulneráveis. `npm audit fix` (dry-run) **não** os
subia — só mexia em `@img/sharp-libvips*`.

## 2. O que mudou

`apps/web/package.json` — dois `overrides` explícitos, no mesmo padrão já usado para
`postcss` (decisão de supply chain versionada no repositório, não um acidente de resolução):

```json
"overrides": { "sharp": "0.35.5", "source-map-js": "1.2.2" }
```

`npm install` regenerou `apps/web/package-lock.json` (290 linhas relativas ao estado anterior
do worktree; o drift pré-existente do lockfile contra `HEAD` foi preservado, não sobrescrito).

Resultado em `npm ls`:

```
postcss@8.5.28 overridden └─ source-map-js@1.2.2 deduped
next@15.5.25 ├─ sharp@0.35.5 overridden
@vitest/coverage-v8 └─ magicast └─ source-map-js@1.2.2 overridden
```

## 3. Gates

| Gate | exit | Resultado |
|---|---|---|
| `npm audit --audit-level=high` (em `apps/web`) | 0 | **found 0 vulnerabilities** (era 2 high) |
| `make web-lint` | 0 | ESLint |
| `make web-typecheck` | 0 | `tsc --noEmit` |
| `make web-build` | 0 | Next build completo |
| `make web-e2e` | 0 | **339 passed** (matriz 375/768/1440), performance `LCP max=856 ms`, `CLS max=0.0022`, 0 skips |
| `pip-audit -r requirements/runtime.lock --strict` | 0 | No known vulnerabilities found |
| `make validate` | 0 | — |

## 4. Limites

- Os dois `overrides` são pins exatos (padrão do repositório): uma nova advisory em `sharp`
  exige bump manual — é a troca por uma decisão explícita e revisável.
- `npm install` continua emitindo o aviso de `install scripts` (`esbuild`, `unrs-resolver`);
  nenhum script de instalação foi aprovado nem removido por esta mudança.
- A validação de runtime do front (`make frontend-supply-runtime`) exige o ambiente de
  execução correspondente e não faz parte deste corte; os gates acima cobrem build, lint,
  typecheck, E2E e as duas cadeias de dependência (npm e PyPI).
