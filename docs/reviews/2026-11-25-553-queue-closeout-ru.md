# #553 — приёмка очередей decode/prefetch: закрытие

> **Снимок на 2026-11-25.** Документ закрывает чек-лист приёмки issue #553: сводит
> выполненное срезами #573, #574, #601 и этим PR в одну таблицу. Актуальное состояние —
> в коде, README, HELP и открытых issues.

## Статус критериев приёмки

| Критерий | Статус | Реализация и доказательство |
|---|---|---|
| Измерены queue depth, pending bytes и latency при scrub/смене вкладок | **выполнен** | `DecodeQueueStats` (`application/decode_gate.py`): parked requests/frames, pending bytes, drops — снимок уходит в `PlaybackDiagnostics.on_prefetch_cancel(queue_stats=…)` при каждой инвалидации prefetch (scroll/смена файла/вкладки) и печатается в отчёте `ECHO_PLAYBACK_DIAG=1` (срез #574). Синтетические цифры: `tests/bench/test_decode_queue_bench.py` (scrub-бёрст и смена вкладок), `tests/unit/test_decode_queue_acceptance.py` (детерминированные потоки). Этим PR в рантайм-отчёт добавлена третья метрика — интерактивная латентность scrub-цели «submit → published» (`PlaybackDiagnostics.on_interactive_decode`, раздел «Interactive decode round trip» в отчёте; отменённые/заменённые цели не считаются). |
| Ограничены speculative queues без регрессии playback | **выполнен** | Бюджеты `DecodeGate`: ≤8 parked-запросов и ≤128 кадров на файл, ≤32 запросов и ≤512 MiB pending глобально; вытесняется только speculative-работа (NEIGHBORS/PLAYBACK/BACKGROUND), INTERACTIVE не вытесняется никогда; входящий запрос защищён, но сам может быть снят при переполнении (фикс #601). Лимиты выше штатного набора контроллера, поэтому playback не меняется; дедупликация перекрывающихся диапазонов вместо полного слияния сохраняла скорость (#573, замер 45→50 мс при отбрасывании). |
| Отмена/generation проверяются между кадрами и перед публикацией | **выполнен** | `FrameLoaderWorker.cancel()` — между кадрами и перед публикацией батча (+`cancel_parked` для заменённых в очереди, одноразовый `cancelled`-сигнал); `DicomDecodeWorker` — `cancel()` + `cancel_check` внутри `decode_all_frames`; полный decode держит ≤4 futures и не пополняет очередь после отмены (регрессия «50 из 50 codec calls» → «≤5», #601). Идентичность публикации — request_id/generation на стороне контроллера (`_prefetch_load_id`, `_study_load_generation`, guard в `_on_leading_scan_batch_loaded`/`_on_scroll_target_loaded`); acceptance-тест `test_tab_switch_cancels_running_and_parked_without_stale_publication`. |

## Что сознательно осталось (и почему это не часть критериев)

- **Отдельный worker-process для нативного декодера** — в issue помечен как
  «разумный опциональный hardening»: поток не даёт жёсткого memory/time limit.
  Не делалось: существующие декодеры кооперативно отменяемы, а вынос сессии в
  процесс меняет модель владения `DicomSession` и окупается только при
  подтверждённых зависаниях нативного кодека на поддерживаемых платформах.
- **Жёсткий глобальный RSS-бюджет** — это область #545 (owned frame buffers +
  unified budget), не #553; счётчики gate описывают оценки parked-работы.
- **MP4 вне gate** — намеренно: интерливинг interactive-цели в seek-bound
  видеоконтейнер замедляет оба потока (замер в `frame_loader_worker.py`:
  44.5 мс gated против 37.1 мс ungated). Отмена и generation-проверки для mp4
  работают на уровне пула и контроллера.
- **Нативная приёмка на supported platforms** (реальные vendor-клипы, мышь,
  FPS экрана) — вне sandbox; эта работа принимает на offscreen Qt со stubs
  системных библиотек, как и предыдущие срезы (#573/#574/#601).

## Этот срез

- `PlaybackDiagnostics.on_interactive_decode(frame_index, elapsed_ms)` и раздел
  «Interactive decode round trip (scroll target submit → published)» в отчёте:
  латентность scrub-цели теперь видна в живом отчёте, а не только в bench.
  Источник измерения — `_on_scroll_target_loaded` от `_scroll_load_started_at`
  (момент постановки текущего запроса); публикуется только реально показанный
  кадр, заменённая цель отменена и в статистику не попадает.
- Тесты: `test_playback_diagnostics_metrics.py` — отдельность метрики от batch
  round trip, отсутствие раздела в чистом отчёте, выключенный коллектор.

## Воспроизведение

```bash
QT_QPA_PLATFORM=offscreen pytest \
  tests/unit/test_playback_diagnostics_metrics.py \
  tests/unit/test_playback_diagnostics_instance_switch.py \
  tests/unit/test_playback_prefetch.py \
  tests/unit/test_decode_gate.py \
  tests/unit/test_decode_queue_limits.py \
  tests/unit/test_decode_queue_acceptance.py \
  tests/unit/test_worker_frame_loader.py \
  tests/unit/test_dicom_decode_worker.py -v

ECHO_BENCH=1 pytest tests/bench/test_decode_queue_bench.py -v -s
ECHO_PLAYBACK_DIAG=1  # рантайм-отчёт при воспроизведении/scrub/смене вкладок
```
