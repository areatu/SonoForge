# Orthanc DICOMweb JSON Fixtures

Реальные JSON-ответы Orthanc для unit-тестов.

## Структура

```
tests/fixtures/orthanc/
├── README.md                          # Этот файл
├── qido/                              # QIDO-RS ответы
│   ├── studies_single.json            # Одно исследование
│   ├── studies_multi.json             # Несколько исследований
│   ├── studies_empty.json             # Пустой ответ
│   ├── series_echo.json               # Серии ЭхоКГ
│   └── series_ct.json                 # Серия КТ
├── wado/                              # WADO-RS ответы
│   ├── instance_metadata.json         # Метаданные инстанса
│   └── instances_echo.json            # Список инстансов
├── stow/                              # STOW-RS ответы
│   ├── success.json                   # Успешная загрузка
│   ├── partial_failure.json           # Частичная ошибка
│   └── all_failed.json                # Полная ошибка
└── errors/                            # Ошибки сервера
    ├── 500_internal.json              # Внутренняя ошибка
    ├── 401_unauthorized.json          # Ошибка аутентификации
    ├── 404_not_found.json             # Не найдено
    └── 408_timeout.json               # Таймаут
```

## Формат

Все файлы соответствуют формату DICOM JSON (DICOM PS3.18 F.2.2):

```json
{
  "00100010": {
    "vr": "PN",
    "Value": [{"Alphabetic": "Doe^John"}]
  }
}
```

## Использование в тестах

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

## Обновление фикстур

Для сбора новых фикстур из реального Orthanc:

```python
import httpx
import json

ORTHANC = "http://localhost:8042"
resp = httpx.get(f"{ORTHANC}/dicom-web/studies")
with open("tests/fixtures/orthanc/qido/studies_real.json", "w") as f:
    json.dump(resp.json(), f, indent=2, ensure_ascii=False)
```
