# QH-2b срез 1: чистый evaluator транспортной политики (S-08)

**Область:** спека и план QH (`docs/superpowers/specs/2026-10-13-quality-safety-hardening-spec-plan-ru.md`),
§6.2 «QH-2b: единая транспортная политика», §6.3 «unit tests pure evaluator», инвариант S-08
(transport consent), приёмка A-09/A-10 — **уровень решения**. Второй коммит PR; первый —
QH-2a.1 ч.2 (`docs/reviews/2026-10-14-qh-2a1-locked-ci-security-gates-ru.md`).

**Проверяемая база:** `main` на `1117a02` + коммит QH-2a.1 ч.2.

---

## 1. Разрыв, который закрывает срез

До среза транспортная «политика» существовала только как настройки (`tls_verify`,
`dimse_use_tls`, `dimse_tls_verify`) и предупреждения в логах (`orthanc_client.py`,
`dimse_client.py`: «TLS certificate verification DISABLED — MITM risk!»). Единственный тест
«HTTP предупреждает» (`tests/security/test_https_enforcement.py::TestHttpUrlWarning`) вызывал
`warnings.warn()` **внутри самого теста** и утверждал, что его поймал, — он проходил при любом
коде приложения. Понятия «scoped исключение», «look-alike loopback», «downgrade redirect»,
«credentials на другую authority» в коде не было вовсе. Спека требует один pure evaluator и
адаптеры в клиентах/UI; этот срез — evaluator и его доказательство.

## 2. API (`src/echo_personal_tool/application/transport_policy.py`, только stdlib)

| Элемент | Назначение |
|---|---|
| `classify_host(host) -> HostKind` | `LOOPBACK` (парсинг через `ipaddress`: `127/8`, `::1`, IPv4-mapped `::ffff:127.x` после разворачивания; имя — только ровно `localhost`), `PRIVATE` (всё не-global: RFC1918, CGNAT, link-local, ULA, documentation), `PUBLIC`, `NAME`, `INVALID` (пусто, `0.0.0.0`/`::`, недопустимые символы). Никаких `startswith`/suffix. |
| `parse_dicomweb_endpoint(url, *, tls_verify, tls_ca_path) -> Endpoint` | Нормализует схему/хост/порт (порты по умолчанию 80/443, IPv6 в скобках, регистр). Бросает `EndpointError(code)`: `invalid-url`, `unsupported-scheme` (включая URL без схемы — не «дочинивается» до `http://`), `userinfo-in-url`, `invalid-host`, `invalid-port`. |
| `dimse_endpoint(host, port, *, use_tls, tls_verify, tls_ca_path)` | То же для DIMSE association. |
| `InsecureException.for_endpoint(ep)` / `.covers(ep)` | Scope = транспорт + хост + порт + `secure` + `verify` (для plaintext `verify` нормализован). Это значение, а не флаг: «HTTP разрешён всем» выразить невозможно. |
| `evaluate_endpoint(ep, *, exceptions) -> Decision` | Таблица §6.2 (см. ниже). |
| `evaluate_dicomweb_url(...)`, `evaluate_dimse(...)` | Разбор + решение; ошибка разбора → `block-invalid-endpoint` с `requires_exception=False`. |
| `evaluate_redirect(origin_url, location, ...)` | Эффективная цель (`urljoin`), запрет HTTPS→HTTP, оценка цели самой по себе, `forward_credentials` только при той же authority (схема+хост+порт). |
| `evaluate_profile(...) -> ProfileDecision` | Корень QIDO/WADO, STOW-override и DIMSE — отдельные решения; `allowed`, `blocked`, `insecure`. |
| `Decision` | `verdict`, стабильный `code`, `findings` (код + английское сообщение только с `host:port`), `endpoint`, `requires_exception`, `insecure`, `forward_credentials`, `summary()` без хоста/URL. |

**Таблица решений**

| Ситуация | Код | `requires_exception` |
|---|---|---|
| HTTPS / DIMSE-TLS, `verify=True` (в т.ч. custom CA) | `allow` | — |
| HTTP / clear DIMSE / unverified TLS к распарсенному loopback | `allow-loopback` | — |
| HTTP к PRIVATE / PUBLIC / NAME | `block-plaintext-remote` | да |
| clear DIMSE к PRIVATE / PUBLIC / NAME | `block-dimse-clear-remote` | да |
| TLS `verify=False` вне loopback | `block-tls-unverified` | да |
| то же при покрывающем `InsecureException` | `allow-by-exception`, `insecure=True` | — |
| некорректный endpoint | `block-invalid-endpoint` | **нет** |
| redirect HTTPS→HTTP | `block-redirect-downgrade` | **нет** (даже при исключении на цель) |
| redirect на ту же authority | `allow-redirect`, `forward_credentials=True` | — |
| redirect на другую authority (цель допустима) | `allow-redirect-cross-authority`, `forward_credentials=False` | — |

Сознательные решения, которые стоит проверить рецензенту:

- **Loopback без метки `insecure`.** Спека разрешает HTTP на loopback «для локального профиля»;
  метка нужна для *исключений*. Поэтому дефолтный dev-профиль (`http://127.0.0.1:8042/dicom-web`)
  даёт `ProfileDecision.insecure is False`. Если владелец хочет видимую метку и для loopback —
  это одно поле.
- **`localhost` по имени считается loopback**, остальные имена — нет (`localhost.attacker.example`,
  `127.0.0.1.nip.io`, `*.localhost`). Это буквально §6.2 («HTTP literal loopback / `localhost`»).
- **Имена с `_`** допускаются как `NAME` (интранет-имена), всё остальное вне RFC 1123 — `INVALID`.
- **Loopback → другой loopback-порт по redirect** — другая authority: разрешено, credentials
  не пересылаются. Консервативно; клиент при желании переспросит.

## 3. Тесты

| Набор | Что доказывает |
|---|---|
| `tests/security/test_transport_policy.py` (112) | §6.3 «unit tests pure evaluator» целиком: parsed loopback (IPv4/IPv6/mapped/`localhost`), 11 look-alike **не** loopback, PRIVATE/PUBLIC/NAME/INVALID матрица; 17 некорректных URL со стабильными кодами и `requires_exception=False`; HTTPS verify везде `allow`; custom CA; plaintext к 13 удалённым адресам (включая placeholder диалога `192.168.1.111`) — block; unverified TLS — block; DIMSE зеркально; scoped exception снимает ровно один endpoint и держит метку; смена порта/хоста/flavour/транспорта инвалидирует; «глобального HTTP» нет; redirect: downgrade (и с исключением), same authority, 3 вида cross-authority, loopback-доверие не распространяется, upgrade, некорректные `Location`, unverified-цель со своим исключением; STOW-override и DIMSE в профиле судятся отдельно; log-safety (нет PHI/UID/path/query/userinfo в findings и summary); immutability; чистота модуля (нет импортов Qt/httpx/pynetdicom/infrastructure/presentation). |
| `tests/security/test_https_enforcement.py` (19 → 24) | `TestHttpUrlWarning` → `TestHttpUrlPolicy`: решения берутся из настоящего evaluator на настоящих `ServerSettings`; `test_http_default_gets_marked` → дефолтный профиль = распарсенный loopback, `allow-loopback`, профиль целиком `allowed` без `insecure`; циклы `TestOrthancClientTlsPropagation` требуют ≥2 построенных `httpx.Client`. |
| `.github/required-tests/security.txt` | Оба файла целиком — обязательные записи гейта `test-security`. |

## 4. Доказательства (локально, Python 3.11, offscreen)

- `pytest tests/security -p pytest_ci_metrics` → **319 passed**; count-gate 319/319; required-gate
  8/8 записей.
- `ruff check src/ tests/`, `ruff format --check` — чисто.
- Логический unit-набор после обоих коммитов (`tests/unit -n 2 --dist loadfile -m "not gui and not
  interactive"`): 3477 выбрано, 3464 passed / 7 xfailed / 3 xpassed / 3 skipped, EXIT=0; исходы
  записаны контроллером xdist (`outcomes` = 3477).

## 5. Что остаётся (QH-2b срез 2, не в этом PR)

- Адаптеры: `OrthancDicomWebClient` (все запросы, включая ping/thumbnails/history с credentials,
  обработка redirect через `evaluate_redirect` и `forward_credentials`), `PynetdimseClient`
  (перед association), диалог настроек (RU/EN-предупреждение «Настроить TLS/CA» / «Отмена» /
  «Явно разрешить для этого сервера»).
- Хранение `InsecureException` в профиле и миграция старых remote-insecure профилей в
  `needs_confirmation`; первый сетевой запрос блокируется до решения.
- Production-client тесты «отклонённая операция = 0 сетевых запросов/associations»; TLS service
  tests (CA/hostname/expired, no fallback, auth не уходит на запрещённый redirect).
- Обновление `SECURITY.md` с «не форсируется» на фактическое поведение после enforcement
  (сейчас там явно сказано, что evaluator есть, а enforcement — нет).
