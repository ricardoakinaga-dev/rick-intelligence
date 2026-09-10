# File-ingestion security boundary

`packages/ingestion` treats an uploaded file as hostile input. The public
`validate_file(path, max_bytes=...)` call remains available and still returns
`None` on success; its optional `declared_mime` and `limits` arguments tighten
the same boundary without requiring existing callers to change.

Validation is fail-closed:

- Only `.pdf`, `.docx`, `.md`, and `.txt` are accepted.
- A PDF must begin with the PDF magic header. A DOCX must be a ZIP container
  containing both `[Content_Types].xml` and `word/document.xml`. Text files
  must not contain NUL bytes, an obvious binary signature, or an excessive
  control-byte stream.
- UTF-8 is the only accepted text encoding. Invalid byte sequences are
  rejected with a bounded `validation_error`; parsers never fall back to a
  permissive single-byte decoding that could silently change document text.
- A supplied MIME value is normalized by removing parameters and must belong
  to the extension allowlist. Markdown accepts `text/markdown` and
  `text/plain`; text accepts `text/plain`; PDF accepts `application/pdf`; and
  DOCX accepts its official OOXML type or `application/zip` after the OOXML
  container check succeeds.
- Missing files, directories, symlinks, empty files, malformed containers,
  encrypted ZIP members, duplicate member names, archive links, traversal
  names, and inconsistent decompression sizes are rejected with a bounded
  `ParseError` code. Exception details and attacker-controlled paths are not
  returned in those errors.

The default ceilings are 50 MiB for the file, 8,000,000 decoded text
characters, 10,000 PDF pages, 100,000 Markdown sections, 512 ZIP members,
20 MiB for one decompressed member, 100 MiB for total decompressed DOCX
members, and a 1,000:1 compressed-to-decompressed ratio. `ParserLimits` can
only lower these package ceilings. ZIP members are streamed through
`zipfile` under the member and total budgets; the package never extracts them
to a user-controlled filesystem path.

`normalize_filename` is a metadata-only basename normalizer. It applies NFKC,
decodes up to two percent-encoding layers, handles both slash conventions,
removes control and bidi characters, and removes Windows alias suffixes. The
legacy `sanitize_display_filename` keeps its lossy display behavior. A caller
that needs one safe path segment must call `validate_filename`; generated
storage names accept only the four known suffixes and contain no user filename.

Built-in parser loops use a cooperative 30-second deadline, bounded reads, and
page or section checkpoints. `ProcessParserRunner` is the production runner:
it starts a fresh `spawn` child, applies advisory CPU/memory limits, enforces a
parent wall-clock deadline and terminates the child process group on timeout.
The child response uses a versioned JSON-only envelope; the parent never
unpickles parser-controlled bytes, and the serialized response remains capped
at 32 MiB.
The external composition rejects a custom runner that does not advertise both
`production_safe` and `process_isolated`. The default
`InProcessParserRunner` remains available for local compatibility and converts
a late or malformed result into a failed parse.

The process boundary is still subject to deployment cgroups, host policy and
live parser-library validation. The worker deletes its temporary source file
after every attempt; file, archive, text and page budgets fail closed before
and between bounded operations.
