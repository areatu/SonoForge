# #325, срез 4: `disallow_untyped_defs` включён — `application` и `infrastructure` аннотированы

Дата: 2026-11-01. Продолжение срезов 1–3
(`docs/reviews/2026-11-01-325-type-ignore-ratchet-ru.md`,
`docs/reviews/2026-11-01-325-disable-error-code-ru.md`,
`docs/reviews/2026-11-01-325-attr-defined-ru.md`). Issue: #325.

## Точка старта

После среза 3 в обоих override'ах оставалось по две строки:

```toml
disallow_untyped_defs = false
disallow_incomplete_defs = false
```

и два послабления, не относящихся к аннотациям (`warn_return_any = false`,
`disallow_untyped_calls = false`). Срез 4 — про первые две строки.

Измерение в среде job `lint` после переключения флагов: **117 находок
`no-untyped-def` в 30 файлах**. Все находки одного кода: до этого среза
`check_untyped_defs` уже проверял *тела* неаннотированных функций, а теперь
ошибкой стала сама неаннотированная сигнатура.

| Пакет | Файлов | Находок |
|---|---|---|
| `application` | 12 | 63 |
| `infrastructure` | 18 | 54 |

Самые крупные точки: `application/measurement_persistence.py` (43),
`application/app_controller.py` (12), `infrastructure/measurement_codec.py` (9).

## 1. Что дала аннотация, кроме «зелёного mypy»

Аннотация `__init__` и вспомогательных функций открыла mypy тела, которые до
этого просматривались по диагонали (`check_untyped_defs` смотрит тело, но пока
`self` в `__init__` не типизирован, атрибуты выводятся по первому присваиванию
и дальше не перепроверяются). Поэтому часть цены — не параметры, а состояние
объекта:

| Файл | Что появилось |
|---|---|
| `application/measurement_persistence.py` | Protocol `_MeasurementStore` (`on_change`, `snapshot`, `restore`) вместо «того самого» store-объекта; явные типы всех полей воркера (`_dirty`, `_versions`, `_epochs`, `_contexts`, `_load_errors`, `_first_dirty`); `_RECORD`/`_SOURCES` как псевдонимы вместо голого `dict`; `load(studies: Sequence[StudyMetadata], …)`, поэтому `deepcopy` и повторная итерация по снапшоту обозначены явно (генератор здесь теперь не скомпилируется) |
| `infrastructure/measurement_codec.py` | `_decode(value: Any, hint: Any) -> Any` — рекурсия по JSON намеренно `Any` (вход недоверенный), но `_limits`, `_unique`, `_collapse_legacy_label` типизированы (`Iterable[tuple[Any, Any]]`, `Callable[[Any], tuple[str, str]]`), `check()` получил `uid: str, frame: int \| None` |
| `infrastructure/dimse_client.py` | `_c_find` стал generic: `TypeVar _Found` + `Callable[[Dataset], _Found] -> list[_Found]`; три вызывающих метода (`c_find_studies/series/instances`) получают именно свой тип результата, а не `list` |
| `infrastructure/dicom_frame_count.py`, `properties_extractor.py`, `dicom_metadata_mapper.py` | `Dataset` из `pydicom.dataset` под `TYPE_CHECKING` вместо безымянного параметра; `_safe_float`/`_safe_str` типизированы как `Any` осознанно — это разбор недоверенных DICOM-значений, где `object` запретил бы `float(value)` внутри |
| `infrastructure/logging_setup.py` | обработчик Qt-сообщений: `(QtMsgType, object, str) -> None`, `noqa: ANN001` снят |
| `infrastructure/measurement_report_pdf.py` | `drawOn(canv: Any, x: float, y: float, _sW: float = 0, **kwargs: Any) -> Any` — переопределение метода reportlab, у которого нет стабов |
| `application/saved_records.py` | `read_saved_records(repository: MeasurementRepository, …)` вместо безымянного «чего-то с `entries()`» |
| `application/package_smoke.py` | `_measurements()`, `_snapshot_from()`, `_export()` получили типы через `TYPE_CHECKING`: smoke по-прежнему импортируется до полной сборки пакета |

## 2. Правки, изменившие код (а не только подписи)

Аннотация в трёх местах показала, что тип был не тот, который подразумевался:

1. **`app_controller.calculation_contours`** возвращал `items` в ветке «нет
   дескрипторов» и `tuple(output)` в остальных. С аннотацией
   `-> tuple[Contour, ...]` расхождение стало ошибкой; ветка теперь
   `return tuple(items)`, то есть тип результата одинаков на обоих путях
   (поведение не меняется — вызывающий сразу передаёт значение в `calculate`).
2. **`mitral_annulus`** собирался генератором по двум точкам и получал тип
   «кортеж произвольной длины», тогда как `Contour.mitral_annulus` требует ровно
   две точки. Заменено на явные `(point(annulus[0]), point(annulus[1]))`.
3. **`protocol_runner.set_projection`** разыменовывал `spec` без проверки на
   `None` (в `arm`/`skip` проверка есть). Проверка добавлена; ветка выполняется
   ровно в тех же случаях, что и раньше, потому что `previous is not None`
   возможно только при активном протоколе.

Плюс `application/dicom_io.read_ecg_waveform`: после аннотации
`dicom_session.read_ecg_waveform` (`-> EcgWaveform | None`) `cast` в фасаде стал
избыточным и удалён (`redundant-cast` его и поймал) — тип теперь приходит из
реальной сигнатуры, а не из утверждения на месте вызова.

## 3. Что осталось ослаблено

```toml
warn_return_any = false       # возврат Any из типизированной функции не репортится
disallow_untyped_calls = false # вызовы неаннотированных третьих сторон не репортятся
```

Это следующие срезы #325, и они записаны комментарием прямо в `pyproject.toml`,
чтобы список послаблений читался в одном месте.

Строки `check_untyped_defs = true` и `warn_unused_ignores = true` оставлены на
месте, хотя `disallow_untyped_defs` их подразумевает: их читает ratchet-тест
`tests/unit/test_type_ignore_ratchet.py`, и ослабление должно падать тестом, а
не проходить молча.

## 4. Гейт

`tests/unit/test_type_ignore_ratchet.py` расширен классом
`TestTypedDefinitions`:

* `test_untyped_definitions_are_rejected` — в обоих override'ах
  `disallow_untyped_defs` и `disallow_incomplete_defs` равны `true`;
* `test_only_the_two_known_relaxations_remain` — множество ослабленных ключей
  ограничено `{warn_return_any, disallow_untyped_calls}`; новый `false` или
  `skip` рядом с проверяемым пакетом — падение теста.

## 5. Проверки

| Гейт | Результат |
|---|---|
| `mypy` (job `lint`, `/tmp/ci-mypy`) | `Success: no issues found in 261 source files` |
| `mypy` (полный dev, `~/.venv-sf`) | `Success: no issues found in 261 source files` |
| `ruff check src/ tests/` | чисто |
| `ruff format --check src/ tests/` | чисто |
| `scripts/check_type_ignores.py` | 252 (64 bare) в 78 файлах — без роста |
| `scripts/check_function_length.py` | ни одна функция не перешла 200 строк |
| `tests/unit/test_type_ignore_ratchet.py` | 16 passed |
| `tests/unit/test_docs_links.py` | 10 passed |
| `pytest tests/unit tests/system -m "not gui" -n 4` | см. раздел 6 |

## 6. Полный не-GUI прогон

Полный прогон `tests/unit tests/system -m "not gui" -q -n 4` — **12 падений,
ровно те же, что и до среза**: 5 × `test_ui_scale` (нет экрана нужного размера в
песочнице), 4 × `test_video_reader` и 3 × `test_session_registry` (кодеки
OpenCV/FFmpeg песочницы). Новых падений нет; затронутые модули
(`measurement_persistence`, `study_measurement_session`, `protocol_runner`,
`protocol_session`, `saved_records`, `package_smoke`, `dicom_loading_fixes`)
прогнаны отдельно — зелено.

Инвентарь pytest после добавления двух кейсов: `total 9560 → 9562`,
`not_gui 5641 → 5643` (`update_pytest_baseline.py --fix`), т. е. baseline
разделённого прогона обновлён вместе с тестами.

## Итог по acceptance #325

| Критерий | Статус |
|---|---|
| `keyboard_shortcuts` проходит `strict` без `ignore_errors` | выполнено (S2-05) |
| `warn_unused_ignores` + `check_untyped_defs` для `application`/`infrastructure` | выполнено (срез 1) |
| новый bare `# type: ignore` валит CI | выполнено (срез 1) |
| счётчик подавлений закреплён и убывает | 295 → 254 → 252 |
| `disable_error_code` сокращён | 3 → 1 → 0 |
| `disallow_untyped_defs`/`disallow_incomplete_defs` для обоих пакетов | **выполнено (срез 4)**, 117 аннотаций в 30 файлах |

Остаток: `warn_return_any` и `disallow_untyped_calls` — отдельные срезы, потому
что первый шумит на каждом возврате из `Any`-поверхностей, а второй зависит от
того, какие третьи библиотеки остаются без стабов.
