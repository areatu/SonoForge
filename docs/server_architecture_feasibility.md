# SonoForge Server — анализ возможности серверной архитектуры с workstation-клиентами

> Вопрос: можно ли из существующей архитектуры сделать серверное приложение и
> клиентов типа workstation?
>
> Дата: 2026-10-06. Оценки — в человеко-неделях (hw) для одного опытного разработчика.

---

## 1. Короткий ответ

**Да, и это на порядок дешевле веб-варианта — по одной причине: клиент у вас уже есть.**

Веб-сборка требовала переписать 42k LOC Qt-интерфейса. В серверной модели
`presentation/` (34 464 LOC) **остаётся рабочим кодом клиента**, а меняется только то,
*откуда приходят пиксели и куда сохраняются измерения*. Это смена адаптера порта, а не
переписывание приложения.

Ключевая находка: `ViewerWidget.show_frame(pixels: np.ndarray)` — весь UI потребляет
**сырые numpy-кадры**. Значит источник кадров (локальный `DicomSession` ↔ сеть) подменяется
новой реализацией порта, и 34k LOC интерфейса, оверлеев, калиперов, Doppler и STE-разметки
не трогаются вообще.

| Модель | Суть | Переиспользование кода | Оценка |
|---|---|---|---|
| **A. Хаб** | Сервер = хранилище измерений/отчётов + профили + креды PACS + аудит. Клиент считает всё сам | максимум | **12–18 hw** |
| **B. Сервер вычислений + workstation-клиенты** | Сервер = приём DICOM, хранилище, декод, AI/STE, отчёты, кадры по API. Клиент = нынешний Qt-клиент с удалённым источником кадров | высокое (ядро + весь UI) | **35–55 hw** |
| **C. Серверный рендеринг** (тонкий терминал: сервер рисует, клиент отдаёт мышь) | минимум: UI переписывается | **не рекомендуется** |
| **— Свой PACS** | Хранить DICOM как Orthanc/dcm4chee | — | **не делать**: интегрироваться с готовым |

Рекомендуемый путь: **A как фундамент → B как развитие** (порядок важен: A заодно
заставляет вынести Qt из ядра, без чего B невозможен).

---

## 2. Что уже готово работать headless (замерено по AST по транзитивным импортам)

Анализ: строился граф импортов между модулями проекта и считалась транзитивная достижимость
`PySide6` / `pyqtgraph` / `psutil` / `keyring`.

| Категория | Файлов | LOC |
|---|---|---|
| **Полностью headless-чистые** | 178 | **34 484** |
| Тянут `PySide6` (в т.ч. транзитивно) | 70 | 21 023 |
| `PySide6 + pyqtgraph` | 18 | 17 089 |
| `PySide6 + keyring` | 11 | 6 451 |
| `PySide6 + psutil` | 6 | 5 632 |
| `PySide6 + pyqtgraph + psutil + keyring` | 4 | 3 932 |
| `psutil` | 1 | 547 |

Что важно: почти вся «грязь» вне `presentation/` сводится не к архитектуре, а к
**трём узким местам**:

```
infrastructure/profile.py        (QSettings — отложенный импорт)  ─┐
infrastructure/paths.py (268)     ─────────────────────────────────┤→ тянет onnx_engine,
                                                                    │  measurement_report_pdf
infrastructure/server_settings.py (499)  QSettings + keyring ───────┼→ тянет orthanc_client (666),
                                                                    │  dimse_client (481),
                                                                    │  dicom_retrieve_service (371),
                                                                    │  orthanc_download_worker (582)
infrastructure/user_preferences.py (376) QSettings ─────────────────┘
```

Стоит вынести три интерфейса — `ISettingsStore`, `ISecretStore`, `IPathsProvider` — и
**~2 100 LOC PACS-слоя (orthanc_client, dimse_client, retrieve-сервис, download-воркер)
становятся headless без переписывания**.

### Уже headless и готовы к серверу как есть

| Модуль | LOC | Роль на сервере |
|---|---|---|
| `infrastructure/dicom_session.py` | 905 | Декод DICOM: JPEG2000, инкапсулированные кадры, mmap PixelData, покадровое чтение — **без единого импорта Qt** |
| `application/study_measurement_session.py` | 727 | `StudyMeasurementSessionStore` — сессия измерений **по study_uid**, слияние контуров/калиперов/Doppler, калибровки |
| `application/frame_cache.py` | 446 | LRU-кеш кадров с окном подкачки и лимитом памяти |
| `application/decode_gate.py` | 176 | Гейт параллельного декода |
| `application/dicom_query_service.py` | 160 | QIDO/DIMSE-поиск исследований |
| весь `domain` | 23 295 | Расчёты ASE, Simpson, Doppler, STE, калибровки, отчёты, вендорные профили |
| `infrastructure/orthanc_cache.py` | ~130 | Кеш инстансов с квотами и retention по mtime — готовый прообраз серверного кеша |
| `infrastructure/embedded_storage_scp.py` | ~130 | C-STORE SCP: приём исследований с модальностей (уже есть!) |
| `infrastructure/log_sanitizer.py` | — | Очистка логов от PHI — пригодится на сервере |
| `infrastructure/measurement_report_pdf.py` | 291 | Генерация PDF (reportlab) — переносится на сервер |

---

## 3. Что придётся переделать (узкие места)

| Что | LOC | Проблема | Что делать |
|---|---|---|---|
| `application/app_controller.py` | 4 061 | `QObject` с 20+ `Signal`, `QThreadPool`, `psutil`, единственное активное исследование (`_current_instance`, `_current_study_uid`, `_current_frame_pixels`) | Разделить на headless «ядро сессии» и Qt-оболочку; на сервере — свой session manager |
| `application/workers/*` | 3 384 | Тонкие обёртки `QRunnable` + `Signal` вокруг headless-логики | Интерфейс `IExecutor`: Qt-пул ↔ пул процессов/asyncio |
| `infrastructure/server_settings.py` + `profile.py` + `user_preferences.py` | ~875 | `QSettings` + `keyring` | `ISettingsStore` / `ISecretStore` (БД, env, Vault) |
| `application/state_manager.py` | 223 | `QObject` с сигналами, состояние просмотрщика | Остаётся на клиенте; на сервере — observer/callback |
| `application/measurement_persistence.py` | 454 | `QTimer`, `QEventLoop`, последовательная запись | Остаётся на клиенте; на сервере — транзакции БД |
| `infrastructure/measurement_repository.py` | ~170 | JSON-файлы + **блокировка одного писателя** через `fcntl.flock` / `msvcrt` + оптимистичная ревизия | Ревизии (`expected_revision`) оставить — они идеально ложатся на сервер; файловый lock заменить на транзакцию/version row |
| `infrastructure/dicom_session.py` (реестр) | — | Глобальный реестр сессий (`_max_sessions = 10`) и блокировки на процесс | Per-session изоляция + глобальный бюджет памяти |
| `application/frame_cache.py` | 446 | Лимит **2 ГБ на сессию** | На сервере: 150–300 МБ на сессию + глобальный LRU (10 сессий × 2 ГБ = 20 ГБ — нереально) |
| `psutil`-диагностика | 740 | `app_controller`, `playback_diagnostics`, `system_profiler` | Опционально / заменить на серверные метрики |

**Побочный вывод:** единственное состояние, завязанное на «один пользователь — одно
исследование», — это `app_controller` + `state_manager`. Всё остальное ядро уже
ключуется по `study_uid` / `instance_uid`.

---

## 4. Модель B: как это выглядит (рекомендуемая разбивка)

### Сервер

| Подсистема | Что используем из существующего | Что нового |
|---|---|---|
| **Приём DICOM** | `embedded_storage_scp.py` (C-STORE SCP), `dicom_query_service`, PACS-клиенты | Демон приёма, ретенция, дедупликация по SOPInstanceUID |
| **Гейт к PACS** | `orthanc_client.py` (DICOMweb), `dimse_client.py` (DIMSE) — после выноса `server_settings` | Пул соединений, креды в БД/секретах, кеш инстансов (расширить `OrthancSessionCache`) |
| **Декод кадров** | `dicom_session.py`, `decode_gate.py`, `frame_cache.py` | **Пул процессов** (GIL!), глобальный бюджет памяти, per-session LRU |
| **AI / STE** | `segmentation_service.py` (1 268), `la_segmentation_service.py`, `speckle_tracking.py` (1 065), `strain_computation.py` | Очередь задач (Celery/RQ/arq), GPU-инференс вместо CPU на рабочей станции |
| **Отчёты/экспорт** | `report_builder.py` (781), `measurement_report_pdf.py`, openpyxl-экспорт | HTTP-выдача PDF/XLSX |
| **Хранилище измерений** | `study_measurement_session.py`, `measurement_repository` (ревизии!) | Postgres/SQLite, блокировки, история, аудит, конфликты |
| **API** | — | REST (FastAPI) + WebSocket для прогресса/стриминга; gRPC — если нужен бинарный стриминг кадров |
| **Инфраструктура** | `log_sanitizer.py` (PHI), CA-сертификаты (уже есть в настройках) | Auth (OIDC/LDAP), RBAC, audit trail, TLS, бэкап, health-checks, Docker/systemd |

### Клиент (workstation)

| Что | Меняется? |
|---|---|
| `presentation/*` (34 464 LOC), `ui/*` (4 099) | ❌ нет |
| Источник кадров | ✅ новый адаптер: `RemoteFrameSource` (HTTP/WebSocket) → `np.ndarray`, prefetch + локальный `FrameCache` |
| Загрузка с PACS | ✅ `dicom_query_service` работает с серверным API вместо локального Orthanc-клиента (или через него) |
| Сохранение измерений | ✅ `IMeasurementStore` → REST вместо JSON-файлов |
| Настройки/креды | ✅ профиль пользователя с сервера |
| Офлайн-режим | ✅ локальный кеш загруженных исследований + отложенная синхронизация (отдельная большая тема) |

### Требование к пикселям (клиническая корректность)

`ViewerWidget` получает `np.ndarray` — значит по сети можно слать что угодно, но
**измерения обязаны считаться на-lossless-кадрах**. Практическая схема:

- навигация/предпросмотр — сжатые кадры (JPEG/WebP/AV1);
- кадр, на котором измеряют, — оригинальный DICOM-кадр без потерь (PNG/raw/исходный файл);
- калибровки (вендорные тики, глубина, Doppler-шкала) — всегда с сервера, из метаданных.

Ориентир по трафику (720p, uint8, 1 канал = 0.92 МБ/кадр): сырой поток на 30 fps —
~28 МБ/с (220 Мбит/с); JPEG q90 — 3–4.5 МБ/с; предзагрузка цикла из 100 кадров без потерь
— ~92 МБ разово. То есть на LAN сырьё терпимо, на WAN — только сжатие + предзагрузка.

---

## 5. Оценка работ (модель B)

| # | Этап | hw |
|---|---|---|
| 1 | Вынос `ISettingsStore` / `ISecretStore` / `IPathsProvider`; расчистка `server_settings`, `profile`, `user_preferences` (разблокирует весь PACS-слой) | 2–3 |
| 2 | Разделение `app_controller` (4 061) на headless-ядро и Qt-оболочку; интерфейс `IExecutor` для воркеров | 6–9 |
| 3 | Сервер: каркас API (FastAPI/asyncio), модель данных (studies/instances/measurements/revisions), миграции | 4–6 |
| 4 | Сервер: пул процессов декода + per-session `FrameCache` с глобальным бюджетом; API кадров (lossless + сжатые) | 5–8 |
| 5 | PACS-гейт: DIMSE/DICOMweb с серверными кредами, кеш инстансов с квотами и ретенцией | 4–6 |
| 6 | Клиент: `RemoteFrameSource` + prefetch + локальный кеш (UI не трогаем) | 4–6 |
| 7 | Измерения на сервере: `IMeasurementStore`, слияние/конфликты по ревизиям, аудит изменений | 3–5 |
| 8 | Auth/RBAC, TLS, аудит доступа к PHI, логи без PHI | 3–5 |
| 9 | Очередь задач на AI/STE + GPU-инференс | 3–5 |
| 10 | Эксплуатация: Docker/systemd, health-checks, бэкап, метрики, документация развёртывания | 3–5 |
| 11 | Офлайн-режим клиента и отложенная синхронизация (по желанию) | 6–10 |

**Итого: 35–55 hw** (без офлайн-режима), **12–18 hw** — если ограничиться моделью A
(только шаги 1, 3, 7, 8 и синхронизация измерений на клиенте).

---

## 6. Главные риски

1. **GIL и масштабирование.** Декод частично нативный (cv2/openjpeg отпускают GIL), но
   numpy-тяжёлые STE/strain/optical-flow потоками не масштабируются. Сервер обязан быть
   процессным (pool), а не тредовым; передача кадров между процессами — через shared memory
   или файлы в tmpfs, не через pickle по сокету.
2. **Память.** Текущий дизайн предполагает «одна сессия — держим весь цикл в памяти»
   (до 2 ГБ). На N пользователей нужен жёсткий бюджет и выгрузка неактивных сессий.
3. **Отказоустойчивость.** Сервер стал единой точкой отказа: без локального кеша и
   офлайн-режима клиника встаёт. Это продуктовое решение, а не деталь реализации.
4. **Сеть.** Измерения только на lossless-кадрах; любая «оптимизация» со сжатием перед
   измерением — клиническая ошибка. Зафиксировать в API отдельные эндпоинты
   «preview» и «measurement frame».
5. **Конфликты правок.** Одновременная работа двух врачей над одним исследованием:
   ревизии в `measurement_repository` — хорошая база, но нужны правила слияния
   (merge-функции в `study_measurement_session.py` уже есть) и UI разрешения конфликтов.
6. **Регуляторика.** SonoForge позиционируется как исследовательский/образовательный
   инструмент, не медицинское изделие (`README.md` §Disclaimer, `docs/HELP_RU.md`) —
   это снимает вопрос сертификации, но сервер с PHI всё равно требует аудита доступа,
   шифрования, ролей и бэкапов; для клинического применения статус придётся пересматривать.
7. **Дрейф двух режимов.** Клиент должен уметь работать и локально (как сейчас), и с
   сервером. Держите это за одним интерфейсом (`IFrameSource`, `IMeasurementStore`), иначе
   получите две разные программы.

---

## 7. Чего не делать

- **Не строить свой PACS.** Orthanc/dcm4chee уже умеют хранение, индексацию, WADO/DICOMweb.
  Сервер SonoForge — это слой *аналитики и измерений* над PACS, а не замена ему.
- **Не тащить Qt на сервер.** После расчистки узких мест ядро headless; тянуть
  `QCoreApplication` ради `QSettings`/сигналов — значит закрепить плохую границу.
- **Не делать серверный рендеринг (модель C).** Клиент теряет 34k LOC готового UI, а вы
  получаете свой VNC: задержки, кодеки, ввод, и тот же объём работ по серверу.
- **Начинать не с A.** Модель A (хаб) заставляет вынести настройки/секреты/пути из Qt —
  это prerequisite для B и при этом даёт самостоятельную ценность.

---

## 8. Карта изменений

```
РАСЧИСТИТЬ (3 узких места, ~1.1k LOC правок, разблокируют ~2.1k LOC):
  infrastructure/server_settings.py   499   QSettings + keyring  → ISettingsStore + ISecretStore
  infrastructure/profile.py                 QSettings (отложенный)
  infrastructure/user_preferences.py  376   QSettings            → серверный профиль
  infrastructure/paths.py             268   XDG/AppData          → IPathsProvider

РАЗДЕЛИТЬ:
  application/app_controller.py     4 061  ядро сессии (headless) | Qt-оболочка
  application/workers/*             3 384  логика (headless) | IExecutor
  application/state_manager.py        223  состояние просмотрщика — остаётся на клиенте
  application/measurement_persistence.py 454 — остаётся на клиенте

ЗАМЕНИТЬ БЭКЕНД (интерфейс уже фактически есть):
  infrastructure/measurement_repository.py   JSON+flock+revision → БД + транзакции
  infrastructure/orthanc_cache.py            session-кеш → серверное хранилище инстансов

ОСТАВИТЬ КАК ЕСТЬ:
  domain/**                        23 295
  infrastructure/dicom_session.py     905
  application/study_measurement_session.py 727
  application/frame_cache.py           446
  presentation/**                   34 464  (клиент)
  ui/**                              4 099  (клиент)
```
