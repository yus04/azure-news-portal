"""HTML 抽出と画像候補選別のテスト。"""

from __future__ import annotations

from newsproc.config import ImageSettings
from newsproc.htmlx import ImageCandidate, extract_page
from newsproc.images import score_candidate, select_image_candidates

SAMPLE_HTML = """
<!doctype html>
<html>
  <head>
    <title>Fallback title</title>
    <meta property="og:title" content="Serverless GPUs are now GA" />
    <meta property="og:description" content="GPU workloads scale to zero." />
    <meta property="og:image" content="/assets/hero-architecture.png" />
    <meta name="twitter:image" content="https://cdn.example.com/twitter-card.png" />
    <link rel="canonical" href="https://azure.example.com/updates/gpu-ga" />
    <script>window.tracking = 'evil';</script>
    <style>.x{color:red}</style>
  </head>
  <body onload="steal()">
    <nav><a href="/home">Home</a></nav>
    <article>
      <p>Serverless GPUs in Azure Container Apps are now generally available for production workloads.</p>
      <p>Applications scale to zero when idle and scale out automatically when new requests arrive.</p>
      <p>Billing is per second of GPU usage, which reduces the cost of bursty inference workloads.</p>
      <img src="/assets/diagram-architecture.png" alt="Architecture diagram" width="1200" height="630" />
      <img src="/assets/logo.png" alt="Company logo" width="64" height="64" />
      <img src="https://tracker.example.com/pixel.gif" alt="" width="1" height="1" />
    </article>
    <footer><p>footer text</p></footer>
    <iframe src="https://evil.example.com"></iframe>
  </body>
</html>
"""


class TestExtractPage:
    def test_extracts_metadata_and_text(self) -> None:
        page = extract_page(SAMPLE_HTML, "https://azure.example.com/updates/gpu-ga")

        assert page.title == "Serverless GPUs are now GA"
        assert page.description == "GPU workloads scale to zero."
        assert page.canonical_url == "https://azure.example.com/updates/gpu-ga"
        assert "generally available" in page.text
        assert "footer text" not in page.text
        assert "Home" not in page.text

    def test_removes_dangerous_content(self) -> None:
        page = extract_page(SAMPLE_HTML, "https://azure.example.com/updates/gpu-ga")
        assert "window.tracking" not in page.text
        assert "evil.example.com" not in page.text

    def test_collects_image_candidates_with_absolute_urls(self) -> None:
        page = extract_page(SAMPLE_HTML, "https://azure.example.com/updates/gpu-ga")
        urls = [image.url for image in page.images]

        assert "https://azure.example.com/assets/hero-architecture.png" in urls
        assert "https://cdn.example.com/twitter-card.png" in urls
        assert "https://azure.example.com/assets/diagram-architecture.png" in urls
        assert page.images[0].origin == "og"

    def test_handles_empty_html(self) -> None:
        page = extract_page("", "https://example.com/")
        assert page.text == ""
        assert page.images == []


class TestImageSelection:
    def setup_method(self) -> None:
        self.settings = ImageSettings()

    def test_rejects_logos_icons_and_trackers(self) -> None:
        for url in [
            "https://example.com/assets/logo.png",
            "https://example.com/favicon.ico",
            "https://tracker.example.com/pixel.gif",
            "https://example.com/avatar/user.png",
            "https://ads.example.com/ads/banner.png",
        ]:
            assert score_candidate(ImageCandidate(url=url), self.settings) is None

    def test_rejects_small_images(self) -> None:
        candidate = ImageCandidate(url="https://example.com/x.png", width=80, height=40)
        assert score_candidate(candidate, self.settings) is None

    def test_rejects_svg_and_ico(self) -> None:
        assert score_candidate(ImageCandidate(url="https://example.com/a.svg"), self.settings) is None

    def test_prefers_open_graph_image(self) -> None:
        candidates = [
            ImageCandidate(url="https://example.com/body.png", origin="content", position=5),
            ImageCandidate(url="https://example.com/og.png", origin="og"),
        ]
        selected = select_image_candidates(candidates, self.settings)
        assert selected[0].candidate.url == "https://example.com/og.png"
        assert selected[0].role == "hero"

    def test_boosts_diagrams(self) -> None:
        diagram = score_candidate(
            ImageCandidate(url="https://example.com/architecture-diagram.png", origin="content"),
            self.settings,
        )
        plain = score_candidate(ImageCandidate(url="https://example.com/photo.png", origin="content"), self.settings)
        assert diagram is not None and plain is not None
        assert diagram.score > plain.score
        assert diagram.role == "diagram"

    def test_deduplicates_by_url(self) -> None:
        candidates = [
            ImageCandidate(url="https://example.com/a.png?w=100", origin="content"),
            ImageCandidate(url="https://example.com/a.png?w=200", origin="content"),
        ]
        assert len(select_image_candidates(candidates, self.settings)) == 1

    def test_limits_candidate_pool(self) -> None:
        candidates = [ImageCandidate(url=f"https://example.com/img{i}.png", origin="content") for i in range(50)]
        selected = select_image_candidates(candidates, self.settings)
        assert len(selected) <= self.settings.max_images * 3
