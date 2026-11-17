# Многофайловые CT/MR: patient-space индекс (#557)

## Статус

Первый срез classic CT/MR: **header-only API, не готовый stack viewer**.
Существующая сортировка US/browser по имени/дате не меняется и не объявляется
анатомическим порядком. Нет новой кнопки открытия стека, фонового loader,
прокрутки, общего stack cache, измерений или сохранения CT/MR в документ.
Issue #557 этим срезом не закрывается. Это не диагностическая валидация.

## Контракт

- `domain.models.ctmr_stack`: immutable `StackFrameRef`, `SliceGeometry`,
  `CtMrStack`, `CtMrIndex` и диагностика. Ref содержит путь, study/series/SOP,
  local frame, FrameOfReferenceUID, encoding, geometry и display transform;
  pixels и демография в индекс не попадают.
- `infrastructure.ctmr_index.index_ctmr_files(paths, cancelled=..., max_files=...)`
  принимает выбранные пути. `index_ctmr_directory(directory, ...)` обходит один
  каталог **без рекурсии**, без фильтра по расширению. Подкаталоги/неизображения
  получают диагностику; они тоже учитываются в лимите входов.
- Вход ограничен 10 000 entries, число partitions — 256. Отмена проверяется
  между чтениями и перед возвратом. `complete=False` означает прерванный/ограниченный
  обход, такой результат нельзя молча выдавать за весь каталог. `complete=True`
  означает только завершение обхода: ошибки отдельных файлов остаются в
  `diagnostics`, а полнота исходной acquisition **не доказана**.
- Только classic CT Image Storage / MR Image Storage, Part-10, один кадр на SOP,
  MONOCHROME1/2, scalar integer 8/16/32-bit pixels. `local_frame=0` задан явно,
  а не равен порядковому номеру среза в стеке. Номер будущей UI-позиции не является
  идентификатором измерения: идентичность — `(SOPInstanceUID, local_frame)`.
- Никаких `pixel_array`, объёмного ndarray или декодирования в индексере.
  Используются `stop_before_pixels=True` и allowlist header tags. Сначала
  проверяется classic SOP: Enhanced отклоняется до запроса functional groups.
  Whole-dataset Deflated Explicit VR Little Endian отвергается отдельно:
  pydicom иначе распаковал бы весь dataset, несмотря на `stop_before_pixels`.
  Проверка не обещает жёсткий byte-budget произвольных метаданных файла.
- Per-file stat stamp проверяется до/после чтения. Он **не content hash** и не
  атомарный snapshot. Будущий decoder обязан сверять stamp до decode и перед
  публикацией, а application — generation/cancellation token. Изменённый между
  проходами файл отклоняется.

## Разделение и порядок

Partition учитывает study/series, FrameOfReferenceUID, SOP class/modality,
rows/columns, pixel encoding, photometric, ImageType (в том числе LOCALIZER),
ориентацию и spacing, а также явные temporal/acquisition/echo/trigger/diffusion
и MR sequence dimension tags. Разный rescale **не требует** отдельного стека:
transform принадлежит каждому FrameRef и должен применяться per slice.

IOP проверяется на конечность, единичную длину и ортогональность; spacing —
на положительность и численную устойчивость. Присутствующий повреждённый тег
не превращается в молчаливый fallback при отсутствии другого spatial tag.
Ориентации группируются с абсолютным допуском `1e-5`, spacing — `1e-5 mm`.
Это численные допуски, не клинические границы ошибки.

Для валидной геометрии:

```text
normal = normalize(cross(IOP[0:3], IOP[3:6]))
position_mm = dot(ImagePositionPatient, normal)
```

Порядок — возрастающая `position_mm`, в том числе для oblique planes.
Filename/InstanceNumber/дата не используются как spatial order. Файлы без
геометрии остаются с детерминированным SOP/local-frame порядком и явным
`spatial_order_unverified`; без FrameOfReferenceUID порядок тоже не объявляется
подтверждённым. Это означает проверенность пространственного порядка, **не**
полноту acquisition, правильность анатомии или исчерпывающее распознавание MR dimensions.
Classic MR с неописанными/частными dimensions требует независимой проверки;
совпадение позиций предупреждает о потенциально смешанных frames, но не
заменяет полноценный dimension index.

Предупреждения:

- `series_partitioned`: одна серия разделена на несколько совместимых стеков;
- `duplicate_positions`: разница позиций ≤ `0.001 mm`, порядок не подтверждён;
- `nonuniform_spacing_possible_gaps`: шаг отличается от median положительных
  шагов более чем на max(`0.001 mm`, 5%). Координаты не регуляризуются,
  отсутствующие срезы не синтезируются. Равномерно отсутствующие срезы без
  независимого expected spacing не обнаруживаются; при 1–2 срезах полноту
  также установить нельзя;
- `in_plane_origin_shift`: сдвиг origin внутри плоскости. Не выдаётся за
  rectilinear volume; MPR/3D не реализованы.

Повторный SOP с одинаковыми проиндексированными header facts оставляет один
детерминированный путь и `duplicate_sop_pixels_unverified`: равенство pixels
header-only чтение не доказывает. Конфликтующие metadata одного SOP/local-frame
**целиком исключаются**, каждый путь получает `conflicting_sop`.

`SliceGeometry.patient_point(row, column)` возвращает LPS-mm координату:
первый IOP вектор умножается на **column × column_spacing**, второй — на
**row × row_spacing**. Это seam для будущих измерений, не готовый persistence codec.

## Интенсивность

Экспортирован существующий mapper `map_dicom_display`; используется тот же
F01/F02 display model, без второй реализации W/L. Ref сохраняет signedness,
BitsStored/Allocated, per-file rescale, VOI/window и MONOCHROME1.
Повреждённый/неполный linear rescale отклоняется; MR signal не получает HU
просто по наличию rescale. Синтетический тест проверяет передачу signed CT
stored values через существующий `stored_to_modality`, но новый decoder/UI этим
срезом не проверен. Compressed pixel transfer syntax допускает чтение header
без установленного decoder — это **не доказательство успешного pixel decode**.

## Проверка и продолжение

```bash
.venv/bin/python scripts/run_pure_core_tests.py -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest --pure-core \
  -p pytest_timeout tests/unit/test_ctmr_stacks.py -q -o addopts=
```

56 synthetic tests: shuffled filenames/InstanceNumber, oblique LPS, anisotropy,
signed/rescale/MONOCHROME1 metadata, MR units, localizer/phase/echo/diffusion
partitions, missing/malformed geometry, gaps/duplicates/conflicting SOP,
compressed header, deflated refusal, cancellation/limits/source replacement.
Не проверены реальные vendor/PACS исследования и визуальное совпадение с
независимым viewer.

Следующие отдельные срезы:

1. Lazy frame access текущего/соседних срезов, bounded shared cache, cancellation
   и generation-aware публикация; не склеивать все файлы в гигантский ndarray.
2. Stack selector, scroll/jump, предупреждения, L/R/A/P/H/F labels, slice position,
   spacing и F01/F02 display pipeline в viewer. Без изменения поведения US cine.
3. Линейка/угол/Cobb/площадь/ROI statistics и durable привязка к точному SOP +
   local frame + patient geometry с reopen/export acceptance.
4. Enhanced CT/MR и полноценные multidimensional/private MR — отдельный follow-up,
   без молчаливого fallback на classic single-frame.
5. Независимая native/vendor validation на приёмочном наборе #557.

MPR, volume rendering, segmentation, PET/perfusion/diffusion fitting не входят
в classic 2D MVP.
