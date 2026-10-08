-- Read-only inventory for 0008. Run against an authorized snapshot before --apply.
-- Each count must be zero. Only aggregate counts are returned; no row content leaves the database.
SELECT 'chunks_document_scope' AS check_name, COUNT(*) AS incompatible_rows
FROM rick_chunks AS child
LEFT JOIN rick_documents AS parent ON parent.document_id = child.document_id
WHERE parent.document_id IS NULL
   OR (parent.tenant_id, parent.workspace_id, parent.collection_id)
      IS DISTINCT FROM (child.tenant_id, child.workspace_id, child.collection_id)
UNION ALL
SELECT 'jobs_document_scope', COUNT(*)
FROM rick_ingestion_jobs AS child
LEFT JOIN rick_documents AS parent ON parent.document_id = child.document_id
WHERE child.document_id IS NOT NULL
  AND (parent.document_id IS NULL
       OR (parent.tenant_id, parent.workspace_id, parent.collection_id)
          IS DISTINCT FROM (child.tenant_id, child.workspace_id, child.collection_id))
UNION ALL
SELECT 'conversations_collection_scope', COUNT(*)
FROM rick_conversations AS child
LEFT JOIN rick_collections AS parent
  ON parent.collection_id = child.collection_id
 AND parent.tenant_id = child.tenant_id
 AND parent.workspace_id = child.workspace_id
WHERE child.collection_id IS NOT NULL AND parent.collection_id IS NULL
UNION ALL
SELECT 'messages_conversation_scope', COUNT(*)
FROM rick_messages AS child
LEFT JOIN rick_conversations AS parent ON parent.conversation_id = child.conversation_id
WHERE parent.conversation_id IS NULL
   OR (parent.tenant_id, parent.workspace_id, parent.user_id)
      IS DISTINCT FROM (child.tenant_id, child.workspace_id, child.user_id);
