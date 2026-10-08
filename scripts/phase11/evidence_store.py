#!/usr/bin/env python3
"""Versionable destination for bulk evidence (AUD07-18).

Policy (docs/reports/evidence/README.md is the single home for the rules):

* only *cited* evidence and the ``auditoria-*`` report sets stay under
  ``docs/reports/evidence`` and are versioned in git;
* everything else is moved — never deleted — into the content-addressed store
  ``artifacts/evidence-store/<sha[:2]>/<sha256>`` (gitignored), recorded in
  ``MANIFEST.tsv`` inside the store and anchored by the tracked
  ``STORE-SUMMARY.json`` (hash + provenance);
* ``check`` runs from ``make validate`` and enforces the layout; ``verify``
  recomputes every stored hash; ``restore`` puts a file back at its original
  path.

Subcommands: apply, relink, check, verify, restore, stat.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "reports" / "evidence"
STORE = ROOT / "artifacts" / "evidence-store"
SUMMARY = EVIDENCE / "STORE-SUMMARY.json"
MANIFEST = STORE / "MANIFEST.tsv"
MANIFEST_NAME = "MANIFEST.tsv"
POLICY = "docs/reports/evidence/README.md"
CITED_PATTERN = re.compile(r"docs/reports/evidence/[A-Za-z0-9_.\-/]+")
# Relatórios também citam evidência por link relativo (``evidence/...``,
# ``reports/evidence/...``, ``../reports/evidence/...``). Sem essa forma o
# detector perde cite-alvo e a política movia arquivo ainda citado (AUD07-18).
REL_CITED_PATTERN = re.compile(r"(?:\.\./)*(?:reports/)?evidence/[A-Za-z0-9_.\-/]+")
SCAN_EXCLUDE = {
    ".git", ".gauntlet", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", "artifacts", ".runtime", "__pycache__", ".next", ".venv",
    "evidence",
}
KEPT_PREFIX = "auditoria-"
BINARY_SUFFIX = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".so", ".node", ".pyc",
    ".pyd", ".o", ".a", ".wasm", ".woff", ".woff2", ".ttf", ".otf", ".zip",
    ".gz", ".bz2", ".xz", ".zst", ".tar", ".7z", ".pdf", ".mp4", ".webm",
    ".sqlite", ".db", ".pem", ".crt", ".key",
}
MANIFEST_COLUMNS = ("original_path", "sha256", "bytes", "kind", "store_relpath")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def scan_sources(root: Path) -> list[Path]:
    """Files whose text may cite evidence: control plane, docs, scripts, tests."""
    sources: list[Path] = []
    for base in (root / ".agent", root / "docs", root / "scripts", root / "tests"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or SCAN_EXCLUDE & set(path.parts):
                continue
            if path.suffix in BINARY_SUFFIX:
                continue
            sources.append(path)
    return sources


def _normalize_relative(match: str) -> str:
    text = match
    while text.startswith("../"):
        text = text[3:]
    if text.startswith("reports/"):
        return "docs/" + text
    if text.startswith("evidence/"):
        return "docs/reports/" + text
    return text


MD_LINK_TARGET = re.compile(r"\]\(<?([^)>]+)>?\)")


def _linked_evidence_targets(path: Path, root: Path) -> set[str]:
    """Evidence paths a document's own markdown links resolve to."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    targets: set[str] = set()
    for raw in MD_LINK_TARGET.findall(text):
        if raw.startswith(("http://", "https://", "mailto:", "#")):
            continue
        part = raw.split("#", 1)[0].strip()
        if not part:
            continue
        try:
            resolved = (path.parent / part).resolve()
            rel = resolved.relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            continue
        if rel.startswith("docs/reports/evidence/"):
            targets.add(rel)
    return targets


def scan_citations(root: Path = ROOT) -> tuple[set[str], set[str]]:
    """(citações em forma absoluta, todas as citações normalizadas)."""
    absolute: set[str] = set()
    relative: set[str] = set()
    for path in scan_sources(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in CITED_PATTERN.findall(text):
            absolute.add(match)
        for match in REL_CITED_PATTERN.findall(text):
            relative.add(_normalize_relative(match))
    # Segunda passagem: um relatório mantido dentro de ``docs/reports/evidence``
    # (p. ex. um pacote de revisão) liga-se a ficheiros irmãos. Sem contar esses
    # links o pacote ficava incompleto na árvore e o ``apply`` voltava a mover
    # parte de um conjunto citado (AUD07-18). Contam como citação relativa, de
    # forma que alvo ausente continua a ser aviso, como nas outras formas.
    evidence_root = root.resolve() / "docs" / "reports" / "evidence"
    if evidence_root.is_dir():
        changed = True
        while changed:
            changed = False
            for path in sorted(evidence_root.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                if path.suffix in BINARY_SUFFIX:
                    continue
                try:
                    rel = path.relative_to(root.resolve()).as_posix()
                except ValueError:
                    continue
                if not is_kept(rel, absolute | relative, root):
                    continue
                for target in _linked_evidence_targets(path, root):
                    if target not in relative:
                        relative.add(target)
                        changed = True
    # Sem filtro de existência: uma citação a um arquivo apagado tem de chegar
    # ao gate como ``ausente`` — é exatamente o que ``check`` reporta.
    return absolute, absolute | relative


def cited_paths(root: Path = ROOT) -> set[str]:
    """Citações absolutas — o conjunto que ``check`` exige que exista."""
    return scan_citations(root)[0]


def is_kept(relative: str, cited: set[str], root: Path = ROOT) -> bool:
    """Policy: cited evidence, root-level policy files and ``auditoria-*`` sets."""
    if relative in cited:
        return True
    parts = relative.split("/")
    if len(parts) == 4:
        # Files sitting directly in the evidence root: the policy and summary.
        path = root / relative
        if path.is_symlink() or not path.is_file() or path.stat().st_size >= 1_000_000:
            return False
        try:
            path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return False
        return True
    return len(parts) >= 4 and parts[3].startswith(KEPT_PREFIX)


def iter_evidence_files(evidence_dir: Path) -> list[Path]:
    return sorted(p for p in evidence_dir.rglob("*") if p.is_file() or p.is_symlink())


def ensure_writable(directory: Path) -> None:
    """Evidence trees may be read-only; moving an entry needs write on the dir."""
    if os.access(directory, os.W_OK):
        return
    directory.chmod(directory.stat().st_mode | stat.S_IWUSR)


def move_entry(source: Path, target: Path) -> None:
    """Move ``source`` to ``target``, repairing a read-only parent directory."""
    try:
        os.replace(source, target)
    except PermissionError:
        ensure_writable(source.parent)
        os.replace(source, target)


def store_relpath(digest: str, kind: str) -> str:
    return f"{digest[:2]}/{digest}" if kind == "file" else f"links/{digest[:2]}/{digest}"


def _row(rel: str, digest: str, size: int, kind: str) -> str:
    return "\t".join((rel, digest, str(size), kind, store_relpath(digest, kind)))


def read_manifest(path: Path = MANIFEST) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != len(MANIFEST_COLUMNS):
            raise ValueError(f"manifest line with {len(fields)} columns: {line[:80]}")
        rows.append(dict(zip(MANIFEST_COLUMNS, fields)))
    return rows


def apply(root: Path = ROOT) -> int:
    evidence_dir = root / "docs" / "reports" / "evidence"
    store = root / "artifacts" / "evidence-store"
    manifest_path = store / MANIFEST_NAME
    cited = scan_citations(root)[1]
    # Chave (caminho, hash): as linhas ``-`` de ``relink`` partilham caminho e
    # seriam colapsadas num dicionário indexado só por ``original_path``.
    existing: dict[tuple[str, str], str] = {}
    if manifest_path.is_file():
        for row in read_manifest(manifest_path):
            existing[(row["original_path"], row["sha256"])] = "\t".join(
                row[column] for column in MANIFEST_COLUMNS)
    rows: dict[tuple[str, str], str] = dict(existing)
    summary_path = evidence_dir / "STORE-SUMMARY.json"
    kept_files = kept_bytes = stored_files = stored_bytes = 0
    bytes_moved = 0

    for path in iter_evidence_files(evidence_dir):
        rel = path.relative_to(root).as_posix()
        if is_kept(rel, cited, root):
            kept_files += 1
            if path.is_file() and not path.is_symlink():
                kept_bytes += path.stat().st_size
            continue
        if path.is_symlink():
            payload = os.readlink(path).encode("utf-8")
            digest = sha256_bytes(payload)
            kind = "symlink"
            size = len(payload)
        else:
            digest = sha256_file(path)
            kind = "file"
            size = path.stat().st_size
        target = store / store_relpath(digest, kind)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.is_file() and kind == "file" and sha256_file(target) != digest:
                print(f"FAIL: store blob mismatch for {digest}", file=sys.stderr)
                return 1
            if path.is_symlink():
                path.unlink()
            else:
                try:
                    path.unlink()
                except PermissionError:
                    ensure_writable(path.parent)
                    path.unlink()
        else:
            move_entry(path, target)
            bytes_moved += size
        rows[(rel, digest)] = _row(rel, digest, size, kind)
        stored_files += 1
        stored_bytes += size

    for directory in sorted(
        (p for p in evidence_dir.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts), reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass

    ordered = sorted(rows.values())
    store.mkdir(parents=True, exist_ok=True)
    header = [
        "# evidence-store manifest v1 (content-addressed, gitignored)",
        f"# policy: {POLICY}",
        "# columns: original_path <TAB> sha256 <TAB> bytes <TAB> kind <TAB> store_relpath",
    ]
    payload = "\n".join(header + ordered) + "\n"
    manifest_path.write_text(payload, encoding="utf-8")

    stored_files = len(rows)
    stored_bytes = sum(int(row.split("\t")[2]) for row in rows.values())
    summary = {
        "schema": "evidence-store-summary.v1",
        "policy": POLICY,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "store": "artifacts/evidence-store (gitignored)",
        "manifest": f"artifacts/evidence-store/{MANIFEST_NAME}",
        "manifest_sha256": sha256_bytes(payload.encode("utf-8")),
        "manifest_bytes": len(payload.encode("utf-8")),
        "kept": {"files": kept_files, "bytes": kept_bytes,
                 "rule": "cited by .agent/docs/scripts + auditoria-* sets"},
        "stored": {"files": stored_files, "bytes": stored_bytes,
                   "bytes_moved": bytes_moved},
        "inventory": inventory_counts(store, read_manifest(manifest_path)),
    }
    evidence_dir.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _load_summary(root: Path = ROOT) -> dict | None:
    path = root / "docs" / "reports" / "evidence" / "STORE-SUMMARY.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def inventory_counts(store: Path, rows: list[dict[str, str]]) -> dict[str, int]:
    """Blobs on disk vs manifest rows vs rows without a recoverable path."""
    blobs = [p for p in store.rglob("*") if p.is_file() and p.name != MANIFEST_NAME]
    return {
        "blobs": len(blobs),
        "rows": len(rows),
        "paths_unknown": sum(1 for row in rows if row["original_path"] == "-"),
    }


def structured_pairs(root: Path = ROOT) -> dict[str, set[str]]:
    """(sha256 -> evidence paths) declared by surviving JSON inventories."""
    pairs: dict[str, set[str]] = {}

    def walk(node: object) -> None:
        if isinstance(node, dict):
            path, digest = node.get("path"), node.get("sha256")
            if (isinstance(path, str) and isinstance(digest, str)
                    and len(digest) == 64
                    and path.startswith("docs/reports/evidence/")):
                pairs.setdefault(digest, set()).add(path)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    candidates = [root / ".gauntlet" / "state.json"]
    candidates += sorted((root / ".agent").glob("*.json*"))
    candidates += sorted((root / "docs" / "ci" / "control-inputs").rglob("*.json"))
    candidates += [p for p in (root / "docs" / "reports" / "evidence").rglob("*")
                   if p.suffix in {".json", ".jsonl"}]
    decoder = json.JSONDecoder()
    for path in candidates:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            if path.suffix == ".jsonl":
                for line in text.splitlines():
                    line = line.strip()
                    if line[:1] in "[{":
                        walk(json.loads(line))
            elif path.suffix == ".json":
                walk(json.loads(text))
            else:
                index = 0
                while index < len(text):
                    while index < len(text) and text[index] in " \n\r\t":
                        index += 1
                    if index >= len(text):
                        break
                    node, index = decoder.raw_decode(text, index)
                    walk(node)
        except (json.JSONDecodeError, ValueError):
            continue
    return pairs


def relink(root: Path = ROOT) -> int:
    """Recover paths for store blobs the interrupted ``apply`` left unrecorded.

    Two passes: structured ``(path, sha256)`` pairs from surviving inventories,
    then a residual row (``original_path = -``) for every blob still uncovered,
    so ``MANIFEST.tsv`` is a complete inventory of the store either way.
    """
    store = root / "artifacts" / "evidence-store"
    manifest_path = store / MANIFEST_NAME
    if not manifest_path.is_file():
        print(f"FAIL: {MANIFEST_NAME} ausente — rode apply primeiro", file=sys.stderr)
        return 1
    rows = read_manifest(manifest_path)
    known = {row["sha256"] for row in rows}
    blobs = [p for p in store.rglob("*") if p.is_file() and p.name != MANIFEST_NAME]
    uncovered = [p for p in blobs if p.name not in known]
    recovered: dict[str, str] = {}
    for digest, paths in structured_pairs(root).items():
        if digest not in {b.name for b in uncovered}:
            continue
        for path in sorted(paths):
            if (root / path).exists():
                continue  # still in place: kept, not stored
            recovered[digest] = path
            break
    for path in uncovered:
        digest = path.name
        if digest in recovered:
            rel = recovered[digest]
            size = path.stat().st_size
            rows.append(dict(zip(MANIFEST_COLUMNS, (rel, digest, str(size), "file",
                                                    store_relpath(digest, "file")))))
        else:
            rows.append(dict(zip(MANIFEST_COLUMNS, ("-", digest,
                                                    str(path.stat().st_size), "file",
                                                    store_relpath(digest, "file")))))
    ordered = sorted("\t".join(row[column] for column in MANIFEST_COLUMNS)
                     for row in rows)
    header = [
        "# evidence-store manifest v1 (content-addressed, gitignored)",
        f"# policy: {POLICY}",
        "# columns: original_path <TAB> sha256 <TAB> bytes <TAB> kind <TAB> store_relpath",
    ]
    payload = "\n".join(header + ordered) + "\n"
    manifest_path.write_text(payload, encoding="utf-8")
    summary = _load_summary(root) or {}
    summary.update({
        "manifest_sha256": sha256_bytes(payload.encode("utf-8")),
        "manifest_bytes": len(payload.encode("utf-8")),
        "inventory": inventory_counts(store, rows),
    })
    (root / "docs" / "reports" / "evidence" / "STORE-SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"recovered_paths": len(recovered), **summary["inventory"]},
                     indent=2, sort_keys=True))
    return 0


def _git_ignored(paths: list[str], root: Path) -> list[str]:
    """Kept paths ``.gitignore`` would keep out of the index (AUD07-18).

    Um ficheiro mantido pela política mas escondido por uma regra do
    ``.gitignore`` (p. ex. ``*.log``) não está versionado nem na bolsa: o
    conteúdo existiria só no *worktree*. Sem ``--no-index`` o git ignora a
    regra para ficheiros já no índice e a falha passaria despercebida.
    """
    if not paths or not (root / ".git").exists():
        return []
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "--no-index", "--stdin"],
            input="\n".join(paths) + "\n", capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in proc.stdout.splitlines() if line]


def check(root: Path = ROOT, samples: int = 32) -> list[str]:
    """Fast structural gate; safe on a clone without the gitignored store."""
    evidence_dir = root / "docs" / "reports" / "evidence"
    store = root / "artifacts" / "evidence-store"
    manifest_path = store / MANIFEST_NAME
    errors: list[str] = []
    summary = _load_summary(root)
    if summary is None:
        return ["docs/reports/evidence/STORE-SUMMARY.json ausente: política AUD07-18 não aplicada"]

    cited, all_cited = scan_citations(root)
    missing = sorted(rel for rel in cited if not (root / rel).exists())
    relative_only_missing = sorted(
        rel for rel in all_cited - cited if not (root / rel).exists()
    )

    stored: dict[str, dict[str, str]] = {}
    manifest_rows: list[dict[str, str]] = []
    if store.is_dir() and manifest_path.is_file():
        payload = manifest_path.read_bytes()
        if sha256_bytes(payload) != summary.get("manifest_sha256"):
            errors.append("MANIFEST.tsv não corresponde a manifest_sha256 do STORE-SUMMARY.json")
        try:
            manifest_rows = read_manifest(manifest_path)
            for row in manifest_rows:
                stored[row["original_path"]] = row
        except ValueError as exc:
            errors.append(str(exc))

    # Citação ausente só é aceita quando o manifesto ainda guarda o conteúdo:
    # é o caso de um link de documento para um diretório, cujo conteúdo foi
    # para a bolsa e continua recuperável por hash.
    for rel in missing:
        prefix = rel.rstrip("/") + "/"
        if any(row["original_path"].startswith(prefix) for row in manifest_rows):
            continue
        errors.append(f"evidência citada ausente: {rel}")

    kept_paths: list[str] = []
    for path in iter_evidence_files(evidence_dir):
        rel = path.relative_to(root).as_posix()
        if is_kept(rel, all_cited, root):
            kept_paths.append(rel)
            continue
        if rel in stored:
            row = stored[rel]
            if path.is_symlink() or path.is_file():
                digest = (sha256_bytes(os.readlink(path).encode()) if path.is_symlink()
                          else sha256_file(path))
                if digest != row["sha256"]:
                    errors.append(f"restaurado com hash diferente: {rel}")
            continue
        errors.append(f"arquivo fora da política em docs/reports/evidence: {rel}")

    ignored_kept = _git_ignored(kept_paths, root)
    for rel in ignored_kept[:10]:
        errors.append(f"evidência mantida ignorada pelo git: {rel}")
    if len(ignored_kept) > 10:
        errors.append(f"evidência mantida ignorada pelo git: +{len(ignored_kept) - 10} ficheiros")

    if relative_only_missing:
        print(f"AVISO: {len(relative_only_missing)} citação(ões) em forma relativa sem "
              "arquivo na árvore (consulte docs/reports/evidence/README.md)")
    if not store.is_dir():
        print("NOT_AVAILABLE: artifacts/evidence-store (gitignore) ausente "
              "— cobertura da bolsa verificada apenas localmente")
    if store.is_dir():
        rows = read_manifest(manifest_path) if manifest_path.is_file() else [] if manifest_path.is_file() else []
        covered = {row["store_relpath"] for row in rows}
        for row in rows:
            if not (store / row["store_relpath"]).is_file():
                errors.append(f"blob ausente na bolsa: {row['store_relpath']}")
        blob_files = [p for p in store.rglob("*")
                      if p.is_file() and p.name != MANIFEST_NAME]
        for path in blob_files:
            if path.relative_to(store).as_posix() not in covered:
                errors.append("blob sem linha no manifesto: "
                              + path.relative_to(store).as_posix())
        if summary.get("inventory") and summary["inventory"] != inventory_counts(store, rows):
            errors.append("inventory do STORE-SUMMARY.json não corresponde à bolsa")
        blob_rows = [r for r in rows if r["kind"] == "file"]
        if blob_rows:
            step = max(1, len(blob_rows) // max(1, samples))
            for row in blob_rows[::step][:samples]:
                blob = store / row["store_relpath"]
                if not blob.is_file():
                    errors.append(f"blob ausente na bolsa: {row['store_relpath']}")
                elif sha256_file(blob) != row["sha256"]:
                    errors.append(f"blob corrompido na bolsa: {row['store_relpath']}")
    return errors


def verify(root: Path = ROOT) -> list[str]:
    """Recompute every stored hash; slow but complete."""
    store = root / "artifacts" / "evidence-store"
    manifest_path = store / MANIFEST_NAME
    if not manifest_path.is_file():
        return [f"{MANIFEST_NAME} ausente em {store}"]
    errors: list[str] = []
    for row in read_manifest(manifest_path):
        blob = store / row["store_relpath"]
        if not blob.is_file():
            errors.append(f"blob ausente: {row['store_relpath']} ({row['original_path']})")
            continue
        if row["kind"] == "file" and sha256_file(blob) != row["sha256"]:
            errors.append(f"hash divergente: {row['store_relpath']}")
        elif row["kind"] == "symlink":
            target = blob.read_text(encoding="utf-8")
            if sha256_bytes(target.encode("utf-8")) != row["sha256"]:
                errors.append(f"hash divergente (symlink): {row['store_relpath']}")
    return errors


def restore(paths: list[str], root: Path = ROOT) -> int:
    store = root / "artifacts" / "evidence-store"
    manifest_path = store / MANIFEST_NAME
    if not manifest_path.is_file():
        print(f"FAIL: {MANIFEST_NAME} ausente", file=sys.stderr)
        return 1
    rows = {row["original_path"]: row for row in read_manifest(manifest_path)}
    wanted = paths or sorted(rel for rel in rows if rel != "-")
    failures = 0
    for rel in wanted:
        row = rows.get(rel)
        if row is None:
            print(f"FAIL: não consta no manifesto: {rel}", file=sys.stderr)
            failures += 1
            continue
        blob = store / row["store_relpath"]
        if not blob.is_file():
            print(f"FAIL: blob ausente: {row['store_relpath']}", file=sys.stderr)
            failures += 1
            continue
        digest = sha256_bytes(blob.read_bytes()) if row["kind"] == "symlink" else sha256_file(blob)
        if digest != row["sha256"]:
            print(f"FAIL: hash do blob divergente: {row['store_relpath']}", file=sys.stderr)
            failures += 1
            continue
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            target.unlink()
        if row["kind"] == "symlink":
            os.symlink(blob.read_text(encoding="utf-8"), target)
        else:
            shutil.copyfile(blob, target)
            print(f"restored: {rel}")
    return 1 if failures else 0


def stat_summary(root: Path = ROOT) -> int:
    summary = _load_summary(root)
    if summary is None:
        print("no summary")
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("apply")
    sub.add_parser("relink")
    sub.add_parser("check")
    sub.add_parser("verify")
    sub.add_parser("stat")
    restore_parser = sub.add_parser("restore")
    restore_parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)

    if args.command == "apply":
        return apply()
    if args.command == "relink":
        return relink()
    if args.command == "verify":
        errors = verify()
    elif args.command == "check":
        errors = check()
    elif args.command == "stat":
        return stat_summary()
    else:
        return restore(args.paths)

    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    if args.command == "check":
        print("PASS: evidência citada presente e layout conforme a política AUD07-18")
    else:
        print("PASS: todos os hashes da bolsa conferem")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
