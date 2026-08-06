"""Recursive local media directory scanner (DICOM, MP4, JPEG, PNG)."""

from __future__ import annotations

import logging
from collections import defaultdict
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


class LocalMediaDirectoryScanner:
    """Scan folder trees and build study → series → instance hierarchy."""

    def __init__(self, error_log_path: Path | None = None) -> None:
        self._error_log_path = error_log_path

    def scan(self, root: Path) -> list[StudyMetadata]:
        root = root.resolve()
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {root}")

        studies: list[StudyMetadata] = []
        for study_folder in iter_study_roots(root):
            study = self._scan_study_folder(study_folder)
            if study is not None:
                studies.append(study)

        studies.sort(key=lambda s: s.study_datetime or datetime.min, reverse=True)
        return studies

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

            logger.warning(
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

    def _read_dicom_instance(self, path: Path) -> InstanceMetadata | None:
        try:
            validate_dicom_header(path)
            dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        except Exception as exc:  # noqa: BLE001
            self._log_scan_error(path, exc)
            return None

        study_uid = str(dataset.get("StudyInstanceUID", "") or "")
        series_uid = str(dataset.get("SeriesInstanceUID", "") or "")
        if not study_uid or not series_uid:
            self._log_scan_error(path, ValueError("Missing Study/Series UID"))
            return None

        return map_instance_metadata(dataset, path=path)

    def _read_study_uid(self, path: Path) -> str | None:
        try:
            dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        except Exception:
            return None
        value = str(dataset.get("StudyInstanceUID", "") or "")
        return value or None

    def _read_study_datetime(self, path: Path) -> datetime | None:
        try:
            dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        except Exception:
            return None
        try:
            return parse_study_datetime(dataset)
        except Exception:
            return None

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
        message = f"{path}: {exc}"
        logger.warning("Scan skip: %s", message)
        if self._error_log_path is None:
            return
        try:
            with self._error_log_path.open("a", encoding="utf-8") as fh:
                fh.write(message + "\n")
        except OSError:
            logger.exception("Failed to write scan error log")


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
