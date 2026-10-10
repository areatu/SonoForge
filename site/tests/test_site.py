"""Small, dependency-free regression checks for the static landing page.

Run: python3 -m unittest discover -s site/tests -v
These tests intentionally do not import the Qt application or require Pillow.
"""

from __future__ import annotations

import re
import struct
import unittest
from html.parser import HTMLParser
from pathlib import Path

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


def gif_frames(data):
    """Walk GIF blocks instead of counting byte patterns inside compressed data."""
    index = 13
    if data[10] & 0x80:
        index += 3 * (2 ** ((data[10] & 7) + 1))
    frames = 0

    def skip_subblocks(position):
        while data[position]:
            position += data[position] + 1
        return position + 1

    while index < len(data):
        marker = data[index]
        index += 1
        if marker == 0x3B:  # trailer
            return frames
        if marker == 0x21:  # extension label + variable-length data
            index = skip_subblocks(index + 1)
        elif marker == 0x2C:  # image descriptor, optional palette, LZW data
            packed = data[index + 8]
            index += 9
            if packed & 0x80:
                index += 3 * (2 ** ((packed & 7) + 1))
            index = skip_subblocks(index + 1)  # skip the LZW minimum code size
            frames += 1
        else:
            raise ValueError(f"Unexpected GIF block: {marker:#x}")
    raise ValueError("Missing GIF trailer")


class LandingPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (SITE / "index.html").read_text()
        cls.page = Page(cls.html)

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

    def test_demo_rate_and_removed_decorative_trace(self):
        self.assertIn("30 fps · ONNX", self.html)
        self.assertIn("30 к/с · ONNX", self.html)
        for source in (self.html, (SITE / "styles.css").read_text()):
            self.assertNotIn("hero-trace", source)
            self.assertNotIn("trace-pulse", source)
            self.assertNotIn("mini-viz", source)
        self.assertNotIn("60 fps", self.html)
        self.assertNotIn("60 к/с", self.html)

    def test_only_first_six_cards_have_previews(self):
        self.assertEqual(len(self.page.cards), 9)
        names = ["cardiac", "doppler", "calibration", "segmentation", "pacs", "reports"]
        for index, card in enumerate(self.page.cards):
            with self.subTest(card=index + 1):
                self.assertEqual(len(card), 1 if index < 6 else 0)
                if index >= 6:
                    continue
                image = card[0]
                self.assertEqual(image["src"], f"media/features/{names[index]}-poster.jpg")
                self.assertEqual(image["data-feature-gif"], f"media/features/{names[index]}.gif")
                self.assertEqual(image["loading"], "lazy")
                self.assertEqual(image["alt"], "")
                self.assertEqual((image["width"], image["height"]), ("480", "224"))

    def test_feature_files_are_small_real_animated_gifs_with_posters(self):
        total = 0
        for card in self.page.cards[:6]:
            image = card[0]
            with self.subTest(image=image["data-feature-gif"]):
                data = (SITE / image["data-feature-gif"]).read_bytes()
                total += len(data)
                self.assertEqual(data[:6], b"GIF89a")
                self.assertEqual(struct.unpack("<HH", data[6:10]), (480, 224))
                self.assertGreaterEqual(gif_frames(data), 12)
                self.assertIn(b"NETSCAPE2.0", data)
                self.assertEqual((SITE / image["src"]).read_bytes()[:2], b"\xff\xd8")
        self.assertLess(total, 512 * 1024)
        self.assertIn('cp -R "$SITE/media/features" "$OUT/media/features"', (SITE / "build.sh").read_text())

    def test_pause_control_is_progressive_enhancement(self):
        buttons = [attrs for tag, attrs in self.page.elements if tag == "button" and "data-feature-motion" in attrs]
        self.assertEqual(len(buttons), 1)
        self.assertIn("hidden", buttons[0])
        js = (SITE / "app.js").read_text()
        self.assertIn("prefers-reduced-motion: reduce", js)
        self.assertIn('addEventListener("visibilitychange", syncFeaturePreviews)', js)
        self.assertIn('addEventListener("change", syncFeaturePreviews)', js)
        self.assertIn('addEventListener("error"', js)
        for label in ("Pause previews", "Resume previews", "Остановить анимации", "Включить анимации"):
            self.assertIn(label, js)

    def test_cff_keeps_current_version_and_distinct_dois(self):
        cff = (ROOT / "CITATION.cff").read_text()

        def scalar(key):
            return re.search(rf'^{key}: "([^"]+)"$', cff, re.M).group(1)

        version = re.search(
            r'__version__ = "([^"]+)"', (ROOT / "src/echo_personal_tool/__init__.py").read_text()
        ).group(1)
        self.assertEqual(scalar("version"), version)
        self.assertIn(f"## v{version} — {scalar('date-released')}", (ROOT / "CHANGELOG.md").read_text())
        self.assertEqual(scalar("doi"), DOI)
        # Some converters prefer the first DOI in identifiers over the top-level field.
        identifiers = re.findall(r'^    value: "([^"]+)"$', cff, re.M)
        self.assertEqual(identifiers, [DOI, VERSION_DOI])
        self.assertIn(f'description: "Version-specific DOI for SonoForge v{version}."', cff)

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


if __name__ == "__main__":
    unittest.main()


class TourPageTests(unittest.TestCase):
    """The feature-tour page: recorded GIFs exist, stay small and every text has both languages."""

    ROOT = Path(__file__).resolve().parents[2]
    TOUR = ROOT / "site" / "tour.html"
    MEDIA = ROOT / "site" / "media" / "tour"
    MAX_FILE_BYTES = 8 * 1024 * 1024

    def test_referenced_gifs_are_valid_and_small_when_present(self):
        # The maintainer records the GIFs by hand; a missing file is allowed (the page shows no animation).
        html = self.TOUR.read_text(encoding="utf-8")
        refs = re.findall(r'src="(media/tour/[^"]+\.gif)"', html)
        self.assertGreaterEqual(len(set(refs)), 7)
        for ref in set(refs):
            path = self.ROOT / "site" / ref
            if not path.is_file():
                continue
            self.assertIn(path.read_bytes()[:6], (b"GIF87a", b"GIF89a"), f"not a GIF: {ref}")
            self.assertLessEqual(path.stat().st_size, self.MAX_FILE_BYTES, f"too large: {ref}")

    def test_no_synthetic_or_phantom_content_on_the_tour_page(self):
        html = self.TOUR.read_text(encoding="utf-8").lower()
        self.assertNotIn("phantom", html)
        self.assertNotIn("фантом", html)

    def test_every_gif_on_disk_is_linked_from_the_page(self):
        html = self.TOUR.read_text(encoding="utf-8")
        for path in self.MEDIA.glob("*.gif"):
            self.assertIn(f"media/tour/{path.name}", html, f"unused GIF: {path.name}")

    def test_bilingual_siblings_for_every_visible_block(self):
        html = self.TOUR.read_text(encoding="utf-8")
        for tag in ("span", "p", "h2", "h3", "figcaption"):
            en = len(re.findall(rf'<{tag}[^>]*\blang="en"', html))
            ru = len(re.findall(rf'<{tag}[^>]*\blang="ru"', html))
            self.assertEqual(en, ru, f"<{tag}> blocks: {en} English vs {ru} Russian")

    def test_local_links_resolve(self):
        html = self.TOUR.read_text(encoding="utf-8")
        for href in re.findall(r'href="([^"#?]+)', html):
            if href.startswith(("http", "mailto:", "media/tour/")):
                continue  # GIFs are added by hand; checked by the GIF test instead
            self.assertTrue((self.ROOT / "site" / href).exists(), f"broken local link: {href}")

    def test_index_links_to_tour(self):
        html = (self.ROOT / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="tour.html"', html)
