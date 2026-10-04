"""Build checked source fingerprints off the UI thread; do not persist paths/tags."""

from __future__ import annotations

import hashlib
import json

import pydicom

from echo_personal_tool.infrastructure.measurement_codec import MeasurementStorageError, study_key


def describe_study(study) -> dict:
    study_key(study.study_uid)
    sources = {}
    for series in study.series:
        for instance in series.instances:
            if instance.path is None:
                raise MeasurementStorageError("source")
            path = instance.path
            before = path.stat()
            if instance.media_format == "dicom":
                ds = pydicom.dcmread(path, stop_before_pixels=True)
                if (
                    str(ds.get("StudyInstanceUID", "")) != study.study_uid
                    or str(ds.get("SeriesInstanceUID", "")) != series.series_uid
                    or str(ds.get("SOPInstanceUID", "")) != instance.sop_instance_uid
                ):
                    raise MeasurementStorageError("identity")
                study_key(str(ds.StudyInstanceUID))
                study_key(str(ds.SeriesInstanceUID))
                study_key(str(ds.SOPInstanceUID))
                # Hash only semantic image geometry/calibration, never patient tags or file path.
                keys = (
                    "Rows",
                    "Columns",
                    "NumberOfFrames",
                    "PixelSpacing",
                    "ImagerPixelSpacing",
                    "FrameTime",
                    "FrameTimeVector",
                    "CineRate",
                    "SequenceOfUltrasoundRegions",
                    "SamplesPerPixel",
                    "PhotometricInterpretation",
                    "BitsAllocated",
                )
                header = {key: str(ds.get(key, "")) for key in keys}
                fingerprint = hashlib.sha256(json.dumps(header, sort_keys=True).encode()).hexdigest()
            else:
                digest = hashlib.sha256()
                with path.open("rb") as file:
                    for block in iter(lambda: file.read(1024 * 1024), b""):
                        digest.update(block)
                fingerprint = digest.hexdigest()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise MeasurementStorageError("source")
            source = dict(
                fingerprint=fingerprint,
                frames=instance.number_of_frames,
                spacing=list(instance.pixel_spacing) if instance.pixel_spacing else None,
            )
            uid = instance.sop_instance_uid
            if uid in sources and sources[uid] != source:
                raise MeasurementStorageError("source")
            sources[uid] = source
    return sources
