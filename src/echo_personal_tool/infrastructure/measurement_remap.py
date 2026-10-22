"""Explicit local-media import only: never auto-restore by filename or guess IDs.

The v1–v4 local descriptor contains a full raw-byte SHA-256 (therefore also
binds encoded geometry/timing), decoded frame count and spacing. DICOM's header
fingerprint is NOT a content hash and may never enter this matching path.
"""

from __future__ import annotations

from dataclasses import replace

from echo_personal_tool.infrastructure.measurement_codec import MeasurementStorageError, validate_data

INSTANCE_FIELDS = (
    "doppler_by_instance",
    "doppler_by_instance_frame",
    "doppler_calibration_by_instance",
    "doppler_calibration_by_instance_frame",
    "mmode_calibration_by_instance",
    "cine_segment_roi_by_instance",
    "manual_spacing_by_instance",
    "mmode_time_by_instance",
    "simpson_area_by_frame",
)


def prepare_import(record: dict, study, sources: dict) -> tuple[dict, int]:
    """Return a detached replacement and remapped-source count, or refuse.

    Same-identity imports keep the strict existing descriptor contract. Crossing
    identities is allowed only between local studies, with a complete one-to-one
    content match. Even byte-identical duplicates are ambiguous: no greedy match.
    The caller owns preview/confirmation, fresh hashing and the write barrier.
    """
    uid = study.study_uid
    old_sources = record["sources"]
    if record["study_uid"] == uid and all(sources.get(k) == v for k, v in old_sources.items()):
        return record, 0
    if not record["study_uid"].startswith("local:") or not uid.startswith("local:"):
        raise MeasurementStorageError("identity" if record["study_uid"] != uid else "source")
    instances = [i for series in study.series for i in series.instances]
    if not old_sources or not instances or any(i.media_format == "dicom" for i in instances):
        raise MeasurementStorageError("source")
    live = {i.sop_instance_uid: i for i in instances}
    if len(live) != len(instances) or set(live) != set(sources):
        raise MeasurementStorageError("source")

    def signature(descriptor):
        return (descriptor["fingerprint"], descriptor["frames"], tuple(descriptor["spacing"] or ()))

    # Uniqueness is by full content hash, not by path or by decoder metadata.
    old_hashes = [d["fingerprint"] for d in old_sources.values()]
    if len(set(old_hashes)) != len(old_hashes):
        raise MeasurementStorageError("source")
    by_hash: dict[str, list[str]] = {}
    for key, descriptor in sources.items():
        by_hash.setdefault(descriptor["fingerprint"], []).append(key)
    mapping = {}
    for old_uid, descriptor in old_sources.items():
        matches = by_hash.get(descriptor["fingerprint"], [])
        if len(matches) != 1 or signature(sources[matches[0]]) != signature(descriptor):
            raise MeasurementStorageError("source")
        mapping[old_uid] = matches[0]

    data = record["data"]
    values = {
        field: tuple(replace(item, sop_instance_uid=mapping[item.sop_instance_uid]) for item in getattr(data, field))
        for field in ("contours", "linear_measurements", "vessel_measurements")
    }
    for field in INSTANCE_FIELDS:
        values[field] = tuple((mapping[entry[0]], *entry[1:]) for entry in getattr(data, field))

    def mapped(key):
        if key not in mapping:
            raise MeasurementStorageError("source")
        return mapping[key]

    provenance = []
    for prov in data.result_provenance:
        source = prov.source
        if source is not None:
            if source.study_uid != record["study_uid"]:
                raise MeasurementStorageError("source")
            if source.sop_instance_uid:
                new_sop = mapped(source.sop_instance_uid)
                if source.fingerprint and source.fingerprint != old_sources[source.sop_instance_uid]["fingerprint"]:
                    raise MeasurementStorageError("source")
                source = replace(source, study_uid=uid, sop_instance_uid=new_sop, series_uid=live[new_sop].series_uid)
            else:
                # A series-only dependency has no trustworthy old-series mapping.
                if source.series_uid:
                    raise MeasurementStorageError("source")
                source = replace(source, study_uid=uid)
        calibration = tuple(
            replace(c, source_instance_uid=mapped(c.source_instance_uid)) if c.source_instance_uid else c
            for c in prov.calibration
        )
        provenance.append(replace(prov, source=source, calibration=calibration))
    values["result_provenance"] = tuple(provenance)
    remapped_sources = {mapping[k]: v for k, v in old_sources.items()}
    remapped_data = replace(data, **values)
    validate_data(remapped_data, remapped_sources)
    return {**record, "study_uid": uid, "sources": remapped_sources, "data": remapped_data}, len(mapping)
