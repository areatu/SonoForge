"""Safety gates for the opt-in real disk-full harness (never fill the test disk)."""

from types import SimpleNamespace

import pytest
from scripts.measurement_disk_full_harness import MAX_VOLUME_BYTES, validate_volume


def test_harness_requires_explicit_confirmation(tmp_path):
    with pytest.raises(ValueError, match="confirmation"):
        validate_volume(tmp_path, False)
    assert list(tmp_path.iterdir()) == []


def test_harness_refuses_ordinary_directory(tmp_path):
    with pytest.raises(ValueError, match="dedicated_mount"):
        validate_volume(tmp_path, True)


def test_harness_refuses_nonempty_mount(tmp_path, monkeypatch):
    monkeypatch.setattr(type(tmp_path), "is_mount", lambda _: True)
    sentinel = tmp_path / "do-not-touch"
    sentinel.write_bytes(b"untouched")
    with pytest.raises(ValueError, match="empty_non_root"):
        validate_volume(tmp_path, True)
    assert sentinel.read_bytes() == b"untouched"


@pytest.mark.parametrize("total", [0, MAX_VOLUME_BYTES + 1])
def test_harness_refuses_unbounded_volume(tmp_path, monkeypatch, total):
    monkeypatch.setattr(type(tmp_path), "is_mount", lambda _: True)
    monkeypatch.setattr(
        "scripts.measurement_disk_full_harness.shutil.disk_usage", lambda _: SimpleNamespace(total=total)
    )
    with pytest.raises(ValueError, match="safety_limit"):
        validate_volume(tmp_path, True)
    assert list(tmp_path.iterdir()) == []


def test_harness_admits_empty_bounded_mount_without_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(type(tmp_path), "is_mount", lambda _: True)
    monkeypatch.setattr(
        "scripts.measurement_disk_full_harness.shutil.disk_usage", lambda _: SimpleNamespace(total=8 * 1024**2)
    )
    validate_volume(tmp_path, True)
    assert list(tmp_path.iterdir()) == []
