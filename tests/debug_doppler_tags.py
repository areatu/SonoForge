"""Диагностика допплер-тегов в DICOM-файле."""

import sys
from pathlib import Path

import pydicom


def dump_doppler_tags(path: Path) -> None:
    ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)

    print(f"\n=== {path.name} ===")

    # Базовая информация
    print(f"Modality: {ds.get('Modality')}")
    print(f"Manufacturer: {ds.get('Manufacturer')}")
    print(f"ManufacturerModelName: {ds.get('ManufacturerModelName')}")
    print(f"SamplesPerPixel: {ds.get('SamplesPerPixel')}")
    print(f"NumberOfFrames: {ds.get('NumberOfFrames')}")

    # ImageType (критично для определения, что это спектральный допплер)
    print(f"ImageType: {ds.get('ImageType')}")

    # VelocityScale / VelocityRange — альтернативные теги для скорости
    print("\n--- Velocity tags ---")
    print(f"(0018,6020) VelocityScale: {ds.get('VelocityScale', 'N/A')}")
    print(f"(0018,6050) VelocityRange: {ds.get('VelocityRange', 'N/A')}")
    print(f"(0018,9018) BaselineShift: {ds.get('BaselineShift', 'N/A')}")

    # SequenceOfUltrasoundRegions — главный источник
    regions = ds.get("SequenceOfUltrasoundRegions")
    if not regions:
        print("\n⚠ SequenceOfUltrasoundRegions ОТСУТСТВУЕТ!")
        print("Возможно, калибровка только через VelocityScale + VelocityRange")
        return

    print(f"\n--- SequenceOfUltrasoundRegions ({len(regions)} шт.) ---")
    for i, r in enumerate(regions):
        print(f"\n[Region {i}]")
        print(
            f"  (0018,6012) RegionSpatialFormat: {r.get('RegionSpatialFormat')} (3=spectral, 4=M-mode, 1=2D, 5=color flow)"
        )
        print(f"  (0018,6013) RegionDataType:    {r.get('RegionDataType')} (2=spectral, 17=tissue, 1=B-mode, 0=color)")
        print(f"  (0018,6014) RegionFlags:       {r.get('RegionFlags')}")

        # Bounds
        print(
            f"  Bounds: X[{r.get('RegionLocationMinX0')}..{r.get('RegionLocationMaxX1')}], "
            f"Y[{r.get('RegionLocationMinY0')}..{r.get('RegionLocationMaxY1')}]"
        )

        # Physical deltas — САМОЕ ВАЖНОЕ
        print(f"  (0018,6018) RegionPhysicalDeltaX:   {r.get('RegionPhysicalDeltaX')}  (шаг по X)")
        print(f"  (0018,601A) RegionPhysicalUnitsX:   {r.get('RegionPhysicalUnitsX')}  (ожидаем 3=s или 4=мс)")
        print(f"  (0018,601C) RegionPhysicalDeltaY:   {r.get('RegionPhysicalDeltaY')}  (шаг по Y)")
        print(f"  (0018,601E) RegionPhysicalUnitsY:   {r.get('RegionPhysicalUnitsY')}  (ожидаем 5=cm/s или 6=mm/s)")

        # Альтернативные теги (Philips иногда пишет сюда)
        print(f"  (0018,6020) RegionDataType2:        {r.get('RegionDataType2', 'N/A')}")
        print(f"  ReferencePixelX0:  {r.get('ReferencePixelX0', 'N/A')}")
        print(f"  ReferencePixelY0:  {r.get('ReferencePixelY0', 'N/A')}")
        print(f"  PhysicalUnitsXDirection: {r.get('PhysicalUnitsXDirection', 'N/A')}")
        print(f"  PhysicalUnitsYDirection: {r.get('PhysicalUnitsYDirection', 'N/A')}")

    # Pulse repetition frequency
    print("\n--- Доп. теги ---")
    print(f"PulseRepetitionFrequency: {ds.get('PulseRepetitionFrequency', 'N/A')}")
    print(f"DopplerCorrectionAngle: {ds.get('DopplerCorrectionAngle', 'N/A')}")
    print(f"WallFilter: {ds.get('WallFilter', 'N/A')}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        dump_doppler_tags(Path(p))
