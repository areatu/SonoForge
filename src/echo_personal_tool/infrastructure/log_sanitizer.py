"""Logging sanitization utilities for PHI/PII protection."""

from __future__ import annotations

import re
from pathlib import Path

# DICOM and patient-search metadata frequently appears in exceptions as
# ``PatientID=value`` or ``(0010,0020)=value``. Keep the key for context, but
# drop its complete value up to a conventional field separator.
_PHI_FIELD = re.compile(
    r"(?i)(?P<key>\b(?:patient[\s_]*(?:name|id|birth[\s_]*date|birth[\s_]*time|sex|address|telephone|comments)|"
    r"accession[\s_]*(?:number|no)?|(?:study|series|sop)[\s_]*(?:instance[\s_]*)?uid|"
    r"referring[\s_]*physician(?:[\s_]*name)?|performing[\s_]*physician(?:[\s_]*name)?|"
    r"institution(?:[\s_]*name)?|medical[\s_]*record[\s_]*(?:number|no)|mrn|"
    r"other[\s_]*patient[\s_]*(?:id|name))\b\s*[:=]\s*)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^,;\r\n}\]]*)"
)
_DICOM_TAG_FIELD = re.compile(
    r"(?i)(?P<key>\(?(?:0010|0008|0020|0040|0080|0090),[0-9a-f]{4}\)?\s*[:=]\s*)"
    r"(?P<value>.*?)(?=\s+\(?[0-9a-f]{4},[0-9a-f]{4}\)?\s*[:=]|$)",
    re.MULTILINE,
)
_DICOM_UID = re.compile(r"(?<![0-9A-Za-z])\d+(?:\.\d+){2,}(?![0-9A-Za-z])")
_WINDOWS_PATH = re.compile(r"""(?i)(?<![A-Za-z0-9])(?:[A-Z]:\\|\\\\)[^\r\n"'<>|,;:)}\]]+""")
_POSIX_PATH = re.compile(r"""(?<![\w])/[^\r\n"'<>|,;)}\]]+""")
_URL = re.compile(r"(?i)\b(?:https?|dicomweb)://[^\s\"'<>]+")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_MEDIA_FILENAME = re.compile(
    r"(?i)(?<![\w/\\.-])[^\s\"'<>|,;]+\.(?:dcm|dicom|mp4|avi|mov|jpg|jpeg|png|bmp|tif|tiff|"
    r"csv|xlsx?|json|xml|txt|pdf|zip|ya?ml|html?)\b"
)


def sanitize_uid(uid: str, keep: int = 16) -> str:
    """Truncate DICOM UID for safe logging."""
    if len(uid) <= keep:
        return uid
    return uid[:keep] + "..."


def sanitize_path(path: Path) -> str:
    """Return only filename, not full path with potential PHI."""
    return path.name


def sanitize_log_text(text: str) -> str:
    """Mask common identifiers and filesystem locations in diagnostic text.

    Support archives call this on every log payload. The filters cover DICOM
    identity attributes, UIDs, patient media filenames, email addresses, URLs,
    and absolute Windows/POSIX paths while retaining timestamps, logger names,
    exception types, and source-code line numbers.
    """
    clean = _PHI_FIELD.sub(lambda match: f"{match.group('key')}<redacted>", text)
    clean = _DICOM_TAG_FIELD.sub(lambda match: f"{match.group('key')}<redacted>", clean)
    clean = _URL.sub("<url>", clean)
    clean = _EMAIL.sub("<email>", clean)
    clean = _WINDOWS_PATH.sub("<path>", clean)
    clean = _POSIX_PATH.sub("<path>", clean)
    clean = _DICOM_UID.sub("<dicom-uid>", clean)
    clean = _MEDIA_FILENAME.sub("<media-file>", clean)
    return clean
