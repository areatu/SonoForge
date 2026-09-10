# ПЛАН УЛУЧШЕНИЯ МОДУЛЯ SPECKLE TRACKING ECHOCARDIOGRAPHY

> Дата: 2026-09-10
> Статус: Утверждён, ожидает реализации
> Тестовый файл: `/home/areatu/ECHO2026_src/Test_vendors/Philips/IM_0059` (46 frames, 600x800, ~46.5 fps, pixel spacing 0.449mm)

---

## СОДЕРЖАНИЕ

1. [Корневые причины некорректного GLS](#1-корневые-причины-некорректного-gls)
2. [Фаза 1: Исправление расчёта GLS (алгоритм)](#2-фаза-1-исправление-расчёта-gls-алгоритм)
3. [Фаза 2: UI — Samsung-style layout + animated strain](#3-фаза-2-ui--samsung-style-layout--animated-strain)
4. [Фаза 3: Интеграция 3-view GLS](#4-фаза-3-интеграция-3-view-gls)
5. [Фаза 4: Тестирование и валидация](#5-фаза-4-тестирование-и-валидация)
6. [Приоритеты и порядок реализации](#6-приоритеты-и-порядок-реализации)
7. [Оценка объёма работ](#7-оценка-объёма-работ)
8. [Ключевые риски](#8-ключевые-риски)
9. [Референсы](#9-референсы)

---

## 1. КОРНЕВЫЕ ПРИЧИНЫ НЕКОРРЕКТНОГО GLS

После анализа ~4000 строк кода, 10 научных статей и вендорных референсов выявлено **5 корневых причин**, по которым GLS определяется неправильно.

### Причина 1: Сегментная модель работает только на A4C (6/16 сегментов)

**Файл:** `src/echo_personal_tool/domain/services/aha_segments.py:49`

```python
if view != "A4C": return list(kernels)
```

A2C и A3C **полностью игнорируются**. GLS по стандарту EACVI/ASE = среднее по 16 сегментам из 3 апикальных видов. Сейчас считается только по 6 сегментам одного вида → результат неполный и зависит от того, какой вид был использован.

### Причина 2: Per-kernel strain считается некорректно

**Файл:** `src/echo_personal_tool/application/workers/speckle_worker.py:525-532`

```python
for j in range(len(endo_sorted) - 1):
    d_init = np.linalg.norm(ed_pos[j + 1] - ed_pos[j]) * avg_spacing
    d_es = np.linalg.norm(es_pos[j + 1] - es_pos[j]) * avg_spacing
    ratio = d_es / d_init
    seg_gl = 0.5 * (ratio**2 - 1.0) * 100.0
    per_kernel[endo_sorted[j]] = seg_gl      # ядро j получает strain пары (j, j+1)
    per_kernel[endo_sorted[j + 1]] = seg_gl  # ядро j+1 получает strain пары (j, j+1)
```

Каждое ядро получает strain **соседней пары**, а не собственный. Два соседних ядра получают одинаковое значение. Это даёт артефакты при расчёте per-segment strain.

### Причина 3: GLS на кривой vs на сегментах — путаница в формуле

**Файл:** `src/echo_personal_tool/domain/services/strain_computation.py:78-99`

`compute_gls` ищет `min()` по кривой ED→ES. Но `per_kernel` strain (вычисленный в speckle_worker) уже является **скалярным** значением ED→ES для каждого ядра. `compute_aha_segment_strain` берёт среднее по ядрам сегмента. Затем `choose_clinical_gls` сравнивает curve-based (min кривой) и segment-based (mean сегментов). Проблема: **обе формулы используют разные определения strain**, и они не согласованы.

### Причина 4: Нет rigid body motion compensation (только трансляция)

**Файл:** `src/echo_personal_tool/domain/services/speckle_tracking.py` — `estimate_global_translations` + `remove_global_translations`

Компенсируется **только трансляция** (phase correlation). Коммерческие вендоры (GE, Philips, Samsung) также компенсируют **вращение** сердца. Без этого вращательное движение интерпретируется как strain, апикальные сегменты могут показывать ложные пики.

### Причина 5: Quality-weighted smoothing искажает кривую strain

**Файл:** `src/echo_personal_tool/domain/services/tracking_smoothing.py:155-162`

```python
if config.quality_weighted_smoothing:
    weights = np.clip(ncc_scores[:, i], 0.0, 1.0)
    strong = weights >= 0.5
    if strong.sum() >= 2:
        xs = np.interp(times, times[strong], xs[strong])
        ys = np.interp(times, times[strong], ys[strong])
```

Низкокачественные кадры **замещаются интерполяцией** по высококачественным перед сглаживанием. Если много кадров с низким NCC, кривая может быть сильно искажена.

---

## 2. ФАЗА 1: ИСПРАВЛЕНИЕ РАСЧЁТА GLS (АЛГОРИТМ)

**Цель:** GLS считается корректно по стандарту EACVI/ASE на одном виде (A4C).
**Оценка:** ~5-7 файлов, ~500-800 строк изменений.

### 1.1 Расширить AHA сегментацию на 3 апикальных вида

**Файл:** `src/echo_personal_tool/domain/services/aha_segments.py`

**Изменения:**
- Добавить `assign_aha_segments_a2c()` и `assign_aha_segments_a3c()` (по аналогии с A4C)
- Каждый вид видит 6 сегментов: 3 basal + 3 mid + 3 apical
- Apical сегменты совпадают между видами → при объединении дедуплицируются
- Для GLS: исключить apical cap (сегмент 17) → **16 уникальных сегментов**

**A4C (6 сегментов):**
| ID | Название | Угол от центра LV |
|----|----------|-------------------|
| 1 | Basal septal | 300°–60° |
| 2 | Basal lateral | 60°–120° |
| 3 | Mid septal | 120°–180° |
| 4 | Mid lateral | 180°–240° |
| 5 | Apical septal | 240°–270° |
| 6 | Apical lateral | 270°–300° |

**A2C (6 сегментов):**
| ID | Название | Угол от центра LV |
|----|----------|-------------------|
| 7 | Basal anterior | 300°–60° |
| 8 | Basal inferior | 60°–120° |
| 9 | Mid anterior | 120°–180° |
| 10 | Mid inferior | 180°–240° |
| 11 | Apical anterior | 240°–270° |
| 12 | Apical inferior | 270°–300° |

**A3C (6 сегментов):**
| ID | Название | Угол от центра LV |
|----|----------|-------------------|
| 13 | Basal anteroseptal | 300°–60° |
| 14 | Basal inferolateral | 60°–120° |
| 15 | Mid anteroseptal | 120°–180° |
| 16 | Mid inferolateral | 180°–240° |
| 17 | Apical anteroseptal | 240°–270° |
| 18 | Apical inferolateral | 270°–300° |

### 1.2 Исправить per-kernel strain

**Файл:** `src/echo_personal_tool/application/workers/speckle_worker.py:518-532`

**Проблема:** strain считается попарно (междуждерный), а не по движению каждого ядра.

**Новое решение:** Для каждого эндокардиального ядра считать strain по **дуге между соседними ядрами**:

```python
# Для каждого ядра i:
# L0 = расстояние от ядра i-1 до ядра i+1 в ED (дуга через ядро i)
# L(t) = то же расстояние в кадре t
# strain_kernel(t) = 0.5 * ((L(t)/L0)^2 - 1) * 100
```

Или альтернативно: **не считать per-kernel strain отдельно**, а использовать кривую longitudinal strain и находить пик для каждого сегмента по кривым ядер.

### 1.3 Исправить GLS: segment-based GLS = среднее по пиковым значениям сегментов

**Файл:** `src/echo_personal_tool/domain/services/aha_segments.py`

**Новое решение:**
1. Для каждого сегмента: найти **пик strain** (min значение) между ED→ES по кривой strain этого сегмента
2. GLS = среднее по пиковым значениям всех сегментов с quality ≥ порога
3. Исключить сегменты с quality < 0.4

**Новая функция в `strain_computation.py`:**

```python
def compute_segment_peak_strains(
    per_segment_curves: dict[int, np.ndarray],  # segment_id -> strain_curve
    ed_index: int,
    es_index: int,
) -> dict[int, float]:
    """Find peak systolic strain for each segment."""
    peaks = {}
    for seg_id, curve in per_segment_curves.items():
        window = curve[ed_index:es_index+1]
        peaks[seg_id] = float(np.min(window)) if len(window) > 0 else 0.0
    return peaks
```

### 1.4 Исправить choose_clinical_gls

**Файл:** `src/echo_personal_tool/domain/services/aha_segments.py:121-149`

**Новое решение:**
- GLS = среднее по пиковым значениям сегментов (не среднее по кривым)
- Исключить сегменты с quality < min_segment_quality
- Если < 3 сегментов прошли — использовать curve-based GLS как fallback
- Добавить **quality-weighted average**: вес сегмента = NCC качество

```python
def choose_clinical_gls(
    curve_gls: float,
    segment_peak_strains: dict[int, float],
    segment_quality: dict[int, float],
    min_segment_quality: float = 0.4,
    min_segments: int = 3,
) -> tuple[float, str]:
    passing = [
        (seg, peak) for seg, peak in segment_peak_strains.items()
        if segment_quality.get(seg, 0.0) >= min_segment_quality
    ]
    if len(passing) < min_segments:
        return curve_gls, "curve"
    # Quality-weighted average
    weights = np.array([segment_quality[seg] for seg, _ in passing])
    values = np.array([peak for _, peak in passing])
    weighted_gls = float(np.average(values, weights=weights))
    return weighted_gls, "segments"
```

### 1.5 Добавить rigid body motion compensation (трансляция + вращение)

**Файл:** `src/echo_personal_tool/domain/services/speckle_tracking.py`

**Реализация:**
1. **Landmark tracking:** Отслеживать 3 анатомических ориентира через block matching:
   - Верхушка LV (apex)
   - Септальный mitral annulus
   - Латеральный mitral annulus
2. **Вычислить rigid transform** между каждым кадром и референсным (ED):
   - Трансляция: центроид 3 ориентиров
   - Вращение: угол линии "annulus center → apex"
3. **Применить transform** ко всем позициям ядер перед расчётом strain

**Новые функции:**
- `estimate_global_rigid_transform(frames, landmarks, ed_index)` → `(translations, rotations)`
- `apply_rigid_transform(positions, translations, rotations)` → `positions`

### 1.6 Убрать quality_weighted_smoothing re-interpolation

**Файл:** `src/echo_personal_tool/domain/services/tracking_smoothing.py:155-162`

**Проблема:** Интерполяция низкокачественных кадров перед сглаживанием искажает кривую.

**Решение:** Убрать блок re-interpolation. Savitzky-Golay и так устойчив к выбросам. Если кадр с низким NCC — он должен оставаться как есть, а не замещаться интерполяцией.

---

## 3. ФАЗА 2: UI — SAMSUNG-STYLE LAYOUT + ANIMATED STRAIN

**Цель:** Интерфейс приближён к Samsung/Philips, добавлена обратная связь по tracking quality.
**Оценка:** ~6-8 файлов, ~800-1200 строк изменений.

### 2.1 Новая структура окна StrainWindow

**Файл:** `src/echo_personal_tool/ui/strain_window.py`

**Текущий layout:**
```
[Meta Bar]
[Control Panel | QStackedWidget: 2x2 CineGrid | Summary Table]
```

**Новый layout (Samsung-style):**
```
[GLS prominent banner: "GLS: -19.5%" large font, center]
+------------------+------------------+
| CinePanel A4C    | CinePanel A2C    |  ← верхний ряд
+------------------+------------------+
| CinePanel A3C    | Bull's Eye       |  ← нижний ряд
| (или summary)    | + Metrics Panel  |
+------------------+------------------+
[ECG strip — общий на всё окно]
```

**Вкладка "Curves":**
- Отдельная вкладка (как в Samsung) с strain curves
- 6 кривых/вид + глобальная средняя
- Вертикальный time cursor при playback

**Ключевые изменения:**
- Заменить `QStackedWidget` с 2x2 grid на Samsung-style layout
- Добавить `QTabWidget` с вкладками "Cine" и "Curves"
- Убрать Summary Table в отдельную панель справа от Bull's Eye

### 2.2 Инвертировать цветовую шкалу strain

**Файл:** `src/echo_personal_tool/ui/strain_window.py` — `BullseyeWidget._strain_to_color`

**Текущая шкала (НЕПРАВИЛЬНАЯ):**
- Красный = отрицательный strain (сжатие)
- Синий = положительный strain

**Правильная шкала (как у Samsung/Philips):**

| Strain (%) | Цвет | Описание |
|------------|------|----------|
| < -22% | Зелёный/Голубой | Гиперкинетический |
| -22% .. -18% | Красный/Тёмно-красный | Нормальное сокращение |
| -18% .. -16% | Оранжевый | Пограничный |
| -16% .. -12% | Жёлтый | Сниженное сокращение |
| > -12% | Синий/Голубой | Нарушенное сокращение |
| Нет данных | Тёмно-серый `#282828` | — |
| QC rejected | Серый `#3c3c3c` | — |

### 2.3 Animated strain contour (Philips-style)

**Файл:** `src/echo_personal_tool/presentation/speckle_overlay.py` — новая функция `show_strain_contour_overlay`

**Реализация:**
- На каждом кадре при playback рисовать **тонкую полосу** на эндокарде
- Цвет полосы = цвет strain в этой точке (по той же color map что bull's eye)
- Толщина полосы ≈ 3-4 px (как у Philips в IM_0059)
- Обновлять при каждом кадре playback

**Это критично для обратной связи** — позволяет визуально оценить, правильно ли модуль отслеживает деформацию.

**Алгоритм:**
```python
def show_strain_contour_overlay(self, frame_index, positions, kernels, strain_per_kernel):
    """Draw colored strain band on endocardium for current frame."""
    endo_indices = [i for i, k in enumerate(kernels) if k.layer == "endo"]
    endo_sorted = sorted(endo_indices, key=lambda i: kernels[i].node_index)
    points = positions[frame_index, endo_sorted, :]
    strains = strain_per_kernel[endo_sorted]
    
    for i in range(len(points) - 1):
        color = strain_to_color(strains[i])  # та же map что bull's eye
        pen = pg.mkPen(color, width=4)
        self._strain_band_item.setData([points[i][0], points[i+1][0]],
                                       [points[i][1], points[i+1][1]], pen=pen)
```

### 2.4 GLS prominent display

**Файл:** `src/echo_personal_tool/ui/strain_window.py`

**Изменения:**
- GLS отображается **крупным шрифтом** (24-28px, жирный) в верхней части окна
- Цвет: белый на тёмном фоне
- Формат: `"GLS: -19.5%"` (с знаком процента)
- Рядом: QC score, HR, ED/ES frame numbers

**Пример:**
```
┌─────────────────────────────────────────────────────────┐
│  GLS: -19.5%   QC: 87%   HR: 72 bpm   ED: 0  ES: 18  │
├─────────────────────────────────────────────────────────┤
```

### 2.5 Quality indicators на bull's eye

**Файл:** `src/echo_personal_tool/ui/strain_window.py` — `BullseyeWidget`

**Добавить:**
- Цветные точки рядом с каждым сегментом:
  - Зелёный = quality ≥ 0.7
  - Жёлтый = quality 0.4-0.7
  - Красный = quality < 0.4
- Tooltip при наведении: "Segment: Basal septal, Strain: -21.2%, Quality: 0.85"

### 2.6 Time cursor на strain curves

**Файл:** `src/echo_personal_tool/ui/strain_curves_view.py`

**Добавить:**
- Вертикальную линию-курсор, двигающуюся при playback
- Курсор = жёлтая пунктирная линия (как ES marker, но движущаяся)
- Обновлять позицию курсора при каждом кадре playback

### 2.7 ECG strip — общий для всех CinePanel

**Файл:** `src/echo_personal_tool/ui/strain_window.py`

**Изменения:**
- ECG strip переместить **под основной grid** (общий на все 3 вида)
- R-peak markers: оранжевые вертикальные линии
- ED marker: зелёная пунктирная
- ES marker: жёлтая пунктирная
- Moving frame marker: красная пунктирная

### 2.8 Сохранить поддержку kernel editing

**Файл:** `src/echo_personal_tool/ui/strain_window.py`

**Существующие функции (СОХРАНИТЬ):**
- Клик по ядру → выделение жёлтым кругом
- Drag ядра → изменение позиции
- Undo/Redo стек
- Accept/reject сегментов через QC checkboxes

---

## 4. ФАЗА 3: ИНТЕГРАЦИЯ 3-VIEW GLS

**Цель:** GLS считается по 16 сегментам из 3 апикальных видов.
**Оценка:** ~3-4 файла, ~300-500 строк изменений.

### 3.1 Multi-view tracking

**Файл:** `src/echo_personal_tool/application/workers/speckle_worker.py`

**Изменения:**
- Принимать **3 контура** (A4C, A2C, A3C) вместо одного
- Для каждого контура: создать `MyocardialZone`, запустить tracking
- Объединить результаты: 16 сегментов из 3 видов

### 3.2 Aggregated GLS

**Файл:** `src/echo_personal_tool/domain/services/aha_segments.py` — новая функция `compute_3view_gls`

```python
def compute_3view_gls(
    view_results: dict[str, dict[int, float]],  # view -> {segment_id: peak_strain}
    view_qualities: dict[str, dict[int, float]],  # view -> {segment_id: quality}
    min_quality: float = 0.4,
) -> tuple[float, dict[str, float]]:
    """GLS from 3 apical views."""
    all_peaks = {}
    all_qualities = {}
    for view, peaks in view_results.items():
        for seg_id, peak in peaks.items():
            global_seg = _map_view_seg_to_aha(view, seg_id)
            if global_seg not in all_peaks or view_qualities[view].get(seg_id, 0) > all_qualities.get(global_seg, 0):
                all_peaks[global_seg] = peak
                all_qualities[global_seg] = view_qualities[view].get(seg_id, 0)
    
    passing = [(seg, peak) for seg, peak in all_peaks.items() if all_qualities.get(seg, 0) >= min_quality]
    if len(passing) < 3:
        return 0.0, {}
    gls = float(np.mean([p for _, p in passing]))
    return gls, all_peaks
```

### 3.3 UI для multi-view

**Файл:** `src/echo_personal_tool/ui/strain_window.py`

**Изменения:**
- StrainWindow принимает **3 StrainResult** (по одному на вид)
- Bull's eye показывает **все 16 сегментов** из 3 видов
- Summary table показывает GLS_A4C, GLS_A2C, GLS_A3C, GLS_global

---

## 5. ФАЗА 4: ТЕСТИРОВАНИЕ И ВАЛИДАЦИЯ

**Цель:** Убедиться, что GLS корректен и UI работает правильно.
**Оценка:** ~2-3 файла, ~200-400 строк.

### 4.1 Unit тесты

**Файл:** `tests/test_speckle_tracking.py` (создать/расширить)

**Тесты:**
1. **GLS formula:** Контрольные данные с известным strain → проверка `compute_gls`
2. **AHA segmentation:** Проверить что сегменты правильно назначаются для A4C/A2C/A3C
3. **Per-kernel strain:** Проверить что strain корректно считается для каждого ядра
4. **Quality-weighted GLS:** Проверить что weighted average корректен
5. **Rigid body compensation:** Проверить что трансляция+вращение компенсируются

### 4.2 Integration тест

**Файл:** `tests/test_ste_integration.py`

**Тесты:**
1. **IM_0059:** Запустить tracking → проверить что GLS в диапазоне -15%..-25%
2. **Multi-view:** Запустить tracking на 3 видах → проверить что GLS aggregated корректен
3. **Regression:** Сравнить с предыдущими результатами (если есть)

### 4.3 Visual validation

**Файл:** `tests/test_strain_visual.py`

**Проверки:**
- Animated strain contour отображается корректно
- Bull's eye colors соответствуют шкале
- Time cursor движется синхронно с playback
- ECG markers совпадают с R-peaks
- Export PNG/JSON/CSV работает

---

## 6. ПРИОРИТЕТЫ И ПОРЯДОК РЕАЛИЗАЦИИ

| Приоритет | Фаза | Описание | Сложность | Файлы |
|-----------|------|----------|-----------|-------|
| **P0** | 1.2-1.4 | Исправить per-kernel strain + GLS formula | Средняя | `speckle_worker.py`, `aha_segments.py`, `strain_computation.py` |
| **P0** | 1.1 | Расширить AHA на 3 вида | Средняя | `aha_segments.py` |
| **P1** | 2.1-2.4 | Samsung-style layout + GLS prominent + color scale | Высокая | `strain_window.py`, `strain_curves_view.py` |
| **P1** | 2.3 | Animated strain contour | Средняя | `speckle_overlay.py` |
| **P2** | 1.5 | Rigid body motion compensation | Средняя | `speckle_tracking.py` |
| **P2** | 2.5-2.7 | Quality indicators + time cursor + ECG | Низкая | `strain_window.py`, `strain_curves_view.py` |
| **P3** | 3.1-3.3 | Multi-view integration | Высокая | `speckle_worker.py`, `aha_segments.py`, `strain_window.py` |
| **P3** | 4.1-4.3 | Тестирование | Средняя | `tests/` |

**Рекомендуемый порядок:**
1. Начать с **P0** (алгоритм) — без корректного GLS всё остальное бессмысленно
2. Затем **P1** (UI) — визуальная обратная связь критична для debug
3. Затем **P2** (motion compensation +细节 UI)
4. Последним **P3** (multi-view + тесты)

---

## 7. ОЦЕНКА ОБЪЁМА РАБОТ

| Фаза | Файлы | Строки изменений | Время (оценка) |
|------|-------|-------------------|----------------|
| Фаза 1 (алгоритм) | 5-7 | 500-800 | 2-3 дня |
| Фаза 2 (UI) | 6-8 | 800-1200 | 3-4 дня |
| Фаза 3 (multi-view) | 3-4 | 300-500 | 1-2 дня |
| Фаза 4 (тесты) | 2-3 | 200-400 | 1 день |
| **Итого** | **16-22** | **1800-2900** | **7-10 дней** |

---

## 8. КЛЮЧЕВЫЕ РИСКИ

1. **Per-kernel strain formula** — нужно строго проверять на контрольных данных, иначе GLS будет ещё хуже
2. **AHA segment mapping** — при неправильном маппинге сегментов GLS будет невалидным
3. **Rigid body compensation** — если landmarks отслеживаются неправильно, компенсация ухудшит результат
4. **UI regression** — при перестройке layout можно сломать существующие функции (export, kernel editing)
5. **Temporal smoothing** — изменение параметров сглаживания может повлиять на существующие результаты

---

## 9. РЕФЕРЕНСЫ

1. Voigt J-M et al. (2022). "Definitions for a common standard for 2D speckle-tracking echocardiography." *Eur Heart J Cardiovasc Imaging*. 23(1):e1-e18.
2. Smiseth OA et al. (2025). "Myocardial Strain Imaging." *JACC: Cardiovascular Imaging*. 18(3):340-381.
3. Plana JC et al. (2008). "Expert consensus document: Echocardiographic strain imaging." *JASE*. 21(1):1-23.
4. Lang RM et al. (2015). "Recommendations for cardiac chamber quantification by echocardiography in adults." *Eur Heart J Cardiovasc Imaging*. 16(3):233-270.
5. Amundsen BH et al. (2006). "Noninvasive myocardial strain measurement by speckle tracking echocardiography." *J Am Coll Cardiol*. 47:789-793.
6. Geyer H et al. (2010). "Assessment of Myocardial Mechanics Using Speckle Tracking Echocardiography." *JASE*. 23(4):351-369.
7. Costa SP et al. (2014). "Quantification of the variability associated with repeat measurements of LV 2D GLS." *JASE*. 27(1):50-54.

---

## ТЕСТОВЫЕ ФАЙЛЫ

| Файл | Описание | Использование |
|------|----------|---------------|
| `/home/areatu/ECHO2026_src/Test_vendors/Philips/IM_0059` | Philips US, 46 frames, 600x800, ECG | Основной тестовый файл |
| `/home/areatu/ECHO2026_src/Test_vendors/Philips/IM_0051` | Philips US, 104 MB | Дополнительный (проверка ECG) |
| `/home/areatu/ECHO2026_src/strain_example/US003900.dcm` | Samsung strain overlay | Визуальное сравнение UI |
| `/home/areatu/ECHO2026_src/strain_example/US006700.dcm` | Samsung strain curves | Визуальное сравнение curves |
