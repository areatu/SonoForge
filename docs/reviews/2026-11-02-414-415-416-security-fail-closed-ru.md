# Аудит 2026-11-02, срез 1: #414 / #415 / #416

> **Снимок на 2026-11-02.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

Источник: восемь issues аудита 2026-11-02 (#414–#421). В этом срезе закрываются три
незаблокированные задачи с наибольшей ценой ошибки. Детали угроз намеренно не
публикуются с примерами секретов: в issue #414 это оговорено отдельно.

## #414 — Portable credentials: fail closed

**Что было.** `infrastructure/server_settings.py` хранил пароли PACS в `secrets.ini`
(Fernet, ключ выводится PBKDF2 из `device.key`), но `_portable_device_secret()`
при любой ошибке чтения/создания/валидации ключа возвращал константу
`_PORTABLE_DEVICE_SECRET_FALLBACK`. То есть на read-only носителе, при битом ключе
или сбое записи приложение продолжало шифровать пароли ключом, известным из кода.
`_save_password_keyring()` глушил исключение и просто писал warning, а `_decrypt_secret()`
тихо возвращал `""`. Пользователь не видел отказа, а legacy-пароль при неудачной
миграции удалялся из QSettings без следа.

**Что сделано.**

- Константа удалена. `_portable_device_secret()` либо возвращает ровно 32 байта
  корректного hex-ключа, либо поднимает `PortableSecretStoreError` со стабильным
  кодом: `key_path_unavailable`, `key_unreadable`, `key_invalid`,
  `key_write_failed`, `key_missing_with_secrets`, `secrets_store_unreadable`,
  `encryption_unavailable`.
- Создание ключа эксклюзивно (`O_EXCL`), с полной записью + `fsync` + `0600`;
  где ФС поддерживает hard link, имя `device.key` появляется только после
  публикации уже записанного временного файла (параллельный читатель не видит
  обрезанный ключ). Для FAT/exFAT, где `os.link` недоступен, остаётся
  эксклюзивная запись с проверкой точного формата при чтении. 24 параллельных
  потока в тесте получают один и тот же ключ, временных файлов не остаётся.
- Ключ читается и валидируется при **каждом** обращении, а кэш Fernet привязан
  к паре `(portable_root, bytes ключа)`: удаление/подмена ключа во время работы
  приложения не оставляет старый Fernet живым.
- Если ключа нет, а в `secrets.ini` уже есть токены, новый ключ **не создаётся**:
  иначе старые ciphertext стали бы нечитаемыми. Пользователь должен вернуть ключ
  или осознанно ввести пароли заново.
- Никакого plaintext и никакого перехода на системный keychain при отказе
  portable-хранилища. `PasswordSaveStatus(saved, error_code)` возвращается из
  `save_server_settings` / `save_profile`, показывается локализованное
  предупреждение (RU/EN) в `ServerSettingsDialog`, `UserPreferencesDialog`,
  `ServerProfileDialog` и `prompt_transport_policy_confirmation`. Внутренние
  сохранения, не меняющие пароль (`OrthancStudyDialog._persist_query_source`),
  предупреждение не показывают.
- Legacy-значения (`password` в QSettings, inline-пароль в профиле) при неудачной
  миграции сохраняются для повторного ввода, а не удаляются молча; в лог идёт
  только стабильный код.
- В логах нет пароля, ключа, пути и токена; `keyring.set_password` в portable-ветке
  не вызывается ни при каком отказе (проверено шпионом в тесте).

## #415 — Embedded Storage SCP: политика допуска отправителей

**Инвентарь.** `EmbeddedStorageSCP` (`infrastructure/embedded_storage_scp.py`)
поднимается на время C-MOVE из `CMoveRetrieveAdapter`
(`application/services/dicom_retrieve_service.py`) с `dimse_scp_host` /
`dimse_scp_port` из `ServerSettings`; хост редактируется в
`presentation/server_settings_dialog.py` (поле «SCP host») и попадает в
`save_server_settings`. `start()` умеет уходить на ephemeral port при занятом
порту, `bound_port` затем передаётся в `c_move_*`.

В `infrastructure/dimse_client.py` параметры `scp_host` / `scp_port` объявлены,
но **не используются**: C-MOVE называет только `move_destination_ae`, а адрес и
порт назначения PACS берёт из своей таблицы `DicomModalities`. То есть адрес
слушателя отправителю из клиента не сообщается; при ephemeral-fallback приложение
предупреждает, что конфигурацию PACS надо обновить вручную. AE title —
идентификатор, а не аутентификация; в 0.x нет ни allowlist доверенных
отправителей, ни проверки peer-сертификата для входящего C-STORE, ни TLS для
приёма. Проверяемой политики допуска нет, поэтому безопасный remote bind сейчас
не реализуем — issue разрешает в этом случае просто запретить его.

**Что сделано.** До создания AE и до `start_server()` `start()` проверяет
`is_loopback_bind_host`: принимаются только разобранные loopback-литералы
(`127/8`, `::1`, IPv4-mapped loopback) и ровно `localhost`; отклоняются
`0.0.0.0`, `::`, DNS-имена, look-alike вроде `127.0.0.1.nip.io`, zone-id и пустая
строка. Отказ — `StorageSCPBindError` до открытия сокета, лог не содержит адреса.
Форма настроек и `UserPreferencesDialog` не дают сохранить удалённый хост,
`CMoveRetrieveAdapter` превращает отказ в `RetrieveError(code="scp_bind_rejected")`.
Loopback C-MOVE (включая `port=0`) остаётся рабочим. Ограничение и модель доверия
описаны в `SECURITY.md` и подсказке поля; при появлении реальной политики
допуска её нужно включать отдельным решением, а не ослаблением этой проверки.

## #416 — Приватный канал disclosure

Проверено через GitHub API: Private Vulnerability Reporting для репозитория
уже включён (`GET /repos/areatu/SonoForge/private-vulnerability-reporting` →
`enabled: true`). Проблема была только в маршруте: ссылка из
`.github/ISSUE_TEMPLATE/config.yml` вела на `SECURITY.md`, где не было ни единой
инструкции, куда писать приватно. Теперь contact link ведёт прямо на
`/security/advisories/new`, а `SECURITY.md` содержит раздел «Reporting a
vulnerability»: что включать в отчёт (без PHI, DICOM, паролей и логов), почему
нельзя открывать публичный issue с эксплуатационными деталями, чем
`Settings → Report a problem…` не является, как идёт координированное раскрытие
и почему не обещается невыполнимый SLA.

## Доказательства и границы среза

- 31 новый тест: `tests/security/test_portable_credentials.py`,
  `tests/security/test_scp_bind_policy.py`; оба файла внесены в
  `.github/required-tests/security.txt`.
- 726 тестов затронутого набора + отдельно 205 тестов соседних UI/диалогов —
  зелёные; `ruff check`, `ruff format --check`, `mypy` (262 файла), все семь
  ratchet-скриптов и `pytest counters gate` (9865/3953/5912/205) — зелёные.
- Полный прогон GUI-матрицы (Windows/macOS, 6 шардов) остаётся за CI: локально
  доступен только offscreen Linux.
- Не входит в срез: #417 (typecheck-матрица 3.11–3.13), #419 (направления слоёв),
  #420 (декомпозиция UI), хвост #327, а также #418/#421 с внешними блокировками.
  Шифрование Z2-M/Z3/Z4 (#331) намеренно не начиналось — это отдельное решение
  владельца для версии ≥1.0.
