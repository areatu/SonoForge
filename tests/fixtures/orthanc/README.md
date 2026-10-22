# Orthanc DICOMweb JSON Fixtures

> [Русская версия](README_RU.md)

Real Orthanc JSON responses for unit tests.

## Structure

```
tests/fixtures/orthanc/
├── README.md                          # This file
├── qido/                              # QIDO-RS responses
│   ├── studies_single.json            # Single study
│   ├── studies_multi.json             # Multiple studies
│   ├── studies_empty.json             # Empty response
│   ├── series_echo.json               # Echo series
│   └── series_ct.json                 # CT series
├── wado/                              # WADO-RS responses
│   ├── instance_metadata.json         # Instance metadata
│   └── instances_echo.json            # Instance list
├── stow/                              # STOW-RS responses
│   ├── success.json                   # Successful upload
│   ├── partial_failure.json           # Partial failure
│   └── all_failed.json                # Complete failure
└── errors/                            # Server errors
    ├── 500_internal.json              # Internal error
    ├── 401_unauthorized.json          # Authentication error
    ├── 404_not_found.json             # Not found
    └── 408_timeout.json               # Timeout
```

## Format

All files follow the DICOM JSON format (DICOM PS3.18 F.2.2):

```json
{
  "00100010": {
    "vr": "PN",
    "Value": [{"Alphabetic": "Doe^John"}]
  }
}
```

## Usage in tests

```python
import json
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures" / "orthanc"


def test_parse_studies():
    with open(FIXTURES / "qido" / "studies_single.json") as f:
        data = json.load(f)
    studies = parse_studies(data)
    assert len(studies) == 1
    assert studies[0].patient_name == "Doe^John"
```

## Updating fixtures

To collect new fixtures from a real Orthanc:

```python
import httpx
import json

ORTHANC = "http://localhost:8042"
resp = httpx.get(f"{ORTHANC}/dicom-web/studies")
with open("tests/fixtures/orthanc/qido/studies_real.json", "w") as f:
    json.dump(resp.json(), f, indent=2, ensure_ascii=False)
```
