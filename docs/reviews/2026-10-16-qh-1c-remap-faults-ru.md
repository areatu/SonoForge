# QH-1c (#176): explicit local-media remap и fault evidence

Дата: 2026-10-16. Продолжение среза от 2026-10-14, не закрытие всего WP4/G1.

## Перемещённые локальные источники

- Только явный import → preview → подтверждение полной замены. Автоматическое
  восстановление и DICOM identity не меняются. Исходный record не удаляется.
- Между `local:` studies допускается только полное однозначное сопоставление:
  полный SHA-256 исходных байтов + decoded frames + spacing. В текущей схеме v4
  нет отдельных rows/columns/timing: hash связывает в том числе закодированные
  геометрию и timing, но не является отдельной проверкой версии декодера.
- Один hash в нескольких исходных или подходящих открытых источниках — отказ,
  не выбор первого. UI выбора дубликата нет. Пустой экспорт нельзя переносить
  между identities: нет содержимого, доказывающего принадлежность.
- Все per-instance записи (контуры, линейные, сосудистые, Doppler, калибровки,
  ROI, Simpson area) и структурированные ссылки provenance перепривязываются.
  Opaque measurement/result IDs, inputs/revisions, численные значения и QC не
  выдумываются заново. Неизвестная provenance dependency блокирует перенос.
- Источники повторно хешируются на preview и на Replace; digest привязывает
  подтверждение как к байтам экспорта, так и к проверенному целевому набору.
  Preview содержит counts/digests, не пути, имена или UID.
- Дополнительные live sources допустимы, но их измерения не объединяются с
  импортом. Количество показано до подтверждения, как и число remapped sources.

Evidence: `test_measurement_remap.py` (14 logic), новые cases в
`test_measurement_persistence_disk.py` (реальные synthetic PNG, move + rename,
preview без изменений, подтверждение, restart, изменённые bytes, дубликаты),
`test_measurement_storage_dialog.py` (сообщение о переносе, default No).

## Directory fsync и реальные отказы

`atomic_write` уже выполнял file fsync → replace → POSIX directory fsync.
Новые тесты фиксируют порядок, закрытие directory fd и ошибку именно после
replace: новый JSON виден, но успешного durable acknowledgement нет.

Обнаружено и исправлено тестами: после такого отказа import и delete/delete-all
держали старую ожидаемую revision и застревали на `conflict` при повторе.
Worker read-back теперь продвигает CAS только при точном совпадении записанных
данных/источников и следующей ревизии; после delete — только если файл отсутствует.
Это не success: failed import не восстанавливает RAM и не emits restored, failed
save сохраняет dirty, failed delete возвращает current RAM в retry. Чужая,
повреждённая или неожиданная ревизия не принимается как своя.

### Native ENOSPC: Linux, 2026-10-16 — PASS

Стенд `scripts/measurement_disk_full_harness.py` выполнен **без Qt stubs и без
подмены файловых операций** на отдельном tmpfs 8 МиБ. Никакой repository quota:
файловая система реально заполнена до OS ENOSPC.

```json
{"failed_write_acknowledged": false, "failure": "ENOSPC", "filled_bytes": 8384512,
 "fresh_process_restore": true, "old_bytes_intact": true, "pending_files": 0,
 "platform": "linux", "retry_revision": 2, "status": "PASS"}
```

Изолированный повтор (Linux; mount требует разрешений):

```sh
VOLUME=$(mktemp -d)
sudo mount -t tmpfs -o size=8m,mode=700 tmpfs "$VOLUME"
sudo chown "$(id -u):$(id -g)" "$VOLUME"
.venv/bin/python scripts/measurement_disk_full_harness.py \
  --volume "$VOLUME" --confirm-disposable-volume
# После прогона, в том числе после неудачи:
sudo umount "$VOLUME"
rmdir "$VOLUME"
```

Стенд отказывает без explicit opt-in, на обычном каталоге/корне файловой системы,
на непустом mount или томе >128 МиБ. Пишет только в собственный temporary child,
освобождает filler, проверяет отсутствие pending, retry и чтение новым процессом.
Не используйте реальные данные/профиль. Выход — JSON без путей и raw exception.

## Границы evidence

- Локальный целевой pytest: **178 passed**, включая новые сценарии и соседние
  persistence/reference тесты. Qt-часть запускалась offscreen с существующим
  `tools/qtstub` для отсутствующих системных GL/EGL/dbus/xkb библиотек; это не
  нативная GUI-приёмка. Настоящие Qt objects/event loop, не mock coordinator.
- Дополнительный regression run: **133 passed** (tracker, reference tokens/widget,
  report builder, cache compatibility). Всего в двух непересекающихся прогонах
  **311 passed**. Ruff check/format, locale key parity и git diff --check — PASS.
- Collection unit suite: **7619**, logic **4224**, GUI **3395**, GUI files **172**,
  без collection errors. Полный suite здесь не объявляется PASS.
- Native Linux ENOSPC выше — отдельный реальный FS/subprocess-прогон. tmpfs
  подтверждает disk-full/retry, **не** устойчивость к power loss.
- Windows/macOS native disk-full evidence, power-loss/полный WP4/G1 acceptance
  остаются открытыми. #176 не закрывается автоматически этим PR.

## Синхронизация с main

Перед push в main вошёл PR #222 (`99a81c1`, UI-1 PR-1). Он влит в рабочую
ветку без изменения его поведения; конфликты были только в append-only журнале
спеки UI и счётчике pytest. Повторный combined regression run: **311 passed**.
Повторная collection: **7693**, logic **4287**, GUI **3406**, GUI files **172**.

## CI portability follow-up — 2026-10-17

Run `38964663195` (commit `52aeddb2`): Windows logic job обнаружил три
падения, остальные итоговые test gates упали вслед за ним. Два — чтение UTF-8
справочника через platform-default encoding в новых тестах; третье —
`WindowsPath.is_mount()` выбрасывает `NotImplementedError` в Python 3.11.

Исправления: явный UTF-8 во всех чтениях LVM-теста (его round-trip теперь
эмулирует default cp1252 даже на Linux); неподдерживаемый mount probe переводится
в безопасный отказ `dedicated_mount_required`, **не** в разрешение записи.
Добавлен самостоятельный regression case для неподдерживаемого probe.

## Native Windows/macOS acceptance follow-up

Стенд теперь подтверждает Windows volume root через `GetVolumePathNameW` (вместо
недоступного `WindowsPath.is_mount()` в Python 3.10/3.11), не разрешая обычный
подкаталог на системном томе. На Windows/macOS допускаются только ожидаемые
OS-created metadata folders на чистом mount; любой иной entry всё ещё блокирует
запуск. Добавлен ручной workflow `.github/workflows/native-disk-full.yml`, который
создаёт ограниченный 96 MiB NTFS VHD и 96 MiB APFS sparse image и запускает тот
же сценарий реального ENOSPC/retry/fresh-process.

Это **исполняемая приёмка, не PASS evidence**: запуск native workflow на обоих
GitHub-hosted runners и прикреплённые JSON-отчёты обязательны, чтобы закрыть
остаток #176. В Linux sandbox Windows/macOS FS не эмулируются и их PASS здесь
не заявляется. Перед первым dispatch workflow должен быть доступен в default
branch GitHub Actions UI; после этого его запускают на branch/commit-проверке.

UI-evidence #177 добавлен отдельно: GUI-тест создаёт настоящий `MainWindow`,
вводит RAP через `QLineEdit`, пересоздаёт controller/window из persistence и
очищает значение тем же полем. Локальный target run **24 passed** на настоящих
PySide6 Qt objects/event loop (offscreen; `tools/qtstub` нужен только для
отсутствующих системных GL/EGL/dbus/xkb shared libraries). Это не screenshot и
не ручная проверка на дисплее; повторный CI run ещё нужен для merge evidence.

Локальная команда:

```sh
LD_LIBRARY_PATH=tools/qtstub/lib QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
  .venv/bin/python -m pytest \
  tests/unit/test_measurement_fault_harness.py \
  tests/unit/test_tool_panel_calculators.py -q
```

Результат: **24 passed**; Ruff check/format, workflow YAML parse, Python compile
и `git diff --check` — PASS. Pytest локально предупреждает, что optional
`timeout` plugin не установлен в этой sandbox.
