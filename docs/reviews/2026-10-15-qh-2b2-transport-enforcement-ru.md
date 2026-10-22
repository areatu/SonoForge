# Ревью QH-2b.2 — enforcement транспортной политики в клиентах, миграция профилей, TLS/DIMSE

**Дата:** 2026-10-15
**Задача:** [`areatu/SonoForge#183`](https://github.com/areatu/SonoForge/issues/183) (QH-2b, срез 2 из 2)
**Связанные требования спецификации:** S-08, A-09, A-10 (`docs/superpowers/specs/2026-10-13-quality-safety-hardening-spec-plan-ru.md`, §6.2–§6.3, §10)
**Предыдущий срез:** [`docs/reviews/2026-10-14-qh-2b1-transport-policy-evaluator-ru.md`](2026-10-14-qh-2b1-transport-policy-evaluator-ru.md)

---

## 1. Резюме

Срез QH-2b.2 подключает чистый вычислитель транспортной политики (`application/transport_policy.py`, доставленный в QH-2b.1) к реальным сетевым клиентам, фабрикам, фоновым воркерам, хранилищу профилей `ServerSettings` и пользовательским диалогам:

1. **Enforcement в клиентах и сервисах (`0` сетевых вызовов при блокировке):**
   - `OrthancDicomWebClient` проверяет каждый целевой URL перед отправкой запроса через `_ensure_request_allowed` (для `ping`, `query_studies`, `query_series`, `query_instances`, `fetch_preview` / `OrthancPreviewLoader`, `study_statistics`, `download_instance`, `stow_instances` и STOW override URL) и обрабатывает цепочки HTTP-редиректов вручную через `_follow_redirects` + `evaluate_redirect`.
   - При cross-authority редиректе (`forward_credentials == False`) заголовок `Authorization`, `Cookie`, `X-Api-Key` и все пользовательские заголовки `http_headers` удаляются, а для `httpx` используется пустой `httpx.Auth()`, чтобы учётные данные базовой аутентификации не пересылались на другой `scheme://host:port`.
   - `PynetdimseClient` проверяет `_ensure_transport_allowed()` перед каждой ассоциацией (`_associate`, `c_echo`, `_c_find`, `c_store`, `c_get_instance`, `c_move_instances`, `c_move_series`). Ошибки TLS-рукопожатия и проверки сертификата поднимают `DimseTlsError(DimseAssociationError)` с явным отказом от понижения до незашифрованного DIMSE.
   - `DicomQueryService` и `DicomRetrieveService` в режиме `auto` немедленно пробрасывают `TransportPolicyError` без fallback на другой протокол/адаптер.
   - `OrthancDownloadWorker._make_thread_client` пробрасывает `tls_verify`, `tls_ca_path`, `exceptions`, `allow_insecure_transport` и `needs_confirmation` в рабочие потоки скачивания.
2. **Миграция профилей и область действия исключений (`ServerSettings`):**
   - В `ServerSettings` добавлены `allow_insecure_transport: bool = False`, `insecure_exception_scope: str = ""`, `needs_confirmation: bool = False` и версия миграции `TRANSPORT_POLICY_MIGRATION_VERSION = 1`.
   - Устаревшие сохранённые настройки и именованные профили (`transport_policy_version < 1`) сохраняют URL, логин, заголовки и пароль в keyring / portable secret store; если профиль указывает на удалённый `http://`, `tls_verify=False` или удалённый DIMSE без TLS, он помечается `needs_confirmation=True` и блокирует первый сетевой вызов до решения пользователя.
   - Loopback-профили (`127.0.0.1`, `::1`, `localhost`) мигрируют с `needs_confirmation=False` и продолжают работать без ручного подтверждения.
   - Область действия исключения (`compute_insecure_exception_scope`) привязана к точным кортежам `(transport, host, port, secure, verify)` всех небезопасных конечных точек профиля. Любое изменение хоста, порта, схемы, STOW URL, включение удалённого DIMSE или переключение с CA bundle на `tls_verify=False` аннулирует ранее выданное согласие.
   - Профиль `Presenter` использует исключительно переносимое хранилище (`SONOFORGE_PORTABLE_DIR` / `settings.ini` + `secrets.ini`) без чтения или записи в хостовый `QSettings`.
3. **Предупреждение в UI (RU/EN) и видимый статус:**
   - В `en.json` и `ru.json` добавлены ключи `server_settings.insecure_*` с описанием риска перехвата медицинских данных (PHI) и учётных данных и тремя действиями: «Настроить HTTPS / TLS / CA», «Явно разрешить для этого сервера», «Отмена».
   - В `ServerSettingsForm`, `ServerSettingsDialog`, `ServerProfileDialog`, `OrthancStudyDialog`, `DownloadCoordinator` и `run_dicom_upload_dialog` отображается видимый статус небезопасного режима (`HTTP без шифрования`, `TLS без проверки сертификата`, `DIMSE без TLS`) и выполняется проверка подтверждения перед началом сетевых операций.
4. **Сервисные тесты TLS и DIMSE на локальных сокетных фикстурах:**
   - В `tests/security/test_https_enforcement.py` добавлены реальные сокетные тесты HTTPS (`TestHttpsRealTlsSocketService`) и DIMSE (`TestDimseRealTlsAndLegacyScp`) с генерацией тестового CA и серверных сертификатов (`cryptography.x509`): доверенный CA bundle, недоверенный CA, истёкший сертификат, неверный SAN/hostname, TLS-enabled `pynetdicom` SCP и legacy plaintext `pynetdicom` SCP с явным scoped opt-in.
   - Новые тестовые классы зарегистрированы в `.github/required-tests/security.txt` и проверяются гейтом `check_required_tests.py`.

---

## 2. Статус A-09 и A-10 (с учётом границ локального стенда)

| Критерий | Статус | Доказательство | Примечание о границах |
|---|---|---|---|
| **S-08** (транспортная политика в клиентах, редиректах, миграции и UI) | **PASS** | `tests/security/test_transport_policy.py` + `tests/security/test_https_enforcement.py` (`362 passed` в `tests/security/`, `17/17` записей манифеста `.github/required-tests/security.txt`) | Полностью закрыто в продакшн-клиентах, настройках и UI. |
| **A-09** (TLS с кастомным CA, отказ на невалидном/просроченном/чужом сертификате, отсутствие тихого отката на HTTP или `verify=False`, непересылка секретов при cross-authority redirect) | **PASS (service-level local socket fixtures)** | `TestHttpsRealTlsSocketService` (4 теста) + `TestOrthancRedirectAndHeaderSecurity` (4 теста) + `TestOrthancClientPolicyEnforcement` (5 тестов) | Проверено на реальных локальных TLS-сокетах (`ssl` + `http.server` + `OrthancDicomWebClient`). Интероперабельность с внешним клиническим PACS/reverse-proxy стендом в CI не эмулируется и остаётся эксплуатационной проверкой при развёртывании. |
| **A-10** (DIMSE TLS C-ECHO/C-FIND с CA, явная ошибка без понижения при несовместимом TLS, legacy DIMSE только при явном opt-in) | **PASS (service-level local pynetdicom SCP fixtures)** | `TestDimseRealTlsAndLegacyScp` (3 теста) + `TestPynetdimseClientPolicyEnforcement` (2 теста) | Проверено против in-process `pynetdicom` SCP (с TLS и без TLS). Живой внешний госпитальный PACS с аппаратным/клиническим DIMSE-TLS стендом в репозитории отсутствует и отмечается отдельно от локальных фикстур. |

---

## 3. Верификация

```bash
PYTHONPATH=.github/scripts LD_LIBRARY_PATH=tools/qtstub/lib QT_QPA_PLATFORM=offscreen \
  PYTEST_CURRENT_NODE_FILE=/tmp/pytest-last-node \
  PYTEST_CI_METRICS_FILE=/tmp/pytest-metrics.json \
  PYTEST_LOG_FILE=/tmp/pytest.log \
  .venv/bin/pytest tests/security/ -vv -p pytest_current_node -p pytest_ci_metrics \
  --tb=short --no-header -rsxX --durations=15 --junitxml=/tmp/pytest-junit.xml

.venv/bin/python .github/scripts/check_pytest_counts.py \
  --junit /tmp/pytest-junit.xml --metrics /tmp/pytest-metrics.json
# -> pytest count gate: executed 362 of 362 selected tests, none lost

.venv/bin/python .github/scripts/check_required_tests.py \
  --metrics /tmp/pytest-metrics.json \
  --required .github/required-tests/security.txt \
  --allowed-skips .github/required-tests/security-allowed-skips.txt
# -> required tests gate: 17/17 manifest entries satisfied by 362 executed tests (passed=362)
```
