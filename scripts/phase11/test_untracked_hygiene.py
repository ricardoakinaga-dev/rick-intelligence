"""Higiene do worktree: cobertura do `.gitignore` (AUD07-19).

Pergunta ao próprio git (`git check-ignore --no-index -v`) quais padrões batem,
para que remover uma regra faça o teste falhar e não apenas uma medição manual.
O `--no-index` é obrigatório: sem ele o git deixa de aplicar a regra a ficheiros
já no índice e uma evidência mantida escondida passaria despercebida.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (caminho de exemplo, regra que tem de ser a responsável)
IGNORED_PROBES = [
    ("apps/web/.next/BUILD_ID", "**/.next/"),
    ("apps/web/.next-qa/BUILD_ID", "**/.next-*/"),
    ("coverage/lcov.info", "**/coverage/"),
    ("test-results/report.json", "**/test-results/"),
    (".coverage", "**/.coverage"),
    ("packages/contracts/src/app.tsbuildinfo", "**/*.tsbuildinfo"),
    (".runtime/phase-1/bootstrap.log", "**/.runtime/"),
    (".pytest_cache/v/cache/nodeids", "**/.pytest_cache/"),
    ("artifacts/evidence-store/MANIFEST.tsv", "artifacts/"),
    (".opencode/session.json", ".opencode/"),
    (".agent/.writer.lock", ".agent/*.lock"),
    (".next/standalone/server.js", "**/.next/"),
]

# Ficheiros que a política AUD07-18 mantém e que nenhuma regra pode esconder.
NOT_IGNORED_PROBES = [
    "docs/reports/evidence/README.md",
    "docs/reports/evidence/STORE-SUMMARY.json",
    "docs/reports/evidence/auditoria-2026-10-07/evidence-destination.md",
    "docs/reports/evidence/implementation-q24-2026-09-24/verification-q24-26-strata-harness-20260925T1851Z/validate-final2.log",
    # Verificação Q24 nomeia `apps/api/uv.lock`: escondê-lo faz o
    # check_control_plane falhar num checkout novo (E4).
    "apps/api/uv.lock",
]


def _check_ignore(path: str) -> tuple[bool, str]:
    """(ignorado?, regra que casou). Regra com ``!`` conta como não ignorado."""
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "--no-index", "-v", "--", path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return False, ""
    rule = proc.stdout.splitlines()[0].split("\t")[0]
    pattern = rule.split(":", 2)[2] if rule.count(":") >= 2 else rule
    return not pattern.startswith("!"), pattern


@unittest.skipUnless(shutil.which("git"), "git indisponível")
class UntrackedHygiene(unittest.TestCase):
    def test_generalised_patterns_are_covered_by_gitignore(self) -> None:
        for path, expected_rule in IGNORED_PROBES:
            with self.subTest(path=path):
                ignored, pattern = _check_ignore(path)
                self.assertTrue(
                    ignored,
                    f"{path} continua rastreável: nenhuma regra do .gitignore casa "
                    f"(esperada {expected_rule})",
                )
                self.assertEqual(pattern, expected_rule)

    def test_kept_evidence_is_never_hidden_by_gitignore(self) -> None:
        for path in NOT_IGNORED_PROBES:
            with self.subTest(path=path):
                ignored, pattern = _check_ignore(path)
                self.assertFalse(
                    ignored,
                    f"evidência mantida escondida pelo git: {path} casa com {pattern!r} "
                    "(viola a exceção docs/reports/evidence/**/*.log)",
                )


if __name__ == "__main__":
    unittest.main()
