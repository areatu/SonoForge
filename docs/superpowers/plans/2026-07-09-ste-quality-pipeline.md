# STE Quality Pipeline + Strain Window

**Дата:** 2026-07-09
**Статус:** Partially Complete (9/11 phases done, pending issues documented)
**Ветка:** `feature/ste-clinical-parity` (paused)
**Референс:** Samsung RS85 «Деформация+» (`/home/areatu/ECHO2026-other/strain_example/`)

---

## Цель

Довести STE с текущих ~62% quality до ~75-80% клинической полезности **без ML-допобучения** + создать отдельное окно **Strain Window** с Quad-view компоновкой по образцу Samsung RS85.

## Ключевое архитектурное решение

**Все визуальные надстройки STE компонуются в отдельном окне `StrainWindow`**, а не в основном окне просмотра. Основное окно — только cine + контур. Strain Window открывается по кнопке «Speckle Tracking» из меню измерений.

---

## Samsung RS85 — детальный анализ (референс)

### Компоновка окон (Quad View)

```
┌─────────────────────┬─────────────────────┐
│       A4C           │       A2C           │
│  cine + контур      │  cine + контур      │
│  + подписи сегментов│  + подписи сегментов│
│  + HR + ECG         │  + HR + ECG         │
├─────────────────────┼─────────────────────┤
│       ДАО (A3C)     │   Bull's Eye Plot   │
│  cine + контур      │   17-сегментный     │
│  + подписи сегментов│   polar map         │
│  + HR + ECG         │   + таблица метрик  │
└─────────────────────┴─────────────────────┘
```

### Режим A: Cine + Contour (наложение на cine-loop)

На каждом из 3 апикальных видов отображается:
- **Красный контур миокарда** — толстая линия вдоль эндокарда
- **Белые квадраты** — tracking kernels (6-8 на сегмент), распределённые вдоль миокарда
- **Подписи сегментов** (рус.): АпПер (Apical Septal), АпЛат (Apical Lateral), СрПерг (Mid Septal), Србок (Mid Lateral), БазПерг (Basal Septal), Базбок (Basal Lateral)
- **Заголовок вида**: «A4K Сред.ГлобПродДеф -19.0%, ФВ 42.1%»
- **Счётчик кадров**: 21/53 (текущий/всего)
- **ЧСС**: HR: 67
- **ECG trace**: зелёная линия внизу панели
- **Жёлтая вертикальная линия** на ECG — маркер текущего кадра

### Режим B: Strain Curves (кривые деформации)

На каждом из 3 апикальных видов:
- **6 цветных кривых** — по одной на каждый сегмент (БазПерг, СрПерг, АпПерг, АпЛат, Србок, Базбок)
- **Белая пунктирная кривая** = средняя деформация (GLS curve)
- **Жёлтые точки** на кривых — пики деформации (peak strain markers)
- **Жёлтая вертикальная линия** — маркер ES или текущего времени
- **X-ось**: Время(ms), **Y-ось**: (%) деформация
- **Подписи сегментов** вверху графика (цветные, соответствуют кривым)
- **Эталонные линии**: «Атриовентр. отверстие» и «Атриовентр. канал» (жёлтые вертикальные)
- **ECG trace**: зелёная линия внизу

### Bull's Eye Plot (17-сегментная полярная карта)

- **17-сегментная модель** (стандарт AHA)
- **Цветовое кодирование**: красный = патология (сниженная деформация), белый/серый = норма
- **Значения** в каждом сегменте (например, -21.2, -22.7 — % деформации)
- **Подписи сегментов** по периметру: Пер, Лат, Нижн, Задн, ПерПерг, ПерНижн, и т.д.
- **Заголовок**: «Продольн. деформ. систол. пика»
- **Color bar** справа: шкала от -20.0% до +20.0%

### Сводная таблица (справа от Bull's Eye)

| Параметр | Формат | Пример |
|----------|--------|--------|
| Сред.ГлобПродДеф | % | -17.3% |
| A4C ГлобПродДеф | % | -19.0% |
| A2C ГлобПродДеф | % | -19.4% |
| ДАО ГлобПродДеф | % | -13.7% |
| ФВ [дв-плоск] | % | 43.8% |
| КДО [дв-плоск] | мл | 151.9 мл |
| КСО [дв-плоск] | мл | 85.3 мл |
| АвтоЗАК | мс | 298 мс |
| ЧСС | bpm | 66 bpm |

### Панель управления (слева)

- **3 Point Contour** — режим разметки 3 базовых точек (septal/lateral mitral annulus + apex)
- **Чекбоксы видов**: A4K ✓, A2K ✓, ДАО ✓ (вкл/выкл отображение)
- **Радио-кнопки режимов**:
  - Деформация (Strain) — показывает контур + kernels
  - Скорость деформ. (Strain Rate) — показывает SR values
  - Пик.изм.деформации (Peak Strain) — показывает peak values
- **Инструкция по quality control**: «Установите/снимите фажок напротив области сегмента, чтобы отметить их как приемлемые/неприемлемые в диаграмме»
- **Кнопки**: «Сохр.дан.деформ.», «Выход»

---

## Архитектура Strain Window

```
StrainWindow (QMainWindow)
├── MenuBar
│   ├── File: Save deformation data, Export PNG/SVG, Close
│   ├── View: Toggle A4C/A2C/DAO panels, Toggle curves/contour mode
│   └── Help: ASE guidelines
├── CentralWidget (QSplitter)
│   ├── LeftPanel (ControlPanel)
│   │   ├── ModeSelector (3 Point Contour / Review)
│   │   ├── ViewToggles (A4C ✓, A2C ✓, DAO ✓)
│   │   ├── DisplayMode (Deformation / StrainRate / PeakStrain)
│   │   ├── QualityCheckboxes (per-segment accept/reject)
│   │   └── ActionButtons (Save, Export, Close)
│   ├── QuadView (QGridLayout)
│   │   ├── PanelA4C (CinePanel)
│   │   │   ├── ImageViewer (cine + contour overlay)
│   │   │   ├── SegmentLabels (АпПер, АпЛат, СрПерг, Србок, БазПерг, Базбок)
│   │   │   ├── HRLabel (HR: 67)
│   │   │   ├── FrameCounter (21/53)
│   │   │   └── ECGTrace (green line)
│   │   ├── PanelA2C (CinePanel)
│   │   │   └── ... (same as A4C)
│   │   ├── PanelDAO (CinePanel)
│   │   │   └── ... (same as A4C)
│   │   └── PanelBullseye (BullseyePanel)
│   │       ├── BullseyePlot (17-segment polar map)
│   │       ├── ColorBar (-20% to +20%)
│   │       └── SummaryTable (GLS, EF, volumes, HR)
│   └── RightPanel (optional: StrainCurves)
│       └── StrainCurvesWidget (when in curves mode)
│           ├── CurveA4C (6 colored curves + mean)
│           ├── CurveA2C (6 colored curves + mean)
│           └── CurveDAO (6 colored curves + mean)
└── StatusBar
    ├── TrackingQuality (kernels accepted: 85%)
    └── ProcessingStatus (Ready / Computing...)
```

---

## Фазы

### Phase 1: Quality Threshold Gate

**Effort:** 1 день
**Цель:** Отбраковка kernels с низким NCC confidence перед расчётом strain.

**Задачи:**
- [ ] Добавить параметр `min_quality` (default 0.3) в `SpeckleTrackingWorker`
- [ ] При расчёте strain: исключить kernels с quality < `min_quality`
- [ ] Добавить предупреждение в UI: «X из Y kernels отброшены (low quality)»
- [ ] Логировать отброшенные kernels для анализа

**Файлы:**
- `src/echo_personal_tool/domain/services/speckle_tracking.py`
- `src/echo_personal_tool/ui/speckle_overlay.py`

**Критерии приёмки:**
- Kernels с quality < 0.3 не влияют на GLS/Radial strain
- Пользователь видит, сколько kernels отброшено
- При < 50% kernels — показать предупреждение «Insufficient tracking quality»

---

### Phase 2: Weighted GLS Computation

**Effort:** 1 день
**Цель:** Использовать quality weights при расчёте финального strain.

**Задачи:**
- [ ] Изменить `compute_strain()`: вместо simple average → weighted average по quality
- [ ] Добавить `compute_weighted_strain(kernels, weights)` в `speckle_metrics.py`
- [ ] Обновить overlay: показывать quality-weighted GLS/Radial
- [ ] Добавить fallback: если quality weights не доступны → simple average

**Файлы:**
- `src/echo_personal_tool/domain/services/speckle_metrics.py`
- `src/echo_personal_tool/ui/speckle_overlay.py`

**Критерии приёмки:**
- Weighted GLS ближе к клиническому эталону (если есть reference)
- При низком quality kernels — strain более устойчив
- Fallback работает корректно

---

### Phase 3: Strain Window Shell + Quad-View Layout

**Effort:** 3-4 дня
**Цель:** Создать отдельное окно StrainWindow с 4-панельной компоновкой (A4C + A2C + DAO + Bull's Eye).

**Задачи:**

#### 3.1 StrainWindow основа
- [ ] Создать `src/echo_personal_tool/ui/strain_window.py` (new)
- [ ] `StrainWindow(QMainWindow)` — отдельное окно, не встроено в main
- [ ] `QSplitter` с LeftPanel (управление) + QuadView (контент)
- [ ] Открытие по кнопке «Speckle Tracking» из measures_menu
- [ ] Закрытие: освобождает ресурсы (worker threads, memory)

#### 3.2 QuadView компоновка
- [ ] `QGridLayout` 2×2: PanelA4C, PanelA2C, PanelDAO, PanelBullseye
- [ ] Каждый cine-panel: `ImageViewerWidget` (cine loop) + overlay контура
- [ ] Ресайз: пропорциональное изменение при resize окна
- [ ] Синхронизация playback: play/pause/seek по всем 3 панелям одновременно

#### 3.3 ControlPanel
- [ ] `ModeSelector`: 3 Point Contour / Review (radio buttons)
- [ ] `ViewToggles`: чекбоксы A4C ✓, A2C ✓, DAO ✓
- [ ] `DisplayMode`: Деформация / Скорость деформ. / Пик.изм.деформации (radio buttons)
- [ ] `ActionButtons`: Сохранить, Экспорт PNG, Закрыть

**Файлы:**
- `src/echo_personal_tool/ui/strain_window.py` (new)
- `src/echo_personal_tool/ui/strain_panel.py` (new)
- `src/echo_personal_tool/ui/bullseye_widget.py` (new)
- `src/echo_personal_tool/ui/measures_menu.py` (modify — add button)

**Критерии приёмки:**
- Окно открывается отдельно от main window
- 4 панели отображаются в 2×2 сетке
- Play/pause синхронизирован по всем панелям
- Resize работает корректно
- Закрытие освобождает ресурсы

---

### Phase 4: Myocardial Contour + Tracking Kernels Visualization

**Effort:** 2-3 дня
**Цель:** Визуализация контура миокарда и tracking kernels по образцу Samsung.

**Задачи:**

#### 4.1 Красный контур миокарда
- [ ] `MyocardialContourOverlay` — отрисовка контура эндокарда
- [ ] Стиль: толстая красная линия (3-4px), соединяющая endocardial points
- [ ] Сглаживание: cubic spline между points
- [ ] Обновление при каждом кадре (animation)

#### 4.2 Tracking kernels
- [ ] `TrackingKernelOverlay` — отрисовка kernels как белых квадратов
- [ ] Размер квадрата: 6×6 px
- [ ] Расположение: вдоль контура миокарда (по 6-8 на сегмент)
- [ ] Цвет: белый (нормальный), жёлтый (низкий quality), красный (отброшен)
- [ ] Клик по kernel: показать tooltip с quality value

#### 4.3 Подписи сегментов
- [ ] `SegmentLabelOverlay` — текстовые подписи на контуре
- [ ] Позиция: рядом с каждым сегментом (АпПер, АпЛат, СрПерг, Србок, БазПерг, Базбок)
- [ ] Цвет: соответствует цвету кривой в strain curves mode
- [ ] Шрифт: 10-12px, bold, с тенью для читаемости

#### 4.4 HR + Frame Counter + ECG
- [ ] `HRLabel`: отображение ЧСС (из DICOM или вычисленное)
- [ ] `FrameCounter`: текущий кадр / всего (например, 21/53)
- [ ] `ECGTrace`: зелёная линия внизу панели (если ECG данные доступны)
- [ ] `YellowMarker`: жёлтая вертикальная линия на ECG — текущий кадр

**Файлы:**
- `src/echo_personal_tool/ui/myocardial_contour_overlay.py` (new)
- `src/echo_personal_tool/ui/tracking_kernel_overlay.py` (new)
- `src/echo_personal_tool/ui/segment_label_overlay.py` (new)
- `src/echo_personal_tool/ui/ecg_trace_widget.py` (new)
- `src/echo_personal_tool/ui/cine_panel.py` (new — объединяет всё)

**Критерии приёмки:**
- Красный контур отображается корректно на всех 3 видах
- Kernels видны как белые квадраты вдоль миокарда
- Подписи сегментов читаемы
- HR + Frame Counter отображаются
- ECG trace отображается (если данные есть)

---

### Phase 5: Bull's Eye Plot (17-Segment Polar Map)

**Effort:** 3-4 дня
**Цель:** 17-сегментная полярная карта с цветовым кодированием и значениями strain.

**Задачи:**

#### 5.1 Bull's Eye виджет
- [ ] `BullseyeWidget(QPaintEvent)` — custom QWidget
- [ ] 17-сегментная модель (AHA standard):
  - 6 basal (перегородка, передняя, боковая, задняя, нижняя, medial)
  - 6 mid-ventricular (перегородка, передняя, боковая, задняя, нижняя, medial)
  - 4 apical (перегородка, передняя, боковая, нижняя)
  - 1 apex
- [ ] Отрисовка: concentric circles + radial lines
- [ ] Заполнение сегментов цветом по strain value

#### 5.2 Цветовое кодирование
- [ ] Colormap:jet (red = negative, blue = positive, white = zero)
- [ ] Шкала: от -20.0% до +20.0% (настраиваемая)
- [ ] Color bar справа от polar map
- [ ] Формат значений: «-21.2» (1 десятичная, без % в сегменте)

#### 5.3 Подписи сегментов
- [ ] Внутри каждого сегмента: strain value
- [ ] По периметру: названия сегментов (Пер, Лат, Нижн, Задн, ПерПерг, ПерНижн, и т.д.)
- [ ] Шрифт: 9-11px, bold, контрастный цвет

#### 5.4 Интерактивность
- [ ] Hover по сегменту: tooltip с detailed info (view source, quality, strain value)
- [ ] Клик по сегменту: подсветка corresponding kernels в cine-panel
- [ ] Export: PNG (для отчёта) + SVG (для печати)

**Файлы:**
- `src/echo_personal_tool/ui/bullseye_widget.py` (new)
- `src/echo_personal_tool/domain/services/aha_segment_map.py` (new — модель 17 сегментов)

**Критерии приёмки:**
- 17 сегментов отображаются корректно
- Цвета соответствуют strain values
- Значения читаемы в каждом сегменте
- Hover tooltip работает
- Export PNG/SVG работает

---

### Phase 6: Summary Table

**Effort:** 1-2 дня
**Цель:** Агрегация всех ключевых метрик в одну таблицу (как в Samsung).

**Задачи:**

#### 6.1 Таблица метрик
- [ ] `SummaryTableWidget` — таблица с 9 строками:
  1. Сред.ГлобПродДеф (average GLS)
  2. A4C ГлобПродДеф
  3. A2C ГлобПродДеф
  4. DAO ГлобПродДеф
  5. ФВ [дв-плоск] (biplane EF)
  6. КДО [дв-плоск] (EDV)
  7. КСО [дв-плоск] (ESV)
  8. АвтоЗАК (mitral valve closure)
  9. ЧСС (heart rate)

#### 6.2 Форматирование
- [ ] Значения: bold, yellow (как в Samsung)
- [ ] Параметры: normal weight, white
- [ ] Формат: % для strain/EF, мл для volumes, мс для timing, bpm для HR
- [ ] Auto-update при изменении данных

#### 6.3 Источники данных
- [ ] GLS: из `compute_aha_segment_strain()` (среднее по всем сегментам)
- [ ] Per-view GLS: из A4C/A2C/DAO отдельно
- [ ] EF: из LV Simpson (если есть) или из auto-contour
- [ ] EDV/ESV: из LV Simpson
- [ ] HR: из DICOM или вычисленное из R-R interval
- [ ] АвтоЗАК: из ECG timing (если есть)

**Файлы:**
- `src/echo_personal_tool/ui/strain_summary_table.py` (new)

**Критерии приёмки:**
- Все 9 метрик отображаются
- Значения bold + yellow
- Auto-update работает
- Форматирование корректно

---

### Phase 7: Strain Curves View

**Effort:** 3-4 дня
**Цель:** Кривые деформации по сегментам с ECG sync и color coding.

**Задачи:**

#### 7.1 Curves widget
- [ ] `StrainCurvesWidget(QPaintEvent)` — custom QWidget
- [ ] 3 панели: A4C, A2C, DAO (каждая — отдельный график)
- [ ] X-ось: Время(ms), Y-ось: (%)

#### 7.2 Кривые по сегментам
- [ ] 6 цветных кривых на каждую панель:
  - БазПерг: cyan
  - СрПерг: blue
  - АпПерг: green
  - АпЛат: magenta
  - Србок: yellow
  - Базбок: red
- [ ] Белая пунктирная кривая = средняя деформация (GLS curve)
- [ ] Толщина линий: 2px (segment curves), 3px (mean curve, dashed)

#### 7.3 Маркеры
- [ ] Жёлтые точки на кривых = peak strain markers
- [ ] Жёлтая вертикальная линия = текущий кадр или ES
- [ ] Эталонные линии: «Атриовентр. отверстие» и «Атриовентр. канал» (жёлтые, вертикальные)

#### 7.4 ECG trace
- [ ] Зелёная линия внизу каждой панели
- [ ] Синхронизация с кривыми

#### 7.5 Подписи сегментов
- [ ] Вверху графика: цветные подписи (БазПерг, СрПерг, АпПерг, АпЛат, Србок, Базбок, Сред.)
- [ ] Цвет соответствует цвету кривой

#### 7.6 Интерактивность
- [ ] Hover по кривой: tooltip с segment name + value + time
- [ ] Клик по кривой: подсветка corresponding segment в Bull's Eye
- [ ] Zoom: mouse wheel для zoom по X/Y
- [ ] Pan: drag для pan по X/Y

**Файлы:**
- `src/echo_personal_tool/ui/strain_curves_widget.py` (new)
- `src/echo_personal_tool/ui/strain_curves_panel.py` (new)

**Критерии приёмки:**
- 6 кривых + mean отображаются на каждой панели
- Цвета соответствуют сегментам
- Peak markers видны
- ECG trace синхронизирован
- Hover tooltip работает
- Zoom/Pan работает

---

### Phase 8: Display Mode Toggle

**Effort:** 1-2 дня
**Цель:** Переключение между 3 режимами: Deformation / Strain Rate / Peak Strain.

**Задачи:**

#### 8.1 Deformation mode (default)
- [ ] Показывает: контур + kernels + strain values
- [ ] Bull's eye: peak systolic strain
- [ ] Curves: strain over time

#### 8.2 Strain Rate mode
- [ ] Показывает: контур + SR values (с/сек)
- [ ] Bull's eye: peak SR
- [ ] Curves: SR over time
- [ ] Единицы: с⁻¹

#### 8.3 Peak Strain mode
- [ ] Показывает: контур + peak values (%)
- [ ] Bull's eye: peak strain (как в default)
- [ ] Curves: strain с marked peaks
- [ ] Единицы: %

**Файлы:**
- `src/echo_personal_tool/ui/strain_window.py` (modify — add mode switching)
- `src/echo_personal_tool/domain/services/speckle_metrics.py` (modify — add SR computation)

**Критерии приёмки:**
- Переключение между режимами работает
- Единицы отображаются корректно
- Bull's eye обновляется при переключении
- Curves обновляются при переключении

---

### Phase 9: Quality Control Checkboxes

**Effort:** 2-3 дня
**Цель:** Позволить пользователю отмечать сегменты как acceptable/unacceptable.

**Задачи:**

#### 9.1 Checkboxes в ControlPanel
- [ ] Для каждого из 17 сегментов: checkbox + label
- [ ] По умолчанию: все checked (acceptable)
- [ ] Uncheck = сегмент отмечен как unreliable

#### 9.2 Влияние на Bull's Eye
- [ ] Unchecked segments: серый цвет (neither red nor white)
- [ ] GLS пересчитывается: исключая unchecked segments
- [ ] В summary table: показать «GLS (excl. X segments)»

#### 9.3 Сохранение
- [ ] Checkboxes состояние сохраняется с deformation data
- [ ] При загрузке: восстанавливается состояние checkboxes

**Файлы:**
- `src/echo_personal_tool/ui/strain_window.py` (modify — add QC panel)
- `src/echo_personal_tool/domain/services/speckle_metrics.py` (modify — exclude rejected)

**Критерии приёмки:**
- Checkboxes отображаются для 17 сегментов
- Uncheck влияет на Bull's Eye (серый)
- GLS пересчитывается
- Состояние сохраняется

---

### Phase 10: Manual Kernel Correction

**Effort:** 3-4 дня
**Цель:** Позволить пользователю перетаскивать отдельные kernels с автопересчётом strain.

**Задачи:**
- [ ] Выделение kernels в cine-panel (click)
- [ ] Drag-and-drop kernels на новый position
- [ ] Auto-recompute strain после перемещения
- [ ] Undo/Redo для kernel movements
- [ ] Visual feedback: highlight selected kernel (yellow), show trajectory

**Файлы:**
- `src/echo_personal_tool/ui/cine_panel.py` (modify — add drag)
- `src/echo_personal_tool/domain/services/speckle_tracking.py` (modify — add recompute)

**Критерии приёмки:**
- Kernels можно выбрать и переместить
- Strain пересчитывается автоматически
- Undo возвращает предыдущее состояние
- Не блокирует основной workflow

---

### Phase 11: Save/Export Deformation Data

**Effort:** 1-2 дня
**Цель:** Сохранение и экспорт данных деформации.

**Задачи:**

#### 11.1 Save deformation data
- [ ] Формат: JSON (readable) + binary (for reload)
- [ ] Содержимое: kernels, strain values, quality, QC checkboxes, metadata
- [ ] Кнопка «Сохр.дан.деформ.»

#### 11.2 Export
- [ ] PNG: screenshot текущего view (cine + contour)
- [ ] SVG: Bull's eye plot (для печати)
- [ ] CSV: strain values per segment (для анализа в Excel)
- [ ] PDF: summary report (Bull's eye + table + curves)

**Файлы:**
- `src/echo_personal_tool/domain/services/strain_data_service.py` (new)
- `src/echo_personal_tool/ui/strain_window.py` (modify — add export)

**Критерии приёмки:**
- Save загружает JSON с полными данными
- Export PNG корректен
- Export SVG корректен
- Export CSV содержит все сегменты

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Quality threshold слишком агрессивный | Потеря данных | Default 0.3, allow user override |
| Weighted GLS нестабилен | Некорректный strain | Fallback на simple average |
| Manual correction UX сложный | User frustration | Простой drag, без complex gestures |
| Quad-view performance | Lag при resize | Offload rendering to separate thread |
| ECG data отсутствует | Нет ECG trace | Graceful degradation: hide ECG panel |
| Bull's eye при < 3 views | Неполная карта | Interpolation для missing views |

---

## Dependencies

- **Temporal fusion** — уже реализован (N±2 neighbors)
- **Quality-weighted smoothing** — уже реализован в `smooth_tracking_kernels()`
- **AHA segment strain** — уже реализован в `compute_aha_segment_strain()`
- **PyQtGraph** — уже используется для viewer (аналогично для curves)
- **No external dependencies** — все задачи используют существующий стек

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| STE quality (clinical usefulness) | ~62% | ~75-80% |
| Kernels accepted (NCC ≥ 0.3) | ~80% | > 90% |
| GLS accuracy vs EchoPAC | ~15% error | < 10% error |
| Samsung feature parity | 0% | ~80% (all major features) |
| User satisfaction (qualitative) | - | 「clinically useful」 |

---

## Out of Scope

- **ML fine-tuning** — заблокировано до 200+ gold-инстансов
- **Circumferential strain** — Radial + GLS для v1
- **3D STE** — требует 3D данных
- **Real-time tracking** — offline processing only
- **Multi-frame DICOM export** — Samsung-specific format

---

## Pending Issues (не исправлено на 2026-07-09)

### 1. GLS calculation — positive strain instead of negative
- **Симптом:** GLS = -40.8% (ненормально высоко), strain curves положительные
- **Ожидание:** GLS должен быть -18..-22%, strain curves отрицательные во время систолы
- **Возможная причина:** tracking moving kernels outward instead of inward, или preprocessing искажает speckle pattern
- **Файлы:** `strain_computation.py`, `speckle_worker.py`
- **Диагностика:** проверить `per_kernel` значения в логах

### 2. Bull's Eye — не отображает данные
- **Симптом:** 17 сегментов пустые (dark gray), хотя segment_strain содержит данные
- **Возможная причина:** segment_strain keys не совпадают с SEGMENT_GEOMETRY keys
- **Файлы:** `strain_window.py` (BullseyeWidget.paintEvent)
- **Диагностика:** проверить `STE segment_strain:` в логах worker'а

### 3. A2C / DAO — заглушки
- **Симптом:** Панели A2C и DAO показывают только заголовок с тем же GLS
- **Причина:** Нет отдельного cine/contour/kernels для этих видов
- **Решение:** требует multi-view tracking (отдельная большая задача)

### 4. Нет синхронного playback
- **Симптом:** Панели статичны (ED/ES snapshot), нет play/pause/seek
- **Решение:** интеграция с основным viewer playback

### 5. ECG — синтетический
- **Симптом:** `_generate_synthetic_ecg()` создаёт фейковый PQRST
- **Решение:** извлекать R-peaks из DICOM ECG waveforms (если доступны)

### 6. Strain Rate mode — не реализован
- **Симптом:** Radio button есть, но данные не переключаются
- **Решение:** вычислять strain rate per segment из strain curves

### 7. Kernel drag без пересчёта
- **Симптом:** `_on_kernel_moved` обновляет позицию, но не пересчитывает GLS/segment_strain
- **Решение:** вызывать `compute_strain()` после перемещения kernel

### 8. Двойной UI
- **Симптом:** Открывается и SteResultsDialog (старый) и StrainWindow (новый)
- **Решение:** убрать SteResultsDialog, оставить только StrainWindow

### 9. SteResultsDialog — дублирование
- **Симптом:** `_on_speckle_result_ready` открывает оба окна
- **Решение:** в `_on_speckle_result_ready` убрать вызов `_ensure_ste_dialog()`

---

## Ссылки

- `src/echo_personal_tool/domain/services/speckle_tracking.py` — main tracking pipeline
- `src/echo_personal_tool/domain/services/speckle_metrics.py` — strain computation
- `src/echo_personal_tool/ui/speckle_overlay.py` — visualization
- `docs/superpowers/specs/2026-06-27-ste-clinical-parity.md` — clinical parity spec
- `/home/areatu/ECHO2026-other/strain_example/` — Samsung RS85 reference DICOMs
