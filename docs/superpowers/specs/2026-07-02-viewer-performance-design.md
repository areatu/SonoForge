# Viewer Performance Overhaul — Design Spec

**Дата:** 2026-07-02
**Статус:** Draft
**Автор:** AI Research Agent

---

## 1. Executive Summary

Повышение производительности просмотра DICOM/видео-кадров в echo-personal-tool.
Текущий рендеринг — CPU-bound (pyqtgraph ImageItem + numpy W/L).
Цель: GPU-ускорение W/L, оптимизация кэша, адаптивный prefetch для эхо-циклов.

**Ключевые метрики:**
- W/L latency: 5-20ms → <1ms (GPU) или 1-3ms (LUT)
- Scroll latency: ~100ms → <16ms (60fps)
- Playback buffer underrun: устранение
- RAM cache efficiency: 2x improvement

---

## 2. Текущая архитектура (AS-IS)

```
┌─ UI Layer ─────────────────────────────────────┐
│  ViewerWidget (QWidget)                        │
│  ├── pg.GraphicsLayoutWidget                   │
│  │   └── pg.ImageItem (CPU rendering)          │
│  ├── Window/Level: percentile_range → clip     │
│  │   (pixel_utils.py: compute_display_levels)   │
│  ├── QSlider * 3 (window, level, dr)           │
│  └── Playback: QTimer + step_frame             │
├─ Controller ────────────────────────────────────┤
│  AppController                                  │
│  ├── FrameCache (dict[int, ndarray])            │
│  ├── DicomDecodeWorker (ThreadPoolExecutor 4)   │
│  ├── FrameLoaderWorker (QRunnable)              │
│  ├── PlaybackConfig (prefetch_radius=3-10)      │
│  └── QTimer playback                            │
└─ Infrastructure ────────────────────────────────┤
   ├── DicomSession (thread-local)                │
   ├── pixel_utils.py (numpy W/L, color conv)     │
   └── system_profiler.py (low-end/high-end)      │
```

### Bottlenecks

1. **W/L — CPU per frame:** `percentile_range` → `compute_display_levels` → clip → cast
   — полный проход по всем пикселям при каждом движении слайдера
2. **FrameCache — Python dict:** O(n) eviction, numpy object overhead
3. **Prefetch — консервативен:** radius 3-10 для эхо-циклов (20-90 кадров)
4. **Нет GPU cache:** каждая смена кадра — новая загрузка в texture Qt
5. **Scroll debounce 70ms:** batch не подстраивается под направление скролла

---

## 3. Целевая архитектура (TO-BE)

```
┌─ UI Layer ───────────────────────────────────────────┐
│  ViewerWidget (QWidget)                              │
│  ├── QGraphicsView + QOpenGLWidget viewport          │
│  │   └── pyqtgraph ImageItem (рендеринг через OpenGL)│
│  ├── W/L: GLSL fragment shader ИЛИ cv2.LUT fallback  │
│  ├── QSlider * 3 (w, l, dr) → мгновенный W/L        │
│  └── Playback: adaptive QTimer + wrap-around prefetch│
├─ Controller ──────────────────────────────────────────┤
│  AppController                                        │
│  ├── FrameCache V2 (contiguous ndarray + ring buffer) │
│  ├── GPU Texture Cache (LRU, Qt texture IDs)         │
│  ├── PriorityDecodeQueue (frame decode priority)      │
│  ├── AdaptivePrefetch (frame_count-aware)             │
│  └── DirectionalPrefetch (+ wrap-around)              │
└─ Infrastructure ──────────────────────────────────────┤
   ├── DicomSession (zero-copy fast-path)               │
   ├── gl_wl_shader.glsl (GLSL W/L)                    │
   ├── lut_utils.py (cv2.LUT generation)                │
   └── system_profiler.py (extended: GPU detect)        │
```

---

## 4. Компоненты спецификации

### 4.1 GPU Window/Level (GLSL Shader)

**Файлы:** `src/echo_personal_tool/presentation/gl_wl_shader.glsl`

```glsl
// Fragment shader для W/L
#version 330 core
in vec2 vTexCoord;
uniform sampler2D uFrame;     // исходный кадр (R=grayscale)
uniform float uWindow;
uniform float uLevel;
out vec4 fragColor;

void main() {
    float pixel = texture(uFrame, vTexCoord).r;
    float low = uLevel - uWindow * 0.5;
    float high = uLevel + uWindow * 0.5;
    float result = clamp((pixel - low) / max(high - low, 1.0), 0.0, 1.0);
    // colormap для цветного допплера (опционально)
    fragColor = vec4(result, result, result, 1.0);
}
```

**Назначение:** вытесняет CPU-функцию `compute_display_levels` в GPU.

**Условия:**
- Пиксели загружаются как текстура (GL_RED для grayscale, GL_RGB для цветного допплера)
- W/L параметры передаются как uniform-переменные (без перезагрузки текстуры)
- Dynamic range слайдер маппится на window/level (доп. uniform)
- Поддержка цветного допплера: отдельный шейдер с HSV mixing

**Fallback (CPU):**
```python
def _apply_wl_lut(frame: np.ndarray, w: float, l: float) -> np.ndarray:
    low = l - w * 0.5
    high = l + w * 0.5
    # Предрасчёт LUT для 16-bit → 8-bit
    lut = np.clip((np.arange(65536, dtype=np.float64) - low)
                  / max(high - low, 1.0) * 255.0, 0, 255).astype(np.uint8)
    return cv2.LUT(frame, lut)  # OpenCV vectorized
```

**Интеграция с pyqtgraph:**
- `GraphicsLayoutWidget.setViewport(QOpenGLWidget())` — включает OpenGL-рендеринг
- Shader прикрепляется к `ImageItem` через `QOpenGLShaderProgram`
- Либо через кастомный QGraphicsItem с QOpenGLWidget

### 4.2 FrameCache V2

**Файлы:** `src/echo_personal_tool/application/frame_cache.py` (refactor)

**Текущий:** `dict[int, ndarray]` + LRU-loop.

**Новый:**
```python
@dataclass
class FrameCacheV2:
    source_path: Path | None
    total_frames: int
    # Contiguous storage (avoid Python objects)
    _store: np.ndarray  # (N, H, W) or (N, H, W, C), dtype=uint8
    _loaded: np.ndarray  # bool[N] — какие кадры загружены
    _lru_order: np.ndarray  # int[N] — timestamp последнего доступа
    _evict_window: int
    _pinned: set[int]
```

**Изменения:**
- `np.ndarray` contiguous block вместо dict → cache-friendly memory layout
- `_lru_order` — массив int64 для O(1) LRU (argpartition для eviction)
- `_loaded` — boolean маска (np.where быстрее dict lookup)
- Optional: numpy.memmap для серий >500 кадров

**API migration:**
```python
# Old
cache.get(index) -> ndarray | None
cache.put(index, frame)
cache.is_loaded(index) -> bool

# New
cache[index] -> ndarray  # raises KeyError
cache[index] = frame     # insert
index in cache           # O(1) bool
cache.prefetch(center)   # prefetch вокруг центра
```

### 4.3 GPU Texture Cache

**Новый файл:** `src/echo_personal_tool/application/texture_cache.py`

**Назначение:** избежать повторной загрузки пикселей в GPU при повторном показе кадра.

```python
class TextureCache:
    _textures: dict[int, QOpenGLTexture]  # frame_index → texture
    _lru: OrderedDict[int, QOpenGLTexture]
    _max_textures: int = 100  # ~100 textures * 512KB = 50MB VRAM

    def get_or_upload(self, index: int, pixels: ndarray) -> QOpenGLTexture:
        if index in self._textures:
            return self._textures[index]
        tex = QOpenGLTexture(pixels)  # upload to VRAM
        self._textures[index] = tex
        return tex
```

**Интеграция:** ViewerWidget проверяет texture cache перед upload в ImageItem.

### 4.4 Adaptive + Directional Prefetch

**Файлы:** `src/echo_personal_tool/application/app_controller.py` (modify)

**Специфика эхокардиографии:**
- Циклы 20-90 кадров, frame_time 11-50ms (20-90 fps)
- Пользователь скроллит циклически (0→N→0)
- Воспроизведение — циклический loop

**Новая логика:**
```python
class AdaptivePrefetch:
    def schedule(self, state: ViewerState) -> list[int]:
        total = state.total_frames
        current = state.current_frame_index
        direction = self._detect_direction()
        radius = self._adaptive_radius(total)  # small loop → full prefetch
        if state.is_playing:
            # Wrap-around: prefetch весь цикл
            return list(range(total))
        # Directional: prefetch в направлении + соседи для scroll
        ahead = [(current + i) % total for i in range(1, radius + 1)]
        behind = [(current - i) % total for i in range(1, radius // 2 + 1)]
        return ahead + behind

    def _adaptive_radius(self, total: int) -> int:
        if total <= 60:  # эхо-цикл: prefetch весь
            return total
        return min(total, 30)  # большой цикл: prefetch 30
```

**Scroll debounce:**
- Текущий: `scroll_debounce_ms = 70` (low) / 50 (high)
- Новый: directional batch prefetch + immediate target frame load
- После скролла: prefetch соседних кадров + текущий target с приоритетом

### 4.5 Zero-Copy DICOM Fast Path

**Файлы:** `src/echo_personal_tool/infrastructure/dicom_session.py` (modify)

**Текущий:** `_extract_pixel_data_from_bytes` — сканирование байт, поиск PixelData тега.

**Улучшение:**
- Кэшировать `(path, frame_size, offset)` после первого прохода
- Для uncompressed: `np.frombuffer(raw, offset=..., dtype=uint8).reshape(rows, cols)`
- Избежать копирования: `np.ascontiguousarray(...).copy()` → `np.ascontiguousarray(...)` (view, без copy)

---

## 5. Интеграция с существующими компонентами

| Компонент | Тип интеграции | Затрагиваемые файлы |
|-----------|---------------|---------------------|
| W/L slider → GLSL | Замена compute_display_levels в viewer_widget | `viewer_widget.py`, новый `gl_shader.py` |
| FrameCacheV2 | Замена import + API | `frame_cache.py`, `app_controller.py` |
| Texture Cache | Новый класс, интеграция в _emit_frame | `texture_cache.py`, `viewer_widget.py` |
| AdaptivePrefetch | Замена _prefetch_playback_buffer | `app_controller.py` |
| Zero-copy DICOM | Оптимизация DicomSession | `dicom_session.py` |
| W/L fallback LUT | Новая функция в pixel_utils | `pixel_utils.py` |
| system_profiler | Расширение: GPU detect | `system_profiler.py` |

### 5.1 Event Flow (рендеринг кадра)

```
User moves W/L slider
  → ViewerWidget._update_levels()
  → NEW: gl_program.bind()
         gl_program.setUniformValue("uWindow", w)
         gl_program.setUniformValue("uLevel", l)
         → GPU пересчитывает W/L за <1ms
  → OLD: compute_display_levels(frame, ...) → clip → cast → ImageItem.setImage()

Playback advances frame
  → AppController._advance_playback()
  → AdaptivePrefetch.schedule(current)
  → FrameCacheV2[current] (O(1)) 
     ИЛИ DicomSession.read_frame(current)
  → TextureCache.get_or_upload(current, frame)
  → GLSL W/L шейдер + display
```

---

## 6. План миграции (безопасный rollout)

### Фаза 0: Quick wins (2-3 дня)
1. W/L fallback LUT через cv2.LUT — минимальные изменения, 2-5x ускорение
2. System profiler расширение (GPU detection)
3. FrameCache -> contiguous array (замена dict на ndarray)

### Фаза 1: Prefetch (2 дня)
4. AdaptivePrefetch с wrap-around
5. Directional prefetch для scroll

### Фаза 2: GPU (3-4 дня)
6. QOpenGLWidget viewport для pyqtgraph
7. GLSL W/L шейдер
8. GPU Texture Cache

### Фаза 3: DICOM (1-2 дня)
9. Zero-copy fast-path доработка
10. FrameCacheV2 memmap для больших серий

---

## 7. Тестирование

### Unit-тесты
- `test_wl_shader`: сравнение вывода GLSL с CPU reference (на QGuiApplication)
- `test_frame_cache_v2`: O(1) access, eviction, pin
- `test_texture_cache`: upload/lookup/eviction
- `test_adaptive_prefetch`: wrap-around, direction detection

### Performance benchmarks
```python
# pytest-benchmark
def test_wl_lut(benchmark):
    frame = np.random.randint(0, 65535, (512, 512), dtype=np.uint16)
    benchmark(apply_wl_lut, frame, 200, 100)
    # Target: <3ms

def test_frame_cache_v2_access(benchmark):
    cache = FrameCacheV2(total=60, shape=(512, 512))
    cache[0] = np.zeros((512, 512), dtype=np.uint8)
    benchmark(lambda: cache[0])
    # Target: <1µs

def test_gl_wl_shader(benchmark):
    # Требует QGuiApplication, опционально
    pass
```

### Integration tests (существующие)
- `test_main_window_doppler.py` — проверить, что W/L не сломан
- `test_playback_state.py` — проверить prefetch
- `test_frame_loader_worker.py` — совместимость

---

## 8. Критерии успеха

| Метрика | Текущая | Целевая | Инструмент |
|---------|---------|---------|------------|
| W/L latency (слайдер→экран) | 5-20ms | <1ms (GPU) / <3ms (LUT) | perf_counter |
| Scroll target frame latency | 50-100ms | <16ms | QElapsedTimer |
| Playback buffer underrun | периодически | 0 за 60s playback | log monitor |
| FrameCache memory overhead | ~500 bytes/frame | ~200 bytes/frame | tracemalloc |
| GPU texture re-upload (% miss) | 100% | <20% после cache fill | log counter |
| Cold start (DICOM open→first frame) | 500-2000ms | <300ms | perf_counter |

---

## 9. Приложение: зависимости

**Нет новых зависимостей.** Всё реализуется в рамках существующего стека:
- PySide6 (включает QtOpenGL, QtOpenGLWidgets)
- OpenCV-Python (cv2.LUT уже доступен)
- numpy (ключевой)
- pyqtgraph (setViewport(QOpenGLWidget) уже поддерживает)

**Опционально:** PyOpenGL для прямого GLSL, если понадобится обход pyqtgraph.

---

## 10. Приложение: риски

| Риск | Вероятность | Митигация |
|------|------------|-----------|
| OpenGL не доступен на ПК пользователя | Низкая | CPU fallback LUT |
| pyqtgraph + QOpenGLWidget конфликт оверлеев | Средняя | Тесты overlay; гибридный режим |
| Texture Cache VRAM overflow | Низкая | LRU + max_textures |
| Регрессия цветного допплера | Средняя | Отдельный шейдер + reference тесты |
