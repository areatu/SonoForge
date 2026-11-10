"""Small, dependency-free regression checks for the static landing page.

Run: python3 -m unittest discover -s site/tests -v
These tests intentionally do not import the Qt application or require Pillow.
"""

from __future__ import annotations

import ast
import re
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
LATEST = "https://github.com/areatu/SonoForge/releases/latest"
DOI = "10.5281/zenodo.21463212"
VERSION_DOI = "10.5281/zenodo.23000446"


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.cards = []
        self.card = None
        self.in_features = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.elements.append((tag, attrs))
        if tag == "section" and attrs.get("id") == "features":
            self.in_features = True
        if self.in_features and tag == "article":
            self.card = []
            self.cards.append(self.card)
        if tag == "img" and self.card is not None:
            self.card.append(attrs)

    def handle_endtag(self, tag):
        if tag == "article":
            self.card = None
        if tag == "section":
            self.in_features = False


class LandingPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (SITE / "index.html").read_text()
        cls.page = Page(cls.html)

    def test_experimental_tracking_is_not_advertised(self):
        for path in (SITE / "index.html", SITE / "tour.html",
                     ROOT / "README.md", ROOT / "README_RU.md"):
            with self.subTest(path=path):
                self.assertIsNone(re.search(r"\b(strain|ste|speckle)\b", path.read_text(), re.I))

    def test_both_platform_downloads_have_static_latest_links(self):
        links = {attrs.get("id"): attrs for tag, attrs in self.page.elements if tag == "a"}
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform):
                link = links[f"cta-download-{platform}"]
                self.assertEqual(link["href"], LATEST)
                self.assertNotIn("data-asset", link)  # the API must not replace this release-page link
        self.assertIn('class="cta cta-downloads"', self.html)
        for label in ("Download for Linux", "Download for Windows", "Скачать для Linux", "Скачать для Windows"):
            self.assertIn(label, self.html)

    def test_hero_facts_include_import_export_and_safe_sharing(self):
        facts = re.search(r'<ul class="facts".*?</ul>', self.html, re.S).group()
        self.assertEqual(facts.count("<li>"), 6)
        for value in ("MP4 · JPEG", ".dcm · MP4 · JPEG", 'lang="en"', 'lang="ru"'):
            self.assertIn(value, facts)
        self.assertIn("export clips and snapshots", facts)
        self.assertIn("экспорт видео и снимков", facts)
        self.assertIn("social media", self.html)
        self.assertIn("соцсетях", self.html)
        self.assertIn("patient-identifying information", self.html)

    def test_privacy_and_ci_claims_match_documented_behavior(self):
        for phrase in (
            "local DICOM cache", "локальный DICOM‑кэш", "normal exit by default",
            "обычном выходе", "opt-in in Presenter", "в Presenter — по выбору",
            "does not encrypt", "не шифрует", "reviewed before sharing",
            "проверять перед передачей", "TLS and certificate verification are configurable",
            "TLS и проверка сертификатов настраиваются", "Python 3.11–3.13",
            "For research and education only", "Только для исследований и обучения",
        ):
            self.assertIn(phrase, self.html)
        for stale in ("4400", "~77%", "no PHI is written", "персональные данные не пишутся", "100% local"):
            self.assertNotIn(stale, self.html)
        self.assertIn("combined coverage gate ≥80%", self.html)
        self.assertIn("порог общего покрытия в CI ≥80%", self.html)
        ci = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn("coverage report --fail-under=80", ci)

    def test_schematic_feature_previews_have_posters_and_bilingual_alt(self):
        previews = [attrs for tag, attrs in self.page.elements if tag == "img" and "data-feature-gif" in attrs]
        expected = {"cardiac", "doppler", "calibration", "segmentation", "pacs", "reports"}
        self.assertEqual(len(previews), len(expected))
        self.assertEqual({Path(img["data-feature-gif"]).stem for img in previews}, expected)
        for img in previews:
            self.assertEqual(img["src"], img["data-feature-gif"].replace(".gif", "-poster.jpg"))
            self.assertEqual(img["alt"], img["data-alt-en"])
            self.assertTrue(img["data-alt-ru"])
            self.assertEqual(img["loading"], "lazy")
            self.assertLess((SITE / img["data-feature-gif"]).stat().st_size, 300_000)
        self.assertIn('data-feature-motion hidden', self.html)
        js = (SITE / "app.js").read_text()
        self.assertIn("prefers-reduced-motion: reduce", js)
        self.assertIn('data-alt-" + lang', js)

    def test_current_screenshots_and_no_phantom_demos(self):
        self.assertIn("screenshots/lv-simpson.png", self.html)
        self.assertNotIn("media/preview.mp4", self.html)
        self.assertNotIn("media/presenter.mp4", self.html)
        self.assertNotIn("DICOM SR", self.html)

    def test_cff_keeps_current_version_and_distinct_dois(self):
        cff = (ROOT / "CITATION.cff").read_text()

        def scalar(key):
            return re.search(rf'^{key}: "([^"]+)"$', cff, re.M).group(1)

        version = re.search(
            r'__version__ = "([^"]+)"', (ROOT / "src/echo_personal_tool/__init__.py").read_text()
        ).group(1)
        self.assertEqual(scalar("version"), version)
        date_match = re.search(r'^date-released: "([^"]+)"$', cff, re.M)
        if date_match:
            release_date = date_match.group(1)
            self.assertRegex(release_date, r"^\d{4}-\d{2}-\d{2}$")
            history = ROOT / "changelog" / f"{release_date[:7]}.md"
            self.assertIn(f"## v{version} — {release_date}", history.read_text(encoding="utf-8"))
        self.assertEqual(scalar("doi"), DOI)
        # Some converters prefer the first DOI in identifiers over the top-level field.
        identifiers = re.findall(r'^    value: "([^"]+)"$', cff, re.M)
        self.assertEqual(identifiers, [DOI, VERSION_DOI])
        # A version-specific DOI can refer to an older release; the concept DOI
        # above is the one that always resolves to the latest release.
        self.assertRegex(cff, r'description: "Version-specific DOI for SonoForge v\d+\.\d+\.\d+\."')

    def test_general_citation_uses_all_versions_doi(self):
        cite = re.search(r'<section class="section" id="cite">.*?</section>', self.html, re.S).group()
        self.assertIn(f'href="https://doi.org/{DOI}"', cite)
        self.assertIn(f"DOI {DOI}", cite)
        self.assertIn(f"doi       = {{{DOI}}}", cite)
        self.assertIn("all-versions DOI", cite)
        self.assertIn("общий DOI для всех версий", cite)
        self.assertIn("url       = {https://github.com/areatu/SonoForge}", cite)
        self.assertNotIn(VERSION_DOI, cite)
        self.assertNotIn("version   =", cite)
        self.assertNotIn("/releases/tag/", cite)


class TourPageTests(unittest.TestCase):
    """The feature-tour page: recorded GIFs exist, stay small and every text has both languages."""

    ROOT = Path(__file__).resolve().parents[2]
    TOUR = ROOT / "site" / "tour.html"
    MEDIA = ROOT / "site" / "media" / "tour"
    MAX_FILE_BYTES = 8 * 1024 * 1024

    def test_no_synthetic_or_phantom_content_on_the_tour_page(self):
        html = self.TOUR.read_text(encoding="utf-8").lower()
        self.assertNotIn("phantom", html)
        self.assertNotIn("фантом", html)

    def test_bilingual_siblings_for_every_visible_block(self):
        html = self.TOUR.read_text(encoding="utf-8")
        for tag in ("span", "p", "h2", "h3", "figcaption"):
            en = len(re.findall(rf'<{tag}[^>]*\blang="en"', html))
            ru = len(re.findall(rf'<{tag}[^>]*\blang="ru"', html))
            self.assertEqual(en, ru, f"<{tag}> blocks: {en} English vs {ru} Russian")

    def test_built_site_local_links_and_images_resolve(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["bash", str(SITE / "build.sh"), directory + "/site"], check=True, stdout=subprocess.DEVNULL)
            out = Path(directory) / "site"
            for page in ("index.html", "tour.html", "404.html"):
                parsed = Page((out / page).read_text(encoding="utf-8"))
                for tag, attrs in parsed.elements:
                    for attr in ("href", "src", "data-feature-gif"):
                        value = attrs.get(attr, "")
                        parsed_url = urlsplit(value)
                        if not parsed_url.path or parsed_url.scheme or value.startswith(("//", "/")):
                            continue
                        target = out / parsed_url.path
                        self.assertTrue(target.is_file(), f"{page}: broken {attr} {value}")

    def test_new_feature_screenshots_have_bilingual_descriptions_and_lightboxes(self):
        html = self.TOUR.read_text(encoding="utf-8")
        for section, image in (("measure", "calculators"), ("reference", "reference"), ("server", "server-loader")):
            with self.subTest(section=section):
                block = re.search(rf'<section\b[^>]*id="{section}"[^>]*>.*?</section>', html, re.S).group()
                self.assertIn(f'href="screenshots/{image}.png" data-lightbox', block)
                self.assertIn(f'src="screenshots/{image}.png"', block)
                self.assertIn('lang="en"', block)
                self.assertIn('lang="ru"', block)
                self.assertTrue((self.ROOT / "docs" / "images" / "release-0.4" / f"{image}.png").is_file())
        self.assertIn("identifying details hidden", html)
        self.assertIn("идентифицирующие данные скрыты", html)

    def test_calculator_catalog_matches_registry(self):
        registry = ast.parse((self.ROOT / "src/echo_personal_tool/domain/calculators/registry.py").read_text())
        declared = next(node.value.elts for node in registry.body
                        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                        and node.target.id == "CALCULATORS")
        expected = {node.id.lower() for node in declared}
        actual = re.findall(r'data-calculator="([a-z_]+)"', self.TOUR.read_text())
        self.assertEqual(len(actual), len(expected))
        self.assertEqual(set(actual), expected)

    def test_customization_details_and_landing_links(self):
        html = self.TOUR.read_text()
        for value in ("Classic", "Mirrored", "Filmstrip", "Graphite", "VS Code Dark",
                      "Blue", "Teal", "Violet", "Amber", "radial menu", "радиальном меню",
                      "Reference Constructor", "конструктор справочника", "Excel", "YAML", "PDF", "HTML"):
            self.assertIn(value, html)
        index = (SITE / "index.html").read_text()
        for anchor in ("workspace", "reference", "calculator-catalog"):
            self.assertIn(f'href="tour.html#{anchor}"', index)
            self.assertIn(f'id="{anchor}"', html)

    def test_index_links_to_tour(self):
        html = (self.ROOT / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="tour.html"', html)


if __name__ == "__main__":
    unittest.main()
