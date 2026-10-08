# Conteúdo movido para a bolsa de evidência (AUD07-18)

Este diretório era um conjunto bruto de execução (`ci-restore/`) citado por documentos
e pelo control-plane. Em 2026-10-08 o material foi **movido** — nunca apagado — para a
bolsa *content-addressed* `artifacts/evidence-store/`, inventariado em
`artifacts/evidence-store/MANIFEST.tsv` e ancorado por `docs/reports/evidence/STORE-SUMMARY.json`.

- Recuperar um ficheiro com caminho registado: `python3 scripts/phase11/evidence_store.py restore <caminho>`.
- Política e limites conhecidos (incluindo a interrupção do primeiro `apply`):
  `docs/reports/evidence/README.md`.
