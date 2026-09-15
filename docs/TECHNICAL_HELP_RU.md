# SonoForge — техническая справка (текущая реализация)

Документ описывает текущий конвейер расчётов, источники значений, состояние калибровки, настройки, справочные данные и серверные протоколы. Это описание реализации, а не документ клинической валидации. Формула может быть выполнена корректно на неправильном контуре, масштабе или фазе, поэтому сама по себе не подтверждает клиническую достоверность результата.

Пользовательская инструкция находится в [`HELP_RU.md`](HELP_RU.md); английская версия этой справки — [`TECHNICAL_HELP_EN.md`](TECHNICAL_HELP_EN.md).

## 1. Модель обработки и область действия

SonoForge хранит исходные измерительные входы в расположенном в памяти `StudyMeasurementSessionStore`, индексированном разрешённым Study Instance UID. У измерения также могут быть SOP Instance UID и номер кадра. При каждом существенном изменении состояния контроллер строит `MeasurementSnapshot` из:

1. текущего `ViewerState`, instance и кадра;
2. DICOM/media metadata;
3. контуров, калиперов, Doppler-маркеров, сосудистых записей, M-Mode state и patient metrics текущей study-сессии;
4. действующей пространственной, временной и скоростной калибровки;
5. расчётных модулей и поиска в reference data;
6. форматирования для overlay и PDF.

Сессия измерений существует в памяти во время работы приложения. Это не постоянная база данных и не обещание изменения исходного DICOM. `Reset` очищает измерения и ручную калибровку текущего исследования, но пациентские Height/Weight остаются в структуре текущей сессии.

Видимая галерея не группирует studies: при открытии корня с несколькими папками исследований все найденные файлы сейчас попадают в общий flat-пул миниатюр. Study UID используется внутренне для поиска сессии, но не создаёт отдельных визуальных секций галереи.

## 2. Единицы и конвейер калибровки

### 2.1 Приоритет источников пространственного масштаба DICOM

`map_instance_metadata()` ищет положительную пару `(row_spacing, column_spacing)` в миллиметрах на пиксель в следующем порядке:

1. DICOM `PixelSpacing`;
2. `ImagerPixelSpacing`;
3. `NominalScannedPixelSpacing`;
4. физические дельты `SequenceOfUltrasoundRegions`, преобразованные из cm или mm в mm и, для поддержанных tissue 2D данных, из соответствующих ultrasound units;
5. `SharedFunctionalGroupsSequence/PixelMeasuresSequence/PixelSpacing`;
6. `PerFrameFunctionalGroupsSequence/PixelMeasuresSequence/PixelSpacing`.

Используется первая валидная положительная пара. Имя источника сохраняется в metadata instance и может показываться в Properties. Порядок — row/вертикальный масштаб и column/горизонтальный масштаб; их перестановка даёт направленную ошибку измерения.

Ручная B-mode calibration получает из известной линии изотропный масштаб:

```text
spacing_mm_per_px = known_distance_mm / measured_line_length_px
manual_spacing = (spacing_mm_per_px, spacing_mm_per_px)
```

Действующий масштаб:

```text
effective_spacing = manual_spacing, если он задан,
                    иначе dicom_spacing
```

Таким образом, ручная калибровка перекрывает DICOM-derived spacing в соответствующей study/session. Положительная DICOM или ручная пара выставляет `spacing_calibrated = true`.

### 2.2 Некалиброванный fallback и пиксельные единицы

Если валидный spacing отсутствует, контроллер передаёт геометрии `(1.0, 1.0)`, но помечает snapshot как `spacing_calibrated = false`. Это позволяет выполнить одну и ту же пиксельную геометрию, не выдавая один пиксель за один миллиметр.

Форматтер различает физический и пиксельный результат:

- длина: `px`, если `millimeter_length` недоступна;
- площадь: `px²`, если полигон измерим, но пространственно не откалиброван;
- объём: `px³`, если геометрия Simpson/closed polygon вычислима без физического масштаба;
- при калибровке: mm/cm, cm² или mL по типу результата.

Выбор `mm` или `cm` в Settings изменяет только отображение длины. Он не создаёт отсутствующий Pixel Spacing. Корректно вычисленный pixel-result не становится физическим клиническим значением без проверки масштаба.

### 2.3 Перевод пиксельной длины

Для линии длиной `p` пикселей и углом `θ` код выделяет горизонтальную/вертикальную составляющие и учитывает неодинаковый spacing:

```text
x_px = p cos(θ)
y_px = p sin(θ)
length_mm = sqrt((x_px × column_spacing)² + (y_px × row_spacing)²)
```

Обычный калипер хранит `pixel_length`, возможный `millimeter_length`, координаты начала/конца, frame, и SOP Instance UID. При отсутствии spacing `millimeter_length = None`.

### 2.4 Площадь

Для закрытого полигона пиксельная геометрия масштабируется по row/column spacing, после чего применяется polygon/shoelace area в mm². В физическом режиме:

```text
area_cm² = area_mm² / 100
```

Для надёжного результата нужен полигон минимум из трёх точек без самопересечения. Инструмент сравнения площадей выдаёт относительное совпадение двух валидных площадей:

```text
area_comparison_percent = min(A1, A2) / max(A1, A2) × 100
```

Это не то же самое, что стеноз по площади сосуда:

```text
area_stenosis_percent = (A_total − A_lumen) / A_total × 100
```

### 2.5 Объём и Simpson

Контур переводится в mm-координаты и разбивается на 20 дисков равной высоты. Для одного view при диаметре `d_i` и высоте `h = long_axis / 20`:

```text
V_mm³ = Σ (π / 4) × d_i² × h
V_mL = V_mm³ / 1000
```

Long axis строится по точкам митрального кольца/верхушки, если они есть; без annulus state применяется fallback по y-span. Для бипланового варианта используются соответствующие диаметры двух view:

```text
V_mm³ = Σ (π / 4) × d_A,i × d_B,i × h
h = max(long_axis_A, long_axis_B) / 20
V_mL = V_mm³ / 1000
```

Фракция выброса считается так:

```text
LVEF_percent = (EDV − ESV) / EDV × 100
```

Биплановый LV-результат требует согласованных контуров A4C и A2C для ED/ES. Если полного biplane нет, реализация может показать monoplanar или per-view значения. Simpson для LA/RA/RV использует ту же 20-дисковую механику в тех сценариях, где контуры поддержаны. Объём камеры может быть показан по доступной фазе согласно конкретному модулю; отсутствие ED/ES нельзя подразумевать автоматически.

### 2.6 Teichholz, масса ЛЖ, RWT и процентные размеры

Модуль Teichholz переводит размер из mm в cm:

```text
V_mL = 7 × L_cm³ / (2.4 + L_cm)
```

`LVEDD` используется для EDV, `LVESD` — для ESV. При наличии обоих:

```text
LVEF_percent = (EDV − ESV) / EDV × 100
```

Масса ЛЖ использует реализованную cube-формулу ASE, где IVSd, LVEDD и LVPWd предварительно переводятся в сантиметры:

```text
LVM_g = 0.8 × 1.04 × ((IVSd + LVEDD + LVPWd)³ − LVEDD³) + 0.6
```

Относительная толщина стенки:

```text
RWT = (2 × LVPWd) / LVEDD
```

Некоторые линейные сценарии вычисляют процентное сравнение диастолического и систолического размеров. Проверяйте label и контекст отчёта: это не то же самое, что EF.

### 2.7 LA area-length и RV FAC

Когда контур LA даёт площадь, а калипер `LAL` — длину:

```text
LAV_mL = (8 × A_cm² × A_cm²) / (3π × L_cm)
```

Реализованный RV FAC использует площади полости в ED и ES:

```text
FAC_percent = (Area_ED − Area_ES) / Area_ED × 100
```

Обе формулы зависят от границы контура и пространственного масштаба. Если масштаба нет, контроллер не выдаёт RV FAC, даже когда pixel polygon существует.

### 2.8 Стеноз по диаметру/площади и сосудистые отношения

Для отдельного инструмента стеноза по диаметру:

```text
diameter_stenosis_percent = (1 − min(D1, D2) / max(D1, D2)) × 100
```

Для стеноза по площади:

```text
area_stenosis_percent = (S_total − S_lumen) / S_total × 100
```

Сосудистые Doppler-метрики считаются для положительных PSV/EDV при `EDV ≤ PSV`:

```text
RI = (PSV − EDV) / PSV
S_D = PSV / EDV
mean_velocity_approx = (PSV + 2 × EDV) / 3
```

Это реализованные расчётные surrogate-индексы; они не валидируют клинический протокол сосуда или направление trace.

## 3. BSA и индексированные значения

### 3.1 Источник Height и Weight

Цепочка источников для BSA:

1. из загруженного DICOM instance берутся `PatientSize` (метры) и `PatientWeight` (kg);
2. когда оба значения есть, при загрузке instance приложение передаёт height в cm и weight в kg в measurement session;
3. в панели `Measures` видны поля `Height` и `Weight` как `QSpinBox`: `0–250 cm` и `0–300 kg`, ноль отображается пустым;
4. изменения пользователя передаются целыми cm/kg (отображаемые значения округляются) в `StudyMeasurementSessionStore.set_patient_metrics()`;
5. контроллер помещает `session.height_cm` и `session.weight_kg` в `MeasurementSnapshot`;
6. BSA/indexed расчёт запускается только при положительных обоих значениях.

У MP4/JPEG/PNG нет DICOM patient tags, поэтому поля обычно пусты до ручного ввода. При наличии только одного DICOM значения условие автоматического заполнения не выполняется. Значения в Properties — metadata, а snapshot использует значения session. Они хранятся в памяти и не записываются обратно в DICOM.

### 3.2 BSA Du Bois

Точная формула кода:

```text
BSA_m² = 0.007184 × height_cm^0.725 × weight_kg^0.425
```

На панели BSA показывается с двумя знаками после запятой. Неположительные или отсутствующие Height/Weight дают отсутствие BSA.

### 3.3 Индексация

Когда абсолютный результат существует, код делит физические значения на BSA:

```text
indexed_volume_mL_m² = volume_mL / BSA_m²
indexed_linear_mm_m² = length_mm / BSA_m²
LVMI_g_m² = LV mass_g / BSA_m²
```

Могут индексироваться Simpson EDV/ESV по view и комбинированные значения, Teichholz EDV/ESV, LAV (4C, biplane, area-length), RAV, LV mass и выбранные linear labels. Overlay всегда показывает доступные LAVi/RAVi и может показывать другие индексы согласно formatter нормативов; PDF включает рассчитанные поля, когда они присутствуют.

BSA не исправляет неверный контур, неверную калибровку или ошибочные данные пациента. Изменение Height/Weight меняет indexed values, но не абсолютную геометрию.

## 4. Doppler и временные формулы

### 4.1 Преобразование осей

Doppler mapping хранит ROI, ширину/высоту plot, time origin/span, velocity span и baseline. При калиброванном времени:

```text
time_ms(x) = time_origin_ms + (x − plot_origin_x) / plot_width × time_span_ms
```

При наличии baseline и полного velocity span:

```text
velocity_cm_s(y) = −(y − baseline_y) / (plot_height / velocity_span_cm_s)
```

Fallback по y переводит границы plot между `velocity_min_cm_s` и `velocity_max_cm_s`; без лучшего масштаба обычно используется полный span 200 cm/s (`−100…+100 cm/s`). Неверные ROI, baseline или span меняют все производные velocity/time маркеры этого кадра.

### 4.2 Время и ЧСС

Для интервала `T_ms`:

```text
heart_rate_bpm = 60000 / T_ms
```

Интервал хранит start/end в миллисекундах, duration = `end_ms − start_ms`. DT, IVRT, AT и ET показываются, если есть interval markers и нужная time calibration.

### 4.3 Пики, отношения, VTI и градиенты

Peak markers хранят скорость в cm/s. Отношения — прямое деление при ненулевом знаменателе:

```text
E_A = E / A
E_e′ = E / mean(e′_septal, e′_lateral)   (для доступных e′)
e′ / a′ = e′ / a′
```

VTI trace интегрируется трапецией по `(time_ms, velocity_cm_s)`. Поскольку время задано в миллисекундах, интеграл делится на 1000:

```text
VTI_cm = abs( ∫ velocity_cm_s dt_ms / 1000 )
```

Несколько VTI traces усредняются. При наличии ET:

```text
Vmean_cm_s = abs(VTI_cm) / (ET_ms / 1000)
```

Иначе, если возможно, используется длительность trace. Упрощённый peak-градиент Bernoulli:

```text
PGpeak_mmHg = 4 × (Vpeak_cm_s / 100)²
```

Mean gradient считается по интегралу квадрата скорости, а не как `4 × Vmean²`:

```text
PGmean = (1 / T) × ∫ 4 × (v_cm_s / 100)² dt
```

Значения усредняются по доступным traces. Если ET полностью покрыт trace, он задаёт окно интегрирования; иначе используется диапазон trace.

### 4.4 Диастолическая категория

Реализованный упрощённый алгоритм использует доступные критерии `E/e′ > 14`, septal `e′ < 7 cm/s` или lateral `e′ < 10 cm/s`, LAVi `> 34 mL/m²`, TR Vmax `> 280 cm/s`. Нужно минимум три критерия; большинство даёт `Abnormal` или `Normal`, равенство — `Indeterminate`. Это упрощённое правило приложения, а не полный клинический алгоритм guideline.

## 5. Откуда берутся остальные значения

### 5.1 Frame и DICOM metadata

DICOM mapper читает, среди прочего:

- SOP/Series/Study identifiers и modality;
- число кадров;
- spatial spacing и источник spacing;
- `FrameTime`, с fallback на `CineRate`;
- `FrameTimeVector`, если есть;
- SeriesDescription;
- `PatientSize` и `PatientWeight`.

Показ тегов в DICOM inspector сам по себе не делает тег входом расчёта: нужен соответствующий parser. Overlay интересующих тегов — только display preference.

### 5.2 Measurement state

Contours, linear measurements, vessel records, Doppler markers/calibration, M-Mode calibration, cine ROI, patient metrics и strain report хранятся в study-session. Linear и vessel fields для текущего snapshot фильтруются по SOP Instance; Doppler может агрегировать DTO по instances/frames study. Simpson biplane может объединять совместимые view из разных instances, а физический spacing берётся в текущем расчётном контексте.

Display overlay может использовать Doppler DTO текущего instance для видимого кадра, а производные report values — study aggregate. Поэтому значение может быть в study report, но не соответствовать текущему видимому instance. Проверяйте контекст study/instance.

### 5.3 Reference YAML и нормы

Structured reference store загружает встроенный YAML и, если задано, language-specific файл. Constructor по умолчанию работает с `references_structured.yaml`; русский browser обычно читает `references_structured_ru.yaml`. Запись нормы содержит parameter ID, unit, male/female norms, gradations, pathology, images и source. Поле `Age` в web browser сейчас не фильтрует строки. Пользовательские `.md/.pdf` — материалы для чтения, не входы расчёта.

## 6. Настройки и их техническое влияние

Ниже приведены текущие границы/defaults, если они заданы в коде. Display preference может сохраняться, не будучи входом формулы.

### Interface/display

| Настройка | Текущее влияние |
|---|---|
| UI font size | 9–18 pt, default 12; только читаемость/layout. |
| Results overlay font | 10–28 pt, default 20; только текст. |
| Results overlay opacity | 0.10–1.00, default 0.70; только видимость. |
| Caliper line width | 1–6 px, default 2; только отрисовка калипера. |
| Cine speed multiplier | 0.25–4.0×, default 1.0×; только playback. |
| Playback cache | 8–512 MB, default 64 MB; decode/cache, не формула. |
| W/L | Soft `(70, 40, 35)`, Contrast `(140, 55, 65)` или last-used; только изображение. |
| Thumbnail size | Small/Medium/Large; только layout галереи. |
| Crosshair, panel frames, frame/inline labels | только отображение; labels не меняют geometry. |
| Reduce motion | animation/accessibility. |

### Measurement preferences

| Настройка | Текущее влияние |
|---|---|
| Manual/AI/Simpson contour pen width | 1–6 px, default 2 для каждого; только линия. |
| Magnetic snap | Включён по умолчанию. Edge-map adjustment может менять точки и результат. |
| Magnetic weight threshold | 0.05–0.50, default 0.15; минимальный edge weight для притяжения. |
| Magnetic release strength | 0.50–1.00, default 0.90; сила движения при отпускании/snap. |
| Magnetic release radius | 5–40 px, default 15 px; максимальный радиальный поиск/сдвиг. |
| Doppler from DICOM/scale | Включён по умолчанию; разрешает автоматический путь tags/ticks/ROI. |
| Calibration tick snap | Включён по умолчанию; calibration click может сдвинуться к tick/grid. |
| Auto depth calibration | В preference включён по умолчанию, но текущий open/reset controller path может всё равно попробовать auto depth при необходимости. Проверяйте результат и используйте manual. |
| Length unit | `mm` или `cm`, только отображение. |
| Area tool mode | `click` polygon или `freehand`; меняет сбор точек, не формулу площади. |
| Despeckle/grayscale | display processing; не меняет сохранённый исходный DICOM. |

Толщина линии не меняет координаты. Magnetic и tick snap могут менять координаты/scale и должны учитываться при воспроизводимости.

### Other/experimental

PDF font ограничен 8–16 pt, default 10. Confirm reset, startup mode, DICOM tag inspector/list, last folder, reference directory, Gold Annotation, `Show Strain` и `Show LA Auto` управляют UI/state. Видимость experimental-пунктов не устанавливает зависимости или модели.

### Patient metrics и preferences — разное

Height/Weight — session inputs, а не общие QSettings preferences. Изменение Settings не меняет patient metrics текущей study. Reset measurement inputs оставляет Height/Weight в текущей session; после перезапуска приложения нельзя считать их постоянной медицинской записью.

## 7. Ошибки калибровки и способы исправления

### Неправильные физические единицы или pixels

**Причины:** отсутствуют теги, spacing неположителен, перепутаны row/column, ручная линия поставлена не по той шкале, или в video/image нет шкалы.

**Исправление:** проверьте источник spacing в Properties/DICOM tags, видимую depth ruler, очистите неверную manual calibration, откалибруйте известный интервал и сравните второе известное расстояние. Settings unit не заменяет calibration.

### Неправильная площадь/объём

**Причины:** самопересечение, несоответствие open/closed contour, включённая стенка/клапан, неверные annulus/apex, foreshortened view, неправильный ED/ES frame или spacing от другого instance.

**Исправление:** выберите правильные instance/frame/view, удалите и нарисуйте контур заново, проверьте точки до принятия auto result, проверьте `spacing_calibrated` и unit. Для biplane Simpson проверьте обе view и фазы.

Геометрический validator LV может отклонить контур со слишком маленькими annulus/axis/arc, слишком плоской дугой, неправдоподобным наклоном annulus, перевёрнутой верхушкой A4C, centroid вне ROI или самопересечением. Это защитные проверки, а не диагноз.

### Неправильный magnetic result

**Причины:** edge map следует за speckle, shadow, border или сильной неанатомической линией; radius/threshold/release слишком permissive.

**Исправление:** отключите magnetic snap, уменьшите release radius/измените threshold, вручную перетащите закреплённые endpoints и сравните с неснэпнутым контуром.

### Неправильная автоматическая depth calibration

**Причины:** деления обрезаны, слабый контраст, поверх шкалы расположен ECG/текст или это не depth ruler. `auto_depth_calibration_enabled` сейчас не является надёжным жёстким запретом для каждого вызова controller.

**Исправление:** выполните manual calibration через `K`, введите проверенное расстояние и зафиксируйте факт ручной calibration в рабочем протоколе.

### Неправильные Doppler values

**Причины:** неправильный spectral ROI, baseline, знак направления, введена половина вместо полного span, ложные tick/grid или trace не того cycle/direction.

**Исправление:** запустите `Calibration Doppler`, поставьте baseline на нулевую линию, введите полный velocity span в cm/s, проверьте time ruler и перерисуйте trace. Fallback 200 cm/s не является доказательством, что реальная шкала равна 200 cm/s.

### Неправильный M-Mode result

**Причины:** линия пересекает не ту структуру, неверный ROI, неполная depth/time calibration, отсутствует/неподходящ `FrameTime`, или источник не содержит настоящую M-Mode panel.

**Исправление:** заново задайте line/ROI, внесите depth и time calibration и проверьте M-Mode strip до TAPSE/Teichholz/time HR.

### AI/Strain недоступны или неправдоподобны

**Причины:** отсутствуют optional runtime/model files, неподдержанный frame/view, плохой cine, неверный contour или QC failure.

**Исправление:** включите функцию после установки зависимостей, используйте поддержанный clip, проверьте preliminary contour/QC и сравните с manual workflow. Automated output не является диагнозом.

## 8. Серверные протоколы и безопасная конфигурация

### 8.1 Матрица протоколов

| Задача | DICOMweb | DIMSE |
|---|---|---|
| Query | QIDO-RS | C-FIND |
| Retrieve | WADO-RS | C-GET или C-MOVE |
| Store/send | STOW-RS | C-STORE |
| Проверка соединения | HTTP request | C-ECHO |

Query source в `Load from server…` и retrieval source в `Settings → Server` независимы. `Auto` может переключаться между доступными клиентами/settings, но не гарантирует поддержку каждого протокола данным PACS.

### 8.2 Factory defaults и безопасные defaults для deployment

Factory defaults удобны для локального Orthanc-подобного тестового узла, но не являются production-профилем:

| Настройка | Значение в текущем коде по умолчанию |
|---|---|
| DICOMweb URL | `http://127.0.0.1:8042/dicom-web` |
| HTTP authentication | режим `Basic (username / password)`, credentials пусты до настройки |
| DIMSE | выключен; AE `ECHO2026`, called AE `ORTHANC`, host `127.0.0.1`, port `4242` |
| Retrieval | `Auto`; DIMSE retrieval mode — `C-GET` |
| DIMSE TLS | выключен; проверка сертификата включена при включении TLS |
| Embedded Storage SCP | bind `127.0.0.1`, port `11112`, при пустом поле AE берётся как local AE |
| Network timeout | 30 секунд |

Для удалённого или production deployment замените loopback/HTTP defaults и явно согласуйте контракт PACS. Рекомендуемые безопасные настройки:

- используйте настоящий DICOMweb HTTPS URL или DIMSE endpoint; `Mock` оставляйте выключенным вне тестов;
- оставляйте HTTP и DIMSE certificate verification включённым;
- задавайте доверенный CA и client certificate/key только если PACS этого требует;
- Basic auth используйте через доверенный HTTPS, пароль храните в keyring;
- добавляйте только нужные headers и не коммитьте их;
- default network timeout — 30 секунд; меняйте его только при документированной причине (текущая форма сохраняет поле, но не показывает отдельный timeout control);
- используйте согласованные с PACS AE titles;
- выбирайте C-GET, если PACS его поддерживает и он проще; используйте C-MOVE при необходимости PACS или его routing model;
- для удалённого PACS привязывайте embedded SCP к reachable interface, а не к `127.0.0.1`;
- открывайте в firewall только нужный SCP port и регистрируйте AE/host/port на PACS.

### 8.3 Проверка C-MOVE reachability

Для работы C-MOVE:

1. PACS должен знать destination AE title;
2. destination host/IP должен маршрутизироваться от PACS к машине/container SonoForge;
3. inbound SCP port должен быть разрешён;
4. bind host должен реально слушать reachable interface;
5. при secure DIMSE TLS settings/certificates должны совпадать;
6. у PACS должны быть права на move выбранной study/series.

Ошибка destination unknown или timeout обычно относится к AE/network/routing, а не к измерениям. C-ECHO тестирует DIMSE association, но успешный C-ECHO не доказывает обратную доступность для C-MOVE.

### 8.4 Retrieval, STOW и annotated payload

В server dialog `Load` означает рабочий кэш, а **`Save to Disk`** — постоянное UID-ориентированное локальное DICOM-дерево. `Save to Disk` — это retrieval, а не экспорт измерений.

Upload dialog выбирает STOW-RS или DIMSE C-STORE по доступности target. Исходный DICOM читается, и может быть создан payload с graphic annotations. Исходный файл не переписывается. Другой PACS/viewer может не отображать `Graphic Annotation Sequence`; совместимость проверяется отдельно.

## 9. Диагностический checklist

При неожиданном числе зафиксируйте:

1. Study/Series/SOP Instance UID и frame index;
2. media type и источник spacing/time;
3. manual calibration и факт её приоритета над DICOM;
4. Height/Weight и источник BSA;
5. contour phase/view/endpoints и magnetic/tick-snap settings;
6. Doppler ROI, baseline, velocity span, time span, trace label и cycle;
7. Settings, влияющие на geometry/display;
8. был ли результат взят из current-instance display или study-aggregate report.

Затем повторите измерение с manual calibration и magnetic snap, отключёнными для проверки. Если число изменилось, сравнивайте raw points и axis mapping, а не только отформатированное значение.

## 10. Медицинские и программные ограничения

Формулы реализуют текущий код SonoForge, а не полный движок клинических guideline. Нормы, автоматическая сегментация, Doppler detection, M-Mode inference, contour refinement, gradients, indexing и PDF serialization могут содержать ошибки или не поддерживать edge cases. Используйте исходные изображения, валидированный протокол измерения, независимую проверку и квалифицированное клиническое решение.
