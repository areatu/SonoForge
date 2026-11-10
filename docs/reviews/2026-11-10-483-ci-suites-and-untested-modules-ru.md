# Снимок выполнения #483 — подключение тестовых наборов в CI, покрытие воркеров и ratchet непокрытых модулей

> **Снимок на 2026-11-10.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

Задача: `#483` (фаза 4 эпика `#485`, `docs/reviews/2026-11-09-weakness-analysis-ru.md`, §2.7).

## 1. Подключение ранее не исполнявшихся тестовых каталогов

| Каталог / файлы | Где запускается теперь | Режим |
|---|---|---|
| `tests/exploratory/` | Обязательная джоба `test-exploratory` в `.github/workflows/ci.yml` + агрегирующий гейт `test` | Детерминированный профиль Hypothesis `ci` (`max_examples=40`, `derandomize=True`) |
| `tests/exploratory/` (глубокий прогон) | `.github/workflows/nightly-suites.yml` (`schedule` + `workflow_dispatch`) | Профиль Hypothesis `nightly` (`max_examples=500`, `derandomize=False`) |
| `tests/compat/test_windows_paths.py` | `test-logic (windows-latest, 3.11)` в `.github/workflows/ci.yml` | Нативный Windows runner (исправлен тестовый путь UNC с фиктивного `\\127.0.0.1\share\` на реальный loopback/Win32 `\\?\`) |
| `tests/compat/test_display_server.py` | `test-exploratory (ubuntu-latest, 3.11)` в `.github/workflows/ci.yml` | Оба режима: headless `QT_QPA_PLATFORM=offscreen` и реальный `xvfb-run` (`xcb`) |
| `tests/integration/test_dicom_reader.py` и `tests/test_*.py` | `test-exploratory (ubuntu-latest, 3.11)` в `.github/workflows/ci.yml` | На каждый PR/push (убран хардкод `.venv/lib/python3.11/...` в `test_upload_flow.py`) |
| `tests/integration/test_orthanc_live.py` | `.github/workflows/nightly-suites.yml` (`integration-orthanc`) | Живой контейнер `orthancteam/orthanc:24.12.0` в `services:` (DICOMweb + DIMSE с предзагрузкой синтетического DICOM) |
| `tests/system/` | `.github/workflows/nightly-suites.yml` (`system`) | Чистые runner'ы `ubuntu-latest` и `windows-latest` |
| `tests/interactive/` | Ручная диагностика (задокументировано в `tests/README.md` и `tests/README_RU.md`) | Маркер `@pytest.mark.interactive` |

Добавлен тест `test_every_test_directory_is_wired_into_a_workflow_or_marked_manual` в `tests/unit/test_untested_modules_ratchet.py`, не позволяющий добавить новый каталог `tests/<subdir>/test_*.py` мимо workflow.

## 2. Поведенческие тесты приоритетных модулей и ratchet `audit_untested_modules.py`

Написаны поведенческие юнит-тесты для **5** ранее не покрытых модулей (все проходят `scripts/check_test_signal.py` без `smoke`-исключений):

1. `application/workers/dcm_export_worker.py` → `tests/unit/test_dcm_export_worker.py` (100 % строк: побайтовая копия файла, экспорт диапазона кадров MONOCHROME2 и RGB в Explicit VR Little Endian, зажатие границ, батчинг прогресса, код `export_failed` и отсутствие утечки PHI в лог).
2. `domain/services/roi_validator.py` → `tests/unit/test_roi_validator.py` (100 % строк: валидный спектрограммный ROI с горизонтальными линиями сетки, отбраковка узких/низких/высоких/верхних/выходящих за кадр и B-mode регионов без сетки).
3. `application/workers/orthanc_enrichment_worker.py` → `tests/unit/test_orthanc_enrichment_worker.py` (100 % строк: постраничный `batch`, финальный `finished`, приведение не-словаря к `None`, санитизация ошибок через `safe_error_category` и устойчивость к удалённым Qt-сигналам).
4. `domain/calculations/simpson_contours.py` → `tests/unit/test_simpson_contours.py` (100 % строк: анизотропный пересчёт пикселей в мм с митральным кольцом и фильтрация/группировка контуров).
5. `presentation/window_chrome/caption_drag.py` → `tests/unit/test_caption_drag.py` (GUI-жесты перетаскивания заголовка, защита клиентской зоны, `CAPTION_MOVE_ENABLED` и системной рамки).

Добавлен AST-храповик `scripts/audit_untested_modules.py` + `scripts/untested_modules_baseline.json` (потолок снижен с **25 до 20** модулей; `application/workers/` и `ui/` доведены до **0** непокрытых модулей), подключённый в `lint` с отчётом в GitHub Step Summary.

## 3. Помодульные пороги покрытия для `application/workers/*`

В джобу `coverage` (`.github/workflows/ci.yml`) добавлены:
- суммарный порог `coverage report --include='src/echo_personal_tool/application/workers/*' --fail-under=82` (фактическое покрытие пакета воркеров после добавления тестов — **~85 %**);
- скрипт `.github/scripts/check_worker_coverage.py` с **помодульным порогом `>= 65 %`** для каждого непустого файла в `application/workers/` (минимальный модуль сейчас — `71 %`) и таблицей в GitHub Step Summary.
