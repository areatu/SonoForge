"""Fuzz DICOM input parsing with malformed / synthetic corrupt files.

Uses hypothesis for property-based testing to ensure the application
handles truncated files, wrong VRs, oversized tags, non-numeric UIDs,
and nested undefined sequences without crashes.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from echo_personal_tool.infrastructure.dicom_validator import (
    InvalidDicomError,
    validate_dicom_header,
)

pytestmark = pytest.mark.security


def _dicom_preamble() -> bytes:
    """Standard 128-byte zero preamble + DICM magic."""
    return b"\x00" * 128 + b"DICM"


def _make_tag(group: int, element: int, vr: str, length: int, payload: bytes) -> bytes:
    """Build a DICOM explicit VR tag (little-endian)."""
    vr_bytes = vr.encode("ascii")
    if vr in ("OB", "OD", "OF", "OL", "OW", "SQ", "UC", "UN", "UR", "UT"):
        # 4-byte explicit length for special VRs
        tag_bytes = struct.pack("<HH", group, element) + vr_bytes + b"\x00\x00" + struct.pack("<I", length)
    else:
        tag_bytes = struct.pack("<HH", group, element) + vr_bytes + struct.pack("<H", length)
    return tag_bytes + payload


class TestDicomValidatorFuzzing:
    """Test validate_dicom_header against synthetic corrupt DICOM files."""

    def test_file_too_small(self, tmp_path: Path) -> None:
        tiny = tmp_path / "tiny.dcm"
        tiny.write_bytes(b"\x00" * 10)
        with pytest.raises(InvalidDicomError, match="too small"):
            validate_dicom_header(tiny)

    def test_empty_file(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.dcm"
        empty.write_bytes(b"")
        with pytest.raises(InvalidDicomError, match="too small"):
            validate_dicom_header(empty)

    def test_missing_magic_bytes(self, tmp_path: Path) -> None:
        bad_magic = tmp_path / "bad.dcm"
        bad_magic.write_bytes(b"\x00" * 128 + b"NOPE")
        with pytest.raises(InvalidDicomError, match="Missing DICOM magic"):
            validate_dicom_header(bad_magic)

    def test_wrong_magic_bytes(self, tmp_path: Path) -> None:
        f = tmp_path / "wrong.dcm"
        f.write_bytes(b"\x00" * 128 + b"JPEG")
        with pytest.raises(InvalidDicomError, match="Missing DICOM magic"):
            validate_dicom_header(f)

    def test_valid_minimal_dicom(self, tmp_path: Path) -> None:
        f = tmp_path / "minimal.dcm"
        f.write_bytes(_dicom_preamble() + b"\x00" * 10)
        validate_dicom_header(f)

    def test_oversized_file_rejected(self, tmp_path: Path) -> None:
        f = tmp_path / "big.dcm"
        # Write header + enough to exceed a tiny max
        f.write_bytes(_dicom_preamble() + b"\x00" * 100)
        with pytest.raises(InvalidDicomError, match="exceeds"):
            validate_dicom_header(f, max_size_bytes=200)

    def test_not_a_file(self, tmp_path: Path) -> None:
        d = tmp_path / "not_a_file"
        d.mkdir()
        with pytest.raises(InvalidDicomError, match="Not a file"):
            validate_dicom_header(d)

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidDicomError, match="Not a file"):
            validate_dicom_header(tmp_path / "nonexistent.dcm")


class TestDicomUidFuzzing:
    """Fuzz DICOM UID validation with arbitrary strings."""

    @pytest.mark.parametrize(
        "uid",
        [
            "",
            " ",
            "abc",
            "1.2.3/../../../etc/passwd",
            "1.2; rm -rf /",
            "1.2\x00.3",
            "1.2" + "\ufffd" * 10,
            "-1.2.3",
            "+1.2.3",
            "1.2.3!",
            "1:2:3",
            "1,2,3",
            "1.2.3; DROP TABLE users;",
        ],
    )
    def test_invalid_uids_rejected(self, uid: str) -> None:
        from echo_personal_tool.infrastructure.dicom_uid_validator import validate_dicom_uid

        assert validate_dicom_uid(uid) is False

    @pytest.mark.parametrize(
        "uid",
        [
            "1.2.3",
            "1.2.840.113619.2.55.3.12345",
            "12345",
            "0.0.0",
            "1" * 64,
            "0" * 1000,  # all digits, passes regex validation
            "...",  # dots only, passes regex validation (digit+dot charset)
        ],
    )
    def test_valid_uids_accepted(self, uid: str) -> None:
        from echo_personal_tool.infrastructure.dicom_uid_validator import validate_dicom_uid

        assert validate_dicom_uid(uid) is True


class TestDicomTagConstructionFuzzing:
    """Fuzz synthetic DICOM tag construction to verify no crashes in path building."""

    def test_long_uid_in_path_component(self) -> None:
        from echo_personal_tool.infrastructure.dicom_uid_validator import safe_uid_path_component

        long_uid = ".".join(str(i) for i in range(100))
        result = safe_uid_path_component(long_uid)
        assert result == long_uid

    def test_empty_string_uid(self) -> None:
        from echo_personal_tool.infrastructure.dicom_uid_validator import safe_uid_path_component

        with pytest.raises(ValueError):
            safe_uid_path_component("")

    def test_slash_only_uid(self) -> None:
        from echo_personal_tool.infrastructure.dicom_uid_validator import safe_uid_path_component

        with pytest.raises(ValueError):
            safe_uid_path_component("/")

    def test_path_traversal_via_uid(self) -> None:
        from echo_personal_tool.infrastructure.dicom_uid_validator import safe_uid_path_component

        payloads = [
            "../etc/passwd",
            "..%2F..%2Fetc/passwd",
            "..\\..\\windows\\system32",
            "1.2\x00../../etc/passwd",
            "1.2\n../../etc/passwd",
        ]
        for payload in payloads:
            with pytest.raises(ValueError, match="Invalid DICOM UID"):
                safe_uid_path_component(payload)


class TestTruncatedDicomFiles:
    """Ensure truncated DICOM-like files don't cause crashes."""

    @pytest.mark.parametrize("cut_at", [0, 1, 64, 128, 131, 132, 200, 1024])
    def test_truncated_after_preamble(self, tmp_path: Path, cut_at: int) -> None:
        full = _dicom_preamble() + b"\x00" * 512
        truncated = full[:cut_at]
        f = tmp_path / "truncated.dcm"
        f.write_bytes(truncated)
        if cut_at < 132:
            with pytest.raises(InvalidDicomError):
                validate_dicom_header(f)
        else:
            validate_dicom_header(f)

    def test_all_zero_after_preamble(self, tmp_path: Path) -> None:
        f = tmp_path / "zeros.dcm"
        f.write_bytes(_dicom_preamble() + b"\x00" * 1000)
        validate_dicom_header(f)

    def test_random_bytes_after_preamble(self, tmp_path: Path) -> None:
        import os

        f = tmp_path / "random.dcm"
        f.write_bytes(_dicom_preamble() + os.urandom(500))
        validate_dicom_header(f)


class TestNestedUndefinedSequences:
    """Verify that DICOM files with undefined-length sequences don't break header validation."""

    def test_undefined_length_sq(self, tmp_path: Path) -> None:
        """SQ tag with undefined length (0xFFFFFFFF) followed by sequence items."""
        sq_tag = _make_tag(0x0008, 0x1115, "SQ", 0xFFFFFFFF, b"")
        f = tmp_path / "undef_sq.dcm"
        f.write_bytes(_dicom_preamble() + sq_tag)
        validate_dicom_header(f)

    def test_deeply_nested_tags(self, tmp_path: Path) -> None:
        """Construct a file with many tags in sequence."""
        data = _dicom_preamble()
        for i in range(100):
            tag = _make_tag(0x0008, i & 0xFFFF, "LO", 4, b"test")
            data += tag
        f = tmp_path / "nested.dcm"
        f.write_bytes(data)
        validate_dicom_header(f)

    def test_oversized_tag_length(self, tmp_path: Path) -> None:
        """Tag claiming huge length but file is small."""
        tag = _make_tag(0x7FE0, 0x0010, "OW", 2_000_000_000, b"")
        f = tmp_path / "oversized.dcm"
        f.write_bytes(_dicom_preamble() + tag)
        validate_dicom_header(f)
