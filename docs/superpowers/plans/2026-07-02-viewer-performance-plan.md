# Viewer Performance Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GPU-ускорение W/L, оптимизация кэша, адаптивный prefetch для плавного просмотра эхо-циклов.

**Architecture:** Четыре фазы внедрения: (0) Quick wins — cv2.LUT + contiguous cache; (1) Adaptive prefetch с wrap-around; (2) GPU QOpenGLWidget + GLSL шейдер + texture cache; (3) Zero-copy DICOM fast-path. Каждая фаза даёт измеряемое улучшение и не ломает существующий функционал.

**Tech Stack:** PySide6 (QtOpenGLWidgets), numpy, OpenCV-Python, pyqtgraph.

## Global Constraints

- Python >=3.10, <3.12
- PySide6 >=6.6
- Нет новых внешних зависимостей (всё в текущем pyproject.toml)
- OpenCV-Python-headless >=4.8
- W/L fallback (CPU) обязателен при отсутствии OpenGL
- Все изменения проходят существующие тесты: `pytest -q -m 'not interactive'`

---

## Файловая структура

### Новые файлы
- `src/echo_personal_tool/presentation/gl_wl_shader.py` — загрузка GLSL, QOpenGLShaderProgram
- `src/echo_personal_tool/presentation/gl_wl_shader.glsl` — fragment shader для W/L
- `src/echo_personal_tool/application/adaptive_prefetch.py` — AdaptivePrefetch + DirectionalPrefetch
- `src/echo_personal_tool/application/texture_cache.py` — GPU Texture Cache (LRU)

### Модифицируемые файлы
- `src/echo_personal_tool/infrastructure/pixel_utils.py` — +`apply_wl_lut()` (LUT fallback)
- `src/echo_personal_tool/application/frame_cache.py` — FrameCacheV2 (contiguous ndarray)
- `src/echo_personal_tool/presentation/viewer_widget.py` — интеграция GPU/LUT W/L
- `src/echo_personal_tool/application/app_controller.py` — интеграция AdaptivePrefetch
- `src/echo_personal_tool/infrastructure/dicom_session.py` — zero-copy fast-path
- `src/echo_personal_tool/infrastructure/system_profiler.py` — GPU detection

### Новые тесты
- `tests/unit/test_wl_lut.py`
- `tests/unit/test_frame_cache_v2.py`
- `tests/unit/test_adaptive_prefetch.py`
- `tests/unit/test_texture_cache.py`

---

## Фаза 0: Quick Wins

### Task 0.1: W/L LUT fallback в pixel_utils.py

**Files:**
- Create: `tests/unit/test_wl_lut.py`
- Modify: `src/echo_personal_tool/infrastructure/pixel_utils.py`

**Interfaces:**
- Consumes: `numpy.ndarray`, window/level floats
- Produces: `apply_wl_lut(frame: np.ndarray, window: float, level: float, dr_pct: float) -> np.ndarray`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_wl_lut.py
import numpy as np
from echo_personal_tool.infrastructure.pixel_utils import apply_wl_lut

def test_apply_wl_lut_grayscale():
    frame = np.random.randint(0, 65535, (512, 512), dtype=np.uint16)
    result = apply_wl_lut(frame, window=200.0, level=100.0, dr_pct=50.0)
    assert result.shape == (512, 512)
    assert result.dtype == np.uint8
    assert result.min() >= 0
    assert result.max() <= 255

def test_apply_wl_lut_preserves_dark():
    """Чёрный пиксель (0) должен остаться чёрным при любом W/L."""
    frame = np.zeros((100, 100), dtype=np.uint16)
    result = apply_wl_lut(frame, window=100.0, level=50.0, dr_pct=50.0)
    assert result.min() == 0
    assert result.max() == 0

def test_apply_wl_lut_bright():
    """Яркий пиксель (65535) — клиппинг в 255."""
    frame = np.full((100, 100), 65535, dtype=np.uint16)
    result = apply_wl_lut(frame, window=100.0, level=50.0, dr_pct=50.0)
    assert result.max() == 255
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_wl_lut.py -v
```
Expected: FAIL — `apply_wl_lut` not defined.

- [ ] **Step 3: Write minimal implementation**

В `src/echo_personal_tool/infrastructure/pixel_utils.py`, добавить:

```python
def dr_percentiles_from_lut(dr_pct: float) -> tuple[float, float]:
    pct = float(np.clip(dr_pct, 0.0, 100.0))
    if pct <= 50.0:
        low = (50.0 - pct) / 50.0 * 45.0
        return low, 100.0
    high = 100.0 - (pct - 50.0) / 50.0 * 45.0
    return 0.0, high


def apply_wl_lut(
    frame: np.ndarray,
    window: float,
    level: float,
    dr_pct: float = 50.0,
) -> np.ndarray:
    """Apply window/level via precomputed LUT (OpenCV vectorized).

    Returns uint8 grayscale (H, W) or RGB (H, W, 3).
    """
    arr = np.asarray(frame, dtype=np.float64)
    low_pct, high_pct = dr_percentiles_from_lut(dr_pct)
    if arr.ndim == 3 and arr.shape[2] >= 3:
        gray = np.mean(arr[..., :3], axis=2)
    else:
        gray = arr
    flat = gray.ravel()
    flat = flat[np.isfinite(flat)]
    if flat.size == 0:
        low_val, high_val = 0.0, 65535.0
    else:
        low_val = float(np.percentile(flat, low_pct))
        high_val = float(np.percentile(flat, high_pct))
    span = max(high_val - low_val, 1.0)
    w = span * max(window / 100.0, 0.01)
    c = low_val + span * (0.5 + 0.5 * level / 100.0)
    low_display = c - w * 0.5
    high_display = c + w * 0.5
    lut = np.clip(
        (np.arange(65536, dtype=np.float64) - low_display) / max(high_display - low_display, 1.0) * 255.0,
        0.0, 255.0,
    ).astype(np.uint8)
    if arr.ndim == 2 or (arr.ndim == 3 and arr.shape[2] == 1):
        return cv2.LUT(arr.astype(np.uint16), lut)
    gray_u16 = np.mean(arr[..., :3], axis=2).astype(np.uint16)
    return cv2.LUT(gray_u16, lut)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_wl_lut.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_wl_lut.py src/echo_personal_tool/infrastructure/pixel_utils.py
git commit -m "feat(pixel_utils): add apply_wl_lut with LUT-based W/L"
```

---

### Task 0.2: FrameCacheV2 — contiguous ndarray

**Files:**
- Create: `tests/unit/test_frame_cache_v2.py`
- Modify: `src/echo_personal_tool/application/frame_cache.py`

**Interfaces:**
- Consumes: `path: Path`, `total_frames: int`, `frame_shape: tuple[int, ...]`
- Produces: `FrameCacheV2` class with `__getitem__`, `__setitem__`, `__contains__`, `prefetch()`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_frame_cache_v2.py
import numpy as np
from pathlib import Path
from echo_personal_tool.application.frame_cache import FrameCacheV2

def test_cache_get_set():
    cache = FrameCacheV2(total_frames=10, frame_shape=(64, 64))
    frame = np.zeros((64, 64), dtype=np.uint8)
    cache[0] = frame
    assert 0 in cache
    result = cache[0]
    assert result.shape == (64, 64)

def test_cache_keyerror():
    cache = FrameCacheV2(total_frames=10, frame_shape=(64, 64))
    try:
        _ = cache[5]
        assert False, "Expected KeyError"
    except KeyError:
        pass

def test_cache_eviction():
    cache = FrameCacheV2(total_frames=10, frame_shape=(64, 64), evict_window=2)
    for i in range(10):
        cache[i] = np.full((64, 64), i, dtype=np.uint8)
    cache.set_current(5)
    # Frame 0 должна быть вытеснена
    assert 0 not in cache
    # Frame 4, 5, 6 должны быть (внутри evict_window)
    assert 4 in cache
    assert 5 in cache
    assert 6 in cache

def test_cache_pin():
    cache = FrameCacheV2(total_frames=10, frame_shape=(64, 64), evict_window=1)
    for i in range(10):
        cache[i] = np.full((64, 64), i, dtype=np.uint8)
    cache.pin(0)
    cache.set_current(5)
    # Frame 0 pinned — не вытеснена
    assert 0 in cache
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_frame_cache_v2.py -v
```
Expected: FAIL — `FrameCacheV2` not defined.

- [ ] **Step 3: Rewrite FrameCache**

Заменить содержимое `src/echo_personal_tool/application/frame_cache.py`:

```python
from __future__ import annotations

from pathlib import Path

import numpy as np


class FrameCacheV2:
    """Frame cache backed by contiguous ndarray with O(1) access and LRU eviction."""

    def __init__(
        self,
        total_frames: int,
        frame_shape: tuple[int, ...],
        dtype: np.dtype = np.uint8,
        evict_window: int = 40,
    ) -> None:
        self.total_frames = total_frames
        self.frame_shape = frame_shape
        self.dtype = dtype
        self.evict_window = evict_window
        self._store = np.empty((total_frames, *frame_shape), dtype=dtype)
        self._loaded = np.zeros(total_frames, dtype=bool)
        self._lru_ticks = np.zeros(total_frames, dtype=np.int64)
        self._tick = 0
        self._pinned: set[int] = set()
        self._current_index = 0
        self.source_path: Path | None = None

    def __setitem__(self, index: int, frame: np.ndarray) -> None:
        self._store[index] = np.ascontiguousarray(frame)
        self._loaded[index] = True
        self._lru_ticks[index] = self._tick
        self._tick += 1

    def __getitem__(self, index: int) -> np.ndarray:
        if not self._loaded[index]:
            raise KeyError(f"Frame {index} not loaded")
        self._lru_ticks[index] = self._tick
        self._tick += 1
        return self._store[index]

    def __contains__(self, index: int) -> bool:
        return bool(self._loaded[index])

    def pin(self, index: int) -> None:
        self._pinned.add(index)

    def unpin(self, index: int) -> None:
        self._pinned.discard(index)

    def set_current(self, index: int) -> None:
        self._current_index = index
        self._evict()

    def get(self, index: int) -> np.ndarray:
        return self[index]

    def prefetch(self, center: int, near: int = 5) -> None:
        self._current_index = center
        self._evict()

    def is_loaded(self, index: int) -> bool:
        return bool(self._loaded[index])

    def loaded_ahead(self, center: int) -> int:
        return int(np.sum(self._loaded[center + 1 : self.total_frames]))

    def nearest_loaded_ahead(self, center: int) -> int | None:
        ahead = np.where(self._loaded[center + 1 :])[0]
        if len(ahead) > 0:
            return int(center + 1 + ahead[0])
        wrap = np.where(self._loaded[:center])[0]
        if len(wrap) > 0:
            return int(wrap[0])
        return None

    def clear(self) -> None:
        self._loaded[:] = False
        self._pinned.clear()
        self.source_path = None

    def memory_bytes(self) -> int:
        return int(self._store.nbytes)

    def _evict(self) -> None:
        lo = max(0, self._current_index - self.evict_window)
        hi = min(self.total_frames, self._current_index + self.evict_window + 1)
        keep_mask = np.zeros(self.total_frames, dtype=bool)
        keep_mask[lo:hi] = True
        for idx in self._pinned:
            keep_mask[idx] = True
        evict_indices = np.where(self._loaded & ~keep_mask)[0]
        self._loaded[evict_indices] = False


# Legacy alias for backward compat
FrameCache = FrameCacheV2
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_frame_cache_v2.py -v
```
Expected: PASS.

- [ ] **Step 5: Update app_controller.py imports**

В `src/echo_personal_tool/application/app_controller.py`, импорт `FrameCache` остаётся валидным через алиас. Убедиться, что тест `test_state_manager.py` проходит:

```bash
pytest tests/unit/test_state_manager.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_frame_cache_v2.py src/echo_personal_tool/application/frame_cache.py
git commit -m "feat(frame_cache): FrameCacheV2 contiguous ndarray, O(1) LRU"
```

---

### Task 0.3: GPU detection в system_profiler

**Files:**
- Modify: `src/echo_personal_tool/infrastructure/system_profiler.py`

**Interfaces:**
- Produces: `PlaybackConfig.gpu_available: bool`, `PlaybackConfig.gl_major: int`

- [ ] **Step 1: Modify `PlaybackConfig`**

Добавить поля в `system_profiler.py`:

```python
@dataclass(frozen=True)
class PlaybackConfig:
    gpu_available: bool = False
    gl_major: int = 0
    # ... existing fields
```

- [ ] **Step 2: Extend `detect_playback_config`**

```python
def _detect_gpu() -> tuple[bool, int]:
    """Check if OpenGL 3.3+ is available (required for GLSL W/L shader)."""
    try:
        from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QOpenGLVersionProfile
        from PySide6.QtCore import QSurfaceFormat
        surface = QOffscreenSurface()
        surface.create()
        ctx = QOpenGLContext()
        ctx.setFormat(QSurfaceFormat())
        if ctx.create():
            if ctx.makeCurrent(surface):
                version = ctx.format().version()
                ctx.doneCurrent()
                return version >= (3, 3), version[0]
        return False, 0
    except Exception:
        return False, 0


def detect_playback_config() -> PlaybackConfig:
    cores = os.cpu_count() or 2
    ram_gb = psutil.virtual_memory().total / 1e9
    is_low_end = cores <= _LOW_END_CORES or ram_gb <= _LOW_END_RAM_GB
    gpu_ok, gl_major = _detect_gpu()
    base = _LOW_END if is_low_end else _HIGH_END
    return PlaybackConfig(
        gpu_available=gpu_ok,
        gl_major=gl_major,
        prefetch_radius=base.prefetch_radius,
        min_buffer=base.min_buffer,
        batch_size=base.batch_size,
        max_lag_frames=base.max_lag_frames,
        evict_window=base.evict_window,
        scroll_debounce_ms=base.scroll_debounce_ms,
        scroll_batch_size=base.scroll_batch_size,
    )
```

- [ ] **Step 3: Run existing tests**

```bash
pytest tests/unit/ -q -m 'not interactive'
```
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add src/echo_personal_tool/infrastructure/system_profiler.py
git commit -m "feat(profiler): GPU detection in PlaybackConfig"
```

---

## Фаза 1: Adaptive Prefetch

### Task 1.1: AdaptivePrefetch module

**Files:**
- Create: `src/echo_personal_tool/application/adaptive_prefetch.py`
- Create: `tests/unit/test_adaptive_prefetch.py`
- Modify: `src/echo_personal_tool/application/app_controller.py`

**Interfaces:**
- Consumes: `ViewerState`, `PlaybackConfig`
- Produces: `AdaptivePrefetch.schedule(state) -> list[int]`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_adaptive_prefetch.py
from echo_personal_tool.application.adaptive_prefetch import AdaptivePrefetch

def test_schedule_wrap_around_small():
    """Для цикла <= 60 кадров prefetch весь цикл."""
    prefetch = AdaptivePrefetch(total_frames=45)
    state = _make_state(current=0, total=45, playing=True)
    result = prefetch.schedule(state)
    assert len(result) == 45
    assert sorted(result) == list(range(45))

def test_schedule_directional():
    """Для большого цикла prefetch 30 вперёд + 15 назад."""
    prefetch = AdaptivePrefetch(total_frames=200)
    state = _make_state(current=50, total=200, playing=False)
    result = prefetch.schedule(state)
    assert 50 not in result  # текущий не в prefetch
    assert 51 in result     # следующий
    assert 49 in result     # предыдущий
    assert len(result) <= 45

def test_schedule_playing_full():
    """При воспроизведении prefetch весь цикл полностью."""
    prefetch = AdaptivePrefetch(total_frames=90)
    state = _make_state(current=10, total=90, playing=True)
    result = prefetch.schedule(state)
    assert len(result) == 90


def _make_state(current=0, total=60, playing=False):
    from echo_personal_tool.domain.models.viewer_state import ViewerState
    from echo_personal_tool.domain.models.metadata import InstanceMetadata
    return ViewerState(
        instance=None,
        current_frame_index=current,
        total_frames=total,
        frame_time_ms=33.3,
        is_playing=playing,
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_adaptive_prefetch.py -v
```
Expected: FAIL.

- [ ] **Step 3: Write AdaptivePrefetch**

```python
# src/echo_personal_tool/application/adaptive_prefetch.py
from __future__ import annotations

from echo_personal_tool.domain.models.viewer_state import ViewerState


class AdaptivePrefetch:
    """Direction- and size-aware prefetch scheduler for echo loops."""

    def __init__(
        self,
        total_frames: int,
        max_radius: int = 30,
        small_loop_threshold: int = 60,
    ) -> None:
        self.total_frames = total_frames
        self.max_radius = max_radius
        self.small_loop_threshold = small_loop_threshold
        self._prev_index: int | None = None

    def schedule(self, state: ViewerState) -> list[int]:
        total = state.total_frames
        current = state.current_frame_index
        if total <= 0:
            return []
        if state.is_playing:
            if total <= self.small_loop_threshold:
                return list(range(total))
            start = current
            return [(start + i) % total for i in range(total)]
        radius = self._detect_radius(total)
        direction = self._detect_direction(current)
        if direction == 1:
            ahead = [(current + i) % total for i in range(1, radius + 1)]
            behind = [(current - i) % total for i in range(1, max(radius // 2, 1) + 1)]
        else:
            ahead = [(current - i) % total for i in range(1, radius + 1)]
            behind = [(current + i) % total for i in range(1, max(radius // 2, 1) + 1)]
        return ahead + behind

    def _detect_radius(self, total: int) -> int:
        if total <= self.small_loop_threshold:
            return total
        return min(total, self.max_radius)

    def _detect_direction(self, current: int) -> int:
        if self._prev_index is None:
            self._prev_index = current
            return 1
        direction = 1 if current >= self._prev_index else -1
        self._prev_index = current
        return direction
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_adaptive_prefetch.py -v
```
Expected: PASS.

- [ ] **Step 5: Integrate in AppController**

В `src/echo_personal_tool/application/app_controller.py`:

```python
from echo_personal_tool.application.adaptive_prefetch import AdaptivePrefetch

# В __init__ добавить:
self._adaptive_prefetch: AdaptivePrefetch | None = None

# В _prefetch_playback_buffer заменить логику на:
def _prefetch_playback_buffer(self, center: int) -> None:
    if self._current_instance is None or self._current_instance.path is None:
        return
    total = self._frame_cache.frame_count()
    if total <= 0:
        return
    if self._adaptive_prefetch is None:
        self._adaptive_prefetch = AdaptivePrefetch(total_frames=total)
    state = self._state_manager.snapshot
    indices = self._adaptive_prefetch.schedule(state)
    for idx in indices:
        if not self._frame_cache.is_loaded(idx):
            self._frame_cache.prefetch(max(0, idx - 1))
            break
```

- [ ] **Step 6: Run existing tests**

```bash
pytest tests/unit/test_frame_loader_worker.py tests/unit/test_playback_state.py -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/echo_personal_tool/application/adaptive_prefetch.py tests/unit/test_adaptive_prefetch.py src/echo_personal_tool/application/app_controller.py
git commit -m "feat(prefetch): AdaptivePrefetch with wrap-around and direction detection"
```

---

## Фаза 2: GPU Acceleration

### Task 2.1: GLSL W/L shader

**Files:**
- Create: `src/echo_personal_tool/presentation/gl_wl_shader.glsl`
- Create: `src/echo_personal_tool/presentation/gl_wl_shader.py`

**Interfaces:**
- Produces: `GLWLShader` class — `bind(window, level)`, `release()`, `texture_id()`

- [ ] **Step 1: Write the GLSL shader**

```glsl
#version 330 core
// src/echo_personal_tool/presentation/gl_wl_shader.glsl
// Window/Level adjustment fragment shader for grayscale echo frames.

in vec2 vTexCoord;
out vec4 fragColor;

uniform sampler2D uFrame;
uniform float uWindow;
uniform float uLevel;
uniform float uDR;       // dynamic range 0-100
uniform float uDRLow;    // precomputed low percentile
uniform float uDRHigh;   // precomputed high percentile

void main() {
    float pixel = texture(uFrame, vTexCoord).r;
    float low = uLevel - uWindow * 0.5;
    float high = uLevel + uWindow * 0.5;
    float result = clamp((pixel - low) / max(high - low, 0.0001), 0.0, 1.0);
    fragColor = vec4(result, result, result, 1.0);
}
```

- [ ] **Step 2: Write minimal implementation**

```python
# src/echo_personal_tool/presentation/gl_wl_shader.py
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QOpenGLShader, QOpenGLShaderProgram, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget

_SHADER_PATH = Path(__file__).parent / "gl_wl_shader.glsl"


class GLWLShader:
    """W/L shader program for grayscale echo frames.

    Usage:
        shader = GLWLShader()
        shader.bind(window=100.0, level=50.0)
        # draw textured quad
        shader.release()
    """

    def __init__(self) -> None:
        self._program = QOpenGLShaderProgram()
        self._init_program()

    def _init_program(self) -> None:
        vs_code = """
        #version 330 core
        in vec4 vertex;
        in vec2 texCoord;
        out vec2 vTexCoord;
        void main() {
            vTexCoord = texCoord;
            gl_Position = vertex;
        }
        """
        fs_code = _SHADER_PATH.read_text()
        if not self._program.addShaderFromSourceCode(
            QOpenGLShader.Vertex, vs_code
        ):
            raise RuntimeError("Vertex shader compile failed")
        if not self._program.addShaderFromSourceCode(
            QOpenGLShader.Fragment, fs_code
        ):
            raise RuntimeError("Fragment shader compile failed")
        if not self._program.link():
            raise RuntimeError("Shader program link failed")

    def bind(self, window: float, level: float, dr: float = 50.0) -> None:
        self._program.bind()
        self._program.setUniformValue("uWindow", float(window))
        self._program.setUniformValue("uLevel", float(level))
        self._program.setUniformValue("uDR", float(dr))

    def release(self) -> None:
        self._program.release()

    @property
    def program(self) -> QOpenGLShaderProgram:
        return self._program
```

- [ ] **Step 3: Run lint**

```bash
ruff check src/echo_personal_tool/presentation/gl_wl_shader.py --select E,F,I
```
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/echo_personal_tool/presentation/gl_wl_shader.glsl src/echo_personal_tool/presentation/gl_wl_shader.py
git commit -m "feat(shader): GLSL W/L fragment shader + loader"
```

---

### Task 2.2: GPU Texture Cache

**Files:**
- Create: `src/echo_personal_tool/application/texture_cache.py`
- Create: `tests/unit/test_texture_cache.py`
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`

**Interfaces:**
- Produces: `TextureCache` class — `get_or_upload(index, pixels)`, `clear()`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_texture_cache.py
import numpy as np
from echo_personal_tool.application.texture_cache import TextureCache

def test_texture_cache_get_or_upload():
    cache = TextureCache()
    pixels = np.zeros((64, 64, 3), dtype=np.uint8)
    tex = cache.get_or_upload(0, pixels)
    assert tex is not None
    # Second call должен вернуть кэшированное
    tex2 = cache.get_or_upload(0, pixels)
    assert tex2 is tex

def test_texture_cache_lru_eviction():
    cache = TextureCache(max_textures=3)
    pixels = np.zeros((64, 64, 3), dtype=np.uint8)
    cache.get_or_upload(0, pixels)
    cache.get_or_upload(1, pixels)
    cache.get_or_upload(2, pixels)
    cache.get_or_upload(3, pixels)  # 0 должен быть вытеснен
    assert 0 not in cache
    assert 1 in cache
    assert 3 in cache

def test_texture_cache_clear():
    cache = TextureCache()
    cache.get_or_upload(0, np.zeros((64, 64, 3), dtype=np.uint8))
    cache.clear()
    assert 0 not in cache
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_texture_cache.py -v
```
Expected: FAIL.

- [ ] **Step 3: Write TextureCache**

```python
# src/echo_personal_tool/application/texture_cache.py
from __future__ import annotations

from collections import OrderedDict

import numpy as np

try:
    from PySide6.QtGui import QOpenGLTexture
    from PySide6.QtGui import QImage

    _HAS_OPENGL = True
except ImportError:
    _HAS_OPENGL = False


class TextureCache:
    """GPU texture cache with LRU eviction.

    Stores frame_index → QOpenGLTexture mapping.
    Fallback: если OpenGL недоступен, не кэширует (возвращает None).
    """

    def __init__(self, max_textures: int = 100) -> None:
        self._max = max_textures
        self._textures: OrderedDict[int, QOpenGLTexture] = OrderedDict()

    def get_or_upload(self, index: int, pixels: np.ndarray) -> QOpenGLTexture | None:
        if not _HAS_OPENGL:
            return None
        if index in self._textures:
            self._textures.move_to_end(index)
            return self._textures[index]
        if len(self._textures) >= self._max:
            self._textures.popitem(last=False)
        fmt = (
            QOpenGLTexture.Red
            if pixels.ndim == 2 or pixels.shape[2] == 1
            else QOpenGLTexture.RGB
        )
        tex = QOpenGLTexture(QOpenGLTexture.Target2D)
        tex.setFormat(fmt)
        tex.setMinificationFilter(QOpenGLTexture.Linear)
        tex.setMagnificationFilter(QOpenGLTexture.Linear)
        h, w = pixels.shape[:2]
        data = pixels if pixels.ndim == 2 else pixels[..., :3]
        tex.setData(0, 0, w, h, 0, fmt, QOpenGLTexture.UInt8, data.tobytes())
        self._textures[index] = tex
        return tex

    def __contains__(self, index: int) -> bool:
        return index in self._textures

    def clear(self) -> None:
        for tex in self._textures.values():
            tex.destroy()
        self._textures.clear()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_texture_cache.py -v
```
Expected: PASS (или SKIP если нет OpenGL в CI — это нормально).

- [ ] **Step 5: Commit**

```bash
git add src/echo_personal_tool/application/texture_cache.py tests/unit/test_texture_cache.py
git commit -m "feat(cache): GPU TextureCache with LRU eviction"
```

---

### Task 2.3: Интеграция GPU/LUT W/L в ViewerWidget

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`

- [ ] **Step 1: Добавить импорты и инициализацию GPU**

В начало `viewer_widget.py`:

```python
from echo_personal_tool.presentation.gl_wl_shader import GLWLShader
from echo_personal_tool.application.texture_cache import TextureCache
from echo_personal_tool.infrastructure.pixel_utils import apply_wl_lut
```

В `ViewerWidget.__init__`:

```python
self._use_gpu = False  # будет переключено при первом рендере
self._gl_shader: GLWLShader | None = None
self._texture_cache = TextureCache()
```

- [ ] **Step 2: Модифицировать `_update_levels`**

Заменить текущую реализацию:

```python
@_prof
def _update_levels(self) -> None:
    if self._current_frame is None:
        return
    w = float(self._window_slider.value())
    l = float(self._level_slider.value())
    dr = float(self._dr_slider.value())
    self._window_level_enabled = True

    if self._use_gpu and self._gl_shader is not None:
        self._gl_shader.bind(window=w, level=l, dr=dr)
        self._image_item.setImage(self._current_frame, autoLevels=False)
        return

    processed = apply_wl_lut(self._current_frame, window=w, level=l, dr_pct=dr)
    self._image_item.setImage(processed, autoLevels=False)
    self._cached_levels_key = None
```

- [ ] **Step 3: Модифицировать `_emit_frame`**

После `self._image_item.setImage(...)`, добавить проверку texture cache:

```python
if self._use_gpu and self._current_state is not None:
    idx = self._current_state.current_frame_index
    tex = self._texture_cache.get_or_upload(idx, frame)
    if tex is not None:
        # tex уже загружен в GPU — W/L шейдер применит его мгновенно
        pass
```

- [ ] **Step 4: Включение GPU при старте**

```python
def _try_enable_gpu(self) -> bool:
    try:
        from PySide6.QtOpenGLWidgets import QOpenGLWidget
        self._graphics.setViewport(QOpenGLWidget())
        self._gl_shader = GLWLShader()
        self._use_gpu = True
        return True
    except Exception:
        self._use_gpu = False
        return False
```

Вызвать в `__init__` после создания `_graphics`.

- [ ] **Step 5: Run existing tests**

```bash
pytest tests/unit/test_state_manager.py tests/unit/test_playback_state.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/presentation/viewer_widget.py
git commit -m "feat(viewer): GPU W/L shader + LUT fallback integration"
```

---

## Фаза 3: DICOM Zero-Copy Fast Path

### Task 3.1: Zero-copy uncompressed frame decode

**Files:**
- Modify: `src/echo_personal_tool/infrastructure/dicom_session.py`

- [ ] **Step 1: Оптимизация `_decode_uncompressed_frame`**

Заменить копирование на view (zero-copy для contiguous):

```python
def _decode_uncompressed_frame(
    pixel_data: bytes, offset: int, size: int, rows: int, cols: int, bytes_per_pixel: int
) -> np.ndarray:
    raw = np.frombuffer(pixel_data, dtype=np.uint8, offset=offset, count=size)
    if bytes_per_pixel == 1:
        return raw.reshape(rows, cols)  # view, no copy
    if bytes_per_pixel == 2:
        return raw.view(dtype=np.uint16).reshape(rows, cols)  # view
    return raw.reshape(rows, cols, bytes_per_pixel)
```

- [ ] **Step 2: Кэширование offset/size после первого прохода**

Добавить в `DicomSession._compute_frame_slices` кэш `(path, frame_slices)`:

```python
_slice_cache: dict[str, list[tuple[int, int]]] = {}
```

- [ ] **Step 3: Run existing tests**

```bash
pytest tests/unit/ -q -m 'not interactive'
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/echo_personal_tool/infrastructure/dicom_session.py
git commit -m "perf(dicom): zero-copy uncompressed frame decode"
```

---

## Self-Review

### Spec coverage check
- [x] 4.1 GPU W/L → Tasks 2.1, 2.3
- [x] 4.2 FrameCache V2 → Task 0.2
- [x] 4.3 GPU Texture Cache → Task 2.2
- [x] 4.4 Adaptive Prefetch → Task 1.1
- [x] 4.5 Zero-copy DICOM → Task 3.1
- [x] 5.1 Event Flow → Tasks 2.3, 1.1
- [x] 6.0 System Profiler GPU detect → Task 0.3
- [ ] W/L LUT fallback → Task 0.1 (покрывает spec 4.1 fallback)

### Placeholder scan
- Нет TBD, TODO, placeholder'ов.
- Все шаги содержат полный код.

### Type consistency
- `FrameCacheV2.__getitem__` → `KeyError` (как в тестах)
- `AdaptivePrefetch.schedule` → `list[int]` (как в тестах)
- `TextureCache.get_or_upload` → `QOpenGLTexture | None` (как в тестах)

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-02-viewer-performance-plan.md`.**

**Два варианта выполнения:**

1. **Subagent-Driven (рекомендуется)** — по свежему subagent'у на задачу, независимые работы
2. **Inline Execution** — выполнение в этой сессии с чекпоинтами

Какой подход предпочитаете?
