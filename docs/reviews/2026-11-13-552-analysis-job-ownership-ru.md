# #552 — следующий срез владения состоянием: публикация STE

> **Снимок на 2026-11-13.** Проверена база `91c19ec`; документ фиксирует этот срез, а не полное закрытие #552. Актуальное состояние — в коде и открытом issue.

## Границы изменения

Первый шаг #552 (FrameAccess) уже находится в базе. В этом срезе вынесено
право публикации асинхронного STE-результата из ad-hoc lambda контроллера в
Qt-free `application/analysis_jobs.py`. Это не перенос всех media/session,
калибровки и analysis state в новые контейнеры.

До изменения success проверял только study generation и текущий SOP UID.
Error вообще не имел такой проверки. Повторный STE-запуск на том же клипе,
изменение калибровки или контура оставляли старому результату возможность
публикации. Теперь success/error конкурируют за один одноразовый ticket.

## Владельцы и lifecycle

| Состояние | Владелец | Lifecycle |
|---|---|---|
| Decode residency, eviction, pixels | `FrameCache` / существующие media workers | Без изменений; UI использует read-only `FrameAccess` |
| Активный media/document context | `AppController` + `StateManager` | Существующие study generation и instance lifecycle сохранены |
| Право публикации текущего STE job | `AnalysisJobs` внутри `AppServices` | Последний request выигрывает; старый success/error не меняет документ или UI |
| Калибровка и контуры | Существующие `StateManager` / `StudyMeasurementSessionStore` | Ledger только снимает fingerprint, не становится вторым authoritative store |
| Статус и результат для UI | Существующие controller signals | Публикуются только после допуска ticket |
| Lifetime worker/signals | Существующий `_retain_worker` / `_release_worker` | Cleanup terminal signals не зависит от допуска результата |

`AppServices` создаёт отдельный ledger через `default_factory`. Ledger не
хранит worker, pixels, controller или UI. Callback-провайдеры живут в
сигнальных соединениях существующего worker; сам ledger хранит только
текущий ticket и монотонный request counter. Новых полей у AppController нет.

## Допуск результата

Ticket фиксирует:
- document/study UID и study generation;
- SOP UID и source path;
- effective pixel spacing и полную calibration signature, включая revision,
  источник, frame/region/scope и assumptions;
- frame time, с которым был запущен существующий STE workflow;
- IDs, revisions, frame/phase/view/chamber, координаты и landmarks текущих
  контуров. Point lists копируются в tuple, а не сохраняются по ссылке.

Новый запуск заменяет ticket, даже если все inputs совпадают. Переключение
исследования, закрытие набора studies, reset и любой принятый `load_instance`
явно инвалидируют его, включая reload того же SOP. На state-change ledger
наблюдает clinical basis: изменение и последующая отмена изменения (ABA)
не оживляют старый ticket. На доставке queued callback basis проверяется
повторно. Только первый актуальный terminal callback получает право публикации.

Обычная смена кадра без изменения clinical basis не сбрасывает cine-анализ.
При frame-specific/region-specific смене effective calibration сброс
консервативен и намерен. Без активного job не сканируются ни документ, ни
контуры на playback tick. Request IDs существующих decode workers не менялись.

## Проверки

- Qt-free unit tests: supersession, однократное завершение, различия каждого
  поля basis, invalidation/ABA, копирование mutable contour points,
  отсутствие чтения документа при idle observation.
- Characterization через реальные public controller paths и fake workers:
  смена вкладки A→B→A, reload того же SOP, reset, закрытие studies, изменение
  калибровки с возвратом, revision контура, frame time, два STE-запуска,
  устаревшие success/error, единственная актуальная ошибка.
- Реальные Qt signals / QueuedConnection: worker уже отправил результат,
  затем калибровка изменилась до обработки очереди — результат не записан.
- Existing STE entry/report, tab isolation, scan-signal lifetime, composition,
  FrameAccess, calibration и controller-critical regressions.

Локальная среда: Linux, Python 3.11, зависимости из `.[dev]`, PySide6,
`QT_QPA_PLATFORM=offscreen` и штатные системные stubs из
`tools/qtstub/mkstub.py` из-за отсутствия GL-библиотек. Это не нативная
GUI-приёмка и не frozen-lock release evidence.

Воспроизведение после установки зависимостей и подготовки Qt:

```bash
LD_LIBRARY_PATH=tools/qtstub/lib QT_QPA_PLATFORM=offscreen .venv/bin/pytest \
  tests/unit/test_analysis_jobs.py \
  tests/unit/test_s02_tab_isolation.py \
  tests/unit/test_scan_signal_delivery.py \
  tests/unit/test_ste_protocol_report.py \
  tests/unit/test_ste_entry_flow.py \
  tests/unit/test_architecture_boundaries.py \
  tests/unit/test_composition_root.py \
  tests/unit/test_frame_access.py \
  tests/unit/test_app_controller_critical.py \
  tests/unit/test_calibration_context.py -v
```

Результат: **183 passed** в перечисленном targeted-прогоне; отдельно
`python scripts/run_pure_core_tests.py -q` — **201 passed**, включая
13 новых owner-тестов с запрещёнными Qt imports (они пересекаются с первым
прогоном). Ruff, targeted mypy (3 application-модуля), class/function-size
и private-access ratchets прошли без повышения baselines.

## Что остаётся по #552

- Этот ledger пока применяется **только к STE**, не к auto-segmentation,
  LA assist, temporal fusion или export. Их ownership/validity предстоит
  переносить отдельными срезами.
- Это отмена **права публикации**, не прерывание native tracking/decoder.
  Cooperative cancellation и worker-process hard limits здесь не вводились.
- File generation в этом срезе — существующая study generation + явная
  инвалидация на reload. Изменение файла внешним процессом без reload,
  content hash и отслеживание file-stat здесь не реализованы.
- Конфигурация/модель привязана к конкретному worker/request. Горячая замена
  модели без нового запуска и полная model/tool revision-схема — follow-up.
- Fingerprint консервативно включает все текущие контуры: даже правка
  нерелевантного контура может отменить право публикации. Межвкладочные
  контуры/Simpson inputs вне текущей UI-проекции требуют дальнейшей
  document-owned revision-модели.
- Единый authoritative calibration/measurement document и media owner
  ещё не выделены полностью. #552 не закрывается этим PR.
- Нужны CI и ручная supported-platform приёмка: запуск STE → изменение
  калибровки/смена или закрытие вкладки → поздний result/error; новый UI
  и отчёт не должны меняться старой задачей.
