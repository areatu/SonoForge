# #553 — приёмка очередей decode/prefetch и отмены

> **Снимок на 2026-11-13.** Документ фиксирует проверенный commit и локальный прогон; актуальное состояние — в коде, README, HELP и открытых issues.

## Объём и среда

База: `646b219` (`main`, fast-forward в рабочую ветку). Linux x86_64,
Python 3.11.2, PySide6/Qt 6.11.3, pytest 9.2.0. Зависимости установлены
из `.[dev]`, не из frozen lock: это локальная проверка, не release evidence.

В sandbox отсутствуют системные GL-библиотеки. Использован штатный
`tools/qtstub/mkstub.py` и `QT_QPA_PLATFORM=offscreen`. Сами классы Qt,
сигналы, FrameLoaderWorker, DecodeGate и их run loops настоящие; системные
GL/EGL/DBus-зависимости — stubs. Нативный GUI, рендеринг, vendor/PACS,
реальное переключение вкладок мышью и FPS экрана **не проверены**.

## Найдено и исправлено

1. **Входящий prefetch обходил собственный cap.** Gate защищал новый запрос
   от eviction даже тогда, когда он оставался единственным speculative
   запросом и сам превышал cap. Три новых теста до исправления падали:
   frame cap, byte cap, нулевой byte cap. Теперь после попытки удалить старое
   speculative work допускается удаление самого входящего speculative запроса.
   Interactive targets по-прежнему не удаляются ради speculative caps.
2. **Полный decode продолжал выполнять весь cine после отмены.** Все futures
   заранее подавались в executor; выход из его context manager ожидал
   выполнения оставшейся очереди, а `future.cancel()` в наружном finally
   вызывался слишком поздно. Новый regression до исправления получил
   **50 codec calls из 50**, хотя отмена наступила на первом кадре после
   preview. Теперь одновременно подано не более четырёх futures; после
   отмены очередь не пополняется, ожидающие futures отменяются до shutdown.
   Regression допускает не более **5 calls**: preview + четыре in-flight.
   Staging остаётся непубличным до полного успеха.

## Проверки и результаты

| Сценарий | Результат |
|---|---|
| Реальный FrameLoaderWorker, batch 30, decoder остановлен событием внутри первого кадра; затем 200 interactive targets | 199 отменены; depth=1, pending=524288 bytes; последний target декодируется сразу после первого кадра batch; исходный batch завершается без потери кадров |
| Отмена running batch и parked batch старого файла при заблокированном decoder; новый файл на другом потоке | Новый файл публикуется до разблокирования старого; старые batches не публикуются; каждая отмена уведомляет один раз; pending возвращается в ноль |
| 100 циклов × 20 файлов × 4 prefetch batches | Peak depth=32, frames=960, estimated pending=503316480 bytes (480 MiB); 3200 requests обслужены, 4800 вытеснены; после каждого цикла очередь и ownership очищены |
| DicomDecodeWorker: отмена до run, после первого кадра, непосредственно перед final publication | Final result не публикуется; request_id отмены сохранён; heavy resources освобождены для открытой session |
| DICOM pixel contract | Сохранены atomic publication, typed decode failure и соответствие bulk/single-frame |

Информационные timings последнего локального прогона, **не SLA**:
- 200 scrub submissions: 11.985 ms; resume-to-drain: 1.730 ms.
- Cancel-to-new-frame другого файла: 0.541 ms при ещё заблокированном старом decoder.
- Producer burst для 20 файлов: p50=6.123 ms, p95=6.209 ms.

Это latency искусственно управляемой worker/gate-системы, а не GUI
input-to-display latency и не время работы реального codec.

Основной прогон: **115 passed, 4 xfailed**. Включены 8 существующих
playback/cache benchmarks. Четыре xfail уже существовали в
`test_dicom_session.py`: JPEG random access (2) и JPEG2000 random access/EOT
(2), с причиной `Pixel value mismatch in CI`. Они **не являются успешной
приёмкой этих codecs** и не были добавлены/ослаблены этой работой.

Ruff, targeted mypy, function-length/class-size ratchets, `git diff --check`
прошли. Полный CI в рамках этой локальной проверки не запускался.

## Воспроизведение

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
# Только для sandbox без системных Qt-зависимостей; не для production:
MKSTUB_CI_ONLY=1 .venv/bin/python tools/qtstub/mkstub.py

LD_LIBRARY_PATH=tools/qtstub/lib QT_QPA_PLATFORM=offscreen ECHO_BENCH=1 \
.venv/bin/pytest \
  tests/unit/test_decode_gate.py \
  tests/unit/test_decode_queue_limits.py \
  tests/unit/test_decode_queue_acceptance.py \
  tests/unit/test_frame_loader_worker.py \
  tests/unit/test_dicom_decode_worker.py \
  tests/unit/test_dicom_session.py \
  tests/unit/test_dicom_pixel_contract.py \
  tests/unit/test_app_controller_dicom_cache.py \
  tests/bench/test_decode_queue_bench.py \
  tests/bench/test_playback_fps_bench.py \
  --benchmark-min-rounds=2 --benchmark-max-time=0.05 -v -s -rx
```

На машине с нативными зависимостями убрать `LD_LIBRARY_PATH` и шаг mkstub.

## Границы результата и оставшаяся приёмка

- Queue depth / pending bytes измерены; speculative bounds, hand-off,
  отмена между кадрами и защита от stale publication покрыты автоматикой.
- Pending bytes — **оценка работы**, а не RSS/объём выделенных pixels.
  Active owners, native codec, staging и кеши не входят в parked counters.
  Общий memory ledger / RSS soak остаётся отдельной задачей **#545**.
- Interactive requests намеренно имеют soft-limit исключение. Нельзя
  рекламировать parked caps как жёсткий общий memory limit процесса.
- Gate работает для DICOM/JPEG/PNG; MP4 намеренно обходит single-flight gate
  из-за seek costs. Глобальный предел активных pool tasks этим PR не вводится.
- Нативный codec, уже выполняющийся в потоке, не прерывается; shutdown ждёт
  максимум текущие in-flight calls. Hard timeout/crash isolation требует
  отдельного процесса, это не обещание текущей реализации.
- Нет строгой межфайловой справедливости при исчерпании всего QThreadPool;
  тест доказывает независимость файлов при наличии второго worker thread.
- Для окончательной приёмки нужны обычный CI на supported platforms и ручной
  прогон длинного cine: playback → быстрый scrub → смена/закрытие вкладок,
  с регистрацией input-to-display latency и отсутствия старого изображения.
  Проверить также выход из comparison во время фонового decode.

**Статус:** автоматизированная приёмка выполнена, два дефекта исправлены.
Issue #553 этим локальным прогоном не закрывается; нативная GUI/CI-приёмка
не подменяется синтетическими результатами.

## Дополнение в том же PR: P1.1 / #562 — идентичность пациента

В базе `646b219` уже было сравнение PatientID + IssuerOfPatientID: это не
новая реализация данного PR. Здесь закрыты оставшиеся пути:

- `UNVERIFIED`, как и `DIFFERENT`, требует отдельного согласия до изменения
  текущей пары, включения multiview или загрузки pixels. Default — **No**.
- Для `UNVERIFIED` добавлено отдельное предупреждение RU/EN, без ложного
  утверждения, что разные пациенты доказаны. Согласие не превращает статус
  в `SAME`; предупреждение остаётся в статусе сравнения.
- При отказе сохраняется уже открытая пара, без выгрузки её правой панели.
- Агрегация метаданных сохраняет признак недостоверности, если внутри
  исследования конфликтуют ID/issuer, фамилия, дата рождения или пол.
  Нельзя очистить конфликтующее поле и затем подтвердить пациента по
  оставшемуся совпадающему ID. Если хотя бы у одного instance нет полной
  пары ID/issuer, результат консервативно остаётся `UNVERIFIED`; это также
  исключает склеивание ID из одного заголовка и issuer из другого.
- Значимые внутренние пробелы PatientID больше не схлопываются. Регистр
  идентификаторов по-прежнему учитывается.

103 comparison-теста прошли локально (domain/application, picker, action,
coordinator), включая новые регрессии и прежние правила сравнения.
Нативная ручная приёмка должна дополнительно проверить диалог
`UNVERIFIED`/`DIFFERENT`: No не меняет панели; Yes открывает сравнение,
но не подтверждает идентичность в статусе. При корректной полной паре
PatientID/issuer без конфликтов дополнительный вопрос не нужен.

Совместный итоговый локальный прогон P1.1 + #553: **279 passed, 4 прежних
xfail**, включая i18n, DICOM metadata mapper и docs links. Использованы
тот же offscreen/stub environment и тот же список decode/benchmark тестов
выше, дополнительно:

```text
tests/unit/test_study_comparison.py
tests/unit/test_study_comparison_dialog.py
tests/unit/test_study_comparison_action.py
tests/unit/test_comparison_coordinator.py
tests/unit/test_i18n.py
tests/unit/test_dicom_metadata_mapper.py
tests/unit/test_docs_links.py
```
