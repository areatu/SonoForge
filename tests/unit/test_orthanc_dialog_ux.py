"""Tests for the new server-load dialog UX plumbing.

Covers, without a display:
* ``OrthancDicomWebClient.fetch_preview`` / ``study_statistics`` (route
  fallbacks, multipart unwrapping, graceful degradation);
* ``OrthancPreviewLoader`` (cache, queue, failure memory, shutdown);
* row delegates (height contract, painting without a crash);
* ``CheckableTreeWidget`` (checkbox hit testing, Space toggling);
* the extended QIDO-RS tag parsing used by the study/series rows.
"""

from __future__ import annotations

import httpx
import pytest

from echo_personal_tool.infrastructure.orthanc_client import (
    OrthancDicomWebClient,
    _extract_image_payload,
)
from echo_personal_tool.infrastructure.orthanc_dicom_json import parse_series, parse_studies

pytestmark = pytest.mark.gui


# ── DICOMweb JSON parsing ───────────────────────────────────────────


def _tag(value, vr="LO"):
    return {"vr": vr, "Value": [value]}


class TestEnrichedParsing:
    def test_parse_studies_reads_optional_context(self):
        payload = [
            {
                "0020000D": _tag("1.2.3", "UI"),
                "00100010": _tag("ИВАНОВ^ИВАН"),
                "00100020": _tag("42"),
                "00080020": _tag("20240404", "DA"),
                "00081030": _tag("ЭхоКГ"),
                "00080030": _tag("101500", "TM"),
                "00080050": _tag("A-1"),
                "00080061": _tag("US", "CS"),
                "00080080": _tag("ГКБ №1"),
                "00100030": _tag("19570112", "DA"),
                "00100040": _tag("M", "CS"),
                "00201206": _tag("5", "IS"),
                "00201208": _tag("412", "IS"),
            }
        ]
        study = parse_studies(payload)[0]
        assert study.study_uid == "1.2.3"
        assert study.patient_birth_date == "19570112"
        assert study.patient_sex == "M"
        assert study.study_time == "101500"
        assert study.accession_number == "A-1"
        assert study.modalities_in_study == "US"
        assert study.series_count == 5
        assert study.instances_count == 412

    def test_parse_studies_tolerates_missing_tags(self):
        study = parse_studies([{"0020000D": _tag("1.2.3", "UI")}])[0]
        assert study.patient_name == ""
        assert study.series_count is None
        assert study.instances_count is None

    def test_parse_studies_flattens_backslash_modalities(self):
        payload = [{"0020000D": _tag("1.2.3", "UI"), "00080061": _tag("US\\XA")}]
        assert parse_studies(payload)[0].modalities_in_study == "US, XA"

    def test_parse_series_reads_number_and_body_part(self):
        payload = [
            {
                "0020000E": _tag("1.2.3.1", "UI"),
                "00080060": _tag("US", "CS"),
                "0008103E": _tag("2D PLAX"),
                "00201209": _tag("96", "IS"),
                "00200011": _tag("3", "IS"),
                "00180015": _tag("HEART", "CS"),
            }
        ]
        series = parse_series(payload, "1.2.3")[0]
        assert series.series_number == 3
        assert series.body_part == "HEART"
        assert series.instance_count == 96


# ── httpx-level tests for previews / statistics ─────────────────────


def _client(handler) -> OrthancDicomWebClient:  # noqa: ANN001 - httpx handler
    """Build a client whose transports are backed by *handler*."""
    client = OrthancDicomWebClient("http://orthanc:8042", timeout=1.0)
    client._client = httpx.Client(  # noqa: SLF001 - test double
        base_url="http://orthanc:8042/dicom-web/",
        transport=httpx.MockTransport(handler),
    )
    client._orthanc_client = httpx.Client(  # noqa: SLF001 - test double
        base_url="http://orthanc:8042/",
        transport=httpx.MockTransport(handler),
    )
    return client


def _png_bytes(image) -> bytes:  # noqa: ANN001 - QImage
    from PySide6.QtCore import QBuffer

    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def _blank_png(width: int = 24, height: int = 18) -> bytes:
    """A frame stored at the start of a loop: pure black."""
    from PySide6.QtGui import QColor, QImage

    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(0, 0, 0))
    return _png_bytes(image)


def _textured_png(width: int = 24, height: int = 18) -> bytes:
    """A usable frame: dark background plus a bright sector."""
    from PySide6.QtGui import QColor, QImage

    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(4, 4, 4))
    for y in range(2, height - 2):
        for x in range(3, width // 2):
            image.setPixelColor(x, y, QColor(140, 140, 140))
    return _png_bytes(image)


class TestFetchPreview:
    def test_thumbnail_route_is_used_first(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            if "instances" in request.url.path:
                if request.url.path.endswith("/instances"):
                    return httpx.Response(200, json=[{"00080018": {"vr": "UI", "Value": ["1.2.3.4.5"]}}])
                return httpx.Response(200, content=b"\xff\xd8jpegdata", headers={"Content-Type": "image/jpeg"})
            return httpx.Response(404)

        client = _client(handler)
        payload = client.fetch_preview("1.2.3", "1.2.3.1", width=160, height=120)
        assert payload == b"\xff\xd8jpegdata"
        assert any(path.endswith("/thumbnail") for path in seen)

    def test_falls_back_to_orthanc_preview_route(self):
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/instances"):
                return httpx.Response(200, json=[])
            if "thumbnail" in path or "rendered" in path:
                return httpx.Response(415)
            if path.endswith("/tools/lookup"):
                return httpx.Response(200, json=[{"Type": "Instance", "ID": "abc"}])
            if path.endswith("/instances/abc/preview"):
                return httpx.Response(200, content=b"PNGDATA", headers={"Content-Type": "image/png"})
            return httpx.Response(404)

        client = _client(handler)
        assert client.fetch_preview("1.2.3", "1.2.3.1", "1.2.3.4.5") == b"PNGDATA"

    def test_returns_empty_when_everything_fails(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        client = _client(handler)
        assert client.fetch_preview("1.2.3", "1.2.3.1", "1.2.3.4.5") == b""

    def test_middle_frame_requests_the_middle_of_the_loop(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            seen.append(path)
            if path.endswith("/instances"):
                return httpx.Response(200, json=[{"00080018": {"vr": "UI", "Value": ["1.2.3.4.5"]}}])
            if path.endswith("/tools/lookup"):
                return httpx.Response(200, json=[{"Type": "Instance", "ID": "abc"}])
            if path.endswith("/instances/abc/simplified-tags"):
                return httpx.Response(200, json={"NumberOfFrames": "25"})
            if path.endswith("/instances/abc/frames/12/preview"):
                return httpx.Response(200, content=b"MIDFRAME", headers={"Content-Type": "image/png"})
            return httpx.Response(404)

        payload = _client(handler).fetch_preview("1.2.3", "1.2.3.1", middle_frame=True)
        assert payload == b"MIDFRAME"
        assert "/instances/abc/frames/12/preview" in seen

    def test_instance_uid_is_looked_up_once_per_series(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            seen.append(path)
            if path.endswith("/instances"):
                return httpx.Response(200, json=[{"00080018": {"vr": "UI", "Value": ["1.2.3.4.5"]}}])
            return httpx.Response(200, content=b"IMG", headers={"Content-Type": "image/jpeg"})

        client = _client(handler)
        client.fetch_preview("1.2.3", "1.2.3.1")
        client.fetch_preview("1.2.3", "1.2.3.1")
        assert sum(1 for path in seen if path.endswith("/instances")) == 1

    def test_middle_frame_uses_wadors_when_orthanc_frame_fails(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            seen.append(path)
            if path.endswith("/instances"):
                return httpx.Response(200, json=[{"00080018": {"vr": "UI", "Value": ["1.2.3.4.5"]}}])
            if path.endswith("/tools/lookup"):
                return httpx.Response(200, json=[{"Type": "Instance", "ID": "abc"}])
            if path.endswith("/simplified-tags"):
                return httpx.Response(200, json={"NumberOfFrames": "9"})
            if path.endswith("/instances/abc/frames/4/preview"):
                return httpx.Response(404)
            if path.endswith("/frames/4/rendered"):
                return httpx.Response(200, content=b"WADORS4", headers={"Content-Type": "image/jpeg"})
            return httpx.Response(404)

        assert _client(handler).fetch_preview("1.2.3", "1.2.3.1", middle_frame=True) == b"WADORS4"
        assert any(path.endswith("/frames/4/rendered") for path in seen)

    def test_middle_frame_with_single_frame_falls_back_to_first_frame(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            seen.append(path)
            if path.endswith("/instances"):
                return httpx.Response(200, json=[{"00080018": {"vr": "UI", "Value": ["1.2.3.4.5"]}}])
            if path.endswith("/tools/lookup"):
                return httpx.Response(200, json=[{"Type": "Instance", "ID": "abc"}])
            if path.endswith("/simplified-tags"):
                return httpx.Response(200, json={"NumberOfFrames": "1"})
            if path.endswith("/thumbnail"):
                return httpx.Response(200, content=b"FIRSTFRAME", headers={"Content-Type": "image/jpeg"})
            return httpx.Response(404)

        assert _client(handler).fetch_preview("1.2.3", "1.2.3.1", middle_frame=True) == b"FIRSTFRAME"
        assert not any("/frames/" in path for path in seen)

    def test_middle_frame_without_orthanc_tags_falls_back(self):
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/instances"):
                return httpx.Response(200, json=[{"00080018": {"vr": "UI", "Value": ["1.2.3.4.5"]}}])
            if path.endswith("/tools/lookup"):
                return httpx.Response(200, json=[{"Type": "Instance", "ID": "abc"}])
            if path.endswith("/simplified-tags"):
                return httpx.Response(404)
            if path.endswith("/thumbnail"):
                return httpx.Response(200, content=b"FIRSTFRAME", headers={"Content-Type": "image/jpeg"})
            return httpx.Response(404)

        assert _client(handler).fetch_preview("1.2.3", "1.2.3.1", middle_frame=True) == b"FIRSTFRAME"

    def test_multipart_rendered_bodies_are_unwrapped(self):
        boundary = "BOUND"
        body = (
            f"--{boundary}\r\nContent-Type: image/jpeg\r\n\r\n".encode()
            + b"IMAGEDATA"
            + f"\r\n--{boundary}--\r\n".encode()
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/instances"):
                return httpx.Response(200, json=[])
            if "thumbnail" in request.url.path:
                return httpx.Response(415)
            return httpx.Response(
                200,
                content=body,
                headers={"Content-Type": f'multipart/related; type="image/jpeg"; boundary={boundary}'},
            )

        client = _client(handler)
        assert client.fetch_preview("1.2.3", "1.2.3.1", "1.2.3.4.5") == b"IMAGEDATA"


class TestExtractImagePayload:
    def test_plain_body_passthrough(self):
        response = httpx.Response(200, content=b"abc", headers={"Content-Type": "image/png"})
        assert _extract_image_payload(response) == b"abc"

    def test_no_boundary_yields_empty(self):
        response = httpx.Response(200, content=b"abc", headers={"Content-Type": "multipart/related"})
        assert _extract_image_payload(response) == b""


class TestStudyStatistics:
    def test_reads_orthanc_statistics(self):
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/tools/lookup"):
                return httpx.Response(200, json=[{"Type": "Study", "ID": "st1"}])
            if path.endswith("/statistics"):
                return httpx.Response(200, json={"CountInstances": 412, "CountSeries": 5, "DicomDiskSizeMB": 84})
            if path.endswith("/studies/st1"):
                return httpx.Response(200, json={"IsStable": True, "LastUpdate": "20261003T101533"})
            return httpx.Response(404)

        stats = _client(handler).study_statistics("1.2.3")
        assert stats.instances == 412
        assert stats.series == 5
        assert stats.size_mb == 84
        assert stats.is_stable is True
        assert stats.last_update.startswith("20261003")

    def test_returns_empty_on_plain_dicomweb_server(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        stats = _client(handler).study_statistics("1.2.3")
        assert stats.instances is None
        assert stats.size_mb is None
        assert stats.is_stable is None


class TestQueryStudiesExtendedFields:
    def test_extended_fields_are_requested(self):
        captured: dict[str, list[str]] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["includefield"] = request.url.params.get_list("includefield")
            return httpx.Response(200, json=[])

        _client(handler).query_studies(patient_name="Иванов")
        assert "00100030" in captured["includefield"]  # PatientBirthDate
        assert "00201206" in captured["includefield"]  # NumberOfStudyRelatedSeries
        assert "00100040" in captured["includefield"]  # PatientSex

    def test_strict_server_falls_back_to_minimal_field_set(self):
        calls: list[list[str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            fields = request.url.params.get_list("includefield")
            calls.append(fields)
            if "00201206" in fields:
                return httpx.Response(400)
            return httpx.Response(
                200,
                json=[
                    {
                        "0020000D": {"vr": "UI", "Value": ["1.2.3"]},
                        "00100010": {"vr": "PN", "Value": ["ИВАНОВ^ИВАН"]},
                    }
                ],
            )

        studies = _client(handler).query_studies()
        assert len(calls) == 2
        assert [s.study_uid for s in studies] == ["1.2.3"]
        assert studies[0].patient_name == "ИВАНОВ^ИВАН"


# ── preview loader ──────────────────────────────────────────────────


class _StubClient:
    def __init__(self, *, payload=b"", fail=False):
        self.payload = payload
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def fetch_preview(self, study_uid, series_uid, instance_uid="", *, width=0, height=0):  # noqa: ANN001
        self.calls.append((study_uid, series_uid))
        if self.fail:
            raise RuntimeError("boom")
        return self.payload


class _LoopStubClient:
    """Client double with a blank first frame and a usable middle frame."""

    def __init__(self, first: bytes, middle: bytes) -> None:
        self._payloads = {False: first, True: middle}
        self.calls: list[bool] = []

    def fetch_preview(  # noqa: ANN001
        self,
        study_uid,
        series_uid,
        instance_uid="",
        *,
        width=0,
        height=0,
        middle_frame=False,
    ):
        self.calls.append(bool(middle_frame))
        return self._payloads[bool(middle_frame)]


@pytest.fixture()
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class TestPreviewLoader:
    def test_cache_and_failure_memory(self, qapp):
        from PySide6.QtCore import QBuffer
        from PySide6.QtGui import QImage

        # Build a real PNG payload so QImage can decode it.
        image = QImage(8, 8, QImage.Format.Format_RGB32)
        image.fill(0x20FF00)
        buffer = QBuffer()
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        payload = bytes(buffer.data())

        from echo_personal_tool.presentation.orthanc_preview_loader import OrthancPreviewLoader

        loader = OrthancPreviewLoader(_StubClient(payload=payload))
        assert loader.request("s1", "se1") is None  # queued, not ready yet
        qapp.processEvents()
        for _ in range(200):
            if loader.cached("s1", "se1") is not None:
                break
            qapp.processEvents()
        assert loader.cached("s1", "se1") is not None

        broken = OrthancPreviewLoader(_StubClient(fail=True))
        broken.request("s1", "se1")
        for _ in range(200):
            if ("s1", "se1") in broken._failed:
                break
            qapp.processEvents()
        # A permanently failing preview must not be re-asked on every scroll.
        assert ("s1", "se1") in broken._failed
        broken.request("s1", "se1")
        assert broken._queue == []

    def test_blank_frame_is_retried_from_the_loop_middle(self, qapp):
        from echo_personal_tool.presentation.orthanc_preview_loader import OrthancPreviewLoader

        client = _LoopStubClient(_blank_png(), _textured_png())
        loader = OrthancPreviewLoader(client)
        loader.request("s1", "se1")
        for _ in range(200):
            if loader.cached("s1", "se1") is not None:
                break
            qapp.processEvents()
        pixmap = loader.cached("s1", "se1")
        assert pixmap is not None
        assert client.calls == [False, True]  # plain first, middle frame second
        # The middle frame (bright sector) must have won over the blank one.
        assert pixmap.toImage().pixelColor(10, 10).lightness() > 60

    def test_usable_frame_is_not_retried(self, qapp):
        from echo_personal_tool.presentation.orthanc_preview_loader import OrthancPreviewLoader

        client = _LoopStubClient(_textured_png(), _textured_png())
        loader = OrthancPreviewLoader(client)
        loader.request("s1", "se1")
        for _ in range(200):
            if loader.cached("s1", "se1") is not None:
                break
            qapp.processEvents()
        assert loader.cached("s1", "se1") is not None
        assert client.calls == [False]

    def test_informativeness_probe(self):
        from PySide6.QtGui import QColor, QImage

        from echo_personal_tool.presentation.orthanc_preview_loader import is_informative_image

        assert is_informative_image(None) is False
        blank = QImage(24, 18, QImage.Format.Format_RGB32)
        blank.fill(QColor(0, 0, 0))
        assert is_informative_image(blank) is False
        flat = QImage(24, 18, QImage.Format.Format_RGB32)
        flat.fill(QColor(128, 128, 128))  # uniform grey is not a thumbnail either
        assert is_informative_image(flat) is False
        textured = QImage(24, 18, QImage.Format.Format_RGB32)
        textured.fill(QColor(4, 4, 4))
        for y in range(2, 16):  # a bright sector, like a real echo frame
            for x in range(3, 12):
                textured.setPixelColor(x, y, QColor(140, 140, 140))
        assert is_informative_image(textured) is True

    def test_disabled_loader_never_requests(self, qapp):
        from echo_personal_tool.presentation.orthanc_preview_loader import OrthancPreviewLoader

        client = _StubClient()
        loader = OrthancPreviewLoader(client)
        loader.set_enabled(False)
        assert loader.request("s1", "se1") is None
        qapp.processEvents()
        assert client.calls == []

    def test_shutdown_is_idempotent(self, qapp):
        from echo_personal_tool.presentation.orthanc_preview_loader import OrthancPreviewLoader

        loader = OrthancPreviewLoader(_StubClient())
        loader.shutdown()
        loader.shutdown()
        assert loader.request("s1", "se1") is None


# ── delegates / widgets ─────────────────────────────────────────────


class TestRowDelegate:
    def test_size_hint_keeps_row_height(self, qapp):
        from PySide6.QtWidgets import QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem

        from echo_personal_tool.domain.models.orthanc import StudyInfo
        from echo_personal_tool.presentation.orthanc_study_delegate import (
            ROLE_ROW,
            SERIES_ROW_HEIGHT,
            STUDY_ROW_HEIGHT,
            OrthancRowDelegate,
            SeriesRow,
            StudyRow,
        )

        tree = QTreeWidget()
        tree.setItemDelegate(OrthancRowDelegate(tree, kind="study"))
        item = QTreeWidgetItem(tree)
        item.setData(0, ROLE_ROW, StudyRow(study=StudyInfo("1", "A^B", "", "20240101", ""), title="A B"))
        option = QStyleOptionViewItem()
        option.rect = tree.visualItemRect(item)
        hint = tree.itemDelegate().sizeHint(option, tree.indexFromItem(item))
        assert hint.height() == STUDY_ROW_HEIGHT

        series_tree = QTreeWidget()
        series_delegate = OrthancRowDelegate(series_tree, kind="series")
        assert series_delegate.row_height == SERIES_ROW_HEIGHT
        assert SeriesRow is not None

    def test_paint_does_not_crash_without_data(self, qapp):
        from PySide6.QtGui import QPainter, QPixmap
        from PySide6.QtWidgets import QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem

        from echo_personal_tool.presentation.orthanc_study_delegate import OrthancRowDelegate

        tree = QTreeWidget()
        delegate = OrthancRowDelegate(tree, kind="study")
        tree.setItemDelegate(delegate)
        item = QTreeWidgetItem(tree)
        option = QStyleOptionViewItem()
        option.rect = tree.visualItemRect(item)
        pixmap = QPixmap(400, 100)
        painter = QPainter(pixmap)
        try:
            delegate.paint(painter, option, tree.indexFromItem(item))
        finally:
            painter.end()

    def test_checkbox_rect_is_inside_the_row(self):
        from PySide6.QtCore import QRect

        from echo_personal_tool.presentation.orthanc_study_delegate import CHECKBOX_SIZE, checkbox_rect

        row_rect = QRect(0, 0, 500, 92)
        box = checkbox_rect(row_rect)
        assert box.size().width() == CHECKBOX_SIZE
        assert abs(box.center().y() - row_rect.center().y()) <= 1
        assert box.left() >= row_rect.left()


class TestCheckableTreeWidget:
    def test_checkbox_hit_test_matches_painted_box(self, qapp):
        from PySide6.QtCore import QPoint, QSize
        from PySide6.QtWidgets import QTreeWidgetItem

        from echo_personal_tool.presentation.orthanc_study_dialog import CheckableTreeWidget as Widget

        tree = Widget(row_height=92)
        tree.resize(400, 200)
        item = QTreeWidgetItem()
        item.setSizeHint(0, QSize(400, 92))
        tree.addTopLevelItem(item)
        tree.show()
        qapp.processEvents()

        rect = tree.visualItemRect(item)
        assert tree.checkbox_hit(item, rect.center()) is False
        assert tree.checkbox_hit(item, QPoint(rect.left() + 16, rect.center().y())) is True
        assert tree.selectionMode() == tree.SelectionMode.SingleSelection
        assert tree.indentation() == 0
        assert tree.rootIsDecorated() is False

    def test_space_toggles_current_item(self, qapp):
        from PySide6.QtCore import QSize, Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QTreeWidgetItem

        from echo_personal_tool.presentation.orthanc_study_dialog import CheckableTreeWidget

        tree = CheckableTreeWidget(row_height=60)
        item = QTreeWidgetItem()
        item.setSizeHint(0, QSize(300, 60))
        tree.addTopLevelItem(item)
        tree.setCurrentItem(item)
        toggled: list[object] = []
        tree.checkToggled.connect(toggled.append)

        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        tree.keyPressEvent(event)
        assert toggled == [item]


class TestPreviewStylesheetScope:
    def test_loader_stylesheet_does_not_touch_global_check_indicators(self):
        """The dialog QSS must not restyle checkboxes in the clinical browsers."""
        from echo_personal_tool.presentation.dark_theme import get_theme_palette
        from echo_personal_tool.presentation.orthanc_study_dialog import build_loader_dialog_stylesheet

        qss = build_loader_dialog_stylesheet(get_theme_palette())
        assert "QTreeWidget::indicator" not in qss
        assert "QCheckBox::indicator" not in qss
        assert "#periodChip" in qss
        assert "#primaryButton" in qss


class TestPreviewLoaderLifetime:
    """The dialog may close while thumbnails are still being fetched."""

    def test_loader_destroyed_while_a_request_is_in_flight_is_safe(self, qapp):
        """No queued call may reach a receiver that is already gone.

        Regression: the loader used to hand the decoded frame to the GUI thread
        through a queued signal connected to a bound Python method.  Closing the
        dialog (or dropping the loader in a test) while a worker was still
        inside ``fetch_preview`` left a meta-call event in the queue pointing at
        a freed receiver; delivering it could crash the process with SIGSEGV —
        a race, not a fixed order: 1 crash in ~10 local runs of this file, 3 in
        30 runs of the same file on ``main``, and one red ``test
        (ubuntu-latest)`` CI job.  The test drives exactly that path (worker
        held inside ``fetch_preview``, loader gone) and then checks that a fresh
        loader still works.
        """
        import threading
        import time

        from echo_personal_tool.presentation.orthanc_preview_loader import OrthancPreviewLoader

        in_fetch = threading.Event()
        release = threading.Event()

        class _SlowClient:
            def fetch_preview(  # noqa: ANN001
                self, study_uid, series_uid, instance_uid="", *, width=0, height=0, middle_frame=False
            ):
                in_fetch.set()
                release.wait(10)  # hold the worker until the loader is destroyed
                return _textured_png()

        loader = OrthancPreviewLoader(_SlowClient())
        loader.request("s1", "se1")
        for _ in range(200):
            if in_fetch.is_set():
                break
            qapp.processEvents()
        assert in_fetch.is_set(), "the worker never reached fetch_preview"

        loader.shutdown()  # the dialog is closing…
        del loader  # …and the loader is gone before the worker returns
        release.set()

        # Spin the loop long enough for the worker to finish and for any queued
        # delivery to be attempted; on the old implementation this segfaulted.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            qapp.processEvents()

        # The next loader must still work: nothing global was damaged.
        quiet = OrthancPreviewLoader(_StubClient(payload=_textured_png()))
        quiet.request("s2", "se2")
        for _ in range(200):
            if quiet.cached("s2", "se2") is not None:
                break
            qapp.processEvents()
        assert quiet.cached("s2", "se2") is not None
        quiet.shutdown()
