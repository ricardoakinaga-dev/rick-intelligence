"""Regressão da política de evidência em massa (AUD07-18).

Cada teste monta um repositório mínimo em diretório temporário: nada aqui
toca ``docs/reports/evidence`` real nem a bolsa ``artifacts/evidence-store``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence_store as es  # noqa: E402


class EvidenceStoreContract(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="evstore-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        evidence = self.root / "docs" / "reports" / "evidence"
        (evidence / "auditoria-2026-10-07").mkdir(parents=True)
        (evidence / "implementation-q24-2026-09-24" / "run").mkdir(parents=True)
        (self.root / ".agent").mkdir(parents=True)
        # citada: citada pelo plano de controle
        self.cited = evidence / "implementation-q24-2026-09-24" / "run" / "log.txt"
        self.cited.write_text("cited evidence\n", encoding="utf-8")
        # auditoria: mantida por prefixo
        self.audit = evidence / "auditoria-2026-10-07" / "page.md"
        self.audit.write_text("# auditoria\n", encoding="utf-8")
        # raiz: texto curto na raiz da árvore de evidência
        self.root_level = evidence / "README.md"
        self.root_level.write_text("politica\n", encoding="utf-8")
        # massa: sai para a bolsa
        self.bulk = evidence / "implementation-q24-2026-09-24" / "run" / "node.bin"
        self.bulk.write_bytes(b"\x00bulk payload\xff" * 8)
        (self.root / ".agent" / "plano.md").write_text(
            f"evidencia: {self.cited.relative_to(self.root).as_posix()}\n",
            encoding="utf-8",
        )

    def run_apply(self) -> int:
        return es.apply(self.root)

    # ---------------------------------------------------------------- política
    def test_is_kept_distinguishes_cited_audit_root_and_bulk(self) -> None:
        cited = es.cited_paths(self.root)
        self.assertIn(self.cited.relative_to(self.root).as_posix(), cited)
        self.assertTrue(es.is_kept(self.cited.relative_to(self.root).as_posix(), cited, self.root))
        self.assertTrue(es.is_kept(self.audit.relative_to(self.root).as_posix(), cited, self.root))
        self.assertTrue(es.is_kept(self.root_level.relative_to(self.root).as_posix(), cited, self.root))
        self.assertFalse(es.is_kept(self.bulk.relative_to(self.root).as_posix(), cited, self.root))

    def test_apply_moves_bulk_and_keeps_cited(self) -> None:
        self.assertEqual(self.run_apply(), 0)
        self.assertTrue(self.cited.is_file())
        self.assertTrue(self.audit.is_file())
        self.assertTrue(self.root_level.is_file())
        self.assertFalse(self.bulk.exists())
        rows = es.read_manifest(self.root / "artifacts" / "evidence-store" / "MANIFEST.tsv")
        paths = {row["original_path"] for row in rows}
        self.assertIn(self.bulk.relative_to(self.root).as_posix(), paths)
        summary = json.loads(
            (self.root / "docs" / "reports" / "evidence" / "STORE-SUMMARY.json").read_text()
        )
        self.assertEqual(summary["inventory"]["blobs"], len(rows))
        self.assertEqual(summary["inventory"]["paths_unknown"], 0)

    def test_kept_evidence_document_links_its_siblings(self) -> None:
        # Pacote de revisão: a página é citada pelo plano de controle e liga-se
        # a irmãos por link simples (``review.json``), forma que os padrões de
        # citação normais não apanham — sem a 2.ª passagem o pacote ficava
        # incompleto (AUD07-18).
        packet = (self.root / "docs" / "reports" / "evidence"
                  / "implementation-q24-2026-09-24" / "review")
        packet.mkdir(parents=True, exist_ok=True)
        page = packet / "review.md"
        data = packet / "review.json"
        page.write_text("ver [dados](review.json) e [log](run/log.txt)\n", encoding="utf-8")
        data.write_text('{"ok": true}\n', encoding="utf-8")
        plan = self.root / ".agent" / "plano.md"
        plan.write_text(plan.read_text() + page.relative_to(self.root).as_posix() + "\n",
                        encoding="utf-8")
        self.assertEqual(self.run_apply(), 0)
        self.assertTrue(page.is_file())
        self.assertTrue(data.is_file(), "irmão citado pela página mantida foi movido")
        self.assertTrue(self.cited.is_file())
        self.assertEqual(es.check(self.root), [])

    def test_kept_evidence_hidden_by_gitignore_fails_check(self) -> None:
        # 248 *.log mantidos ficavam escondidos pela regra ``*.log`` do
        # ``.gitignore``: nem versionados nem na bolsa. O gate tem de apanhar.
        import subprocess
        subprocess.run(["git", "init", "-q", str(self.root)], check=True,
                       capture_output=True, text=True)
        (self.root / ".gitignore").write_text("*.log\n", encoding="utf-8")
        hidden = self.audit.parent / "run.log"
        hidden.write_text("evidencia de execucao\n", encoding="utf-8")
        self.assertEqual(self.run_apply(), 0)
        self.assertTrue(hidden.is_file())
        errors = es.check(self.root)
        self.assertTrue(any("ignorada pelo git" in error for error in errors), errors)
        # Exceção explícita no .gitignore (o que a política manda fazer).
        (self.root / ".gitignore").write_text(
            "*.log\n!docs/reports/evidence/**/*.log\n", encoding="utf-8")
        self.assertEqual(es.check(self.root), [])

    def test_check_is_green_after_apply(self) -> None:
        self.assertEqual(self.run_apply(), 0)
        self.assertEqual(es.check(self.root), [])

    def test_check_reports_missing_store_summary(self) -> None:
        errors = es.check(self.root)
        self.assertTrue(any("STORE-SUMMARY.json ausente" in error for error in errors))

    def test_check_rejects_bulk_file_back_in_tree(self) -> None:
        self.assertEqual(self.run_apply(), 0)
        self.bulk.parent.mkdir(parents=True, exist_ok=True)
        self.bulk.write_bytes(b"volta indevida")
        errors = es.check(self.root)
        self.assertTrue(any("fora da política" in error or "hash diferente" in error
                            for error in errors), errors)

    def test_check_rejects_missing_cited_evidence(self) -> None:
        self.assertEqual(self.run_apply(), 0)
        self.cited.unlink()
        errors = es.check(self.root)
        self.assertTrue(any("evidência citada ausente" in error for error in errors), errors)

    def test_tampered_blob_fails_gate_and_repair_turns_it_green(self) -> None:
        self.assertEqual(self.run_apply(), 0)
        rel = self.bulk.relative_to(self.root).as_posix()
        rows = {row["original_path"]: row
                for row in es.read_manifest(self.root / "artifacts" / "evidence-store" / "MANIFEST.tsv")}
        blob = self.root / "artifacts" / "evidence-store" / rows[rel]["store_relpath"]
        healthy = blob.read_bytes()
        self.assertEqual(es.check(self.root, samples=1000), [])
        blob.write_bytes(b"tampered")
        broken = es.check(self.root, samples=1000)
        self.assertTrue(any("corrompido" in error for error in broken), broken)
        # a restauração se recusa a devolver conteúdo não confiável
        self.assertEqual(es.restore([rel], self.root), 1)
        # reparar o blob devolve o gate ao verde (discriminação)
        blob.write_bytes(healthy)
        self.assertEqual(es.check(self.root, samples=1000), [])

    def test_restore_puts_file_back_with_original_hash(self) -> None:
        rel = self.bulk.relative_to(self.root).as_posix()
        expected = hashlib.sha256(self.bulk.read_bytes()).hexdigest()
        self.assertEqual(self.run_apply(), 0)
        self.assertFalse(self.bulk.exists())
        self.assertEqual(es.restore([rel], self.root), 0)
        restored = self.root / rel
        self.assertTrue(restored.is_file())
        self.assertEqual(hashlib.sha256(restored.read_bytes()).hexdigest(), expected)
        # o arquivo restaurado consta no manifesto: o gate continua verde
        self.assertEqual(es.check(self.root), [])

    def test_check_detects_manifest_tampering(self) -> None:
        self.assertEqual(self.run_apply(), 0)
        manifest = self.root / "artifacts" / "evidence-store" / "MANIFEST.tsv"
        manifest.write_text(manifest.read_text(encoding="utf-8") + "# alterado\n", encoding="utf-8")
        errors = es.check(self.root)
        self.assertTrue(any("manifest_sha256" in error for error in errors), errors)

    def test_relink_registers_orphan_blob_and_recovers_path(self) -> None:
        self.assertEqual(self.run_apply(), 0)
        store = self.root / "artifacts" / "evidence-store"
        # simula o apply interrompido: blob na bolsa, sem linha no manifesto
        orphan_payload = b"orphan content recorded by a later relink"
        digest = hashlib.sha256(orphan_payload).hexdigest()
        orphan = store / digest[:2] / digest
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(orphan_payload)
        # inventário sobrevivente declara o caminho original (literal construída
        # por concatenação para não virar citação de evidência deste próprio teste)
        cited_rel = "docs/reports/evidence/" + "implementation-q24-2026-09-24/run/orphan.txt"
        gauntlet = self.root / ".gauntlet"
        gauntlet.mkdir(parents=True, exist_ok=True)
        (gauntlet / "state.json").write_text(
            json.dumps({"path": cited_rel, "sha256": digest, "size": len(orphan_payload)}),
            encoding="utf-8",
        )
        self.assertEqual(es.relink(self.root), 0)
        rows = es.read_manifest(store / "MANIFEST.tsv")
        recovered = [row for row in rows if row["sha256"] == digest]
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["original_path"], cited_rel)
        self.assertEqual(es.check(self.root), [])

    def test_relink_registers_unrecoverable_blob_with_unknown_path(self) -> None:
        self.assertEqual(self.run_apply(), 0)
        store = self.root / "artifacts" / "evidence-store"
        payload = b"sem inventario sobrevivente"
        digest = hashlib.sha256(payload).hexdigest()
        orphan = store / digest[:2] / digest
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(payload)
        self.assertEqual(es.relink(self.root), 0)
        rows = es.read_manifest(store / "MANIFEST.tsv")
        self.assertTrue(any(row["sha256"] == digest and row["original_path"] == "-"
                            for row in rows))
        self.assertEqual(es.check(self.root), [])

    def test_verify_recomputes_every_hash(self) -> None:
        self.assertEqual(self.run_apply(), 0)
        self.assertEqual(es.verify(self.root), [])
        store = self.root / "artifacts" / "evidence-store"
        rows = es.read_manifest(store / "MANIFEST.tsv")
        (store / rows[0]["store_relpath"]).write_bytes(b"quebra")
        self.assertTrue(es.verify(self.root))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
