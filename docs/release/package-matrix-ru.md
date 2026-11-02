# Матрица релизных пакетов и доказательства по упакованному артефакту

> [English version](package-matrix.md)

**Статус:** реализовано для Gate **G5a** (QH-5a, issue #188, спека
[2026-10-13 §9.1](../superpowers/specs/2026-10-13-quality-safety-hardening-spec-plan-ru.md),
строки приёмки A-16/A-17). **Снимок:** 2026-10-21.
**Машиночитаемый источник истины:** [`.github/package-matrix.yml`](../../.github/package-matrix.yml).

Документ отвечает на три вопроса, на которые релиз обязан отвечать честно:

1. **Что такое релиз SonoForge?** Набор ассетов из таблицы ниже, собранный
   названной джобой названного workflow из названного профиля на названной
   платформе.
2. **Чем это подтверждается?** Релиз подтверждается **запуском упакованного
   артефакта** — а не импортом из checkout'а — и проверкой опубликованных
   байтов по контрольным суммам, SBOM и build-записям.
3. **Что не подтверждается?** Пробелы в конце документа. Они же перечислены в
   самом файле матрицы, чтобы их нельзя было тихо забыть.

---

## 1. Профили

| | Full | Presenter (lite) |
|---|---|---|
| Точка входа | `src/echo_personal_tool/__main__.py` | `src/echo_personal_tool/__main_presenter__.py` |
| Зависимости | runtime-набор `pyproject.toml`, разрешённый в `uv.lock` | `build/presenter/pinned-packages.txt` — подмножество, сверенное с lock'ом |
| AI-сегментация (ONNX, модели) | да | **нет** (`onnxruntime` исключён) |
| Справочник ASE / конструктор | да (PySide6-WebEngine, PyMuPDF, openpyxl) | **нет** |
| Измерения, допплер, М-режим, strain, PACS, PDF-отчёт | да | да |
| Хранение | per-user каталог данных | портативно рядом с исполняемым файлом (`SONOFORGE_PORTABLE=1`) |
| Инструменты сборки | `uv sync --locked --extra build` | пинованный lite-набор + PyInstaller из `uv.lock` |
| Проверка профиля в smoke | ONNX/PyMuPDF/openpyxl **есть**, справочник доступен, портативное хранение соблюдено | те же модули **отсутствуют**, справочник скрыт, портативное хранение соблюдено |

Список пинов Presenter — это второй список зависимостей, и он допустим только
пока доказуемо принадлежит тому же lock'у: `tools/release/presenter_pins.py`
запускается в CI и в сборке Presenter и падает, если пин разошёлся с
`uv.lock`, если пакет не входит в замыкание зависимостей проекта или если в
lite-профиль просочился исключённый пакет.

## 2. Матрица

Каждая строка — публикуемый ассет, джоба, которая его собирает, глубина
проверки именно упакованных байтов и доказательства рядом с ним.

| Ассет (`{version}` = `__version__`) | Профиль | Платформа | Workflow / джоба | Тип | Smoke | SBOM | Манифест сумм |
|---|---|---|---|---|---|---|---|
| `sonoforge_{version}_amd64.deb` | Full | linux-amd64 | `release.yml` / `build-linux` | lite `.deb` | payload | `SonoForge-{version}-linux-amd64.sbom.cdx.json` | `SHA256SUMS` |
| `SonoForge-Setup-{version}-x64.exe` | Full | windows-x64 | `release.yml` / `build-windows` | установщик Inno Setup | artifact | `SonoForge-{version}-windows-x64.sbom.cdx.json` | `SHA256SUMS` |
| `SonoForge-{version}-portable.exe` | Full | windows-x64 | `release.yml` / `build-windows` | onefile portable | artifact | тот же SBOM | `SHA256SUMS` |
| `SonoForge-{version}-macos-arm64.dmg` | Full | macos-arm64 | `release.yml` / `build-macos-apple-silicon` | `.dmg` с `.app` | artifact | `SonoForge-{version}-macos-arm64.sbom.cdx.json` | `SHA256SUMS` |
| `sonoforge-{version}.tar.gz` | Full | source | `release.yml` / `build-source` | sdist | none | — | `SHA256SUMS` |
| `SonoForgePresenter-{version}.exe` | Presenter | windows-x64 | `presenter.yml` / `build-windows` | onefile portable | artifact | `SonoForge-Presenter-{version}-windows-x64.sbom.cdx.json` | `SHA256SUMS-presenter.txt` |
| `SonoForge-Presenter-{version}-x86_64.AppImage` | Presenter | linux-x86_64 | `presenter.yml` / `build-linux` | AppImage | artifact | `SonoForge-Presenter-{version}-linux-x86_64.sbom.cdx.json` | `SHA256SUMS-presenter.txt` |

`latest.json` — манифест с постоянным именем, который указывает на самые свежие
версии всего перечисленного (ассеты основного релиза плюс сборки Presenter).
Он содержит только бинарники, покрытые манифестами сумм, и только после
проверки их дайджестов.

**Уровни smoke**

* `artifact` — запускается именно поставляемый исполняемый файл: первый запуск,
  синтетический cine, измерение через настоящий слой персистентности, **второй
  процесс** восстанавливает запись с диска, текстовое представление результатов
  и экспортированный PDF (единственный файл отчёта, который пишет продукт),
  границы портативного хранения и возможности профиля из §1.
* `payload` — запускаются файлы, которые пакет устанавливает, с
  зафиксированным интерпретатором (используется для lite `.deb`, чей первый
  запуск скачивает зависимости).
* `none` — только исходники, запускать нечего.

## 3. Политика зависимостей

Одна зафиксированная инструментальная цепочка для CI, сборки, релиза и
Presenter (QH-2a.1, расширено QH-5a):

* `uv.lock` — единственный источник версий; `uv lock --check` выполняется в
  джобе `lint`, `uv sync --locked` — в каждой джобе, которая ставит
  Python-зависимости. `UV_PYTHON_DOWNLOADS=never` не даёт подменить
  интерпретатор из `setup-python`.
* Инструменты упаковки — `pyinstaller`, `pyinstaller-hooks-contrib`,
  `cyclonedx-bom`, `hatchling` — это extra `build` проекта, разрешаемый из того
  же lock'а.
* В workflow сборки/релиза/Presenter/бенчмарков нет `pip install -e .` и нет
  запасного плавающего `pip install <зависимость>`. Провалившаяся установка из
  lock'а валит джобу и никогда не скрывается альтернативной установкой. Это
  проверяется тестом `tests/unit/test_release_package_matrix.py` по файлам
  workflow.
* Пины Presenter сверяются с lock'ом (`tools/release/presenter_pins.py`) до
  сборки lite-окружения.

## 4. Доказательства, публикуемые с релизом

| Доказательство | Кто пишет | Содержимое |
|---|---|---|
| `SHA256SUMS`, `SHA256SUMS-presenter.txt` | джоба релиза / джоба релиза Presenter | дайджест + опубликованное имя файла для каждого бинарника |
| `*.sbom.cdx.json` | каждая джоба упаковки | CycloneDX 1.6 набора зависимостей, который попал в пакет; `metadata.component.version` = версия пакета, детерминированный `serialNumber` = `uuid5(NAMESPACE_URL, …/releases/tag/v{version})` |
| `build-record-{profile}-{platform}.json` | `tools/release/build_record.py` в каждой джобе упаковки | тег/версия, commit/ref источника, id/attempt прогона workflow, профиль, платформа/архитектура, версии Python/Qt/NumPy/ORT/PyMuPDF, SHA-256 `uv.lock` + число пакетов, хеш манифеста моделей (или `null`), дайджесты/размеры артефактов, статус smoke-доказательства |
| `package-smoke-{profile}-{platform}.json` | `tools/release/run_package_smoke.py` | проверки каждого этапа упакованного запуска (плюс артефакт workflow) |
| Sigstore-аттестации | `actions/attest` | provenance сборки для каждого бинарника плюс аттестация CycloneDX SBOM на тот же дайджест |
| `latest.json` | джоба релиза / джоба релиза Presenter | имена ассетов с версией, размеры, SHA-256 и URL загрузки |

## 5. Проверка опубликованного релиза

Workflow проверяет себя после публикации: джоба релиза скачивает опубликованные
ассеты обратно из релиза (`gh release download`) и запускает

```bash
python tools/release/verify_release.py \
  --dir published --tag v0.3.3 --version 0.3.3 --profile full \
  --latest-json published/latest.json --attestations --json-out release-verification.json
```

что валит workflow, если не выполняется хотя бы одно из условий:

| Проверка | Что означает |
|---|---|
| `matrix` | все ассеты, объявленные матрицей для выбранного профиля, опубликованы, и каждое имя содержит версию |
| `checksums` | каждый манифест сумм перечисляет ровно свои бинарники, и каждый дайджест совпадает со скачанным файлом |
| `sboms` | по одному CycloneDX 1.6 SBOM на упакованный артефакт, привязанному к версии, serialNumber выводится из тега, список компонентов не пуст |
| `records` | build-запись на каждую пару профиль/платформа: тот же тег/версия, тот же хеш `uv.lock`, что у помеченного коммита, дайджесты артефактов равны опубликованным байтам, package smoke `pass` для каждого упакованного ассета |
| `latest_json` | каждая запись указывает на опубликованный файл с указанным дайджестом и размером, и каждый проверенный по суммам бинарник в нём есть |
| `attestations` | `gh attestation verify` проходит для каждого бинарника и для его CycloneDX SBOM |

Пользователь или ИТ-служба больницы может воспроизвести существенную часть без
workflow:

```bash
sha256sum -c SHA256SUMS
gh attestation verify sonoforge_0.3.3_amd64.deb --repo areatu/SonoForge
gh attestation verify sonoforge_0.3.3_amd64.deb --repo areatu/SonoForge \
  --predicate-type https://cyclonedx.org/bom
```

Оставшийся вопрос доверия — *тот ли это издатель* — это вопрос OS-подписи и
относится к Gate G5b ([`docs/security/code-signing.md`](../security/code-signing.md)).
Неподписанные сборки остаются явно неподписанными.

## 6. Как запустить smoke локально

```bash
# сценарий на checkout'е (то же, что делает обязательная джоба CI)
uv run python tools/release/run_package_smoke.py \
  --runner module --profile full --workdir /tmp/package-smoke

# сценарий на поставляемом артефакте
uv run python tools/release/run_package_smoke.py \
  --runner artifact --artifact dist/SonoForge/SonoForge.exe --profile full \
  --workdir /tmp/package-smoke --evidence dist/package-smoke-full-windows-x64.json
```

Сам сценарий — `echo_personal_tool.application.package_smoke`; в замороженных
сборках он доступен как `<artifact> --package-smoke save|restart|compare` (см.
`src/echo_personal_tool/__main__.py` и `__main_presenter__.py`). Два этапа
обязаны быть двумя разными процессами — это и есть перезапуск.

## 7. Объявленные пробелы

Матрица перечисляет их в разделе `gaps`; они не покрыты PASS и не должны
читаться как покрытые:

* Lite `.deb` скачивает зависимости при первом запуске. Его **payload**
  проверяется smoke'ом на зафиксированном наборе зависимостей; сам сетевой
  bootstrap в CI не выполняется.
* Приёмка Presenter на USB-флешке (owner-run P1–P7, поведение read-only
  носителя) остаётся отдельной приёмкой, а не автоматической проверкой.
* Windows Authenticode, macOS Developer ID/нотаризация и их проверка на
  опубликованных ассетах — это **Gate G5b**, статус **Blocked** до появления
  провайдера подписи, владельца и хранения ключей. Текущие артефакты
  неподписанные (macOS несёт только ad-hoc подпись, которую ставит PyInstaller).
* Клиническая/регуляторная приёмка вне этого документа.

## 8. Как менять матрицу

Добавление, переименование или удаление публикуемого ассета — это изменение
трёх файлов:

1. `.github/package-matrix.yml` — строка ассета (имя, профиль, платформа,
   джоба, уровень smoke, SBOM, манифест) и, если нужно, новые имена
   манифеста/SBOM;
2. workflow упаковки — собрать, прогнать smoke, записать build-record,
   аттестовать, загрузить;
3. этот документ и его английский близнец.

`tests/unit/test_release_package_matrix.py` падает, если матрица противоречит
себе, если workflow упаковки теряет lock, проверку пинов или smoke, или если
задокументированная build-запись не пишется workflow'ом — поэтому
документация не может тихо разойтись с тем, что публикуется.
