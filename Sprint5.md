# Sprint 5 — EchoNet ONNX + Spline Editor

**Фаза:** 2  
**Предшественник:** Sprint 4 (`feat/phase1-mvp` @ `92962ed`)  
**Статус:** Завершён  
**Scope:** [`Этап2.md`](Этап2.md) S5 — EchoNet Segmentation Lite (ONNX интеграция), сплайн-редактор

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task with spec + quality review after each task.

**Goal:** Auto Segment (hotkey `I`) на кадре ED/ES через ONNX → контур эндокарда; коррекция сплайн-узлами (`ScatterPlotItem`) с пересчётом Симпсона.

**Architecture:** Domain `segmentation_service` (NumPy); Infrastructure `OnnxInferenceEngine`; Application `OnnxWorker` (`ProcessPoolExecutor`, max_workers=1); Presentation — `PlotDataItem` контур + `ScatterPlotItem` узлы.

**Tech Stack:** onnxruntime (CPU), NumPy, SciPy, OpenCV (resize в Domain через cv2 — **нет**, resize в Domain через numpy/scipy или pure numpy; Этап2 говорит prepare_tensor в Domain, cv2 только Infrastructure — используем scipy.ndimage или numpy для resize в Domain)

**Model contract:** `models/model_manifest.json` — вход `(1,3,112,112)` float32, выход logits → sigmoid → threshold 0.5.

---

## 1. Цель

| Функция | Описание |
|---|---|
| **Auto Segment (`I`)** | ONNX на текущем кадре ED/ES → маска → контур (`source="ai"`) |
| **Сплайн-редактор** | Узлы на контуре (`ScatterPlotItem`), drag → обновление точек → `contours_changed` |
| **Fallback** | Нет модели / timeout > 2 с / OOM → статус-бар «используйте ручной контур» |
| **Анти-OOM** | `ProcessPoolExecutor(max_workers=1)`; инференс только на остановленном кадре |

---

## 2. Контекст

- S4: `Contour` с `source="manual"`, `ViewerWidget` ручной полигон (`C` + клики + Enter)
- S2: ED (`D`) / ES (`S`) hotkeys, `ViewerState.ed_frame_index` / `es_frame_index`
- Экспорт ONNX уже есть: `scripts/export_echonet_seg_to_onnx.py`, manifest `status: exported`
- `IOnnxSegmenter` в `domain/ports.py` — **добавить** (сейчас отсутствует на phase1-mvp)
- Presentation **не импортирует** onnxruntime / cv2

### UX (Этап3 §4.2, сценарий А2)

1. Маркировка ED/ES (`D` / `S`)
2. На кадре ED: `I` → AI-контур
3. На кадре ES: повторить `I`
4. Перетаскивание сплайн-узлов для коррекции
5. `MeasurementPanel` пересчитывает Симпсон (уже wired в S4)

---

## 3. Задачи

### Task 1: Domain segmentation_service ✅

**Files:**
- Create: `src/echo_personal_tool/domain/services/__init__.py`
- Create: `src/echo_personal_tool/domain/services/segmentation_service.py`
- Test: `tests/unit/test_segmentation_service.py`

**Functions (pure NumPy/SciPy, no Qt/onnx/cv2):**

```python
def prepare_tensor(frame: np.ndarray, *, target_size: int = 112) -> np.ndarray:
    """RGB/BGR or grayscale H×W → (1, 3, H, W) float32, per-frame mean/std norm."""

def logits_to_mask(logits: np.ndarray, threshold: float = 0.5) -> np.ndarray:
    """(1,1,h,w) or (h,w) logits → binary mask (h,w) uint8 {0,1}."""

def mask_to_contour(mask: np.ndarray, original_shape: tuple[int, int]) -> list[tuple[float, float]]:
    """Largest connected component → closed polygon in original pixel coords."""

def smooth_contour(points: list[tuple[float, float]], *, num_nodes: int = 32) -> list[tuple[float, float]]:
    """Resample closed contour to num_nodes for spline editing."""
```

**Tests:** synthetic circle mask → contour area; prepare_tensor shape/dtype; smooth_contour count.

---

### Task 2: IOnnxSegmenter port + OnnxInferenceEngine ✅

**Files:**
- Modify: `src/echo_personal_tool/domain/ports.py` — add `IOnnxSegmenter`
- Create: `src/echo_personal_tool/infrastructure/onnx_engine.py`
- Test: `tests/unit/test_onnx_engine.py` (mock session or skip if no model file)

**IOnnxSegmenter:**
```python
class IOnnxSegmenter(Protocol):
    def segment(self, frame: np.ndarray) -> np.ndarray: ...  # mask H×W uint8
    def is_available(self) -> bool: ...
```

**OnnxInferenceEngine:**
- Load model from `models/` via `model_manifest.json` (`active_model`)
- `segment(frame)`: prepare_tensor → session.run → logits_to_mask → return mask (112×112 upscaled to frame H×W optional in engine or delegate mask_to_contour with scale)
- `is_available()`: manifest + file exists
- Use onnxruntime CPU provider only
- No cv2 in presentation; cv2 resize allowed in infrastructure if needed for frame prep before domain tensor

---

### Task 3: OnnxWorker (background inference) ✅

**Files:**
- Create: `src/echo_personal_tool/application/workers/onnx_worker.py`
- Test: `tests/unit/test_onnx_worker.py`

**Behavior:**
- `QRunnable` or wrapper around `ProcessPoolExecutor(max_workers=1)` for `segment(frame)`
- Signals: `finished(mask_or_contour_points)`, `failed(message)`, `timed_out`
- Timeout 2.0 s (from manifest `inference.timeout_sec`)
- Cancel if playback active (controller checks before dispatch)

**Note:** Process pool function must be picklable — top-level function in onnx_engine or worker module.

---

### Task 4: AppController auto-segment orchestration ✅

**Files:**
- Modify: `src/echo_personal_tool/application/app_controller.py`
- Test: `tests/unit/test_auto_segment_controller.py`

**`request_auto_segment()`:**
- Require: 2D mode, not playing, current frame is ED or ES (or warn)
- Get current frame from state / last loaded pixels
- Dispatch OnnxWorker
- On success: build `Contour(phase=..., points=smooth_contour(mask_to_contour(...)), source="ai")`, replace existing contour for same phase+view, `on_contours_changed`
- On failure: `status_message` with Russian message per Этап2 §8

**Inject** `IOnnxSegmenter` (default `OnnxInferenceEngine`) for testing.

---

### Task 5: ViewerWidget spline editor ✅

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`
- Test: `tests/unit/test_spline_editor.py`

**Add:**
- `set_contour_from_domain(contour: Contour)` — replace/add contour with PlotDataItem + ScatterPlotItem nodes
- Draggable nodes: `sigPointsChanged` or custom mouse drag on ScatterPlotItem
- On node drag end: update `Contour.points`, emit `contours_changed`
- `enable_spline_edit(contour_index)` or auto-enable for AI/manual completed contours
- Pen color distinct for AI (`source=="ai"`) vs manual

**Keep** existing manual polygon flow (`C` key) unchanged.

---

### Task 6: MainWindow hotkey `I` + status UX ✅

**Files:**
- Modify: `src/echo_personal_tool/presentation/main_window.py`
- Modify: `tests/unit/test_phase_hotkeys.py` (extend)

- Hotkey `I` in 2D mode → `controller.request_auto_segment()`
- Block `I` during playback
- Status bar hints on segment start/complete/fail

---

### Task 7: Integration smoke + docs ✅

**Files:**
- Modify: `README.md` — ONNX usage section (install phase2 extra, export script)
- Test: extend `tests/test_smoke.py` if needed (import onnx_engine optional)

**Acceptance:**
- All unit tests pass with `uv run pytest`
- ruff clean
- Manual: `I` on ED frame with local `.onnx` produces visible contour

---

## 4. Критерии приёмки

1. `I` на кадре ED/ES запускает сегментацию (если модель есть)
2. AI-контур отображается, `source="ai"` в domain model
3. Узлы сплайна перетаскиваются, LVEF пересчитывается
4. Timeout / отсутствие модели → сообщение, ручной контур работает
5. Presentation не импортирует onnxruntime
6. Все тесты проходят

### Этап E — Верификация

- [x] `uv run pytest` (156 tests)
- [x] `uv run ruff check .`
- [ ] Ручная проверка с `models/echonet_seg_resnet50.onnx` (локально)

---

## 5. Out of scope (S5b+)

- MasterClock / side-by-side
- MobileNetV3-Lite export (manifest stub only)
- ECG-based ED/ES
- AI validation ±3% vs EchoPAC
