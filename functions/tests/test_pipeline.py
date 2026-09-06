"""Event Grid イベントから Cosmos DB 保存までの統合テスト。"""

from __future__ import annotations

import json
from typing import Any

import pytest
from newsproc.fetcher import FetchError
from newsproc.foundry import FoundryError
from newsproc.pipeline import ArticlePipeline, TransientProcessingError, parse_blob_created_event

from tests.conftest import FakeGenerator, blob_created_event, make_fetch_result

pytestmark = pytest.mark.integration

ARTICLE_HTML = """
<html><head>
  <meta property="og:image" content="https://cdn.example.com/hero-architecture.png" />
</head><body><article>
  <p>Serverless GPUs in Azure Container Apps are generally available today for all customers.</p>
  <p>Workloads scale to zero when idle, and billing is per second of GPU usage.</p>
  <p>NVIDIA A100 and T4 profiles are offered in selected Azure regions worldwide.</p>
</article></body></html>
"""


def make_pipeline(settings, blob_store, repository, generator, fetch_fn=None) -> ArticlePipeline:
    return ArticlePipeline(
        settings=settings,
        blob_store=blob_store,
        repository=repository,
        generator=generator,
        fetch_fn=fetch_fn or (lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("fetch not expected"))),
    )


def seed_blob(blob_store, payload: dict[str, Any], blob_name: str = "2026/08/28/article.json") -> None:
    blob_store.put("raw-articles", blob_name, payload)


class TestEventParsing:
    def test_parses_blob_created_event(self) -> None:
        parsed = parse_blob_created_event(blob_created_event())
        assert parsed.container == "raw-articles"
        assert parsed.blob_name == "2026/08/28/article.json"
        assert parsed.etag == "0x8D000000000000"

    def test_decodes_url_encoded_paths(self) -> None:
        event = blob_created_event(blob_name="2026/08/28/a%20b.json")
        assert parse_blob_created_event(event).blob_name == "2026/08/28/a b.json"

    def test_rejects_other_event_types(self) -> None:
        event = blob_created_event()
        event["eventType"] = "Microsoft.Storage.BlobDeleted"
        with pytest.raises(ValueError):
            parse_blob_created_event(event)


class TestEventFiltering:
    def test_ignores_other_containers(self, settings, blob_store, repository, generator) -> None:
        pipeline = make_pipeline(settings, blob_store, repository, generator)
        outcome = pipeline.handle_event(blob_created_event(container="article-images"))
        assert outcome.status == "skipped"
        assert outcome.reason == "container_not_monitored"

    def test_ignores_non_json_blobs(self, settings, blob_store, repository, generator) -> None:
        pipeline = make_pipeline(settings, blob_store, repository, generator)
        outcome = pipeline.handle_event(blob_created_event(blob_name="2026/08/28/image.png"))
        assert outcome.status == "skipped"
        assert outcome.reason == "not_json"

    def test_ignores_unsupported_event_type(self, settings, blob_store, repository, generator) -> None:
        pipeline = make_pipeline(settings, blob_store, repository, generator)
        event = blob_created_event()
        event["eventType"] = "Microsoft.Storage.BlobDeleted"
        assert pipeline.handle_event(event).status == "skipped"


class TestHappyPath:
    def test_stores_article_document(self, settings, blob_store, repository, generator, sample_input) -> None:
        seed_blob(blob_store, sample_input)
        pipeline = make_pipeline(settings, blob_store, repository, generator)

        outcome = pipeline.handle_event(blob_created_event())

        assert outcome.status == "succeeded"
        document = repository.articles[outcome.article_id]
        assert document["partitionKey"] == "2026-08"
        assert document["titleJa"] == generator.insights.title_ja
        assert document["processingStatus"] == "succeeded"
        assert document["processingVersion"] == "1.0.0"
        assert document["modelDeployment"] == "test-deployment"
        assert document["importanceRank"] == 3
        assert document["rawBlobPath"] == "raw-articles/2026/08/28/article.json"
        assert "container apps" in document["searchText"]
        assert generator.calls == 1

    def test_archives_body_to_blob_not_cosmos(self, settings, blob_store, repository, generator, sample_input) -> None:
        seed_blob(blob_store, sample_input)
        pipeline = make_pipeline(settings, blob_store, repository, generator)
        outcome = pipeline.handle_event(blob_created_event())

        document = repository.articles[outcome.article_id]
        assert document["contentBlobPath"] == f"article-content/{outcome.article_id}.txt"
        assert "bodyText" not in document
        assert ("article-content", f"{outcome.article_id}.txt") in blob_store.blobs

    def test_records_success_state(self, settings, blob_store, repository, generator, sample_input) -> None:
        seed_blob(blob_store, sample_input)
        make_pipeline(settings, blob_store, repository, generator).handle_event(blob_created_event())
        assert repository.states[-1]["status"] == "succeeded"


class TestIdempotency:
    def test_duplicate_event_is_skipped(self, settings, blob_store, repository, generator, sample_input) -> None:
        seed_blob(blob_store, sample_input)
        pipeline = make_pipeline(settings, blob_store, repository, generator)

        first = pipeline.handle_event(blob_created_event())
        second = pipeline.handle_event(blob_created_event())

        assert first.status == "succeeded"
        assert second.status == "skipped"
        assert second.reason == "duplicate_event"
        assert generator.calls == 1

    def test_unchanged_article_is_not_reprocessed(
        self, settings, blob_store, repository, generator, sample_input
    ) -> None:
        seed_blob(blob_store, sample_input)
        pipeline = make_pipeline(settings, blob_store, repository, generator)

        pipeline.handle_event(blob_created_event(event_id="event-1"))
        second = pipeline.handle_event(blob_created_event(event_id="event-2"))

        assert second.status == "skipped"
        assert second.reason == "unchanged"
        assert generator.calls == 1
        assert len(repository.articles) == 1

    def test_changed_article_is_reprocessed_without_duplicates(
        self, settings, blob_store, repository, generator, sample_input
    ) -> None:
        seed_blob(blob_store, sample_input)
        pipeline = make_pipeline(settings, blob_store, repository, generator)
        first = pipeline.handle_event(blob_created_event(event_id="event-1"))

        updated = dict(sample_input, summary="Updated summary with new details.")
        seed_blob(blob_store, updated)
        second = pipeline.handle_event(blob_created_event(event_id="event-2"))

        assert second.status == "succeeded"
        assert second.article_id == first.article_id
        assert len(repository.articles) == 1
        assert generator.calls == 2


class TestInvalidInput:
    def test_invalid_json_is_not_retried(self, settings, blob_store, repository, generator) -> None:
        blob_store.put("raw-articles", "2026/08/28/article.json", b"{not-json")
        pipeline = make_pipeline(settings, blob_store, repository, generator)

        outcome = pipeline.handle_event(blob_created_event())

        assert outcome.status == "failed"
        assert outcome.reason == "invalid_json"
        assert ("failed-articles", "2026/08/28/article.json.error.json") in blob_store.blobs
        assert generator.calls == 0

    def test_missing_required_fields_is_not_retried(self, settings, blob_store, repository, generator) -> None:
        blob_store.put("raw-articles", "2026/08/28/article.json", {"title": "no url"})
        pipeline = make_pipeline(settings, blob_store, repository, generator)

        outcome = pipeline.handle_event(blob_created_event())

        assert outcome.status == "failed"
        assert outcome.reason == "normalization_failed"

    def test_blob_download_failure_is_retriable(self, settings, blob_store, repository, generator) -> None:
        blob_store.download_error = RuntimeError("network down")
        pipeline = make_pipeline(settings, blob_store, repository, generator)

        with pytest.raises(TransientProcessingError):
            pipeline.handle_event(blob_created_event())


class TestExternalFailures:
    def test_original_fetch_failure_still_produces_article(
        self, settings_with_fetch, blob_store, repository, generator, sample_input
    ) -> None:
        def failing_fetch(*args, **kwargs):
            raise FetchError("timeout", category="timeout")

        seed_blob(blob_store, sample_input)
        pipeline = make_pipeline(settings_with_fetch, blob_store, repository, generator, fetch_fn=failing_fetch)

        outcome = pipeline.handle_event(blob_created_event())

        assert outcome.status == "succeeded"
        assert outcome.metrics["originalFetchError"] == "timeout"

    def test_image_failure_does_not_fail_article(
        self, settings_with_fetch, blob_store, repository, generator, sample_input
    ) -> None:
        calls: list[str] = []

        def fetch(url, fetch_settings, **kwargs):
            calls.append(url)
            if kwargs.get("allowed_content_types", ("text/html",))[0].startswith("image"):
                raise FetchError("image gone", category="http_4xx")
            return make_fetch_result(ARTICLE_HTML, url)

        seed_blob(blob_store, sample_input)
        pipeline = make_pipeline(settings_with_fetch, blob_store, repository, generator, fetch_fn=fetch)

        outcome = pipeline.handle_event(blob_created_event())

        assert outcome.status == "succeeded"
        assert outcome.metrics["imagesDownloaded"] == 0
        assert outcome.metrics["imagesFailed"] >= 1
        assert repository.articles[outcome.article_id]["imageAssets"] == []

    def test_transient_foundry_error_requests_retry(
        self, settings, blob_store, repository, sample_input
    ) -> None:
        seed_blob(blob_store, sample_input)
        generator = FakeGenerator(error=FoundryError("rate limited", category="transient"))
        pipeline = make_pipeline(settings, blob_store, repository, generator)

        with pytest.raises(TransientProcessingError):
            pipeline.handle_event(blob_created_event())

        stored = next(iter(repository.articles.values()))
        assert stored["processingStatus"] == "failed"
        assert stored["retryCount"] == 1
        assert stored["lastError"].startswith("FoundryError")

    def test_permanent_foundry_error_is_not_retried(self, settings, blob_store, repository, sample_input) -> None:
        seed_blob(blob_store, sample_input)
        generator = FakeGenerator(error=FoundryError("schema", category="schema"))
        pipeline = make_pipeline(settings, blob_store, repository, generator)

        outcome = pipeline.handle_event(blob_created_event())

        assert outcome.status == "failed"
        assert "FoundryError" in outcome.reason

    def test_poison_blob_stops_retrying_after_max(self, settings, blob_store, repository, sample_input) -> None:
        seed_blob(blob_store, sample_input)
        generator = FakeGenerator(error=FoundryError("rate limited", category="transient"))
        pipeline = make_pipeline(settings, blob_store, repository, generator)

        for index in range(settings.max_processing_retries):
            with pytest.raises(TransientProcessingError):
                pipeline.handle_event(blob_created_event(event_id=f"event-{index}"))

        outcome = pipeline.handle_event(blob_created_event(event_id="event-final"))
        assert outcome.status == "failed"

    def test_cosmos_write_failure_is_retriable(
        self, settings, blob_store, repository, generator, sample_input
    ) -> None:
        seed_blob(blob_store, sample_input)
        repository.upsert_error = RuntimeError("cosmos 503")
        pipeline = make_pipeline(settings, blob_store, repository, generator)

        with pytest.raises(TransientProcessingError):
            pipeline.handle_event(blob_created_event())


class TestImagePersistence:
    def test_stores_images_in_processed_container(
        self, settings_with_fetch, blob_store, repository, generator, sample_input, monkeypatch
    ) -> None:
        png = _tiny_png()
        monkeypatch.setattr("newsproc.images._probe_image", lambda data: (1200, 630, "png"))

        def fetch(url, fetch_settings, **kwargs):
            allowed = kwargs.get("allowed_content_types") or ("text/html",)
            if allowed[0].startswith("image"):
                from newsproc.fetcher import FetchResult

                return FetchResult(url=url, status_code=200, content_type="image/png", content=png)
            return make_fetch_result(ARTICLE_HTML, url)

        seed_blob(blob_store, sample_input)
        pipeline = make_pipeline(settings_with_fetch, blob_store, repository, generator, fetch_fn=fetch)

        outcome = pipeline.handle_event(blob_created_event())
        document = repository.articles[outcome.article_id]

        assert document["imageAssets"]
        first = document["imageAssets"][0]
        assert first["blobPath"].startswith("article-images/")
        assert first["altTextJa"]
        assert first["width"] == 1200
        assert any(upload["container"] == "article-images" for upload in blob_store.uploads)


def _tiny_png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def test_document_is_json_serializable(settings, blob_store, repository, generator, sample_input) -> None:
    seed_blob(blob_store, sample_input)
    outcome = make_pipeline(settings, blob_store, repository, generator).handle_event(blob_created_event())
    json.dumps(repository.articles[outcome.article_id], ensure_ascii=False)
