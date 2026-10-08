from copy import deepcopy

import pytest

from rick_ingestion import IngestionService
from rick_knowledge import SQLiteKnowledgeStore
from rick_knowledge.fencing import OwnershipLostError
from rick_retrieval import DeterministicHashEmbedding, SQLiteVectorStore


SCOPE = dict(tenant_id='t', workspace_id='w', collection_id='c')


class UncertainKnowledge(SQLiteKnowledgeStore):
    unavailable = False
    commit = True

    def get_publication(self, *args, **kwargs):
        if self.unavailable:
            raise RuntimeError('outcome unavailable')
        return super().get_publication(*args, **kwargs)

    def get_document(self, *args, **kwargs):
        if self.unavailable:
            raise RuntimeError('document outcome unavailable')
        return super().get_document(*args, **kwargs)

    def set_document_status(self, document_id, status):
        if status == 'published':
            if self.commit:
                super().set_document_status(document_id, status)
            self.unavailable = True
            raise RuntimeError('publication acknowledgement lost')
        return super().set_document_status(document_id, status)


class NoReplayEmbedding(DeterministicHashEmbedding):
    def embed(self, texts):
        raise AssertionError('recovery must not replay embeddings')


def prepare(tmp_path, *, commit=True):
    knowledge = UncertainKnowledge(tmp_path / 'knowledge.sqlite')
    knowledge.commit = commit
    vectors = SQLiteVectorStore(tmp_path / 'vectors.sqlite')
    ingestion = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
    path = tmp_path / 'guide.txt'
    path.write_text('Durable publication authority. ' * 80)
    job = ingestion.ingest(path, **SCOPE, job_id='restart')
    assert job.status == 'verifying'
    assert job.metadata['publication_outcome_unknown'] is True
    return knowledge, vectors, ingestion, path, job


def test_restart_recovers_committed_authority_without_replaying(tmp_path):
    knowledge, vectors, ingestion, path, job = prepare(tmp_path)
    knowledge.unavailable = False
    before = deepcopy((knowledge.get_document(job.document_id), knowledge.get_chunks(job.document_id), vectors.all_points()))
    knowledge.close()
    vectors.close()
    knowledge = SQLiteKnowledgeStore(tmp_path / 'knowledge.sqlite')
    vectors = SQLiteVectorStore(tmp_path / 'vectors.sqlite')
    try:
        restarted = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=NoReplayEmbedding())
        result = restarted.recover_publication('restart', **SCOPE, snapshot=job)
        assert result.status == 'published'
        assert result.metadata['publication_attempt'] == job.metadata['publication_attempt']
        assert (knowledge.get_document(job.document_id), knowledge.get_chunks(job.document_id), vectors.all_points()) == before
        path.unlink()
        assert restarted.ingest(path, **SCOPE, job_id='restart').status == 'published'
    finally:
        knowledge.close()
        vectors.close()


def test_restart_pending_cancel_and_unavailable_outcome_keep_authority(tmp_path):
    knowledge, vectors, ingestion, path, job = prepare(tmp_path, commit=False)
    knowledge.unavailable = False
    restarted = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=NoReplayEmbedding())
    original_get = knowledge.get_document
    reads = []
    def unavailable(*args, **kwargs):
        reads.append(1)
        raise RuntimeError('document unavailable')
    knowledge.get_document = unavailable
    try:
        result = restarted.recover_publication('restart', **SCOPE, snapshot=job)
        assert len(reads) == 3
        assert result.status == 'verifying'
        assert restarted.cancel('restart') is True
        assert result.status == 'verifying' and result.cancel_requested
        assert knowledge.get_publication('restart', **SCOPE)['cancel_requested']
        assert restarted.recover_publication('restart', **SCOPE).status == 'verifying'
        knowledge.get_document = original_get
        # Discard every closure and cancellation flag before resolving.
        restarted = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=NoReplayEmbedding())
        result = restarted.recover_publication('restart', **SCOPE)
        assert result.status == 'cancelled'
        assert knowledge.get_document(result.document_id).status != 'published'
        assert vectors.all_points() == []
        assert knowledge.get_publication('restart', **SCOPE)['outcome'] == 'cancelled'
    finally:
        knowledge.close()
        vectors.close()


def test_restart_stale_attempt_and_foreign_scope_do_not_overwrite_winner(tmp_path):
    knowledge, vectors, ingestion, path, job = prepare(tmp_path, commit=False)
    knowledge.unavailable = False
    # A new attempt can win while the old process cannot read its outcome.
    knowledge.set_document_status = lambda doc, status: SQLiteKnowledgeStore.set_document_status(knowledge, doc, status)
    winner_service = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
    winner = winner_service.ingest(path, **SCOPE, job_id='winner')
    before = deepcopy((knowledge.get_document(winner.document_id), vectors.all_points()))
    restarted = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=NoReplayEmbedding())
    try:
        assert restarted.recover_publication('restart', tenant_id='foreign', workspace_id='w', collection_id='c') is None
        stale = deepcopy(job)
        stale.metadata['publication_attempt'] = 'stale'
        with pytest.raises(OwnershipLostError):
            restarted.recover_publication('restart', **SCOPE, snapshot=stale)
        assert restarted.recover_publication('restart', **SCOPE, snapshot=job).status == 'failed'
        assert (knowledge.get_document(winner.document_id), vectors.all_points()) == before
    finally:
        knowledge.close()
        vectors.close()


@pytest.mark.parametrize('kind', ['memory', 'sqlite'])
def test_cancellation_request_cannot_be_lost_by_stale_resolution(tmp_path, kind):
    from rick_ingestion.jobs import IngestionJob
    from rick_knowledge import InMemoryKnowledgeStore
    knowledge = InMemoryKnowledgeStore() if kind == 'memory' else SQLiteKnowledgeStore(tmp_path / 'cancel.sqlite')
    job = IngestionJob(**SCOPE, job_id='cancel', document_id='doc', metadata={'publication_attempt': 'a' * 32})
    try:
        knowledge.begin_publication(job)
        stale = knowledge.get_publication('cancel', **SCOPE)
        knowledge.request_publication_cancel(job)
        resolved = knowledge.resolve_publication(stale, 'failed')
        assert resolved['outcome'] == 'cancelled'
        assert resolved['cancel_requested']
    finally:
        if kind == 'sqlite':
            knowledge.close()


def test_committed_receipt_survives_later_winner_without_overwriting_it(tmp_path):
    knowledge, vectors, old_service, path, old_job = prepare(tmp_path)
    knowledge.unavailable = False
    knowledge.set_document_status = lambda doc, status: SQLiteKnowledgeStore.set_document_status(knowledge, doc, status)
    knowledge.set_document_status(old_job.document_id, 'unpublished')
    winner = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding()).ingest(
        path, **SCOPE, job_id='later-winner')
    assert winner.status == 'published'
    assert winner.metadata['publication_attempt'] != old_job.metadata['publication_attempt']
    before = deepcopy((knowledge.get_document(winner.document_id), knowledge.get_chunks(winner.document_id), vectors.all_points()))
    restarted = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=NoReplayEmbedding())
    try:
        assert restarted.recover_publication('restart', **SCOPE, snapshot=old_job).status == 'published'
        assert (knowledge.get_document(winner.document_id), knowledge.get_chunks(winner.document_id), vectors.all_points()) == before
    finally:
        knowledge.close()
        vectors.close()


def test_attempt_change_between_receipt_read_and_effect_fence_is_rejected(tmp_path):
    knowledge, vectors, old_service, path, old_job = prepare(tmp_path, commit=False)
    knowledge.unavailable = False
    knowledge.set_document_status = lambda doc, status: SQLiteKnowledgeStore.set_document_status(knowledge, doc, status)
    real_get = knowledge.get_publication
    reads = 0
    winner = []
    before = []
    def takeover(*args, **kwargs):
        nonlocal reads
        reads += 1
        if reads == 1:
            stale_receipt = real_get(*args, **kwargs)
            # Take over after the initial receipt read, before the recovery
            # transaction starts. A reentrant takeover inside the same SQLite
            # transaction would roll back with that transaction.
            knowledge.get_publication = real_get
            # A ready same-attempt intent now resumes, so explicitly resolve
            # the original attempt before simulating a genuinely new owner.
            knowledge.resolve_publication(real_get('restart', **SCOPE), 'failed')
            winner.append(IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding()).ingest(
                path, **SCOPE, job_id='restart'))
            before.append(deepcopy((knowledge.get_document(winner[0].document_id), knowledge.get_chunks(winner[0].document_id), vectors.all_points())))
            return stale_receipt
        return real_get(*args, **kwargs)
    knowledge.get_publication = takeover
    restarted = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=NoReplayEmbedding())
    try:
        with pytest.raises(OwnershipLostError):
            restarted.recover_publication('restart', **SCOPE, snapshot=old_job)
        assert winner[0].status == 'published'
        assert restarted.get_status('restart').metadata['publication_attempt'] != winner[0].metadata['publication_attempt']
        assert (knowledge.get_document(winner[0].document_id), knowledge.get_chunks(winner[0].document_id), vectors.all_points()) == before[0]
    finally:
        knowledge.close()
        vectors.close()
