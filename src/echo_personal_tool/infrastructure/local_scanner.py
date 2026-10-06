"""Recursive local media directory scanner (DICOM, MP4, JPEG, PNG)."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import pydicom

from echo_personal_tool.domain.models import (
    InstanceMetadata,
    SeriesMetadata,
    StudyMetadata,
)
from echo_personal_tool.infrastructure.dicom_metadata_mapper import (
    map_instance_metadata,
    parse_study_datetime,
)
from echo_personal_tool.infrastructure.dicom_validator import validate_dicom_header
from echo_personal_tool.infrastructure.instance_sort import sort_instances, sort_series_list
from echo_personal_tool.infrastructure.media_formats import (
    MediaFormat,
    detect_media_format,
    is_ignored_scan_path,
    is_media_file,
)
from echo_personal_tool.infrastructure.media_metadata_mapper import (
    JPEG_SERIES_DESCRIPTION,
    MP4_SERIES_DESCRIPTION,
    map_image_instance,
    map_mp4_instance,
    synthetic_series_uid,
    synthetic_study_uid,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _HeaderInfo:
    """The few header fields the scanner needs after the first parse (Э3).

    Caching the whole ``Dataset`` would keep every header of a large folder in
    memory; these three fields are enough for the study split and the datetime.
    """

    study_uid: str
    series_uid: str
    study_datetime: datetime | None


_SAFE_SCAN_EXTENSIONS = frozenset(
    {".dcm", ".dicom", ".mp4", ".avi", ".mov", ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
)


class LocalMediaDirectoryScanner:
    """Scan folder trees and build study → series → instance hierarchy."""

    def __init__(self, error_log_path: Path | None = None) -> None:
        self._error_log_path = error_log_path
        #: path → parsed header fields (or ``None`` when the file was rejected).
        #: Filled during ``scan()`` so every DICOM is read once per scan (П.4).
        self._header_info: dict[Path, _HeaderInfo | None] = {}

    def scan(self, root: Path) -> list[StudyMetadata]:
        root = root.resolve()
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {root}")
        # Never reuse headers across scans: files may have been replaced.
        self._header_info.clear()

        studies: list[StudyMetadata] = []
        for study_folder in iter_study_roots(root):
            study = self._scan_study_folder(study_folder)
            if study is not None:
                studies.extend(self._split_verified_studies(study, study_folder))

        studies.sort(key=lambda s: s.study_datetime or datetime.min, reverse=True)
        return studies

    def _split_verified_studies(self, study: StudyMetadata, folder: Path) -> list[StudyMetadata]:
        """A folder is not a patient identity. Never assign every file the first UID."""
        groups: dict[str, dict[str, list[InstanceMetadata]]] = defaultdict(lambda: defaultdict(list))
        dates = {}
        for series in study.series:
            for instance in series.instances:
                if instance.media_format == "dicom":
                    uid = self._read_study_uid(instance.path)
                    if not uid:
                        continue
                    dates.setdefault(uid, self._read_study_datetime(instance.path) or study.study_datetime)
                else:
                    uid = synthetic_study_uid(folder)
                groups[uid][series.series_uid].append(instance)
        output = []
        for uid, series_map in groups.items():
            series = tuple(
                SeriesMetadata(
                    series_uid=key,
                    study_uid=uid,
                    modality=items[0].modality,
                    description=items[0].series_description,
                    instances=tuple(items),
                )
                for key, items in series_map.items()
            )
            output.append(
                replace(study, study_uid=uid, series=series, study_datetime=dates.get(uid, study.study_datetime))
            )
        return output

    def _scan_study_folder(self, study_folder: Path) -> StudyMetadata | None:
        dicom_by_series: dict[str, list[InstanceMetadata]] = defaultdict(list)
        mp4_instances: list[InstanceMetadata] = []
        image_instances: list[InstanceMetadata] = []

        study_uid: str | None = None
        study_datetime: datetime | None = None
        study_uids_seen: set[str] = set()

        for path in iter_media_files(study_folder):
            media_format = detect_media_format(path)
            if media_format is None:
                continue

            if media_format == "dicom":
                instance = self._read_dicom_instance(path)
                if instance is None:
                    continue
                dicom_by_series[instance.series_uid].append(instance)
                dataset_study_uid = self._read_study_uid(path)
                if dataset_study_uid:
                    study_uids_seen.add(dataset_study_uid)
                    if study_uid is None:
                        study_uid = dataset_study_uid
                        study_datetime = self._read_study_datetime(path)
                continue

            resolved_study_uid = study_uid or synthetic_study_uid(study_folder)
            if media_format == "mp4":
                instance = self._read_mp4_instance(path, study_folder, resolved_study_uid)
                if instance is not None:
                    mp4_instances.append(instance)
            elif media_format in ("jpeg", "png"):
                instance = self._read_image_instance(
                    path,
                    study_folder,
                    resolved_study_uid,
                    media_format,
                )
                if instance is not None:
                    image_instances.append(instance)

        if not dicom_by_series and not mp4_instances and not image_instances:
            return None

        if len(study_uids_seen) > 1:
            from echo_personal_tool.infrastructure.log_sanitizer import sanitize_uid

            logger.debug(
                "Multiple StudyInstanceUID values in %s: %s",
                study_folder,
                ", ".join(sanitize_uid(u) for u in sorted(study_uids_seen)),
            )

        resolved_study_uid = study_uid or synthetic_study_uid(study_folder)
        resolved_study_datetime = study_datetime or datetime.fromtimestamp(study_folder.stat().st_mtime)

        series_list: list[SeriesMetadata] = []
        for series_uid, instances in dicom_by_series.items():
            instances_sorted = sort_instances(instances)
            first = instances_sorted[0]
            series_list.append(
                SeriesMetadata(
                    series_uid=series_uid,
                    study_uid=resolved_study_uid,
                    modality=first.modality,
                    description=first.series_description,
                    instances=instances_sorted,
                )
            )

        if mp4_instances:
            mp4_sorted = sort_instances(mp4_instances)
            series_list.append(
                SeriesMetadata(
                    series_uid=synthetic_series_uid(study_folder, "mp4"),
                    study_uid=resolved_study_uid,
                    modality="US",
                    description=MP4_SERIES_DESCRIPTION,
                    instances=mp4_sorted,
                )
            )

        if image_instances:
            image_sorted = sort_instances(image_instances)
            series_list.append(
                SeriesMetadata(
                    series_uid=synthetic_series_uid(study_folder, "jpeg"),
                    study_uid=resolved_study_uid,
                    modality="US",
                    description=JPEG_SERIES_DESCRIPTION,
                    instances=image_sorted,
                )
            )

        sort_series_list(series_list)
        return StudyMetadata(
            study_uid=resolved_study_uid,
            study_datetime=resolved_study_datetime,
            series=tuple(series_list),
        )

    def _parse_header(self, path: Path) -> tuple[object | None, _HeaderInfo | None]:
        """Read and validate a DICOM header once per file per scan.

        Returns ``(dataset, info)``; the dataset is not retained (a folder with
        thousands of clips would otherwise keep every header alive), only the
        three fields other code paths need.  ``(None, None)`` means the file was
        rejected and the error was already logged.
        """
        if path in self._header_info:
            return None, self._header_info[path]
        try:
            validate_dicom_header(path)
            dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        except Exception as exc:  # noqa: BLE001
            self._log_scan_error(path, exc)
            self._header_info[path] = None
            return None, None
        study_datetime: datetime | None
        try:
            study_datetime = parse_study_datetime(dataset)
        except Exception:  # noqa: BLE001 - a malformed date must not drop the file
            study_datetime = None
        info = _HeaderInfo(
            study_uid=str(dataset.get("StudyInstanceUID", "") or ""),
            series_uid=str(dataset.get("SeriesInstanceUID", "") or ""),
            study_datetime=study_datetime,
        )
        self._header_info[path] = info
        return dataset, info

    def _read_dicom_instance(self, path: Path) -> InstanceMetadata | None:
        dataset, info = self._parse_header(path)
        if dataset is None or info is None:
            return None
        study_uid = info.study_uid
        series_uid = info.series_uid
        if not study_uid or not series_uid:
            self._log_scan_error(path, ValueError("Missing Study/Series UID"))
            self._header_info[path] = None
            return None

        pixel_data = None
        if "NumberOfFrames" not in dataset:
            # The header read skipped pixels; a vendor may have omitted
            # (0028,0008) NumberOfFrames on a genuinely multi-frame clip.  Do a
            # one-off full read so the frame count can be inferred from pixels.
            try:
                full = pydicom.dcmread(path, force=True)
            except Exception:  # noqa: BLE001
                full = None
            if full is not None and hasattr(full, "PixelData"):
                pixel_data = bytes(full.PixelData)

        return map_instance_metadata(dataset, path=path, pixel_data=pixel_data)

    def _read_study_uid(self, path: Path) -> str | None:
        _, info = self._parse_header(path)
        if info is None:
            return None
        return info.study_uid or None

    def _read_study_datetime(self, path: Path) -> datetime | None:
        _, info = self._parse_header(path)
        return info.study_datetime if info is not None else None

    def _read_mp4_instance(
        self,
        path: Path,
        study_folder: Path,
        study_uid: str,
    ) -> InstanceMetadata | None:
        try:
            return map_mp4_instance(
                path,
                study_folder=study_folder,
                study_uid=study_uid,
                series_uid=synthetic_series_uid(study_folder, "mp4"),
            )
        except Exception as exc:  # noqa: BLE001
            self._log_scan_error(path, exc)
            return None

    def _read_image_instance(
        self,
        path: Path,
        study_folder: Path,
        study_uid: str,
        media_format: MediaFormat,
    ) -> InstanceMetadata | None:
        try:
            return map_image_instance(
                path,
                study_folder=study_folder,
                study_uid=study_uid,
                series_uid=synthetic_series_uid(study_folder, "jpeg"),
                media_format=media_format,
            )
        except Exception as exc:  # noqa: BLE001
            self._log_scan_error(path, exc)
            return None

    def _log_scan_error(self, path: Path, exc: Exception) -> None:
        # Do not persist patient folder names, media filenames, UIDs, or parser
        # exception text. The format and exception class are enough to diagnose
        # unsupported/corrupt inputs without recording PHI.
        extension = path.suffix.lower()
        safe_format = extension if extension in _SAFE_SCAN_EXTENSIONS else "unknown"
        message = f"format={safe_format} error={type(exc).__name__}"
        logger.warning("Scan skipped media (%s)", message)
        if self._error_log_path is None:
            return
        try:
            self._error_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._error_log_path.open("a", encoding="utf-8") as fh:
                fh.write(message + "\n")
        except OSError:
            logger.exception("Failed to write central scan error log")


LocalDicomDirectoryScanner = LocalMediaDirectoryScanner


def has_media(folder: Path) -> bool:
    return any(iter_media_files(folder))


def has_media_in_directory(folder: Path, *, recursive: bool) -> bool:
    if recursive:
        return any(iter_media_files(folder))
    for path in folder.iterdir():
        if path.is_file() and is_media_file(path):
            return True
    return False


def iter_media_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if is_ignored_scan_path(path):
            continue
        if is_media_file(path):
            yield path


def iter_study_roots(root: Path) -> list[Path]:
    media_in_root = has_media_in_directory(root, recursive=False)
    child_dirs = sorted(
        (path for path in root.iterdir() if path.is_dir() and has_media(path)),
        key=lambda path: path.name,
    )
    if child_dirs and not media_in_root:
        return child_dirs
    return [root]
