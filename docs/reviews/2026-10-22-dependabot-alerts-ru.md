# Dependabot-алерты: разбор и закрытие (2026-10-22)

> **Снимок на 2026-10-22.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

Дата: 2026-10-22. Ветка: `arena/6f43a2ff-sonoforge`. Связанные решения: QH-2a.1
(зафиксированный toolchain), QH-5a (одна политика зависимостей), спека QH
2026-10-13 §"Toolchain" («сокращение диапазона — отдельное явное решение, не
скрытое следствие lock»).

## Как собиралась картина

API алертов (`/repos/areatu/SonoForge/dependabot/alerts` и `/code-scanning/alerts`)
отдаёт `403 Resource not accessible by integration` для токена рабочей песочницы,
поэтому список восстановлен по тем же источникам, которые читает Dependabot,
в два прохода:

1. **Черновой проход** — `uv.lock`: все 146 записей проверены по JSON-API PyPI
   (`https://pypi.org/pypi/<pkg>/<version>/json`, поле `vulnerabilities`,
   источник — OSV/PYSEC). Он дал 3 пакета и 26 GHSA.
2. **Авторитетный проход** — тот же lock проверен напрямую по GitHub Advisory
   Database (`GET /advisories?ecosystem=pip&affects=<pkg>`), с разбором
   `vulnerable_version_range` через `packaging.SpecifierSet` против каждой
   запертой версии. Именно эту базу читает Dependabot, и она оказалась полнее:
   **31 запись вместо 26**. PyPI/OSV на момент проверки не отдавал 4 бюллетеня
   Pillow — CVE-2026-112403 (**critical**, heap overflow в `ImagingJpegDecode`),
   CVE-2026-112902 (high, раскрытие памяти и segfault в энкодере libtiff),
   CVE-2026-112394 (medium, чтение за буфер в декодерах `P;2L`/`P;4L`) и
   CVE-2026-112898 (medium, `Image.quantize()` с пустой палитрой). Вывод по
   методике: для pip-экосистемы OSV/PyPI пригоден только как первый проход,
   решение нужно сверять с GHSA.
3. `.github/workflows/*.yml` — все 22 уникальных `uses:` проверены по
   `GET /advisories?ecosystem=actions&affects=<action>`.

Что граф зависимостей действительно видит эти версии, подтверждено независимо:
`GET /repos/areatu/SonoForge/dependency-graph/sbom` (168 пакетов) содержит
`pkg:pypi/pillow@12.3.0`, `pkg:pypi/cryptography@49.0.0`, `pkg:pypi/nltk@3.10.3`
и `pkg:githubactions/actions/download-artifact@4.*.*` (плюс `7.*.*` и `8.*.*`).
При `git push` GitHub сам сообщил: «found **28** vulnerabilities on the default
branch (3 critical, 16 high, 9 moderate)» — это в точности набор Pillow
(3 + 16 + 9), то есть алерты по `cryptography` и `nltk` в UI, судя всего, уже
были сняты вручную (PR #37 и #57 закрыты мейнтейнером с комментарием «resolved»,
хотя уязвимые пины из lock не исчезли — PR #57 чинил nltk до 3.10.3, а уязвимый
диапазон этого бюллетеня как раз `<= 3.10.3`).

Косвенное подтверждение полноты по Pillow: прогон Dependabot
`uv in /. for Pillow — Update` (#1644318232, 2026-10-22T04:31Z) завершился
`failure`, а `Graph Update: uv in /.` успешно — граф читает `uv.lock`, и именно
Pillow был тем алертом, который Dependabot не смог починить сам.

## Что найдено

| # | Пакет / экшен | Было | Тяжесть | Advisory | Исправлено в |
|---|---|---|---|---|---|
| 1 | `pillow` | 12.3.0 | **critical** ×3, **high** ×16, **medium** ×9 | 28 бюллетеней (CVE-2026-112390 … CVE-2026-112902) | 13.0.0 |
| 2 | `cryptography` | 49.0.0 | **high** | GHSA-g6cj-pr64-35w5 / CVE-2026-69247 | 50.0.0 (взято 50.0.2) |
| 3 | `nltk` | 3.10.3 | **high** ×2 | GHSA-8mgp-746c-j5xp / CVE-2026-81726 + дубликат GHSA-hqj7-phwp-c3fp | 3.10.4 |
| 4 | `actions/download-artifact` | `@v4` (11 мест в `ci.yml`) | **high** | GHSA-cxww-7g56-2vh6 | 4.1.3 (взято v4.3.0) |

Итого 31 уязвимая запись в старом lock по данным GHSA (28 + 1 + 2) плюс одно
неоднозначное место в экосистеме actions: 3 critical, 19 high, 9 medium.

По пункту 4 отдельно: граф записывает плавающий мажор как `4.*.*`, а уязвимый
диапазон — `>= 4.0.0, < 4.1.3`. Открыт ли алерт фактически, извне не видно
(403 на API алертов), но `@v4.3.0` снимает неоднозначность: в графе появляется
точная версия, заведомо вне диапазона. Поэтому в сводке GitHub из 28
уязвимостей этот экшен не фигурирует — и правка остаётся бесплатной страховкой,
а не закрытием подтверждённого алерта.

По пункту 3: прежний фикс nltk до 3.10.3 (PR #57, комментарий «The security
vulnerabilities are now resolved») не закрывал бюллетень — его диапазон
`<= 3.10.3` включает 3.10.3, а `first_patched_version` в GHSA пуст. Реально
устраняет попадание в диапазон только 3.10.4.

Пункты 1–3 — транзитивные зависимости: `pillow` приходит из `reportlab`
(`pillow>=9.0.0`), `nltk` раньше приходил из удалённого dev-extra `safety`, а
`cryptography` объявлен явно в extra `presenter` (`cryptography>=44,<51`) и
транзитивно приходит через `secretstorage` (`keyring`). `authlib`/`joserfc`
также раньше находились в lock через `safety` и удалены вместе с ним.

Информационно (не требует правки):

* `pypa/gh-action-pypi-publish@release/v1` — GHSA-vxmw-7h4f-hqxh (low, патч
  1.13.0). Ref `release/v1` — плавающая ветка, которая уже содержит 1.13.0+,
  поэтому фактически не уязвима; версии для графа зависимостей она не даёт.
* `github/codeql-action@v4` — CVE-2025-24362 затрагивает 2.26.11–2.x и
  3.26.11–3.28.2, v4 вне диапазона.
* `Dockerfile` (`python:3.11-slim`) не отслеживается: в `.github/dependabot.yml`
  объявлены только экосистемы `pip` и `github-actions` (осознанно не менялось —
  см. «Вне объёма»).

## Реальная экспозиция продукта

Разбор нужен не только чтобы закрыть счётчик, но и чтобы понимать риск до фикса:

* **Pillow.** Продуктовый код `PIL` не импортирует: PDF-отчёт
  (`infrastructure/measurement_report_pdf.py`) собирается reportlab'ом из текста,
  таблиц и параграфов и не вкладывает растр (`drawImage`/`ImageReader` в `src/`
  отсутствуют; одноимённый класс `infrastructure/image_reader.py` — собственный
  порт, а не PIL). `PIL` используется только дев-скриптами `tools/design_mockups`
  на доверенных локальных файлах. То есть 28 бюллетеней по парсингу
  TIFF/GIF/PDF/MSP/EPS/XBM в поставленный артефакт не попадают — но остаются в
  установленном замыкании и в SBOM, поэтому чинились, а не списывались.
* **cryptography.** CVE-2026-69247 — Bleichenbacher-оракул в
  `pkcs7_decrypt_der`/PEM/S-MIME. Проект использует только `Fernet`,
  `PBKDF2HMAC` и `hashes.SHA256` (`infrastructure/server_settings.py`,
  портативное хранилище паролей PACS) — уязвимый путь не вызывается. Бамп
  всё равно сделан: граница `<51` в `pyproject.toml` его разрешала.
* **nltk.** CVE-2026-81726 — выход за разрешённые корни при работе с
  model-artifact API. На момент аудита `nltk` лежал только в dev-extra через
  `safety`; `safety` удалён из dev-extra, поэтому транзитивный пакет больше не
  входит и в lock-файл.
* **download-artifact.** Уязвимость — произвольная запись файла при распаковке
  артефакта. В `ci.yml` экшен скачивает артефакты того же run
  (`coverage-data-*`, `pytest-*-diagnostics`, `dist`); подмена артефакта требует
  прав на запись в репозиторий, то есть риск — эскалация внутри CI, а не внешний
  вектор. Закрыто всё равно: патч-пин ничего не меняет в поведении.

## Почему Dependabot не смог починить Pillow сам

Pillow 13.0.0 требует `CPython >=3.11`, а `requires-python` был `">=3.10,<3.12"`.
Универсальный lock в таком случае обязан держать две вилки: 13.0.0 для 3.11 и
уязвимый 12.3.0 для 3.10. Проверялось практически — `uv lock --upgrade-package
pillow` на старом `requires-python` даёт ровно `Updated pillow v12.3.0 ->
v12.3.0, v13.0.0`, а автоматический security-update Dependabot падает.
Единственный способ убрать 12.3.0 из lock — поднять нижнюю границу.

## Решение: нижняя граница Python 3.10 → 3.11

Принято явно (а не как следствие lock), потому что:

* CPython 3.10 вышел из поддержки upstream в октябре 2026 — «самый старый
  интерпретатор, который обещают метаданные» больше не получает исправлений;
* без этого шага 28 бюллетеней Pillow (3 critical, 16 high, 9 medium) остаются в lock
  навсегда, а security-update Dependabot продолжает падать каждую неделю;
* опорная версия CI, релизов и Presenter-профиля и так 3.11
  (`python-version: "3.11"` во всех джобах, `TARGET_ENV` в
  `tools/release/presenter_pins.py` — CPython 3.11.9), то есть поставленные
  артефакты уже собирались на 3.11.

Изменения:

| Файл | Что |
|---|---|
| `pyproject.toml` | `requires-python = ">=3.11,<3.12"` с обоснованием; `ruff target-version` **оставлен** `py310` (см. ниже) |
| `uv.lock` | пересобран uv 0.13.0 (та же версия, что закреплена в `ci.yml`): `pillow` 12.3.0→13.0.0, `cryptography` 49.0.0→50.0.2, `nltk` 3.10.3→3.10.4; вилки по Python схлопнулись — `scipy` 1.15.3, `onnxruntime` 1.23.2, `rpds-py` 0.30.0, `stevedore` 5.8.0 остались одной версией (1.17.1 / 1.26.0 / 2026.6.3 / 5.9.0), из замыкания выпали 7 пакетов только для 3.10 (`exceptiongroup`, `backports-datetime-fromisoformat`, `sympy`, `mpmath`, `coloredlogs`, `humanfriendly`, `pyreadline3`); 142 → 135 записей |
| `build/presenter/pinned-packages.txt` | перегенерирован `tools/release/presenter_pins.py --write`: `cryptography==50.0.2`, `pillow==13.0.0`, убран `exceptiongroup==1.3.1` (44 → 43 пина) |
| `.github/workflows/ci.yml` | 11× `actions/download-artifact@v4` → `@v4.3.0` (с комментарием про GHSA и про то, почему не v7/v8); снята ячейка `ubuntu-latest / 3.10` из матрицы `test_compat`, комментарии и итоговое echo агрегатного гейта приведены к новому полу |
| `src/echo_personal_tool/infrastructure/runtime_setup.py` | `check_python_version()` → `sys.version_info >= (3, 11)` |
| `tests/system/test_first_run.py`, `tests/unit/test_infrastructure_extended.py` | утверждения и докстринги под новый пол; число тестов не изменилось |
| `tests/unit/test_runtime_setup.py` | `test_python_3_10_exact` закреплял, что ровно 3.10 ещё поддерживается, и после подъёма пола упал (`assert False is True`) на всех трёх ОС. Переименован в `test_python_3_11_exact` (3.11.0 → `True`), а `test_old_python_fails` теперь патчит 3.10.0 → `False`: граница проверена с двух сторон, число тестов то же (3), поэтому baseline инвентаря не пересобирался |
| `src/echo_personal_tool/presentation/measurement_action.py`, 2× `src/`, 2× `tests/unit` | комментарии «Python 3.10 compatibility» больше не обещают то, чего нет: `str`-миксин вместо `StrEnum` и `timezone.utc` вместо `datetime.UTC` **оставлены как есть** (контракт закреплён тестами), но помечены как отложенный рефакторинг |
| `README.md`, `README_RU.md` | бейдж `Python 3.10+` → `Python 3.11+` |
| `scripts/measurement_disk_full_harness.py`, `tools/release/presenter_pins.py` | комментарии про поддерживаемые версии |
| `.github/tracker/qh-plan.yml` | срез `[x] Python 3.10 compatibility cell` дополнен пометкой о снятии (маркер `[x]` сохранён — счётчик срезов `qh-2a1` не меняется) |

Почему `ruff target-version` не поднят до `py311`: при `py311` включается UP017
и `ruff check src/ tests/` даёт 24 новых замечания (`timezone.utc` →
`datetime.UTC`) — это косметическая миграция на 24 места, не связанная ни с одним
алертом. Поднимать target и игнорировать правило молча — хуже, чем оставить
`py310` с комментарием: правило просто не срабатывает, а зелёный lint остаётся
честным. Миграция `datetime.UTC` + `enum.StrEnum` — отдельный срез.

## Evidence

Локально (Linux, CPython 3.11.2, uv 0.13.0, Qt offscreen через `tools/qtstub`,
который в `.gitignore`):

* **главная проверка** — тот же авторитетный GHSA-аудит (диапазоны из
  `/advisories?ecosystem=pip`, сравнение через `packaging.SpecifierSet`),
  повторённый против нового `uv.lock`: **0 уязвимых записей из 135**
  (было 31 из 146). Отдельно сверено, что Pillow 13.0.0 не попадает ни в один из
  28 диапазонов, cryptography 50.0.2 — вне `>= 44.0.0, < 50.0.0`, nltk 3.10.4 —
  вне `<= 3.10.3`;
* `uv lock --check` — `Resolved 136 packages`, расхождения нет (гейт `lint` в CI);
* `python tools/release/presenter_pins.py` — `43 pin(s) match uv.lock for
  3.11.9/linux, excluded set absent, lite replacement present`;
* `ruff check src/ tests/` — All checks passed; `ruff format --check src/ tests/`
  — 990 files already formatted;
* все `.github/workflows/*.yml` парсятся; матрица `test_compat` — ровно
  macOS/Windows на 3.11; в `coverage` и `release` только `download-artifact@v4.3.0`;
* целевые наборы: `test_release_package_matrix.py` + `test_project_sync.py` +
  `test_first_run.py` + `test_infrastructure_extended.py` — **133 passed**
  (тесты, которые читают `ci.yml` и `qh-plan.yml`, правки пережили);
  `test_measurement_report_pdf.py`, `test_report_export.py`,
  `test_report_builder.py`, `test_calculator_report.py`,
  `test_presenter_profile.py`, `test_package_smoke.py` — **147 passed**
  (реальный рендер reportlab на Pillow 13); `test_no_credentials_in_settings.py`,
  `test_https_enforcement.py`, `test_network_timeouts.py`,
  `test_layout_settings.py` — **95 passed**;
* прямой смок нового замыкания: `cryptography` 50.0.2 — `PBKDF2HMAC`/`Fernet`
  round-trip пароля PACS и различимость шифртекстов; `reportlab` 4.5.1 +
  `Pillow` 13.0.0 — `drawImage(ImageReader(...))` в PDF из PNG/JPEG/TIFF/BMP;
* `update_pytest_baseline.py --check` — `pytest baseline matches the audited
  inventory: {'total': 8871, 'gui': 3764, 'not_gui': 5107, 'gui_files': 195}`,
  то есть переименование теста границу инвентаря не сдвинуло.

Первый прогон CI на этом диффе (run `39737110445`) — более сильное доказательство,
чем локальные запуски, и он же нашёл единственную ошибку автора правки:

* **зелёные**: `lint` (включая `uv lock --check` на uv 0.13.0), `Check for
  vulnerabilities` (Dependency Review), `Analyze (python)`/CodeQL,
  `pytest counters gate`, все 4 шарда `test-gui`, `test-security`,
  `test-acceptance`, `test-bench`, `package-smoke`, `ui-colors`,
  `build-linux`/`build-windows`/`build-macos-apple-silicon`, `Run benchmarks`;
* **красные**: `test-logic` на ubuntu, macOS и Windows — по аннотации
  `pytest failures: 1`, ровно
  `tests/unit/test_runtime_setup.py::TestCheckPythonVersion::test_python_3_10_exact`
  (`assert False is True`): тест закреплял, что 3.10 поддерживается, и локальный
  целевой прогон его не покрыл. Весь остальной логический набор (5107 тестов)
  прошёл на всех трёх ОС с новым lock — то есть Pillow 13, cryptography 50.0.2 и
  nltk 3.10.4 логические тесты не ломают;
* причину удалось прочитать только через `GET /check-runs/<id>/annotations`:
  хосты логов и артефактов Actions (`results-receiver.actions.githubusercontent.com`,
  `productionresultssa11.blob.core.windows.net`) недоступны из песочницы,
  `gh run view --log` и скачивание `pytest-logic-diagnostics` падают с EOF.
  Аннотации в этом репозитории информативны именно потому, что
  `annotate_pytest_failures.py` пишет `::error` с node id и текстом утверждения;
* тест исправлен (см. таблицу выше), после чего `tests/unit/test_runtime_setup.py`
  + `tests/system/test_first_run.py` + `tests/unit/test_infrastructure_extended.py`
  — **45 passed** локально.

## Ограничения и вне объёма

* Полный `pytest tests/unit` и GUI-наборы локально не прогнаны (нет системных
  `libGL.so.1`/`xvfb`, `apt-get` пакеты не видит; qtstub-заглушки покрывают не
  всё) — их закрыл CI: в первом прогоне логика на трёх ОС и 4 GUI-шарда прошли
  целиком, единственное падение исправлено; второй прогон (commit `3ed28bd`)
  зелёный полностью — 26 SUCCESS + 1 SKIPPED (`release`, он по тегу), включая
  `Combined Linux coverage` и все три агрегатных `test (...)`.
* Python 3.10 больше нигде не проверяется — это и есть принятое решение;
  пользователи на 3.10 смогут установить только прежние релизы.
* **Снятая ячейка не была обязательным статус-чеком — проверено фактом.**
  Имена обязательных чеков прочитать нельзя (`/branches/main/protection` → 403
  и для токена песочницы, и, по `docs/reviews/2026-10-14-qh-2a1-...`, для
  прежних попыток; `rulesets` → `[]`), поэтому риск оценивался косвенно: если бы
  `test-logic (ubuntu-latest, 3.10)` входил в protection, после снятия ячейки он
  никогда бы не отчитался и PR остался бы заблокированным ожидаемым чеком.
  Фактически в `statusCheckRollup` PR #291 нет ни одной записи
  `EXPECTED`/`QUEUED`/`PENDING` — 26 SUCCESS и 1 SKIPPED, а
  `mergeStateStatus: BLOCKED` объясняется только `reviewDecision:
  REVIEW_REQUIRED`: ровно в том же состоянии (`REVIEW_REQUIRED`) владелец
  смержил PR #290. Матрица агрегатного `test (...)`
  (`ubuntu`/`macos`/`windows` на 3.11) диффом не меняется — комментарий в
  `ci.yml` про сохранение имён обязательных чеков («Existing required
  status-check names are preserved by the test matrix below») остался правдой.
* Базовый образ `python:3.11-slim` в `Dockerfile` остаётся непрослеживаемым:
  экосистема `docker` в `.github/dependabot.yml` не объявлена (по решению
  «только алерты»).
* Сторонние экшены (`benchmark-action/github-action-benchmark@v1`,
  `softprops/action-gh-release@v3`, `coverallsapp/github-action@v2`,
  `release-drafter/release-drafter@v7`, `pypa/gh-action-pypi-publish@release/v1`)
  остаются на плавающих тегах — advisory по ним нет, SHA-пины отложены тем же
  решением; `astral-sh/setup-uv` и `jgehrcke/github-repo-stats` закреплены по SHA
  как и раньше.
* `actions/checkout@v4` (22 места) и `actions/upload-artifact@v7`/`@v4` не
  затронуты: advisories в экосистеме actions по ним нет, а смешение мажоров —
  вопрос обновления, а не безопасности (Dependabot для этого откроет обычный PR).
* Алерты CodeQL (`/code-scanning/alerts`) прочитать тем же токеном не удалось,
  поэтому этот разбор их не покрывает; прогон `CodeQL` на `main` 2026-10-22 —
  `success`.
