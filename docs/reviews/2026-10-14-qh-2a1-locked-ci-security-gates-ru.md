# QH-2a.1 ч.2: зафиксированная инструментальная цепочка CI и невакуумные гейты security/acceptance

**Область:** спека и план QH (`docs/superpowers/specs/2026-10-13-quality-safety-hardening-spec-plan-ru.md`),
§3 QH-2a.1 (часть 2), гейт G1, инвариант S-12 («пропущенный обязательный тест ≠ PASS»),
приёмка A-13 (гейт по ID тестов) и A-09 частично (стартовые security-тесты как обязательные).

**Проверяемая база:** `main` на `1117a02` (после merge PR #156 — QH-1a.2), перебазировано на `68ec766` (merge PR #157). Первая часть QH-2a.1
(count-gate и lossless-partition, PR #155) уже в `main`; этот срез её не переписывает, а
расширяет.

---

## 1. Разрывы, которые закрывает срез

1. **Toolchain CI не был зафиксирован.** Все джобы ставили зависимости через
   `pip install -e ".[dev]" "PySide6!=6.12.0"` — верхние границы из `pyproject.toml`, а не
   `uv.lock`; lint ставил `ruff==0.16.0`, тогда как `uv.lock` фиксирует 0.15.16; coverage —
   `coverage>=7,<8`. Зелёный CI не доказывал, что зафиксированный набор вообще собирается.
2. **`tests/security` и `tests/acceptance` не исполнялись нигде.** Ни одна джоба `ci.yml` их не
   запускала; `tests/README*.md` обещали флаги `ECHO_SECURITY=1`/`ECHO_ACCEPTANCE=1`, которых
   нет ни в одном `conftest.py` (grep `ECHO_` по `tests/`). При первом же локальном прогоне
   `tests/security` показал 11 падений — устаревшие тесты, не замеченные месяцами.
3. **Гейт по количеству тестов не защищал от вакуумности.** `check_pytest_counts.py` сверяет
   «выполнено == выбрано», но набор из одних `skip`/`xfail` или удалённый файл с обязательным
   тестом проходил бы его.
4. **Нижняя граница `requires-python = ">=3.10"` не проверялась** — и `main` на 3.10 не
   импортируется: `enum.StrEnum` (`presentation/measurement_action.py`), `datetime.UTC`
   (`domain/services/gold_store.py`, `infrastructure/diagnostics.py`) и пять тестовых модулей с
   `from datetime import UTC`.

## 2. Что сделано

| Слой | Изменение |
|---|---|
| `.github/workflows/ci.yml` | Глобально `UV_PYTHON_DOWNLOADS=never`; в каждой тестовой джобе `astral-sh/setup-uv@1c37ad07…` (SHA = v10.3.0, как в README upstream; плавающих тегов `v8+` у действия нет), `version: "0.13.0"`, кэш по `uv.lock`; `uv sync --locked --extra dev --python <ver>` + `uv run --no-sync pytest …`. `cache: pip` и `PySide6!=6.12.0` убраны (lock фиксирует 6.11.1, pyproject — `<6.12`). Lint: `ruff` версии из lock + `uv lock --check`. Coverage: `coverage` из lock. |
| `ci.yml` → `test_compat` | Новая ячейка `test-logic (ubuntu-latest, 3.10)` на том же теле джобы (apt-шаг под `runner.os == 'Linux'`, `cache-suffix` по версии Python). |
| `ci.yml` → `test_security`, `test_acceptance` | Новые обязательные джобы (входят в `needs` и условие агрегатного гейта `test (...)`). Security — без Xvfb (offscreen), acceptance — под `xvfb-run -a`. После pytest: `annotate_pytest_failures.py`, `check_pytest_counts.py`, `check_required_tests.py`; артефакты `pytest-{security,acceptance}-evidence` (лог, метрики с исходами, JUnit). |
| `.github/scripts/pytest_ci_metrics.py` | Помимо инвентаря пишет `outcomes` (nodeid → `passed/failed/skipped/xfailed/xpassed/error`), `skip_reasons`, `collection_errors`, `exit_status`. Пишет контроллер xdist (или одиночный процесс); воркеры (`PYTEST_XDIST_WORKER`) исходы не трогают. Ошибка teardown перекрывает исход call. |
| `.github/scripts/check_required_tests.py` (новый) | Чистая функция `evaluate()` + CLI. Провал, если: нет исходов (плагин не загружен/прогон прерван); есть ошибки сборки; выполнено 0 тестов или 0 прошло; запись манифеста не совпала ни с одним выполненным node id; совпавший node id не `passed`. Пропуск допускается только для точного node id из allowed-skips **с причиной**; xfail/xpass/failed не допускаются никогда. |
| `.github/scripts/locked_version.py` (новый) | Печатает версию дистрибутива из `uv.lock`; падает, если его нет или версия зависит от маркеров (например, `onnxruntime` → 1.23.2/1.26.0). |
| `.github/required-tests/security.txt`, `acceptance.txt`, `security-allowed-skips.txt` | Манифесты: записи — префиксы node id (файл/класс/тест). В security 10 записей покрывают все 7 файлов, кроме `TestDefaultUrlScheme`/`TestHttpUrlWarning` в `test_https_enforcement.py` — их тела само-утверждающие (`assert is_http or is_https`, `warnings.warn` внутри самого теста), их заменяет transport-policy evaluator (QH-2b, второй коммит этого PR). Allowed-skips пуст: у security-набора нет живых предусловий. |
| `.github/scripts/verify_pytest_partition.py` | `_BASELINE` 6734/3459 → 6752/3477 (добавлены 18 юнит-тестов гейта); GUI 3275/167 файлов без изменений (после merge PR #157 в `main`). Пересчитано локально тем же `pytest_ci_metrics` (`--collect-only`), совпадение с CI-инвентарём до правки проверено (6730/3271/3459/167 на `1117a02`). |
| `src/…/presentation/measurement_action.py` | `class MeasurementAction(str, Enum)` + `__str__`/`__format__` → значение. Контракт `str(MeasurementAction.X) == "x"` (на нём держится `_AI_ONNX_ACTIONS` в `measures_menu.py:277-283`) сохранён; `==`/`in`/`hash` для `(str, Enum)` и `StrEnum` одинаковы (оба хэшируют имя члена). |
| `gold_store.py`, `diagnostics.py`, `scripts/purge_actions_artifacts.py`, `scripts/export_echonet_seg_to_onnx.py`, 5 тестов | `datetime.UTC` → `timezone.utc`. Два файла в `scripts/` нашёл первый CI-прогон ячейки 3.10 (локальный grep покрывал только `src/` и `tests/`): `test_purge_actions_artifacts.py` импортирует `scripts.purge_actions_artifacts` → ImportError → count-gate «3470 ≠ 3469». |
| `tests/unit/test_measurement_repository.py` | `test_process_lock_and_recovery_after_process_death` упал на `windows-latest` в первом прогоне PR (`busy` после `child.kill(); child.wait()`): Windows освобождает byte-range lock убитого процесса асинхронно после возврата `wait()`. Тест опрашивает `acquire()` до 5 с (шаг 50 мс) вместо единственной попытки; семантика «восстановление после смерти процесса» не ослаблена — отказ по-прежнему падает, только по таймауту. На `main` тот же тест проходил, то есть это гонка, а не следствие `uv run`. |
| `pyproject.toml` | `ruff target-version = "py310"` (иначе UP017 требует `datetime.UTC`); описания маркеров `acceptance`/`security` без несуществующих флагов. |
| `tests/security/test_api_fuzzing.py` | 7 падений: тесты создавали клиент через `__new__` без `_cancel_event` и подсовывали `MagicMock` без `status_code` в retry-цикл (`r.status_code < 500` → `TypeError`). Общие хелперы `_bare_client()`/`_mock_response()`; тест 5xx теперь утверждает «ровно `_QUERY_RETRIES` GET, `_QUERY_RETRIES-1` пауз, исключение наружу» (пауза подменена, чтобы не спать 1,5 с). |
| `tests/security/test_dicom_fuzzing.py` | 3 падения: `validate_dicom_uid` давно ужесточён до PS3.5 (≤64 символов, начинается и кончается цифрой). `"0"*1000` и `"..."` перенесены в отвергаемые (+ `"0"*65`, `".1.2"`, `"1.2."`); `test_long_uid_in_path_component` ожидает `ValueError`, а не усечение, и проверяет граничный UID из 64 символов. |
| `tests/security/test_network_timeouts.py` | 1 падение: конструктор `OrthancDicomWebClient` имеет дефолт 10 с, `ServerSettings.network_timeout` — 30 с; тест утверждал равенство. Теперь: построен хотя бы один `httpx.Client`, и у каждого конечный положительный таймаут (≤300 с); распространение `network_timeout` проверяется соседним `test_from_settings_uses_network_timeout`. |
| `tests/acceptance/test_constructor_workflow.py` | `test_constructor_dialog_opens` блокировался в `QDialog.exec()` (offscreen — до таймаута 60 с, затем жёсткий выход всего прогона) и глушил исключения `try/except`. Теперь `ConstructorDialog.exec` подменяется на `show()`, `QMessageBox.critical` — на mock; проверяются отсутствие fallback-ошибки, видимость диалога и подменённый путь YAML. |
| `tests/unit/test_ci_required_tests_gate.py` (новый, 18) | Чистая логика гейта (все исходы, кроме `passed`, валят; отсутствующая запись валит; пустой/полностью пропущенный прогон валит; ошибка сборки валит; allowed-skip принимает только `skipped` и требует причину) + реальный под-прогон `pytest -p pytest_ci_metrics` во временном каталоге (чистое окружение без `PYTEST_*`), проверяющий записанные исходы, причины пропусков и слияние с инвентарём, и CLI-вход. |
| `tests/README.md`, `tests/README_RU.md`, `CHANGELOG.md` | Раздел о гейтах обязательных тестов, локальный запуск, обновлённые числа инвентаря, `uv sync --locked`. |

## 3. Доказательства (локально, Python 3.11, PySide6 6.11.1 offscreen)

| Проверка | Результат |
|---|---|
| `uv sync --locked --extra dev --python 3.11` (uv 0.13.0, без скачивания Python) | OK |
| `ruff check src/ tests/`, `ruff format --check src/ tests/` (ruff 0.15.16 из lock, `target-version = py310`) | чисто, 813 файлов |
| `pytest tests/security -p pytest_ci_metrics` → `check_pytest_counts.py` → `check_required_tests.py` | 202 passed; count-gate 202/202; required-gate 10/10 записей, `passed=202` |
| `pytest tests/acceptance -p pytest_ci_metrics` → оба гейта | 54 passed за ~4,6 с (раньше — зависание на `test_constructor_dialog_opens`); count-gate 54/54; required-gate 7/7 |
| Негативный контроль гейта | манифест с несуществующим классом → `exit 1`, «required test was not collected or not executed»; инвентарь без `outcomes` → `exit 1` |
| `tests/unit/test_ci_required_tests_gate.py` | 18 passed, в т.ч. под `-n 2` (контроллер корректно записал 18 исходов) |
| Логический unit-набор `tests/unit -m "not gui and not interactive"` **до** правок (`-n 2 --dist loadfile`) | EXIT=0 — базовая линия для сравнения |
| Затронутые unit-модули после правок (`test_app_controller_critical/vessel`, `test_dicom_upload_utils*`, `test_purge_actions_artifacts`, `test_diagnostics`, `test_gold_store`, `test_measurement_worksheet`, `test_measures_menu*`, `test_presenter_view`) | passed |
| Инвентарь `--collect-only -p pytest_ci_metrics` после добавления тестов | 6752 / gui 3275 / not_gui 3477 / gui_files 167 = новый `_BASELINE` (на базе `68ec766`) |

**Python 3.10 локально не проверяется:** в песочнице только системный 3.11, а
`uv python install 3.10` упирается в заблокированный хост `release-assets.githubusercontent.com`.
Поэтому ячейка `test-logic (ubuntu-latest, 3.10)` — первое реальное исполнение на 3.10; исправлены
только находки статического поиска (`StrEnum`, `datetime.UTC`, `from datetime import UTC`). Если CI
покажет более глубокие несовместимости, решение (чинить или явно сузить `requires-python`)
принимается отдельно и фиксируется в спеке — молча снижать ячейку до advisory нельзя.

## 4. Что остаётся вне среза

- `pip install …` в `build.yml`, `release.yml`, `presenter.yml`, `benchmark.yml` — QH-5a
  (унификация release/benchmark toolchain).
- Подтверждение branch protection / rulesets для новых обязательных джоб — **BLOCKED**:
  `gh api repos/areatu/SonoForge/branches/main/protection` → 403, `rulesets` → `[]`; нужна правка
  владельцем. До этого джобы входят в агрегатный `test (...)`, который уже в protection.
- Реальная замена `TestHttpUrlWarning`/`TestDefaultUrlScheme::test_http_default_gets_marked` —
  второй коммит этого PR (QH-2b, срез 1).
- Хэш-пин остальных actions (`actions/checkout@v4`, `setup-python@v7`, …) — не входит; закреплён
  только новый `setup-uv`, чтобы диф оставался читаемым.
