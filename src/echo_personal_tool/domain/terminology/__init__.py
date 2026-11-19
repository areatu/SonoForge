"""Unified clinical terminology dictionary for outbound interop (#625).

Pure domain package (standard library only): it maps the app's measurement
catalog ids and ASE Table 6 rows to LOINC, UCUM, SNOMED CT and DICOM CID
codes, and converts display units to their canonical UCUM unit explicitly.
No I/O, no Qt, no third-party imports.
"""

from echo_personal_tool.domain.terminology.codes import (
    LOCAL_CODE_SYSTEM,
    LOCAL_CODE_SYSTEM_URI,
    LOINC_SYSTEM,
    LOINC_SYSTEM_URI,
    SNOMED_SYSTEM,
    SNOMED_SYSTEM_URI,
    TerminologyCode,
    code_for,
    code_for_ase_row,
)
from echo_personal_tool.domain.terminology.units import (
    UCUM_SYSTEM,
    ConversionError,
    canonical_ucum_unit,
    convert_value,
    ucum_for_display_unit,
)

__all__ = [
    "LOCAL_CODE_SYSTEM",
    "LOCAL_CODE_SYSTEM_URI",
    "LOINC_SYSTEM",
    "LOINC_SYSTEM_URI",
    "SNOMED_SYSTEM",
    "SNOMED_SYSTEM_URI",
    "UCUM_SYSTEM",
    "ConversionError",
    "TerminologyCode",
    "canonical_ucum_unit",
    "code_for",
    "code_for_ase_row",
    "convert_value",
    "ucum_for_display_unit",
]
