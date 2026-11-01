# #326: `runtime_setup.install_deps` — модули против дистрибутивов

Дата: 2026-11-01. Источник: аудит 2026-10-22 (§9.2 п. 2, §12), проверка 2026-10-25.
Связанные: #302 (воспроизводимая дистрибуция), #324 (аудит зависимостей).

## Триаж тела issue

Центральное утверждение issue — «`install_deps` передаёт `cv2` и `yaml` в pip как
имена дистрибутивов, которых на PyPI нет» — **на HEAD не воспроизводится**.
Установка идёт только из `pinned-packages.txt`, сгенерированного из `uv.lock`
(`uv export --locked --require-hashes`), с `--require-hashes` и без
unpinned-фолбэка (это принёс P1-3 / #302):

```python
args = ["install", "--quiet", "--require-hashes", ...]   # + ["-r", "<pins>"]
subprocess.run([str(pip), *args], check=True, capture_output=True)
```

Тело issue описывает код до этого изменения. Первый ремонт этого среза (часть
работы по #302) уже сделал: переименование `_REQUIRED_PACKAGES` →
`_REQUIRED_MODULES`, таблицу `_MODULE_DISTRIBUTIONS`
(`cv2→opencv-python-headless`, `yaml→pyyaml`, `libjpeg→pylibjpeg-libjpeg`,
`openjpeg→pylibjpeg-openjpeg`), полноту списка (`pymupdf`, `pylibjpeg*`) и
пост-проверку `_verify_installed_deps()`.

Что оставалось незакрытым и сделано здесь.

## 1. Диалог первого запуска всегда отвечал «успех»

```python
return worker.isRunning() or not worker.isRunning()   # всегда True
```

То есть даже когда `install_deps()` честно возвращал `False`, наружу уходило
`True`: вызывающий не мог отличить рабочее окружение от сломанного, а именно это
требует приёмка issue («не считать установку успешной, если…»).

Стало:

- `SetupWorker` хранит `self.result: bool | None` — итог `run()`; `show_setup_dialog()`
  возвращает `worker.result is True`;
- после `exec()` диалог ждёт поток (`worker.wait()`), если пользователь закрыл окно
  раньше: прерывать установку pip нельзя, и «забыть» работающий поток за спиной —
  это половина установленного окружения и повторный вход в тот же диалог;
- сама последовательность вынесена в `run_setup_tasks(status, progress, *, frozen)`
  и стала юнит-тестируемой без Qt: зависимости → модели, первая неудача
  останавливает цепочку, `frozen`-сборки (PyInstaller, зависимости внутри)
  ставят только модели.

## 2. Ошибка установки говорила одно и то же при разных причинах

Было: любая неудача pip — `"Dependency installation failed; check network or
wheelhouse."`; провал создания venv вообще не доходил до пользователя (только в лог).
Причина «пакет не проходит проверку хеша» и «нет сети» требуют разных действий.

Стало: таблица `_INSTALL_FAILURE_MESSAGES` со стабильными кодами причин
(`venv_failed`, `pins_missing`, `pip_missing`, `mode_invalid`, `pip_failed`,
`pip_failed_network`, `pip_failed_hash`, `pip_failed_unavailable`, `verify_failed`)
и классификатор `_pip_failure_reason(stderr)`; `_report_install_failure()` пишет
код в лог и **одну фразу** пользователю. Текст pip (пути, индексы, хеши,
трассировка) не показывается никогда — именно из-за этого в issue стояло «ошибка
доходит до пользователя текстом, а не трассировкой»:

| Причина | Фраза пользователю |
|---|---|
| `pip_failed_network` | Could not reach the package index; check the connection and retry. |
| `pip_failed_hash` | A downloaded package failed the integrity check; retry, then reinstall SonoForge. |
| `pip_failed_unavailable` | A required package is not offered by the configured package index. |
| `venv_failed` | Could not create the application environment; check free disk space and permissions. |
| `verify_failed` | Dependencies installed but verification failed; reinstall SonoForge. |

Заодно `check_deps()` теперь считает отсутствующим и модуль, который импортируется,
но не грузит нативную библиотеку (`OSError`: нет `libGL`, нет VC-рантайма,
обрезанная нативная сборка). Раньше такой модуль проходил проверку, и диалог
объявлял «Dependencies installed.» над окружением, которое падает при первом
использовании.

## 3. Идемпотентность и «чистое окружение»

`install_deps()` идемпотентен по построению: существующий venv не пересоздаётся,
повторный запуск — тот же `pip install --require-hashes -r pinned-packages.txt`
(pip превращает его в no-op), после чего пост-проверка подтверждает результат.
Закреплено тестом: две установки подряд → ровно два вызова pip, ни одного
`python -m venv`.

Сеть в тестах не нужна и специально не используется: сценарий «сеть недоступна»
моделируется `CalledProcessError` со stderr от ConnectionError, проверяется
и фраза пользователю, и отсутствие вывода pip в сообщениях.

## 4. Что сознательно не менялось

- **Гейт в `main.py` остаётся дешёвым** (`check_models()`, файловая проверка).
  Полная проверка импортов на старте стоит ~1.5 с прогретого кеша (измерено):
  `check_deps()` импортирует 20 модулей, включая `scipy`, `cv2`, `onnxruntime`.
  Ставить это на путь каждого запуска ради сценария «сломанное окружение при
  наличии моделей» — неправильный размен. Первый запуск всегда идёт без моделей,
  поэтому диалог открывается и `run_setup_tasks()` ставит зависимости **до**
  скачивания моделей. Комментарий об этом — в `main.py` рядом с гейтом.
- **Список не собирается руками.** Единственный источник — `uv.lock` через
  `pinned-packages.txt`; `_REQUIRED_MODULES` — только поверхность импорта для
  `importlib` (и она сверяется с `uv.lock` тестом
  `test_every_required_module_maps_to_a_locked_distribution`).
- Офлайн-wheelhouse и PyInstaller-сборки — вне области (это #302; там зависимости
  уже внутри).

## Приёмка #326

- [x] Ни одно имя из установочного пути не является «только именем модуля»:
      pip получает файл пинов, не имена; тест `test_pip_never_receives_a_bare_module_name`
      проверяет, что ни `cv2`, ни `yaml`, ни `PIL`, ни `fitz`, ни любой элемент
      `_REQUIRED_MODULES` не попадает в argv установки.
- [x] Тест сверки с `uv.lock` зелёный
      (`test_every_required_module_maps_to_a_locked_distribution`).
- [x] `install_deps()` в подготовленном venv ставит полный набор, повторный вызов
      идемпотентен (`test_second_run_reuses_the_venv_and_succeeds`).
- [x] Ошибка установки доходит до пользователя текстом: 9 причин → 9 фраз,
      ни `Traceback`, ни `ERROR:` (тесты `TestInstallFailureMessages`).
- [x] Успех установки верифицируется в целевом venv; диалог возвращает реальный
      результат (`TestRunSetupTasks`, `TestShowSetupDialogOutcome`).

## Тесты

`tests/unit/test_runtime_setup.py`: +24 логических кейса.

| Класс | Что закрепляет |
|---|---|
| `TestInstallIdempotency` (2) | повторный запуск не пересоздаёт venv; в argv pip нет имён модулей |
| `TestInstallFailureMessages` (12) | классификация stderr pip, 9 фраз (одна строка, без трассировки), отказ при отсутствии пинов, провал создания venv, неисполняемый pip, провал верификации |
| `TestRunSetupTasks` (7) | порядок «зависимости → модели», короткое замыкание на первой ошибке, `frozen` пропускает установку, проброс callback |
| `TestCheckDeps` (2) | `OSError` при импорте = зависимость отсутствует |
| `TestShowSetupDialogOutcome` (1) | готовое окружение отвечает `True`, не строя диалог |

Baseline инвентаря pytest: 9 522 → 9 546 (`not_gui` 5 603 → 5 627).

## Проверки

```bash
uv run pytest tests/unit/test_runtime_setup.py -q          # 57 passed
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src/echo_personal_tool/infrastructure/runtime_setup.py   # success
python .github/scripts/update_pytest_baseline.py --fix     # 9522 -> 9546
```
