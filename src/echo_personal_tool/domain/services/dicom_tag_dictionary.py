"""Lightweight DICOM tag dictionary for echocardiography.

Pure Python, no pydicom dependency. Lookup by int, hex string, or group/element tuple.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class TagInfo:
    """Metadata for a single DICOM tag."""

    tag: int
    keyword: str
    vr: str
    description: str
    vm: str | None = None


def _t(group: int, elem: int) -> int:
    return (group << 16) | elem


_TAGS: dict[int, TagInfo] = {}

def _add(
    group: int, elem: int, keyword: str,
    vr: str, description: str, vm: str | None = None,
) -> None:
    tag_int = _t(group, elem)
    _TAGS[tag_int] = TagInfo(tag=tag_int, keyword=keyword, vr=vr, description=description, vm=vm)


# ── File Meta Information (0002xxxx) ──────────────────────────────────────────
_add(0x0002, 0x0000, "FileMetaInformationGroupLength", "UL", "File Meta Information Group Length")
_add(0x0002, 0x0001, "FileMetaInformationVersion", "OB", "File Meta Information Version")
_add(0x0002, 0x0002, "MediaStorageSOPClassUID", "UI", "Media Storage SOP Class UID")
_add(0x0002, 0x0003, "MediaStorageSOPInstanceUID", "UI", "Media Storage SOP Instance UID")
_add(0x0002, 0x0010, "TransferSyntaxUID", "UI", "Transfer Syntax UID")
_add(0x0002, 0x0012, "ImplementationClassUID", "UI", "Implementation Class UID")
_add(0x0002, 0x0013, "ImplementationVersionName", "SH", "Implementation Version Name")

# ── Patient (0010xxxx) ────────────────────────────────────────────────────────
_add(0x0010, 0x0000, "PatientGroupLength", "UL", "Patient Group Length")
_add(0x0010, 0x0010, "PatientName", "PN", "Patient's Name")
_add(0x0010, 0x0020, "PatientID", "LO", "Patient ID")
_add(0x0010, 0x0021, "IssuerOfPatientID", "LO", "Issuer of Patient ID")
_add(0x0010, 0x0030, "PatientBirthDate", "DA", "Patient's Birth Date")
_add(0x0010, 0x0032, "PatientBirthTime", "TM", "Patient's Birth Time")
_add(0x0010, 0x0040, "PatientSex", "CS", "Patient's Sex")
_add(0x0010, 0x0101, "OtherPatientIDsSequence", "SQ", "Other Patient IDs Sequence")
_add(0x0010, 0x1000, "OtherPatientIDs", "LO", "Other Patient IDs")
_add(0x0010, 0x1001, "OtherPatientNames", "PN", "Other Patient Names")
_add(0x0010, 0x1010, "PatientAge", "AS", "Patient's Age")
_add(0x0010, 0x1020, "PatientSize", "DS", "Patient's Size")
_add(0x0010, 0x1030, "PatientWeight", "DS", "Patient's Weight")
_add(0x0010, 0x1040, "PatientAddress", "LO", "Patient's Address")
_add(0x0010, 0x2150, "CountryOfResidence", "LO", "Country of Residence")
_add(0x0010, 0x2152, "RegionOfResidence", "LO", "Region of Residence")
_add(0x0010, 0x2180, "PatientMotherBirthName", "SH", "Patient's Mother Birth Name")
_add(0x0010, 0x21B0, "AdditionalPatientHistory", "LT", "Additional Patient History")
_add(0x0010, 0x2297, "ResponsiblePerson", "PN", "Responsible Person")
_add(0x0010, 0x4000, "PatientComments", "LT", "Patient Comments")

# ── General Study (0008xxxx) ──────────────────────────────────────────────────
_add(0x0008, 0x0005, "SpecificCharacterSet", "CS", "Specific Character Set")
_add(0x0008, 0x0008, "ImageType", "CS", "Image Type", "2")
_add(0x0008, 0x0016, "SOPClassUID", "UI", "SOP Class UID")
_add(0x0008, 0x0018, "SOPInstanceUID", "UI", "SOP Instance UID")
_add(0x0008, 0x0020, "StudyDate", "DA", "Study Date")
_add(0x0008, 0x0021, "SeriesDate", "DA", "Series Date")
_add(0x0008, 0x0022, "AcquisitionDate", "DA", "Acquisition Date")
_add(0x0008, 0x0023, "ContentDate", "DA", "Content Date")
_add(0x0008, 0x0030, "StudyTime", "TM", "Study Time")
_add(0x0008, 0x0031, "SeriesTime", "TM", "Series Time")
_add(0x0008, 0x0032, "AcquisitionTime", "TM", "Acquisition Time")
_add(0x0008, 0x0033, "ContentTime", "TM", "Content Time")
_add(0x0008, 0x0050, "AccessionNumber", "SH", "Accession Number")
_add(0x0008, 0x0060, "Modality", "CS", "Modality")
_add(0x0008, 0x0070, "Manufacturer", "LO", "Manufacturer")
_add(0x0008, 0x0080, "InstitutionName", "LO", "Institution Name")
_add(0x0008, 0x0090, "ReferringPhysicianName", "PN", "Referring Physician's Name")
_add(0x0008, 0x1010, "StationName", "SH", "Station Name")
_add(0x0008, 0x1020, "StudyID", "SH", "Study ID")
_add(0x0008, 0x1030, "StudyDescription", "LO", "Study Description")
_add(0x0008, 0x1032, "ProcedureCodeSequence", "SQ", "Procedure Code Sequence")
_add(0x0008, 0x103E, "SeriesDescription", "LO", "Series Description")
_add(0x0008, 0x1050, "PerformingPhysicianName", "PN", "Performing Physician's Name")
_add(0x0008, 0x1070, "OperatorsName", "PN", "Operator's Name")
_add(0x0008, 0x1080, "AdmittingDiagnosesDescription", "LO", "Admitting Diagnoses Description")
_add(0x0008, 0x1090, "ManufacturerModelName", "LO", "Manufacturer's Model Name")

# ── General Series (0020xxxx) ─────────────────────────────────────────────────
_add(0x0020, 0x000D, "StudyInstanceUID", "UI", "Study Instance UID")
_add(0x0020, 0x000E, "SeriesInstanceUID", "UI", "Series Instance UID")
_add(0x0020, 0x0010, "StudyID", "SH", "Study ID")
_add(0x0020, 0x0011, "SeriesNumber", "IS", "Series Number")
_add(0x0020, 0x0013, "InstanceNumber", "IS", "Instance Number")
_add(0x0020, 0x0020, "PatientOrientation", "CS", "Patient Orientation")
_add(0x0020, 0x0032, "ImagePositionPatient", "DS", "Image Position (Patient)", "3")
_add(0x0020, 0x0037, "ImageOrientationPatient", "DS", "Image Orientation (Patient)", "6")
_add(0x0020, 0x0052, "FrameOfReferenceUID", "UI", "Frame of Reference UID")
_add(0x0020, 0x0105, "NumberOfTemporalPositions", "IS", "Number of Temporal Positions")
_add(0x0020, 0x1041, "SliceLocation", "DS", "Slice Location")
_add(0x0020, 0x1042, "ImageComments", "IS", "Image Comments")
_add(0x0020, 0x1209, "NumberOfSeriesRelatedInstances", "IS", "Number of Series Related Instances")

# ── Frame of Reference (0020xxxx continued) ───────────────────────────────────
_add(0x0020, 0x1002, "NumberOfFrames", "IS", "Number of Frames")
_add(0x0020, 0x4000, "ImageComments_", "LT", "Image Comments (retired)")

# ── General Image (0020xxxx continued) ────────────────────────────────────────
_add(0x0020, 0x9111, "TemporalPositionIndex", "US", "Temporal Position Index")
_add(0x0020, 0x9128, "TemporalPositionNumberOfFrames", "UL", "Temporal Position Number of Frames")
_add(0x0020, 0x9156, "FrameAcquisitionNumber", "IS", "Frame Acquisition Number")
_add(0x0020, 0x9157, "DimensionIndexValues", "UL", "Dimension Index Values")
_add(0x0020, 0x9211, "ActualFrameAcquisitionNumber", "IS", "Actual Frame Acquisition Number")
_add(0x0020, 0x9245, "DimensionIndexPointer", "AT", "Dimension Index Pointer")
_add(0x0020, 0x9246, "FunctionalGroupPointer", "AT", "Functional Group Pointer")

# ── Image Pixel (0028xxxx) ───────────────────────────────────────────────────
_add(0x0028, 0x0002, "SamplesPerPixel", "US", "Samples per Pixel")
_add(0x0028, 0x0004, "PhotometricInterpretation", "CS", "Photometric Interpretation")
_add(0x0028, 0x0008, "NumberOfFrames", "IS", "Number of Frames")
_add(0x0028, 0x0010, "Rows", "US", "Rows")
_add(0x0028, 0x0011, "Columns", "US", "Columns")
_add(
    0x0028, 0x0014, "UltrasoundColorDataRepresentation",
    "US", "Ultrasound Color Data Representation",
)
_add(0x0028, 0x0030, "PixelSpacing", "DS", "Pixel Spacing", "2")
_add(0x0028, 0x0034, "PixelAspectRatio", "IS", "Pixel Aspect Ratio", "2")
_add(0x0028, 0x0100, "BitsAllocated", "US", "Bits Allocated")
_add(0x0028, 0x0101, "BitsStored", "US", "Bits Stored")
_add(0x0028, 0x0102, "HighBit", "US", "High Bit")
_add(0x0028, 0x0103, "PixelRepresentation", "US", "Pixel Representation")
_add(0x0028, 0x0301, "BurnedInAnnotation", "CS", "Burned In Annotation")
_add(0x0028, 0x1050, "WindowCenter", "DS", "Window Center")
_add(0x0028, 0x1051, "WindowWidth", "DS", "Window Width")
_add(0x0028, 0x1052, "RescaleIntercept", "DS", "Rescale Intercept")
_add(0x0028, 0x1053, "RescaleSlope", "DS", "Rescale Slope")
_add(0x0028, 0x1054, "RescaleType", "LO", "Rescale Type")
_add(0x0028, 0x1055, "WindowCenterAndWidthExplanation", "LO", "Window Center & Width Explanation")

# ── Modality LUT (0028xxxx continued) ────────────────────────────────────────
_add(0x0028, 0x1056, "VOILUTFunction", "CS", "VOI LUT Function")
_add(0x0028, 0x1090, "RecommendedViewingMode", "CS", "Recommended Viewing Mode")
_add(
    0x0028, 0x1101, "RedPaletteColorLookupTableDescriptor",
    "US", "Red Palette Color LUT Descriptor",
)
_add(
    0x0028, 0x1102,
    "GreenPaletteColorLookupTableDescriptor",
    "US", "Green Palette Color LUT Descriptor",
)
_add(
    0x0028, 0x1103,
    "BluePaletteColorLookupTableDescriptor",
    "US", "Blue Palette Color LUT Descriptor",
)
_add(0x0028, 0x1221, "ColorSpace", "CS", "Color Space")

# ── CT / MR Image (0028xxxx continued) ──────────────────────────────────────
_add(0x0028, 0x1300, "AcquisitionCircumstances", "CS", "Acquisition Circumstances")

# ── Cine (0028xxxx continued) ────────────────────────────────────────────────
_add(0x0028, 0x0040, "LossyImageCompression", "CS", "Lossy Image Compression")
_add(0x0028, 0x0041, "LossyImageCompressionRatio", "DS", "Lossy Image Compression Ratio")
_add(0x0028, 0x0042, "LossyImageCompressionMethod", "CS", "Lossy Image Compression Method")

# ── Device (0018xxxx) ─────────────────────────────────────────────────────────
_add(0x0018, 0x0015, "BodyPartExamined", "CS", "Body Part Examined")
_add(0x0018, 0x0050, "SliceThickness", "DS", "Slice Thickness")
_add(0x0018, 0x0060, "KVP", "DS", "KVP")
_add(0x0018, 0x0088, "SpacingBetweenSlices", "DS", "Spacing Between Slices")
_add(0x0018, 0x1030, "ProtocolName", "LO", "Protocol Name")
_add(0x0018, 0x1034, "ContrastBolusAgent", "LO", "Contrast/Bolus Agent")
_add(0x0018, 0x1050, "SpatialResolution", "DS", "Spatial Resolution")
_add(0x0018, 0x1060, "TriggerTime", "DS", "Trigger Time")
_add(0x0018, 0x1081, "LowRRValue", "IS", "Low R-R Interval")
_add(0x0018, 0x1082, "HighRRValue", "IS", "High R-R Interval")
_add(0x0018, 0x1088, "HeartRate", "IS", "Heart Rate")
_add(0x0018, 0x1090, "CardiacNumberOfImages", "IS", "Cardiac Number of Images")
_add(0x0018, 0x1094, "TriggerWindow", "IS", "Trigger Window")
_add(0x0018, 0x1100, "ReconstructionDiameter", "DS", "Reconstruction Diameter")
_add(0x0018, 0x1110, "DistanceSourceToDetector", "DS", "Distance Source to Detector")
_add(0x0018, 0x1111, "DistanceSourceToPatient", "DS", "Distance Source to Patient")
_add(0x0018, 0x1120, "GantryTilt", "DS", "Gantry Tilt")
_add(0x0018, 0x1130, "TableHeight", "DS", "Table Height")
_add(0x0018, 0x1131, "TablePosition", "DS", "Table Position")
_add(0x0018, 0x1150, "ExposureTime", "IS", "Exposure Time")
_add(0x0018, 0x1151, "XrayTubeCurrent", "IS", "X-ray Tube Current")
_add(0x0018, 0x1152, "Exposure", "IS", "Exposure")
_add(0x0018, 0x1210, "ConvolutionKernel", "SH", "Convolution Kernel")
_add(0x0018, 0x1310, "AcquisitionMatrix", "US", "Acquisition Matrix", "4")
_add(0x0018, 0x1312, "InPlanePhaseEncodingDirection", "CS", "In-plane Phase Encoding Direction")
_add(0x0018, 0x1314, "FlipAngle", "DS", "Flip Angle")
_add(0x0018, 0x1316, "SAR", "DS", "Specific Absorption Rate")

# ── Ultrasound (0018xxxx) ────────────────────────────────────────────────────
_add(0x0018, 0x6000, "Sensitivity", "DS", "Sensitivity")
_add(0x0018, 0x6004, "FrameRate", "DS", "Frame Rate")
_add(0x0018, 0x6008, "TransducerFrequency", "DS", "Transducer Frequency")
_add(0x0018, 0x6011, "TransducerType", "CS", "Transducer Type")
_add(
    0x0018, 0x6014, "TransducerBeamFormerCodeDesignation",
    "LO", "Transducer Beam Former Code Designation",
)
_add(0x0018, 0x6016, "TransducerApplication", "LO", "Transducer Application")
_add(0x0018, 0x6030, "PulseRepetitionFrequency", "DS", "Pulse Repetition Frequency")
_add(0x0018, 0x6034, "DopplerCorrectionAngle", "DS", "Doppler Correction Angle")
_add(0x0018, 0x6036, "SteeringAngle", "DS", "Steering Angle")
_add(0x0018, 0x603C, "DopplerSampleVolumeXPosition", "IS", "Doppler Sample Volume X Position")
_add(0x0018, 0x603E, "DopplerSampleVolumeYPosition", "IS", "Doppler Sample Volume Y Position")
_add(0x0018, 0x6040, "DopplerGatePositionX", "IS", "Doppler Gate Position X")
_add(0x0018, 0x6042, "DopplerGatePositionY", "IS", "Doppler Gate Position Y")

# ── Sequence of Ultrasound Regions (0018xxxx continued) ──────────────────────
_add(0x0018, 0x6011, "SequenceOfUltrasoundRegions", "SQ", "Sequence of Ultrasound Regions")
_add(0x0018, 0x6012, "RegionSpatialFormat", "US", "Region Spatial Format")
_add(0x0018, 0x6013, "RegionDataType", "US", "Region Data Type")
_add(0x0018, 0x6014, "RegionMinX", "UL", "Region Min X")
_add(0x0018, 0x6015, "RegionMinY", "UL", "Region Min Y")
_add(0x0018, 0x6016, "RegionMaxX", "UL", "Region Max X")
_add(0x0018, 0x6017, "RegionMaxY", "UL", "Region Max Y")
_add(0x0018, 0x6018, "RegionPhysicalDeltaX", "FD", "Region Physical Delta X")
_add(0x0018, 0x601C, "RegionPhysicalDeltaY", "FD", "Region Physical Delta Y")
_add(0x0018, 0x6020, "PhysicalUnitsXDirection", "US", "Physical Units X Direction")
_add(0x0018, 0x6022, "PhysicalUnitsYDirection", "US", "Physical Units Y Direction")
_add(0x0018, 0x6024, "ReferencePixelX0", "IS", "Reference Pixel X0")
_add(0x0018, 0x6026, "ReferencePixelY0", "IS", "Reference Pixel Y0")
_add(0x0018, 0x6028, "ReferencePixelX1", "FD", "Reference Pixel X1")
_add(0x0018, 0x602A, "ReferencePixelY1", "FD", "Reference Pixel Y1")
_add(0x0018, 0x602C, "PhysicalDeltaX", "FD", "Physical Delta X")
_add(0x0018, 0x602E, "PhysicalDeltaY", "FD", "Physical Delta Y")

# ── M-Mode (0018xxxx continued) ──────────────────────────────────────────────
_add(0x0018, 0x6050, "M-modeSamplingFrequency", "DS", "M-mode Sampling Frequency")
_add(0x0018, 0x6052, "M-modeTimeOffset", "DS", "M-mode Time Offset")
_add(0x0018, 0x6054, "M-modePeakVelocity", "DS", "M-mode Peak Velocity")

# ── Acquisition / Content (0008xxxx continued) ──────────────────────────────
_add(0x0008, 0x002A, "AcquisitionDateTime", "DT", "Acquisition Date/Time")
_add(0x0008, 0x0071, "AcquisitionContrast", "CS", "Acquisition Contrast")
_add(0x0008, 0x1072, "PhysicianOfRecord", "PN", "Physician(s) of Record")
_add(0x0008, 0x107E, "PhysicianOfReadingStudy", "PN", "Physician(s) Reading Study")
_add(
    0x0008, 0x109A,
    "ReferencedPerformedProcedureStepSequence",
    "SQ", "Referenced Performed Procedure Step Sequence",
)

# ── Equipment (0018xxxx continued) ──────────────────────────────────────────
_add(0x0018, 0x1000, "DeviceSerialNumber", "LO", "Device Serial Number")
_add(0x0018, 0x1020, "SoftwareVersions", "LO", "Software Versions")
_add(0x0018, 0x1030, "ProtocolName", "LO", "Protocol Name")
_add(0x0018, 0x1040, "ContrastBolusRoute", "LO", "Contrast/Bolus Route")
_add(0x0018, 0x1042, "ContrastBolusStartVolumeNumber", "IS", "Contrast/Bolus Start Volume Number")
_add(0x0018, 0x1044, "ContrastBolusStopVolumeNumber", "IS", "Contrast/Bolus Stop Volume Number")
_add(0x0018, 0x1046, "ContrastBolusTotalDose", "DS", "Contrast/Bolus Total Dose")
_add(0x0018, 0x1048, "ContrastBolusIngredient", "CS", "Contrast/Bolus Ingredient")
_add(
    0x0018, 0x1049,
    "ContrastBolusIngredientConcentration",
    "DS", "Contrast/Bolus Ingredient Concentration",
)

# ── Display Shutter / Film (0018xxxx continued) ──────────────────────────────
_add(0x0018, 0x7000, "SafetyMode", "CS", "Safety Mode")
_add(0x0018, 0x7001, "DetectorConfiguration", "CS", "Detector Configuration")

# ── SOP Common (0008xxxx continued) ──────────────────────────────────────────
_add(0x0008, 0x0018, "SOPInstanceUID", "UI", "SOP Instance UID")
_add(0x0008, 0x0016, "SOPClassUID", "UI", "SOP Class UID")
_add(0x0008, 0x0100, "AffectedSOPClassUID", "UI", "Affected SOP Class UID")
_add(0x0008, 0x0101, "RequestedSOPClassUID", "UI", "Requested SOP Class UID")
_add(0x0008, 0x0102, "AffectedSOPInstanceUID", "UI", "Affected SOP Instance UID")
_add(0x0008, 0x0110, "RetiredUID", "UI", "Retired UID")

# ── Common Sequence Tags ─────────────────────────────────────────────────────
_add(0x0008, 0x1115, "ReferencedSeriesSequence", "SQ", "Referenced Series Sequence")
_add(0x0008, 0x1120, "ReferencedStudySequence", "SQ", "Referenced Study Sequence")
_add(0x0008, 0x1130, "ReferencedPatientSequence", "SQ", "Referenced Patient Sequence")
_add(0x0008, 0x1140, "ReferencedImageSequence", "SQ", "Referenced Image Sequence")
_add(0x0008, 0x1150, "ReferencedSOPClassUIDInFile", "UI", "Referenced SOP Class UID in File")
_add(0x0008, 0x1155, "ReferencedSOPInstanceUIDInFile", "UI", "Referenced SOP Instance UID in File")
_add(0x0008, 0x1160, "ReferencedFrameNumber", "IS", "Referenced Frame Number")
_add(0x0008, 0x1199, "ReferencedSOPSequence", "SQ", "Referenced SOP Sequence")
_add(0x0008, 0x120A, "ReferencedAccessionSequence", "SQ", "Referenced Accession Sequence")

# ── Common Functional Groups Sequence (5200xxxx) ─────────────────────────────
_add(
    0x5200, 0x9229, "SharedFunctionalGroupsSequence",
    "SQ", "Shared Functional Groups Sequence",
)
_add(
    0x5200, 0x9230, "PerFrameFunctionalGroupsSequence",
    "SQ", "Per-Frame Functional Groups Sequence",
)
_add(0x5200, 0x9232, "FrameContentSequence", "SQ", "Frame Content Sequence")

# ── Pixel Measures Sequence (0028xxxx / 5200xxxx) ────────────────────────────
_add(0x0028, 0x9110, "PixelMeasuresSequence", "SQ", "Pixel Measures Sequence")
_add(0x0028, 0x9132, "FrameVOILUTSequence", "SQ", "Frame VOI LUT Sequence")
_add(0x0028, 0x9145, "RealWorldValueMappingSequence", "SQ", "Real World Value Mapping Sequence")

# ── LUT Sequence ─────────────────────────────────────────────────────────────
_add(0x0028, 0x3010, "VOILUTSequence", "SQ", "VOI LUT Sequence")
_add(0x0028, 0x3006, "LUTData", "OW/US", "LUT Data")
_add(0x0028, 0x3002, "LUTDescriptor", "US", "LUT Descriptor", "3")

# ── Encapsulated Document (0042xxxx) ─────────────────────────────────────────
_add(0x0042, 0x0010, "DocumentTitle", "CS", "Document Title")
_add(0x0042, 0x0011, "BurnedInAnnotation", "CS", "Burned In Annotation")
_add(0x0042, 0x0012, "ContentSequence", "SQ", "Content Sequence")
_add(0x0042, 0x0013, "ContentTemplateSequence", "SQ", "Content Template Sequence")

# ── Application State (0070xxxx) ─────────────────────────────────────────────
_add(
    0x0070, 0x005A,
    "DisplayAreaTopLeftHandCornerTrial",
    "DS", "Display Area Top Left Hand Corner (Trial)",
)
_add(
    0x0070, 0x005B,
    "DisplayAreaBottomRightHandCornerTrial",
    "DS", "Display Area Bottom Right Hand Corner (Trial)",
)
_add(
    0x0070, 0x0275,
    "GraphicLayerRecommendedDisplayGrayscaleValue",
    "US", "Graphic Layer Recommended Display Grayscale Value",
)

# ── Digital Signature (0400xxxx) ─────────────────────────────────────────────
_add(0x0400, 0x0550, "DataSetTrailingPadding", "UT", "Dataset Trailing Padding")

# ── Waveform (5400xxxx) ──────────────────────────────────────────────────────
_add(0x5400, 0x0100, "WaveformSampleValue", "US/SS", "Waveform Sample Value")

# ── Common Private Tags (vendor-specific but widely used in echo) ────────────
_add(0x0009, 0x0010, "PrivateCreator", "LO", "Private Creator")
_add(0x0029, 0x0010, "PrivateCreator_", "LO", "Private Creator (0029)")
_add(0x0039, 0x0010, "PrivateCreator__", "LO", "Private Creator (0039)")

# ── Retired but still encountered in legacy echo equipment ────────────────────
_add(0x0010, 0x0022, "IssuerOfPatientID", "LO", "Issuer of Patient ID")
_add(0x0020, 0x000D, "StudyInstanceUID", "UI", "Study Instance UID")
_add(0x0020, 0x000E, "SeriesInstanceUID", "UI", "Series Instance UID")

# ── Common US/SOP Class UIDs ─────────────────────────────────────────────────
_add(0x0002, 0x0002, "MediaStorageSOPClassUID", "UI", "Media Storage SOP Class UID")
_add(0x0008, 0x0016, "SOPClassUID", "UI", "SOP Class UID")


# ─── Public API ───────────────────────────────────────────────────────────────

def lookup(tag_number_or_hex: int | str | tuple[int, int]) -> TagInfo | None:
    """Look up a DICOM tag by integer, hex string, or (group, element) tuple.

    Examples::

        lookup(0x00100010)
        lookup("00100010")
        lookup((0x0010, 0x0010))
    """
    if isinstance(tag_number_or_hex, int):
        return _TAGS.get(tag_number_or_hex)
    if isinstance(tag_number_or_hex, tuple):
        group, elem = tag_number_or_hex
        return _TAGS.get(_t(group, elem))
    if isinstance(tag_number_or_hex, str):
        tag_int = int(tag_number_or_hex, 16)
        return _TAGS.get(tag_int)
    return None


def all_tags() -> Iterator[TagInfo]:
    """Iterate over all registered tags, ordered by tag number."""
    for key in sorted(_TAGS):
        yield _TAGS[key]


def search_by_keyword(pattern: str) -> list[TagInfo]:
    """Return tags whose keyword contains *pattern* (case-insensitive)."""
    lower = pattern.lower()
    return [info for info in _TAGS.values() if lower in info.keyword.lower()]


# ─── Module-level constants for the most common echo tags ─────────────────────
_TAG_CONSTANTS: dict[str, int] = {}

def _define_constant(name: str, tag_int: int) -> None:
    globals()[name] = tag_int
    _TAG_CONSTANTS[name] = tag_int


_define_constant("PATIENT_NAME", 0x00100010)
_define_constant("PATIENT_ID", 0x00100020)
_define_constant("PATIENT_BIRTH_DATE", 0x00100030)
_define_constant("PATIENT_SEX", 0x00100040)
_define_constant("PATIENT_AGE", 0x00101010)
_define_constant("PATIENT_WEIGHT", 0x00101030)
_define_constant("PATIENT_SIZE", 0x00101020)
_define_constant("STUDY_DATE", 0x00080020)
_define_constant("STUDY_TIME", 0x00080030)
_define_constant("STUDY_DESCRIPTION", 0x00081030)
_define_constant("STUDY_INSTANCE_UID", 0x0020000D)
_define_constant("STUDY_ID", 0x00200010)
_define_constant("ACCESSION_NUMBER", 0x00080050)
_define_constant("MODALITY", 0x00080060)
_define_constant("MANUFACTURER", 0x00080070)
_define_constant("INSTITUTION_NAME", 0x00080080)
_define_constant("REFERENCING_PHYSICIAN", 0x00080090)
_define_constant("STATION_NAME", 0x00081010)
_define_constant("MANUFACTURER_MODEL_NAME", 0x00081090)
_define_constant("SERIES_DESCRIPTION", 0x0008103E)
_define_constant("SERIES_NUMBER", 0x00200011)
_define_constant("SERIES_INSTANCE_UID", 0x0020000E)
_define_constant("INSTANCE_NUMBER", 0x00200013)
_define_constant("NUMBER_OF_SERIES_RELATED_INSTANCES", 0x00201209)
_define_constant("SOP_INSTANCE_UID", 0x00080018)
_define_constant("SOP_CLASS_UID", 0x00080016)
_define_constant("IMAGE_TYPE", 0x00080008)
_define_constant("SPECIFIC_CHARACTER_SET", 0x00080005)
_define_constant("CONTENT_DATE", 0x00080023)
_define_constant("CONTENT_TIME", 0x00080033)
_define_constant("ACQUISITION_DATE", 0x00080022)
_define_constant("ACQUISITION_TIME", 0x00080032)
_define_constant("ACQUISITION_DATETIME", 0x0008002A)
_define_constant("ROWS", 0x00280010)
_define_constant("COLUMNS", 0x00280011)
_define_constant("BITS_ALLOCATED", 0x00280100)
_define_constant("BITS_STORED", 0x00280101)
_define_constant("HIGH_BIT", 0x00280102)
_define_constant("PIXEL_REPRESENTATION", 0x00280103)
_define_constant("PIXEL_SPACING", 0x00280030)
_define_constant("SAMPLES_PER_PIXEL", 0x00280002)
_define_constant("PHOTOMETRIC_INTERPRETATION", 0x00280004)
_define_constant("WINDOW_CENTER", 0x00281050)
_define_constant("WINDOW_WIDTH", 0x00281051)
_define_constant("RESCALE_INTERCEPT", 0x00281052)
_define_constant("RESCALE_SLOPE", 0x00281053)
_define_constant("FRAME_OF_REFERENCE_UID", 0x00200052)
_define_constant("SLICE_LOCATION", 0x00201041)
_define_constant("IMAGE_POSITION_PATIENT", 0x00200032)
_define_constant("IMAGE_ORIENTATION_PATIENT", 0x00200037)
_define_constant("FRAME_RATE", 0x00186004)
_define_constant("FRAME_OF_REF_POSITION", 0x00200032)
_define_constant("NUMBER_OF_FRAMES", 0x00280008)
_define_constant("PIXEL_ASPECT_RATIO", 0x00280034)
_define_constant("BURNED_IN_ANNOTATION", 0x00280301)
_define_constant("CONTRAST_BOLUS_AGENT", 0x00181030)
_define_constant("BODY_PART_EXAMINED", 0x00180015)
_define_constant("SLICE_THICKNESS", 0x00180050)
_define_constant("RECONSTRUCTION_DIAMETER", 0x00181100)
_define_constant("GANTRY_TILT", 0x00181120)
_define_constant("TABLE_HEIGHT", 0x00181130)
_define_constant("HEART_RATE", 0x00181088)
_define_constant("CARDIAC_NUMBER_OF_IMAGES", 0x00181090)
_define_constant("TRIGGER_TIME", 0x00181060)
_define_constant("PROTOCOL_NAME", 0x00181030)
_define_constant("DEVICE_SERIAL_NUMBER", 0x00181000)
_define_constant("SOFTWARE_VERSIONS", 0x00181020)
_define_constant("TRANSUCER_FREQUENCY", 0x00186008)
_define_constant("SHARED_FUNCTIONAL_GROUPS_SEQUENCE", 0x52009229)
_define_constant("PER_FRAME_FUNCTIONAL_GROUPS_SEQUENCE", 0x52009230)
_define_constant("PIXEL_MEASURES_SEQUENCE", 0x00289110)
_define_constant("LOSSY_IMAGE_COMPRESSION", 0x00280040)
_define_constant("OPERATORS_NAME", 0x00081070)
_define_constant("SPATIAL_RESOLUTION", 0x00181050)
_define_constant("SEQUENCE_OF_ULTRASOUND_REGIONS", 0x00186011)

# ─── Expose constants for introspection ──────────────────────────────────────
TAG_CONSTANTS: dict[str, int] = dict(_TAG_CONSTANTS)
