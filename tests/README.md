# Tests

Тесты SonoForge: юнит, интеграционные, приёмочные, регрессионные, миграционные,
безопасность, совместимость и бенчмарки.

## Структура

| Папка | Описание |
|-------|----------|
| `unit/` | ~333 файла юнит-тестов: domain, infrastructure, application, presentation |
| `integration/` | Реальный DICOM и живой Orthanc (`ECHO_ORTHANC=1`) |
| `acceptance/` | Сквозные пользовательские сценарии (`ECHO_ACCEPTANCE=1`) |
| `regression/` | Снапшотные и golden-file регрессии (контуры, допплер, M-Mode) |
| `migration/` | Миграции данных, совместимость схем, резервные копии |
| `security/` | SAST/DAST, фаззинг, анонимизация (`ECHO_SECURITY=1`) |
| `system/` | Black-box тесты установленного приложения (`ECHO_SYSTEM=1`) |
| `compat/` | Совместимость ОС/платформ (`ECHO_COMPAT=1`) |
| `exploratory/` | Property-based и фаззинг-исследования |
| `interactive/` | Ручная диагностика сегментации cine (по умолчанию исключены: `-m 'not interactive'` в `pyproject.toml`) |
| `bench/` | Производительность: декодирование, память, сеть, pipeline, playback, прокрутка, рендеринг (`ECHO_BENCH=1`) |
| `benchmark/` | pytest-benchmark эталоны ядерных операций |
| `fixtures/` | Тестовые данные и генераторы (см. ниже) |

В корне `tests/` также лежат сквозные модули: `test_smoke.py`,
`test_annotation_chain.py`, `test_dicom_tag_dictionary.py`,
`test_samsung_tick_calibration.py`, `test_upload_flow.py`,
`test_vendor_profiles*.py`, общий `conftest.py` и отладочный хелпер
`debug_doppler_tags.py`.

## Запуск

```bash
# Весь набор (без interactive)
python -m pytest tests/ -x -q

# Только юнит-тесты
python -m pytest tests/unit/ -x -q

# Отдельные группы (переменные окружения включают соответствующие маркеры)
ECHO_ORTHANC=1    python -m pytest tests/integration/ -v
ECHO_ACCEPTANCE=1 python -m pytest tests/acceptance/ -v
ECHO_SECURITY=1   python -m pytest tests/security/ -v
ECHO_SYSTEM=1     python -m pytest tests/system/ -v
ECHO_COMPAT=1     python -m pytest tests/compat/ -v
ECHO_BENCH=1      python -m pytest tests/bench/ -v

# Эталоны производительности
python -m pytest tests/benchmark/ --benchmark-json=results.json

# GUI-тесты (в CI обычно исключаются)
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -m gui
```

Обёртка для проблемных окружений (кириллические пути, неактивируемый venv):
[`scripts/run_tests.sh`](../scripts/run_tests.sh) — сам выставляет
`PYTHONPATH` и `QT_QPA_PLATFORM=offscreen`.

## Фикстуры (`fixtures/`)

| Путь | Описание |
|------|----------|
| `generate_synthetic_dicom.py` | Генерация синтетических DICOM |
| `generate_synthetic_media.py` | Генерация MP4/JPEG тестовых данных |
| `orthanc/` | Моки ответов Orthanc API (+ пример `sample.dcm`) |
| `reference_manifest.json` | Тестовый манифест справочника |
| `ste_phantom.py` | Генератор синтетического STE-фантома |
| `for_pero/` | Компактные фикстуры из реальных клипов — см. [`for_pero/README.md`](fixtures/for_pero/README.md); контракт к ним проверяет `unit/test_ste_real_clips.py` |

## Юнит-тесты (`unit/`)

Покрывают:
- Модели данных (Contour, Doppler, Speckle, MMode)
- Расчёты (Simpson, Bernoulli, Teichholz, BSA, RWT, FAC)
- Инфраструктуру (DICOM, Orthanc, ONNX, DIMSE)
- Презентационный слой (Viewer, M-Mode, Doppler, STE)
- Безопасность (валидация, PHI-фильтрация, TLS)
