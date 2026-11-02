# #325, срез 2: `disable_error_code` сжат до одного кода

> **Снимок на 2026-11-01.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

Дата: 2026-11-01. Продолжение среза 1 (`docs/reviews/2026-11-01-325-type-ignore-ratchet-ru.md`).
Issue: #325. Источник: аудит 2026-10-22 (§12 P2-11, §5.3).

## Точка старта

После среза 1 в `[tool.mypy]` осталась одна ослабка для `application` и
`infrastructure`:

```toml
disable_error_code = ["misc", "attr-defined", "untyped-decorator"]
```

То есть три кода были выключены целиком — молча и для всех проверяемых файлов.

## Измерение перед правкой

Стоимость снятия каждого кода измерена в среде, **совпадающей с job `lint`**
(mypy, `PySide6`, `numpy`, `opencv-python-headless`, `pydicom`, `types-PyYAML`
— после среза 1 Qt там есть), а не в полном dev-окружении:

| Код | Находок | Файлов |
|---|---|---|
| `untyped-decorator` | 1 | 1 |
| `misc` | 7 | 2 |
| `attr-defined` | **39** | **14** |

Первые два снимаются в этом срезе, третий — отдельный (см. §4).

## 1. `untyped-decorator`: декоратор PDF-экспорта был нетипизирован

`_atomic_pdf_export` не имел аннотаций, поэтому `disallow_untyped_decorators`
(часть `strict`) считал **любую** обёрнутую им функцию нетипизированной —
включая `export_report_document_pdf`, то есть публичный экспорт отчёта
выпадал из проверки целиком.

Стало: декоратор типизирован через `ParamSpec` + `Concatenate`, сигнатура
обёрнутой функции сохраняется для вызывающих:

```python
_ExportParams = ParamSpec("_ExportParams")
_PayloadT = TypeVar("_PayloadT")

def _atomic_pdf_export(
    exporter: Callable[Concatenate[_PayloadT, Path, _ExportParams], Path],
) -> Callable[Concatenate[_PayloadT, Path, _ExportParams], Path]:
```

Поведение не изменилось: `*args: _ExportParams.args, **kwargs: _ExportParams.kwargs`
передаются в экспортёр как раньше, `font_size` больше не «прибит» в обёртке, а
идёт из сигнатуры самого экспортёра (у него тот же дефолт `10`, существующие
тесты на `font_size` зелёные). `functools.wraps` возвращает `_Wrapped[...]`,
который mypy не сворачивает обратно в `ParamSpec`, поэтому результат
переобъявлен через `cast(...)` с комментарием — это утверждение о том, что
обёртка и так делает в рантайме, а не подавление.

## 2. `misc`: шесть аннотаций на `SimpleNamespace` и один базовый класс без стабов

**Шесть находок** — аннотации на атрибутах `types.SimpleNamespace`
(`speckle_worker.py:956-960`, `1319`): `state.node_curves_full: np.ndarray | None = None`.
Такая запись не является аннотацией переменной (цель — не `self`), mypy её
отвергает; раньше код был выключен целиком, и это никого не сдерживало.
Аннотации убраны, намерение сохранено комментариями (`# np.ndarray | None`), а
типы реально проверяются на самом объекте-сборщике.

**Седьмая находка** — `class _AnchoredParagraph(Paragraph)`: `reportlab` не
поставляет стабов, поэтому `Paragraph` для mypy — `Any`, а подкласс `Any` — это
`misc`. Здесь единственный честный вариант — точечное подавление с причиной:

```python
class _AnchoredParagraph(Paragraph):  # type: ignore[misc]  # reportlab ships no type stubs, so its base class is Any
```

Это ровно то, чего требует issue: **код назван, причина написана**, и
подавление учтено ratchet'ом из среза 1 (счётчик 253 → **254**, файл
`measurement_report_pdf.py` +1). Один явный, объяснённый ignore вместо
выключенного для всего проекта кода ошибок.

## 3. Что осталось включённым

```toml
disable_error_code = ["attr-defined"]
```

Один код, с измеренной ценой, а не «корзина». Тест
`test_only_attr_defined_is_allowed_to_stay_disabled` фиксирует это во обоих
override'ах, чтобы расширение списка было осознанной правкой с ревью, а не
побочным эффектом.

## 4. Почему `attr-defined` — отдельный срез

39 находок в 14 файлах — и это не косметика: среди них есть настоящие дефекты,
которые выключенный код скрывал.

| Находка | Что это на самом деле |
|---|---|
| `"QOpenGLContext" has no attribute "destroy"` (`system_profiler.py`) | в Qt 6 такого метода нет — вызов, который не может сработать |
| `"type[Qt]" has no attribute "WindowContextHelpButtonHint"` / `"SmoothTransformation"` (`runtime_setup.py`) | обращение к перечислениям через устаревший `Qt`, а не `Qt.WindowType`/`Qt.TransformationMode` |
| `Module "dicom_tag_dictionary" has no attribute "PATIENT_NAME"` и ещё 8 (`orthanc_dicom_json.py`) | обращение к константам, которых в модуле нет — работает только потому, что код не исполнялся под тестом |
| `Module has no attribute "locking"` / `"LK_NBLCK"` (`measurement_repository.py`) | тип модуля `fcntl`/`msvcrt` не сходится с использованием |
| `"object" has no attribute "flush"/"close"/"release"/"send_c_store"` (≈14) | следствие слабых аннотаций возврата (`-> object`), нужен протокол или точный тип |
| `Module ... does not explicitly export attribute "PropertiesSnapshot"` (`dicom_io.py`) | реэкспорт без явного имени |

Каждая группа — правка поведения или контракта, а не «поставить ignore». Это
отдельный PR, который deserves собственного ревью, а не прицеп к снятию
настройки.

## 5. Среда проверки

Оба окружения дают одинаковый результат, и это специально проверено, потому что
срез 1 показал, как легко здесь разъехаться:

```bash
# среда job lint (mypy + PySide6 + numpy + opencv + pydicom + types-PyYAML)
/tmp/ci-mypy/bin/python -m mypy        # Success: no issues found in 261 source files
# полное dev-окружение (uv sync)
~/.venv-sf/bin/python -m mypy          # Success: no issues found in 261 source files
```

## Приёмка #325

- [x] Новый bare-`type: ignore` валит CI (срез 1).
- [x] Счётчик подавлений только уменьшается: сейчас 254 (66 bare) в 78 файлах;
      срез 2 добавил один объяснённый `# type: ignore[misc]`, зато снял два
      выключенных кода ошибок.
- [x] `warn_unused_ignores` + `check_untyped_defs` включены для `application` и
      `infrastructure` (срез 1).
- [x] `disable_error_code` сжат с трёх кодов до одного (`attr-defined`).
- [ ] Снятие `attr-defined` — следующий срез (39 находок, часть — реальные
      дефекты, см. §4).
- [ ] `disallow_untyped_defs`/`disallow_incomplete_defs` для
      `application`/`infrastructure` — после `attr-defined`.

## Тесты и проверки

Новый кейс: `test_only_attr_defined_is_allowed_to_stay_disabled` (фиксирует
оставшееся разрешение в обоих override'ах).

```bash
uv run pytest tests/unit/test_type_ignore_ratchet.py -q                  # 14 passed
uv run pytest tests/unit/test_measurement_report_pdf.py tests/unit/test_report_export_worker.py \
              tests/unit/test_report_export_job.py tests/unit/test_speckle_worker.py \
              tests/unit/test_speckle_worker_anchors.py tests/unit/test_worker_speckle.py -q   # 72 passed
uv run mypy                                                              # 261 files, no issues
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/  # clean
python scripts/check_type_ignores.py                                     # 254 (66 bare) within baseline
```
