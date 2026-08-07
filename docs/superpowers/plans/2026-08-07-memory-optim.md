## Memory optimization plan for SonoForge DICOM playback

### Corrected after critical review (2026-08-07)

Этот план — исправленная версия после критического анализа. Исправлены:
- Опечатка `release_heial` → `release_heavy`
- Серьёзная ошибка: `levels_changed` — dead code в `show_frame_fast()`, пропозиция использовать её для gating `_update_levels()` сломала бы W/L rendering
- Перестоценка: `_is_levels_outlier` не вызывается каждый кадр (уже есть внутренний кеш `_cached_levels_key`)
- Неверная формулировка race condition (уже исправлена — `_metadata` намеренно сохраняется в `release_heavy()`)
- Добавлена: пути к файлам, стратегия тестирования, реалистичные time estimate

---

## Оставшиеся неисправленные проблемы

Выявлено **3 реальных узкие места**, которые Playback Resilience Layer plan не затрагивает:

### Проблема 1: `release_stale_sessions()` блокирует главный поток

**Где:** `app_controller.py:363` — вызывается синхронно в `load_instance()` при переключении файлов.

**Что происходит:** `release_stale_sessions()` обходит все thread-local `DicomSession` (до 10 штук, `_max_sessions = 10`), каждый вызывает `release_heavy()`. На слабом ПК с 10 сессиями по 19 МБ каждая — это до 190 МБ работы по очистке на каждом переключении, выполняемой синхронно на UI потоке.

**Важно:** Это **не race condition** — `release_heavy()` (line 588) намеренно не трогает `_metadata` (исправление 2026-08-06, checkpoint §7). Worker-потоки `decode_all_frames()` корректно читают `_metadata.Rows`, `_metadata.Columns`. Проблема — **blocking UI**, а не data race.

**Решение:** Перенести в `QRunnable` — аналогично `_StudyQueryWorker`. Сигнал `stale_sessions_released` → продолжить загрузку файла в `load_instance()`.

### Проблема 2: `_update_levels()` вызывается каждый кадр, но работает неэффективно для grayscale

**Факт:** `_is_levels_outlier` (line 6617) вызывается **только внутри cache-miss branch** `_update_levels()` (line 6552). Внутренний кеш (`_cached_levels_key == sliders_key`, line 6533) уже корректно пропускает `compute_display_levels` + `_is_levels_outlier` при стабильных слайдерах.

**⚠️ Plan's proposed fix would BREAK W/L rendering.** Переменная `levels_changed` (line 1751) — dead code: вычисляется, не используется. Но добавление `if levels_changed: _update_levels()` на call-site **сломало бы window leveling**: при стабильных слайдерах LUT перестанет применяться к новым кадрам. LUT application на каждый кадр необходим (`cv2.LUT` ~1-2ms), т.к. каждый кадр имеет новые пиксели.

**Решение: cleanup, не fix.** Удалить dead variable `levels_changed` на line 1751 для читаемости. Логика gating уже корректна внутри `_update_levels()`.

### Проблема 3: Нет адаптивного memory budget

**Где:** `frame_cache.py:19` — `_MAX_CACHE_MEMORY_BYTES = 2 * 1024 * 1024 * 1024` (2 GB), `_evict_window = 40`.

**Что происходит:** 2 ГБ кэша = 25% всей памяти на ПК с 8 ГБ. На больших файлах (4K) — полный лимит на один файл (60 кадров × 33 МБ = 2 ГБ).

**Решение:** Адаптивный бюджет:
```python
import psutil
available = psutil.virtual_memory().available
max_cache = min(128 * 1024 * 1024, int(available * 0.08))
```
+ адаптивный `evict_window`: если frame_size > 2 МБ, уменьшать window до 10-15.

---

## Что из плана стоит взять

| Идея плана | Готово? | Применимо? | Рекомендация |
|---|---|---|---|
| Generation ID / запрос-отмена | ✅ (`request_id` в `DicomDecodeWorker`, `_pending_frame_request_id` в viewer) | ✅ | Расширить на prefetch cancellation |
| LRU FrameCache с memory budget | ✅ (`frame_cache.py`), но лимит 2ГБ | ✅ | Сделать адаптивным + добавить профили |
| Single active decoder | ✅ Thread-local `DicomSession` | ✅ | Оставить |
| Cancel prefetch on file switch | ✅ (`release_stale_sessions`) | ✅ | Перенести в фон (см. Проблема 1) |
| First-frame fast display | ✅ (`decode_first_frame()`, `first_frame_ready`) | ✅ | Оставить |
| D3D11VA/DXVA2 GPU pipeline | ❌ | ❌ | НЕТ — Python/PySide6, нет FFmpeg, D3D11 interop требует C++ |
| Дисковый proxy-cache | ❌ | ❌ | НЕТ — нарушает de-identification PHI |
| Resolution-adaptive decode | Частично (`VideoReader` ring buffer) | ⚠️ | Только для MP4: `video_reader.py:61,86`. DICOM decode уже быстрый |
| Low-memory profile | ❌ | ✅ | `UserPreferences.playback_max_cache_mb` (default 64) + `PlaybackConfig.evict_window` (12 for low-end) |
| Метрики памяти | ✅ (`playback_diagnostics.py`) | ✅ | Добавить per-switch дельты |
| Не более 1-2 decode workers | ✅ Thread-local | ✅ | Оставить |

**Не берём:** дисковый кэш, GPU D3D11VA пайплайн, proxy-файлы на диск, FFmpeg-замена.

---

## Конкретные действия (в порядке приоритета)

1. **Адаптивный memory budget + low-memory profile** — 3-4 часа.
   - `UserPreferences.playback_profile` (enum: auto|low_memory|balanced|performance)
   - `FrameCache.__init__` читает профиль, устанавливает `_MAX_CACHE_MEMORY_BYTES = min(128MB, available * 0.08)` и адаптивный `evict_window`
   - **File:** `frame_cache.py:19`

2. **Удалить dead variable `levels_changed`** — 15 мин (cleanup).
   - `show_frame_fast()` вычисляет `levels_changed` (line 1751), но не использует
   - Удалить строки 1751 + 1752, т.к. внутренний кеш `_update_levels()` (line 6533) уже обрабатывает gating корректно
   - **File:** `viewer_widget.py:1751-1752`

3. **Убрать явный `release_stale_sessions()` из `load_instance()`** — 30 мин.
   - QRunnable подход отклонён: race condition — `release_stale_sessions()` (без `exclude`) может вызвать `release_heavy()` на сессии, которая сейчас декодируется в `DicomDecodeWorker.run()` → `decode_all_frames()` → `ThreadPoolExecutor`. `release_heavy()` ставит `self._frames = None`, и строка `self._frames[idx] = future.result()` падает с `TypeError`.
   - `DicomSession.open()` (line 333) уже вызывает `release_stale_sessions(exclude=self)` на воркере — до начала декодирования. Старые сессии освобождаются на воркере, а не на главном потоке.
   - **File:** `app_controller.py:363` (remove call, rely on `DicomSession.open()`)

4. **Расширить telemetry** — 1-2 часа.
   - Добавить `on_instance_switch()` и `on_prefetch_cancel()` в `playback_diagnostics.py:36`
   - `_prefetch_playback_buffer()` в `app_controller.py:1717` должен emit сигнал при отмене для диагностики

---

## Стратегия тестирования

| Цель | Тест-кейс | Ожидаемое поведение |
|---|---|---|
| Adaptive budget | `_MIN_FRAME_SIZE_BYTES` floor в `FrameCache.__init__` | `max_cache_bytes < 600KB` → бампится до 600KB + warning log |
| Adaptive budget | `load_user_preferences().playback_max_cache_mb` в `AppController` | уважает user preference, а не class default (64) |
| evict_window | `system_profiler.py`: low-end 12, high-end 20 | `detect_playback_config()` возвращает правильные значения |
| `_update_levels()` caching | grayscale W/L, слайдеры не двигаются | `np.mean`/`np.std` (в `_is_levels_outlier`) вызываются ≤1 раз/сессия; LUT применяется каждый кадр (~1-2ms) |
| Despeckle + W/L | `_despeckle_enabled=True`, W/L on/off | W/L применяется правильно в обоих режимах |
| release_stale_sessions | `DicomSession.open()` calls `release_stale_sessions(exclude=self)` на воркере | старые сессии освобождаются до декодирования; `_RELEASE_stale_sessionsWorker` НЕ существует (race condition) |
| Prefetch cancel | смена файла во время prefetch | старый `FrameLoaderWorker` отменяется, `on_prefetch_cancel` вызывается |

### Dependencies
- `psutil` — уже используется в `system_profiler.py:8` и `playback_diagnostics.py:36` ✅

### File paths reference
- `frame_cache.py` → `src/echo_personal_tool/application/frame_cache.py` (line 19: `_MAX_CACHE_MEMORY_BYTES`, line 22: `_DEFAULT_EVICT_WINDOW`)
- `dicom_session.py` → `src/echo_personal_tool/infrastructure/dicom_session.py` (line 55: `_max_sessions`, line 85: `release_stale_sessions`, line 588: `release_heavy`)
- `viewer_widget.py` → `src/echo_personal_tool/presentation/viewer_widget.py` (line 1751: `levels_changed` in `show_frame_fast`, line 1788: grayscale `_update_levels()` call, line 6517: `_update_levels`, line 6533: internal cache check, line 6617: `_is_levels_outlier`)
- `video_reader.py` → `src/echo_personal_tool/infrastructure/video_reader.py` (line 61,86: `VideoReader.open()`)
- `app_controller.py` → `src/echo_personal_tool/application/app_controller.py` (line 363: `release_stale_sessions` call, line 1717: `_prefetch_playback_buffer`)
- `playback_diagnostics.py` → `src/echo_personal_tool/infrastructure/playback_diagnostics.py` (line 36: psutil)