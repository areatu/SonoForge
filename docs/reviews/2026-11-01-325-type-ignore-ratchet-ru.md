# #325, срез 1: bare `# type: ignore` под запрет + ratchet

> **Снимок на 2026-11-01.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

Дата: 2026-11-01. Источник: аудит 2026-10-22 (§12 P2-11, §5.3), проверка 2026-10-25.
Заменяет #309 (mypy для `domain`/`application`): гейт уже есть и строже, чем просили,
проблема — в его качестве.

## Что проверено на HEAD перед срезом

- `mypy` (job `lint`) зелёный: **261 файл, 0 ошибок** — то есть «2 замечания» из
  тела issue (`heart_rate.py:219` `no-any-return`, отсутствие `types-PyYAML`)
  уже исправлены в предыдущих срезах, повторно не воспроизводятся.
  `types-PyYAML` есть в dev-группе `pyproject.toml` (строка 75).
- `keyboard_shortcuts` уже выведен из `ignore_errors` (комментарий S2-05 в
  `[tool.mypy]`); `domain`/`imaging` уже работают под `strict`, включая
  `warn_unused_ignores`.
- Реальные ослабления, которые остались: `application` и `infrastructure` живут
  с `check_untyped_defs = false`, `warn_unused_ignores = false`,
  `disallow_untyped_defs = false` и `disable_error_code = ["misc",
  "attr-defined", "untyped-decorator"]`.
- Подавлений в `src`: **295** `# type: ignore`, из них **94 bare** (в теле issue
  было 297/99 — часть снялась попутными правками).

## Срез 1: что сделано

### 1. Гейт: `scripts/check_type_ignores.py`

Новый ratchet по образцу `check_function_length.py` (тот же стиль: baseline-JSON,
`--fix`, коды возврата 0/1/2), с двумя правилами:

| Правило | Следствие |
|---|---|
| New suppression in a file with no baseline entry | CI краснеет |
| Growth of `ignores` or `bare` in a grandfathered file | CI краснеет |
| Growth of the totals | CI краснеет |
| `--fix` rewrites the baseline | кредит не возвращается: числа только вниз |

Ключевое отличие от простого счётчика: `bare` учитывается **отдельно** от
общего числа, поэтому замена `# type: ignore[arg-type]` на `# type: ignore`
(тот же счётчик, но подавление всего) — это нарушение, а не «без изменений».

Шаг добавлен в job `lint` сразу после ratchet'а длины функций и перед `mypy`.

Baseline `scripts/type_ignore_baseline.json` зафиксировал стартовую точку
**295 / 94 bare в 84 файлах** — и после правок этого среза опустился до
**253 / 66 bare в 78 файлах** (−42 подавления, −28 из них bare).

### 2. `application` и `infrastructure` подняты на ступень

Общий override разбит на два, и обе ослабки сняты **в обоих** пакетах
(`infrastructure` догонял в том же срезе — см. ниже):

```toml
check_untyped_defs = true    # тела неаннотированных функций проверяются
warn_unused_ignores = true   # мёртвое подавление — ошибка
```

Цена среза измерена до правки и оказалась 11 находками:

- **9 мёртвых подавлений** — удалены (`app_controller.py` ×3,
  `measurement_persistence.py` ×2, `workers/speckle_worker.py` ×3 (все три —
  bare), `workers/thumbnail_loader_worker.py` ×1 (bare)). Итого −9 к общему
  счётчику и −4 к bare, то есть ratchet сразу опустился.
- **2 настоящие ошибки типов** в `measurement_persistence.py`
  (`_load_records_worker.read`): словарь результатов выводился как
  `dict[str, tuple[StudyMeasurementData, dict, str]]` по первой ветке, а ветки
  «не удалось восстановить» кладут `None` вместо данных. Пока тела
  неаннотированных функций не проверялись, ошибка была невидима. Теперь словарь
  аннотирован явно: `dict[str, tuple[StudyMeasurementData | None, dict, str]]` —
  без `cast`, без подавления.

### 3. `infrastructure` — дороже по счётчику, дешевле по правкам

Перед срезом объём оценивался примерно в 40 находок; измерение показало другое
распределение, и это оказалось удачей:

| Настройка | Находок |
|---|---|
| `check_untyped_defs = true` | **0** — тела неаннотированных функций `infrastructure` уже были чистыми |
| `warn_unused_ignores = true` | **33** — и все 33 оказались `unused-ignore`, ни одной настоящей ошибки типов |

То есть вся цена — удалить 33 мёртвых подавления, которые больше ничего не
подавляли (часть из них появилась до того, как соответствующие модули получили
стабы и точные сигнатуры). Удалены, `mypy`: `Success: no issues found in
261 source files`. Каждое снятое подавление — место, где будущая регрессия снова
станет видимой, поэтому это не косметика, а возвращённая чувствительность гейта.

### 4. Среда mypy: почему CI сначала покраснел

Первый прогон PR упал не на коде, а на среде: job `lint` ставит только
`ruff`, `mypy`, `numpy`, `opencv-python-headless`, `pydicom`, `types-PyYAML`,
а `PySide6` — нет. Пока `warn_unused_ignores` был выключен, это ничего не
меняло. Как только он включился, выяснилось, что **9 подавлений**
(`server_settings.py` ×4, `logging_setup.py` ×2, `support_report.py` ×1,
`app_controller.py` ×2) «используются» на машине разработчика и «не
используются» в CI: без Qt-стабов соответствующие выражения имеют тип `Any`,
писать их нечего — и гейт начинал зависеть от того, что установлено в
окружении, а не от кода.

Правка из двух частей:

1. **`PySide6` добавлен в установку инструментов job `lint`** (версия из
   `uv.lock` через `locked_version.py`, как у ruff/mypy/numpy) — Qt-стабы
   решают, подавляет ли ignore что-то, значит они часть среды проверки типов,
   а не «опциональная зависимость».
2. **`cryptography` и `openjpeg` добавлены в `ignore_missing_imports`**:
   это настоящие runtime-зависимости, которых в лёгкой среде нет, и с
   включённым `check_untyped_defs` их импорт стало видно (`import-not-found`).

После этого локальная среда и среда CI дают **одинаковый результат**:
`Success: no issues found in 261 source files` в обоих.

## Что осталось за срезом

- Снятие `disable_error_code` по одному коду (`attr-defined` → `misc` →
  `untyped-decorator`) — каждый отдельным PR с фиксами; это последняя
  оставшаяся ослабка в `[tool.mypy]`.
- `disallow_untyped_defs`/`disallow_incomplete_defs` для `application` и
  `infrastructure` — следующий уровень (сейчас `false`).
- Требование «причина рядом с подавлением» (комментарий-обоснование): сначала
  нужно опустить счётчик, иначе правило нарушат 286 строк.
- `keyboard_shortcuts` — уже вне `ignore_errors`, отдельного среза не требует.

## Приёмка #325 (по пунктам)

- [x] **Новый bare-`type: ignore` валит CI** — `bare` учитывается отдельно от
      общего счётчика, нарушение в файле без baseline-записи ловится сразу
      (`TestViolations`).
- [x] **Счётчик `# type: ignore` зафиксирован в baseline и уменьшается** —
      295 → 286 (bare 94 → 90) этим же срезом; `--fix` пишет только текущее
      состояние, «вернуть кредит» нельзя (`test_the_baseline_only_allows_a_decrease`).
- [x] **Для `application` включены `warn_unused_ignores` и `check_untyped_defs`,
      число ошибок = 0** — `mypy`: `Success: no issues found in 261 source files`.
- [x] То же для `infrastructure`: 0 ошибок типов, 33 мёртвых подавления сняты.
- [ ] `mypy` без `ignore_errors` для `keyboard_shortcuts` — уже выполнено
      предыдущим срезом (S2-05), проверено чтением конфига.
- [ ] Снятие `disable_error_code` (`attr-defined`, `misc`, `untyped-decorator`)
      и `disallow_untyped_defs` — следующие срезы #325.

## Тесты

`tests/unit/test_type_ignore_ratchet.py` — 13 кейсов: подсчёт coded/bare
(включая `#type:ignore` без пробелов и `# type: ignore[...]  # noqa`),
относительные пути в отчёте, отказ на новой подавлении в новом файле, на росте
в существующем, на появлении bare при неизменном тотале, разрешение на
уменьшение и на удаление файла, совпадение baseline с деревом, зелёный прогон
на коммите, запись baseline, наличие шага в `ci.yml`, конфигурация
`check_untyped_defs`/`warn_unused_ignores` для `application`.

Baseline инвентаря pytest: 9 546 → 9 559 (`not_gui` 5 627 → 5 640).

## Проверки

```bash
uv run pytest tests/unit/test_type_ignore_ratchet.py -q          # 13 passed
uv run pytest tests/unit/test_measurement_persistence_disk.py \
              tests/unit/test_measurement_persistence_rules.py \
              tests/unit/test_speckle_worker.py tests/unit/test_speckle_worker_anchors.py \
              tests/unit/test_worker_speckle.py tests/unit/test_app_controller_critical.py -q   # 137 passed
uv run mypy                                                       # 261 files, no issues
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/
python scripts/check_type_ignores.py                              # 253 (66 bare) within baseline
python scripts/check_function_length.py                           # passed
```
