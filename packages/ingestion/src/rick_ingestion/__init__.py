"""Canonical ingestion package — validated pipeline as platform capability."""

from rick_ingestion.chunking import (
    CHUNKER_VERSION,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP,
    ChunkPlan,
    ChunkingStrategy,
    RecursiveChunkingStrategy,
)
from rick_ingestion.jobs import (
    DEFAULT_MAX_JOBS,
    MAX_HEARTBEATS,
    PERMANENT_ERROR_CODES,
    TERMINAL_STATES,
    TRANSIENT_ERROR_CODES,
    IngestionJob,
    InvalidTransitionError,
    is_retryable,
)
from rick_ingestion.parsers import (
    MAX_FILE_BYTES,
    PARSER_VERSION,
    ControlledPdfParser,
    DocxParser,
    DocumentParser,
    MarkdownParser,
    ParseError,
    ParsedDocument,
    ParsedPage,
    TxtParser,
    UnsupportedFormatError,
    generated_storage_name,
    parser_for,
    sanitize_display_filename,
    validate_file,
)
from rick_ingestion.pipeline import EmbeddingProvider, IngestionService, VectorStore
from rick_ingestion.admission import (
    ALLOWED_OPERATIONS,
    ALLOWED_SOURCE_TYPES,
    InvalidChecksumError,
    InvalidUploadFieldError,
    InvalidUploadSizeError,
    MAX_TOKEN_LENGTH,
    MAX_UPLOAD_BYTES,
    ObjectScopeLike,
    UnsupportedOperationError,
    UnsupportedSourceTypeError,
    UploadJobEnvelope,
    UploadJobEnvelopeError,
    UploadJobScope,
)

__all__ = [
    "CHUNKER_VERSION", "DEFAULT_CHUNK_SIZE", "DEFAULT_OVERLAP",
    "DEFAULT_MAX_JOBS", "MAX_FILE_BYTES", "MAX_HEARTBEATS", "PARSER_VERSION", "PERMANENT_ERROR_CODES",
    "TERMINAL_STATES", "TRANSIENT_ERROR_CODES",
    "ChunkPlan", "ChunkingStrategy", "ControlledPdfParser", "DocxParser",
    "DocumentParser", "EmbeddingProvider", "IngestionJob", "IngestionService",
    "InvalidTransitionError", "MarkdownParser", "ParseError", "ParsedDocument",
    "ParsedPage", "TxtParser", "UnsupportedFormatError", "VectorStore",
    "generated_storage_name", "is_retryable", "parser_for",
    "sanitize_display_filename", "validate_file",
    "ALLOWED_OPERATIONS", "ALLOWED_SOURCE_TYPES", "InvalidChecksumError",
    "InvalidUploadFieldError", "InvalidUploadSizeError", "MAX_TOKEN_LENGTH",
    "MAX_UPLOAD_BYTES", "ObjectScopeLike", "UnsupportedOperationError",
    "UnsupportedSourceTypeError", "UploadJobEnvelope", "UploadJobEnvelopeError",
    "UploadJobScope",
]
