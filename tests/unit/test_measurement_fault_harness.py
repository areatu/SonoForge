"""Safety gates for the opt-in real disk-full harness (never fill the test disk)."""

from types import SimpleNamespace

import pytest
from scripts.measurement_disk_full_harness import MAX_VOLUME_BYTES, _is_mount_root, validate_volume


def test_harness_requires_explicit_confirmation(tmp_path):
    with pytest.raises(ValueError, match="confirmation"):
        validate_volume(tmp_path, False)
    assert list(tmp_path.iterdir()) == []


def test_harness_refuses_ordinary_directory(tmp_path):
    with pytest.raises(ValueError, match="dedicated_mount"):
        validate_volume(tmp_path, True)


def test_harness_refuses_nonempty_mount(tmp_path, monkeypatch):
    import scripts.measurement_disk_full_harness as harness

    # Patch the harness-level probe: on win32 the native volume-root probe
    # (not Path.is_mount) decides whether the path counts as a mount root.
    monkeypatch.setattr(harness, "_is_mount_root", lambda _: True)
    sentinel = tmp_path / "do-not-touch"
    sentinel.write_bytes(b"untouched")
    with pytest.raises(ValueError, match="empty_non_root"):
        validate_volume(tmp_path, True)
    assert sentinel.read_bytes() == b"untouched"


@pytest.mark.parametrize("total", [0, MAX_VOLUME_BYTES + 1])
def test_harness_refuses_unbounded_volume(tmp_path, monkeypatch, total):
    import scripts.measurement_disk_full_harness as harness

    monkeypatch.setattr(harness, "_is_mount_root", lambda _: True)
    monkeypatch.setattr(
        "scripts.measurement_disk_full_harness.shutil.disk_usage", lambda _: SimpleNamespace(total=total)
    )
    with pytest.raises(ValueError, match="safety_limit"):
        validate_volume(tmp_path, True)
    assert list(tmp_path.iterdir()) == []


def test_harness_admits_empty_bounded_mount_without_writing(tmp_path, monkeypatch):
    import scripts.measurement_disk_full_harness as harness

    monkeypatch.setattr(harness, "_is_mount_root", lambda _: True)
    monkeypatch.setattr(
        "scripts.measurement_disk_full_harness.shutil.disk_usage", lambda _: SimpleNamespace(total=8 * 1024**2)
    )
    validate_volume(tmp_path, True)
    assert list(tmp_path.iterdir()) == []


def test_harness_refuses_unsupported_mount_probe(tmp_path, monkeypatch):
    def unsupported(_):
        raise NotImplementedError("Path.is_mount() is unsupported on this system")

    monkeypatch.setattr(type(tmp_path), "is_mount", unsupported)
    with pytest.raises(ValueError, match="dedicated_mount_required"):
        validate_volume(tmp_path, True)
    assert list(tmp_path.iterdir()) == []


def test_windows_mount_probe_accepts_only_the_native_volume_root(tmp_path, monkeypatch):
    import scripts.measurement_disk_full_harness as harness

    monkeypatch.setattr(harness.sys, "platform", "win32")
    monkeypatch.setattr(harness, "_windows_volume_root", lambda _path: r"X:\\")
    monkeypatch.setattr(harness.os.path, "abspath", lambda value: str(value))
    monkeypatch.setattr(harness.os.path, "normcase", lambda value: value.lower())
    assert _is_mount_root(type(tmp_path)(r"X:\\"))
    assert not _is_mount_root(type(tmp_path)(r"X:\\subdir"))


@pytest.mark.parametrize(("drive", "accepted"), [("C:", False), ("W:", True)])
def test_windows_volume_root_excludes_system_drive(tmp_path, monkeypatch, drive, accepted):
    import scripts.measurement_disk_full_harness as harness

    monkeypatch.setattr(harness.sys, "platform", "win32")
    monkeypatch.setattr(harness, "_is_mount_root", lambda _: True)
    monkeypatch.setattr(harness, "_only_os_volume_metadata", lambda _: True)
    monkeypatch.setattr(harness.os.path, "splitdrive", lambda _: (drive, ""))
    monkeypatch.setattr(
        "scripts.measurement_disk_full_harness.shutil.disk_usage", lambda _: SimpleNamespace(total=8 * 1024**2)
    )
    monkeypatch.setenv("SystemDrive", "C:")
    if accepted:
        validate_volume(type(tmp_path)("/"), True)
    else:
        with pytest.raises(ValueError, match="empty_non_root"):
            validate_volume(type(tmp_path)("/"), True)


def test_harness_allows_only_known_os_metadata_on_native_mount(tmp_path, monkeypatch):
    import scripts.measurement_disk_full_harness as harness

    monkeypatch.setattr(harness.sys, "platform", "darwin")
    monkeypatch.setattr(type(tmp_path), "is_mount", lambda _: True)
    metadata = tmp_path / ".fseventsd"
    metadata.mkdir()
    monkeypatch.setattr(
        "scripts.measurement_disk_full_harness.shutil.disk_usage", lambda _: SimpleNamespace(total=8 * 1024**2)
    )
    validate_volume(tmp_path, True)
    payload = tmp_path / "user-data"
    payload.write_text("leave me alone")
    with pytest.raises(ValueError, match="empty_non_root"):
        validate_volume(tmp_path, True)
    assert payload.read_text() == "leave me alone"
