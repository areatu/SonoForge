# #325, срез 3: `attr-defined` включён — `disable_error_code` больше нет

Дата: 2026-11-01. Продолжение срезов 1–2
(`docs/reviews/2026-11-01-325-type-ignore-ratchet-ru.md`,
`docs/reviews/2026-11-01-325-disable-error-code-ru.md`). Issue: #325.

## Точка старта

После среза 2 в `[tool.mypy]` оставался один выключенный код ошибок:

```toml
disable_error_code = ["attr-defined"]
```

Измерение в среде job `lint` дало **39 находок в 14 файлах**. В отличие от
`misc`/`untyped-decorator`, это оказались не стилистические придирки, а в
основном код, который не мог работать так, как написано.

## 1. Реальные дефекты, которые прятал выключенный код

| Файл | Находка | Что было не так |
|---|---|---|
| `system_profiler.py` | `QOpenGLContext has no attribute "destroy"` | В Qt 6 метода `destroy()` нет. Вызов сидел в `finally` под `except Exception`, поэтому **каждый** запуск писал `AttributeError` в лог и ничего не освобождал. Метод убран, `doneCurrent()` оставлен, контекст освобождает Python. |
| `runtime_setup.py` | `type[Qt] has no attribute "WindowContextHelpButtonHint"` / `"SmoothTransformation"` | Устаревшее обращение к перечислениям через `Qt`. Заменено на `Qt.WindowType.WindowContextHelpButtonHint` и `Qt.TransformationMode.SmoothTransformation`. |
| `dicom_tag_dictionary.py` | 9 импортов констант, которых «нет» | Модуль создавал 75 констант через `globals()[name] = tag_int`. Для Python они существовали, для mypy, IDE и `from ... import` — нет. Константы выписаны явными аннотированными присваиваниями (`PATIENT_NAME: int = 0x00100010`), `TAG_CONSTANTS` собирается из пространства имён, так что числа остаются в одном месте. |
| `measurement_repository.py` | `Module has no attribute "locking"/"LK_NBLCK"` | Ветка Windows проверялась стабами Linux и потому «не существовала». Проверка переведена с `os.name == "nt"` на `sys.platform == "win32"` — mypy сужает платформенные блоки и проверяет Windows-ветку по Windows-стабам. Поведение то же. |
| `dicom_io.py` | `properties_extractor` «не экспортирует» `PropertiesSnapshot` | Реэкспорт из `infrastructure` через импорт-импорт. Теперь `PropertiesSnapshot` берётся из своего модуля — `domain.models.properties_snapshot`, что и правильнее по слоям. |

## 2. Контракты вместо `object`

| Файл | Было | Стало |
|---|---|---|
| `dimse_client.py` | `_associate() -> object`, шесть обращений `assoc.send_c_*`/`release` непроверяемы | Protocol `_Association` с восемью членами, которые клиент реально использует (`is_established`, `release`, `abort`, `send_c_echo/find/get/move/store`); возвращаемые объекты pynetdicom остаются `Any`, потому что стабов у библиотеки нет |
| `logging_setup.py` | `stream: object`, `_crash_stream: object \| None` (9 находок) | `TextIO` для потока и `_SanitizingCrashStream \| None` для слота сессии |
| `dicom_doppler_calibration.py`, `vendor_calibration_bridge.py` | `regions: object` | `Sequence[Dataset]` (`| None` там, где вызывающий может передать `None`) |
| `playback_diagnostics.py` | `.items()` на `object` | `isinstance(by_dtype, dict)` — сужение вместо предположения |
| `speckle_worker.py` | один локальный `all_frames` получал и `ndarray`, и `list` | явная аннотация `np.ndarray \| list[np.ndarray]`: mypy больше не выводит тип по первой ветке |
| `thumbnail_loader_worker.py` | `reader` из mp4-ветки переиспользован для DICOM | отдельная переменная `dicom_reader` |

## 3. Внешние API, которые стubs описывают иначе, чем рантайм

- `pydicom.pixels.pixel_array` — `pydicom` реэкспортирует функцию неявно; импорт
  теперь из определяющего модуля: `from pydicom.pixels.utils import pixel_array as _pixel_array`.
- `cv2.VideoWriter_fourcc` — в OpenCV 5 рантайм-атрибут остался, а стабы его
  больше не объявляют. Вызов читается через
  `getattr(cv2, "VideoWriter_fourcc", None) or cv2.VideoWriter.fourcc`: работает
  на 4.x и 5.x, и не требует подавления.

## 4. Паритет окружений (иначе гейт врёт)

После включения `attr-defined` всплыла вторая сторона проблемы, найденной в
срезе 1: job `lint` ставит только `PySide6`, `numpy`, `opencv-python-headless`,
`pydicom`, `types-PyYAML`, а на машине разработчика стоят **все** зависимости.
С реальными пакетами локально появлялись находки, которых CI не видит
(`openjpeg.decode`, четыре имени `pynetdicom.sop_class`, несовместимость
`Association` с протоколом).

Лечение — новый override в `pyproject.toml`: `follow_imports = "skip"` для всех
третьих библиотек, которых нет в среде `lint` (`onnxruntime`, `scipy`,
`pyqtgraph`, `pylibjpeg*`, `openjpeg`, `pynetdicom`, `httpx`, `psutil`,
`reportlab`, `openpyxl`, `keyring`, `cryptography`, `PIL`). Эти библиотеки
остаются `Any` **в обоих** окружениях, поэтому разработчик и CI получают один и
тот же ответ, вместо «проверяется у меня, невидимо в CI».

Цена решения названа прямо: типы этих библиотек в dev-окружении больше не
проверяются. Компенсация — протоколы и точные аннотации на границе
(`_Association`, `Sequence[Dataset]`, `TextIO`), они и держат контракт.

## 5. Итоговое состояние `[tool.mypy]`

```toml
[[tool.mypy.overrides]]   # application
disallow_untyped_defs = false
disallow_incomplete_defs = false
check_untyped_defs = true
warn_return_any = false
warn_unused_ignores = true
disallow_untyped_calls = false
```

То же для `infrastructure`. **`disable_error_code` больше нет ни в одном
override'е.** Оставшиеся послабления относятся к тому, сколько кода
аннотировано (`disallow_untyped_defs`), а не к тому, какие ошибки репортятся.

Тест `test_no_error_code_stays_disabled` фиксирует это: ни
`disable_error_code`, ни `ignore_errors`, а `check_untyped_defs` и
`warn_unused_ignores` — `true` в обоих пакетах.

## Приёмка #325

- [x] Новый bare-`type: ignore` валит CI (срез 1).
- [x] Счётчик подавлений только уменьшается: **252 (64 bare) в 78 файлах**
      (было 295/94).
- [x] `warn_unused_ignores` + `check_untyped_defs` для `application` и
      `infrastructure` (срез 1).
- [x] `disable_error_code` снят полностью (срезы 2–3).
- [ ] `disallow_untyped_defs`/`disallow_incomplete_defs` для
      `application`/`infrastructure` — следующий (последний) срез #325.

## Проверки

```bash
# среда job lint (mypy + PySide6 + numpy + opencv + pydicom + types-PyYAML)
/tmp/ci-mypy/bin/python -m mypy        # Success: no issues found in 261 source files
# полное dev-окружение
~/.venv-sf/bin/python -m mypy          # Success: no issues found in 261 source files
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/   # clean
python scripts/check_type_ignores.py   # 252 (64 bare) within baseline
python scripts/check_function_length.py                                   # passed
```

Смежные наборы, затронутые правками (`test_dicom_tag_dictionary`,
`test_orthanc_dicom_json`, `test_worker_mp4_export`, `test_logging_setup`,
`test_system_profiler`, `test_dimse_client*`, `test_runtime_setup`,
`test_dicom_doppler_calibration`, `test_speckle_worker`, `test_dicom_session`,
`test_measurement_repository`) — зелёные; полный не-GUI прогон — без новых
падений относительно 12 известных песочных.
