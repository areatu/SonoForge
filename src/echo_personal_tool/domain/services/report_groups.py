"""The vocabulary of report groups — a leaf both report modules import.

A report is printed in anatomical groups (left ventricle, mitral valve, the
derived calculations, ...), and two domain services need the very same ids:

* :mod:`echo_personal_tool.domain.services.report_builder` assigns a group to
  every value it collects and orders the groups of the sheet;
* :mod:`echo_personal_tool.domain.services.report_profiles` says which groups a
  format prints — a generic ultrasound protocol drops the cardiology chambers.

If the ids lived in the builder, the formats imported the builder and the
builder imported the formats back to resolve ``profile_id``: a circle, and a
circle is what the import-graph guard of issue 328 forbids (two modules that
cannot be read or tested apart).  So the ids live here, in a leaf that imports
nothing from the report layer, and both sides take them from it.

The key is also the i18n suffix: ``report.group.<key>`` is the localised title
of the group, so renaming an id renames a translation key and changes saved
documents — an id is part of the data, not a private detail.
"""

from __future__ import annotations

#: Anatomical groups in report order. The key is also the i18n suffix.
GROUP_LEFT_VENTRICLE = "lv"
GROUP_LEFT_ATRIUM = "la"
GROUP_RIGHT_VENTRICLE = "rv"
GROUP_RIGHT_ATRIUM = "ra"
GROUP_MITRAL_VALVE = "mv"
GROUP_AORTIC_VALVE = "av"
GROUP_TRICUSPID_VALVE = "tv"
GROUP_VESSELS = "vessels"
GROUP_PLANIMETRY = "planimetry"
GROUP_CALCULATIONS = "calculations"
GROUP_OTHER = "other"

#: The order the groups are printed in, whatever order the values arrived in.
GROUP_ORDER: tuple[str, ...] = (
    GROUP_LEFT_VENTRICLE,
    GROUP_LEFT_ATRIUM,
    GROUP_RIGHT_VENTRICLE,
    GROUP_RIGHT_ATRIUM,
    GROUP_MITRAL_VALVE,
    GROUP_AORTIC_VALVE,
    GROUP_TRICUSPID_VALVE,
    GROUP_VESSELS,
    GROUP_PLANIMETRY,
    GROUP_CALCULATIONS,
    GROUP_OTHER,
)
