"""Tests for the session logging configuration (Э1 follow-ups).

Born from a real Windows support bundle: the session header lost its version
numbers to the UID sanitizer, and 98% of the archive was httpcore DEBUG noise.
"""

from __future__ import annotations

import logging

import pytest

from echo_personal_tool import __version__
from echo_personal_tool.infrastructure import logging_setup
from echo_personal_tool.infrastructure.log_sanitizer import sanitize_log_text


class TestSanitizedSessionHeader:
    def test_versions_survive_sanitization(self) -> None:
        header = logging_setup.system_info_text(None)
        clean = sanitize_log_text(header)

        assert f"SonoForge version: {__version__}" in clean
        assert "<dicom-uid>" not in clean

    def test_real_uids_are_still_masked(self) -> None:
        line = "study=1.2.410.200001.1.1185.2062614048.1.20251111.1220602869.758.1 done"
        clean = sanitize_log_text(line)

        assert "<dicom-uid>" in clean
        assert "2062614048" not in clean

    def test_addresses_are_still_masked(self) -> None:
        clean = sanitize_log_text("connect_tcp.started host='212.12.34.56' port=8042")

        assert "212.12.34.56" not in clean


class TestThirdPartyVerbosity:
    @pytest.fixture()
    def session(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ECHO_DEBUG", raising=False)
        sess = logging_setup.configure_logging(directory=tmp_path)
        yield sess
        logging_setup._shutdown_logging()

    def test_http_chatter_is_info_by_default(self, session) -> None:
        assert logging.getLogger("httpcore").level == logging.INFO
        assert logging.getLogger("httpcore.http11").level == logging.INFO
        assert logging.getLogger("httpx").level == logging.INFO

    def test_echo_debug_restores_full_verbosity(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("ECHO_DEBUG", "1")
        logging_setup.configure_logging(directory=tmp_path)
        try:
            assert logging.getLogger("httpcore").level == logging.DEBUG
        finally:
            logging_setup._shutdown_logging()

    def test_levels_are_restored_on_shutdown(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("ECHO_DEBUG", raising=False)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        try:
            sess = logging_setup.configure_logging(directory=tmp_path)
            assert logging.getLogger("httpx").level == logging.INFO
            logging_setup._shutdown_logging()
            assert sess is not None
            assert logging.getLogger("httpx").level == logging.WARNING
        finally:
            logging.getLogger("httpx").setLevel(logging.NOTSET)

    def test_session_log_contains_the_unmasked_header(self, session) -> None:
        assert session.log_path is not None
        text = session.log_path.read_text(encoding="utf-8")

        assert f"SonoForge version: {__version__}" in text
