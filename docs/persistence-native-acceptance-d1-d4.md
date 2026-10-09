# Native-приёмка persistence WP4.1–4.2 (D1–D4)

Живой прогон native-аварий хранилища измерений на Windows: `taskkill /F`, два процесса,
read-only каталог через `icacls`, закрытие после правки, битый JSON.
Дата прогона: 2026-10-08. Машина: Windows 10/11 (win32), Python 3.11, `.venv` проекта.
Корни стенда — изолированные temp-каталоги с той же раскладкой, что
`%LOCALAPPDATA%\SonoForge\measurements` (боевые данные не трогались).
Стенд: `worker.py` (сабпроцессы holder/writer/trylock) + оркестратор с `taskkill /F /PID`.

Что покрыто юнит-тестами, а не живым прогоном: строки статус-бара и диалоги
(`test_measurement_persistence_disk.py`: retry после сбоя, flush/close, blocked-навигация;
`test_measurement_repository.py`: busy после смерти процесса, corrupt-never-overwritten,
чистка темпов). Живой прогон ниже — про то, чего юнит-тесты дать не могут:
настоящий `taskkill /F`, настоящий второй процесс, настоящий ACL.

## Результаты

| ID | Сценарий | Команда / шаги | Ожидание | Наблюдение | Итог |
|----|----------|----------------|----------|------------|------|
| D1 | `taskkill /F` во время записи | writer-цикл валидных записей (~1,9 МБ, ~2 с/шт), `taskkill /F /PID` на 5-й секунде, 3 раунда; плюс подброшенный `.pending-kill.tmp` перед `acquire` | Последняя подтверждённая ревизия цела и парсится, `.pending-*.tmp` вычищены на `acquire` | 3/3: ревизии целы либо чисто отсутствуют (kill до первой записи), запись парсится, темпов нет. Попадания с доказанным timestamp «внутрь записи» — 0/3 (kill ложились между записями); путь остатка недописанного темпа покрыт детерминированно подбросом + юнит-тестом `test_temp_not_recovered...` | PASS |
| D2 | `taskkill /F` после записи | rev=2 подтверждена → `taskkill /F` держателя лока → новый `acquire` + `load` | rev=2 на месте, лок свободен | rev=2 intact, re-acquire OK | PASS |
| D3 | Два экземпляра | holder держит лок → второй процесс `acquire` и `save` → `taskkill /F` первого → повтор | Второй: `BUSY:busy` и на acquire, и на save; после kill — `ACQUIRED` | Точно так; в UI этому соответствуют статус `persistence.error(busy)` + Retry/экспорт из RAM | PASS |
| D4 | Read-only каталог | `icacls <dir> /deny %USERNAME%:W` → запись → `icacls <dir> /remove:d %USERNAME%` → повтор | Запись падает быстро, файл побайтово цел, повтор после отката — rev+1 | **Найден дефект (см. ниже)**; после фикса: deny бьёт мгновенно (`PermissionError`), файл идентичен, retry после `/remove:d` — rev=2 | PASS (с фиксом) |
| D5 | Закрытие сразу после правки | Код: `closeEvent → persistence.close() → flush()` (2 с) → при неудаче окно не закрывается + диалог «заблокировано» (повторить/экспорт/без сохранения) | Данные либо сохранены, либо честный блок без молчаливой потери | Проверено чтением кода + юнит-тестами `test_failed_save_keeps_dirty_snapshot_and_retry`, `test_restart_metrics...` (flush/close-пути зелёные); живого GUI-прогона тут не было | PASS (unit) |
| D6 | Битый JSON записи | Дописать мусор в `<hash>.json` → `load`/`save` → восстановить из `.bak` | `load` → `invalid`, `save` заблокирован, байты не тронуты, бэкап встаёт с rev=1 | Точно так | PASS |

## Найденный дефект: ступор записи на ACL-denied каталоге (исправлен)

До фикса `MeasurementRepository.atomic_write` использовал `tempfile.mkstemp()`.
На Windows его ветка `except PermissionError` доверяет `os.access(dir, W_OK)`,
а тот не видит deny-ACE (`icacls /deny`) и возвращает True — `mkstemp` уходит
в до **10000** повторных попыток. Замер: **>240 с** ступора воркера вместо
мгновенного отказа (таймаут стенда, `faulthandler` показал цикл в
`_mkstemp_inner`). На UI это выливалось бы в 2-секундный `flush`, диалог
«заблокировано» и минуту фонового горения потока на каждый Retry.

Фикс (`infrastructure/measurement_repository.py`): одна попытка создания
uuid-именованного `.pending-*.tmp` через `os.open(O_CREAT|O_EXCL)` — отказ
мгновенный (`PermissionError`), атомарность (`os.replace` + `fsync`) и уборка
темпов без изменений. Регрессия:
`test_denied_directory_fails_fast_without_retry_storm` (ровно 1 попытка,
быстрее 5 с, запись цела, темпов нет) — зелёный.

Сопутствующие ловушки стенда (не продукт): русскоязычный вывод `icacls` (cp866)
роняет reader-thread сабпроцесса при `PYTHONUTF8=1` → дедлок `communicate`
(лечится `encoding="cp866"`); процессы прошлых оборванных прогонов держат
`.writer.lock` — чистить перед повтором.

## Команды для ручного повтора

```cmd
:: запрет записи (D4)
icacls "%LOCALAPPDATA%\SonoForge\measurements" /deny %USERNAME%:W
:: откат — обязательно после проверки
icacls "%LOCALAPPDATA%\SonoForge\measurements" /remove:d %USERNAME%

:: жёсткое убийство (D1/D2)
taskkill /F /IM SonoForge.exe
:: или точечно
taskkill /F /PID <pid>

:: битый JSON (D6) — сначала бэкап!
copy <hash>.json <hash>.json.bak
echo GARBAGE>> <hash>.json
:: восстановление
copy /Y <hash>.json.bak <hash>.json
```
