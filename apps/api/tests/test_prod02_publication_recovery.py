from services.job_journal import JobJournal
from services.ingestion_service import IngestionApplicationService
from rick_ingestion import IngestionService
from rick_knowledge import SQLiteKnowledgeStore
from rick_retrieval import SQLiteVectorStore, DeterministicHashEmbedding


SCOPE = dict(tenant_id='t', workspace_id='w', collection_id='c')


class NoReplayEmbedding(DeterministicHashEmbedding):
    def embed(self, texts):
        raise AssertionError('restart must not replay committed publication')


def test_journal_retains_publication_authority(tmp_path):
    path = tmp_path / 'private' / 'jobs.sqlite'
    journal = JobJournal(path)
    job = dict(job_id='recover', tenant_id='t', workspace_id='w', collection_id='c',
               document_id='doc', status='verifying', stage='verifying',
               metadata={'publication_outcome_unknown': True, 'publication_attempt': 'a' * 32})
    journal.upsert(job)
    journal.close()
    journal = JobJournal(path)
    try:
        recovered = journal.get('recover')
        assert recovered['metadata']['publication_outcome_unknown'] is True
        assert recovered['metadata']['publication_attempt'] == 'a' * 32
    finally:
        journal.close()


def test_api_restart_adopts_commit_even_without_staged_source(tmp_path):
    knowledge_path = tmp_path / 'knowledge.sqlite'
    vectors_path = tmp_path / 'vectors.sqlite'
    knowledge = SQLiteKnowledgeStore(knowledge_path)
    vectors = SQLiteVectorStore(vectors_path)
    canonical = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
    staging = tmp_path / 'staging'
    staging.mkdir()
    source = staging / 'guide.txt'
    source.write_text('Commit survived pre-ack crash. ' * 80)
    job = canonical.ingest(source, **SCOPE, job_id='api-restart')
    assert job.status == 'published'
    job.status = job.stage = 'verifying'
    job.finished_at = None
    job.metadata['publication_outcome_unknown'] = True
    journal = JobJournal(tmp_path / 'private' / 'jobs.sqlite')
    journal.upsert(job, source_path=str(source), display_filename='guide.txt')
    journal.close()
    knowledge.close()
    vectors.close()
    source.unlink()
    knowledge = SQLiteKnowledgeStore(knowledge_path)
    vectors = SQLiteVectorStore(vectors_path)
    journal = JobJournal(tmp_path / 'private' / 'jobs.sqlite')
    service = IngestionApplicationService(
        IngestionService(knowledge=knowledge, vectors=vectors, embeddings=NoReplayEmbedding()),
        staging_root=staging, job_journal=journal)
    try:
        public = service.get_status('api-restart', tenant_id='t', workspace_id='w', allowed_collection_ids=['c'])
        assert public['status'] == 'published'
        assert service.get_status('api-restart', tenant_id='foreign', workspace_id='w', allowed_collection_ids=['c']) is None
        assert public['document_id'] == job.document_id
        assert 'publication_attempt' not in public['metadata']
        assert journal.get('api-restart')['status'] == 'published'
        assert knowledge.get_document(job.document_id).status == 'published'
        assert vectors.all_points()
    finally:
        service.shutdown(wait=True)
        knowledge.close()
        vectors.close()


def test_api_journal_restart_ready_attempt_metadata_and_retry_budget(tmp_path):
    import pytest
    db_path=tmp_path/'knowledge.sqlite';vec_path=tmp_path/'vectors.sqlite';journal_path=tmp_path/'private'/'jobs.sqlite'
    knowledge=SQLiteKnowledgeStore(db_path);vectors=SQLiteVectorStore(vec_path)
    canonical=IngestionService(knowledge=knowledge,vectors=vectors,embeddings=DeterministicHashEmbedding())
    staging=tmp_path/'staging';staging.mkdir();source=staging/'ready.txt';source.write_text('Ready journal recovery. '*80)
    real=knowledge.set_document_status
    def die(doc,status):
        if status=='published': raise SystemExit('before commit')
        return real(doc,status)
    knowledge.set_document_status=die
    with pytest.raises(SystemExit): canonical.ingest(source,**SCOPE,job_id='ready-journal')
    job=canonical.get_status('ready-journal')
    authority=knowledge.get_publication(job.job_id,**SCOPE)['job_snapshot']
    # The journal is a stale projection; durable receipt attempt/start facts win.
    job.created_at=10;job.started_at=11
    job.metadata.update(durability='local-sqlite',restart_recovery=True,publication_outcome_unknown=True)
    journal=JobJournal(journal_path);journal.upsert(job,source_path=str(source),retry_count=2);journal.close()
    knowledge.close();vectors.close();source.unlink()
    knowledge=SQLiteKnowledgeStore(db_path);vectors=SQLiteVectorStore(vec_path);journal=JobJournal(journal_path)
    app=IngestionApplicationService(IngestionService(knowledge=knowledge,vectors=vectors,embeddings=NoReplayEmbedding()),staging_root=staging,job_journal=journal)
    try:
        public=app.get_status('ready-journal',tenant_id='t',workspace_id='w',allowed_collection_ids=['c'])
        assert public['status']=='published'
        assert (public['attempt'],public['created_at'],public['started_at'])==tuple(authority[k] for k in ('attempt','created_at','started_at'))
        saved=journal.get('ready-journal')
        assert saved['retry_count']==2 and saved['metadata']['durability']=='local-sqlite' and saved['metadata']['restart_recovery']
    finally: app.shutdown(wait=True);knowledge.close();vectors.close();journal.close()


def test_committed_authority_repairs_stale_journal_token_and_facts(tmp_path):
    from copy import deepcopy
    knowledge=SQLiteKnowledgeStore(tmp_path/'authority.sqlite');vectors=SQLiteVectorStore(tmp_path/'vectors.sqlite')
    staging=tmp_path/'staging';staging.mkdir();path=staging/'source.txt';path.write_text('Committed projection repair. '*80)
    canonical=IngestionService(knowledge=knowledge,vectors=vectors,embeddings=DeterministicHashEmbedding())
    winner=canonical.ingest(path,**SCOPE,job_id='stale-journal')
    before=deepcopy(knowledge.get_publication(winner.job_id,**SCOPE))
    stale=deepcopy(winner);stale.metadata['publication_attempt']='obsolete'
    stale.status=stale.stage='verifying';stale.attempt=7
    stale.created_at=10.;stale.started_at=11.;stale.finished_at=None
    journal=JobJournal(tmp_path/'private/jobs.sqlite')
    journal.upsert(stale,source_path=str(path),retry_count=2);journal.close();path.unlink()
    journal=JobJournal(tmp_path/'private/jobs.sqlite')
    app=IngestionApplicationService(IngestionService(knowledge=knowledge,vectors=vectors,embeddings=NoReplayEmbedding()),staging_root=staging,job_journal=journal)
    try:
        public=app.get_status(winner.job_id,tenant_id='t',workspace_id='w',allowed_collection_ids=['c'])
        assert public['status']=='published' and public['attempt']==winner.attempt
        saved=journal.get(winner.job_id)
        assert saved['metadata']['publication_attempt']==winner.metadata['publication_attempt']
        assert saved['retry_count']==2
        assert (saved['attempt'],saved['created_at'],saved['started_at'],saved['finished_at'])==tuple(getattr(winner,k) for k in ('attempt','created_at','started_at','finished_at'))
        assert knowledge.get_publication(winner.job_id,**SCOPE)==before
    finally:
        app.shutdown(wait=True);journal.close();knowledge.close();vectors.close()
