# i18n: Fix Untranslated Russian Text in English UI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all hardcoded Russian strings in the UI with `tr()` calls and add corresponding English/Russian locale keys, so the interface is fully translated when switching to English.

**Architecture:** Each task targets a logical module group. For each hardcoded Russian string: (1) add a new key to both `ru.json` and `en.json`, (2) replace the hardcoded string with `tr("new.key")`, (3) add `from echo_personal_tool.infrastructure.i18n import tr` if not already imported. Locale keys follow existing naming conventions (e.g. `strain.segment_name`, `constructor.file_menu`).

**Tech Stack:** Python, PySide6 (Qt), custom `tr()` i18n module from `infrastructure/i18n.py`

## Global Constraints

- Locale files: `src/echo_personal_tool/infrastructure/locales/{ru,en}.json`
- Translation function: `tr(key: str, **kwargs) -> str` from `echo_personal_tool.infrastructure.i18n`
- Key format: dot-notation, lowercase, e.g. `"strain.view_mode"`, `"constructor.file_menu.save"`
- Existing keys must NOT be modified (only add new ones)
- `ru.json` values = Russian text, `en.json` values = English text
- Domain-layer messages (validation errors, status strings) also go through `tr()`
- Do NOT touch files that already correctly use `tr()` — only fix hardcoded strings

## File Structure

| File | Role |
|------|------|
| `infrastructure/locales/ru.json` | Russian translations — add new keys |
| `infrastructure/locales/en.json` | English translations — add new keys |
| `ui/strain_window.py` | Strain analysis window — ~40 hardcoded strings |
| `ui/strain_curves_view.py` | Strain curves plot — segment names, axis label |
| `presentation/mmode_widget.py` | M-Mode widget — button labels |
| `presentation/styled_dialogs.py` | File dialog helpers — default titles/filters |
| `presentation/main_window.py` | Main window — Teichholz status strings |
| `presentation/system_bar.py` | System bar — button label, tooltips |
| `presentation/mmode_measurement.py` | M-Mode measurement — labels |
| `presentation/ase_reference_dialog.py` | ASE reference — button/menu text |
| `presentation/structured_reference_widget.py` | Structured reference — all UI text |
| `presentation/user_preferences_dialog.py` | Preferences — experimental tab labels |
| `presentation/viewer_widget.py` | Viewer — comments only (no user-facing) |
| `constructor/constructor_widget.py` | Constructor widget — buttons, dialogs |
| `constructor/constructor_dialog.py` | Constructor dialog — menus, window title |
| `constructor/dialogs.py` | Constructor file dialogs — defaults |
| `constructor/editors/topic_editor.py` | Topic editor — all UI text |
| `constructor/editors/image_editor.py` | Image editor — all UI text |
| `constructor/editors/parameter_table_editor.py` | Parameter table editor — headers, buttons, dialogs |
| `constructor/editors/pathology_editor.py` | Pathology editor — all UI text |
| `constructor/editors/metadata_editor.py` | Metadata editor — labels |
| `constructor/preview/reference_preview.py` | Reference preview — HTML headers |
| `constructor/exporters/pdf_exporter.py` | PDF export — HTML table headers |
| `constructor/exporters/html_exporter.py` | HTML export — page title, headers |
| `domain/calculations/lvef_simpson.py` | LVEF validation messages |
| `domain/calculations/rv_fac.py` | RV FAC status strings |
| `domain/calculations/planimeter.py` | Planimeter labels |
| `domain/services/la_segmentation_service.py` | LA segmentation error messages |
| `domain/services/cine_segment_diagnostics.py` | Cine diagnostics messages |
| `domain/services/measurement_report_formatter.py` | Report section headers |
| `infrastructure/measurement_report_pdf.py` | PDF title |
| `application/workers/orthanc_download_worker.py` | Download status messages |
| `application/app_controller.py` | Status message |

---

## Task 1: Add All New Locale Keys to ru.json and en.json

**Files:**
- Modify: `src/echo_personal_tool/infrastructure/locales/ru.json`
- Modify: `src/echo_personal_tool/infrastructure/locales/en.json`

**Interfaces:**
- Consumes: (none — this is the foundation)
- Produces: All new translation keys available for `tr()` calls in subsequent tasks

- [ ] **Step 1: Add strain window keys**

Append to `ru.json` before the closing `}`:

```json
"strain.segment_name.{id}": "БазПерг",
"strain.segment_a4c": "A4C",
"strain.segment_a2c": "A2C",
"strain.segment_apical": "Апикальный",
"strain.summary_table": "Сводная таблица",
"strain.gls_global": "Сред.ГлобПродДеф",
"strain.gls_a4c": "A4C ГлобПродДеф",
"strain.gls_a2c": "A2C ГлобПродДеф",
"strain.gls_dao": "ДАО ГлобПродДеф",
"strain.ef_biplane": "ФВ [дв-плоск]",
"strain.edv_biplane": "КДО [дв-плоск]",
"strain.esv_biplane": "КСО [дв-плоск]",
"strain.autozak": "АвтоЗАК",
"strain.hr": "ЧСС",
"strain.unit_ml": "мл",
"strain.unit_ms": "мс",
"strain.view_mode": "Вид",
"strain.mode_cine_contour": "Cine + контур",
"strain.mode_curves": "Кривые деформации",
"strain.metric": "Параметр",
"strain.metric_deformation": "Деформация",
"strain.metric_sr": "Скорость деформ.",
"strain.metric_peak": "Пик.изм.деформации",
"strain.load_results": "Загрузите результаты",
"strain.actions": "Действия",
"strain.btn_edit_mode": "Режим редактирования",
"strain.btn_undo": "Отменить (Ctrl+Z)",
"strain.btn_redo": "Повторить (Ctrl+Y)",
"strain.btn_save_json": "Сохранить JSON",
"strain.btn_export_png": "Экспорт PNG",
"strain.btn_export_csv": "Экспорт CSV",
"strain.btn_close": "Закрыть",
"strain.segment_fallback": "Сегмент {id}",
"strain.save_dialog_title": "Сохранить данные деформации",
"strain.export_png_title": "Экспорт PNG",
"strain.export_csv_title": "Экспорт CSV",
"strain.time_axis": "Время(ms)",
"strain.seg_basal_sept": "БазПерг",
"strain.seg_basal_lat": "Базбок",
"strain.seg_mid_sept": "СрПерг",
"strain.seg_mid_lat": "Србок",
"strain.seg_apical_sept": "АпПер",
"strain.seg_apical_lat": "АпЛат",
"strain.label_sept": "Пер",
"strain.label_lat": "Лат",
"strain.label_inferior": "Нижн",
"strain.label_posterior": "Задн",
"strain.label_apical_sept": "АпПер",
"strain.label_apical_lat": "АпЛат",
"strain.label_apical_inferior": "АпНижн"
```

Append to `en.json` before the closing `}`:

```json
"strain.segment_name.{id}": "BasSept",
"strain.segment_a4c": "A4C",
"strain.segment_a2c": "A2C",
"strain.segment_apical": "Apical",
"strain.summary_table": "Summary Table",
"strain.gls_global": "Mean GLS",
"strain.gls_a4c": "A4C GLS",
"strain.gls_a2c": "A2C GLS",
"strain.gls_dao": "DAO GLS",
"strain.ef_biplane": "EF [biplane]",
"strain.edv_biplane": "EDV [biplane]",
"strain.esv_biplane": "ESV [biplane]",
"strain.autozak": "AutoZAK",
"strain.hr": "HR",
"strain.unit_ml": "mL",
"strain.unit_ms": "ms",
"strain.view_mode": "View",
"strain.mode_cine_contour": "Cine + contour",
"strain.mode_curves": "Strain curves",
"strain.metric": "Metric",
"strain.metric_deformation": "Deformation",
"strain.metric_sr": "Strain rate",
"strain.metric_peak": "Peak S. deformation",
"strain.load_results": "Load results",
"strain.actions": "Actions",
"strain.btn_edit_mode": "Edit mode",
"strain.btn_undo": "Undo (Ctrl+Z)",
"strain.btn_redo": "Redo (Ctrl+Y)",
"strain.btn_save_json": "Save JSON",
"strain.btn_export_png": "Export PNG",
"strain.btn_export_csv": "Export CSV",
"strain.btn_close": "Close",
"strain.segment_fallback": "Segment {id}",
"strain.save_dialog_title": "Save strain data",
"strain.export_png_title": "Export PNG",
"strain.export_csv_title": "Export CSV",
"strain.time_axis": "Time(ms)",
"strain.seg_basal_sept": "BasSept",
"strain.seg_basal_lat": "BasLat",
"strain.seg_mid_sept": "MidSept",
"strain.seg_mid_lat": "MidLat",
"strain.seg_apical_sept": "ApSept",
"strain.seg_apical_lat": "ApLat",
"strain.label_sept": "Ant",
"strain.label_lat": "Lat",
"strain.label_inferior": "Inf",
"strain.label_posterior": "Post",
"strain.label_apical_sept": "ApAnt",
"strain.label_apical_lat": "ApLat",
"strain.label_apical_inferior": "ApInf"
```

- [ ] **Step 2: Add constructor keys**

Append to `ru.json`:

```json
"constructor.search_placeholder": "Поиск параметра, патологии, темы...",
"constructor.validation_errors": "Ошибки валидации",
"constructor.validation_error_count": "Найдено {count} ошибок:\n\n{msg}",
"constructor.validation_no_errors": "Ошибок не найдено ✓",
"constructor.cancel_title": "Отмена",
"constructor.cancel_body": "Отменить все изменения с момента последнего сохранения?",
"constructor.import_excel": "Импорт Excel",
"constructor.export_pdf": "Экспорт PDF",
"constructor.export_html": "Экспорт HTML",
"constructor.import_error": "Ошибка импорта",
"constructor.export_error": "Ошибка экспорта",
"constructor.file_menu": "Файл",
"constructor.file_menu.save": "Сохранить",
"constructor.file_menu.save_as": "Сохранить как...",
"constructor.file_menu.import_excel": "Импорт Excel...",
"constructor.file_menu.export_pdf": "Экспорт PDF...",
"constructor.file_menu.export_html": "Экспорт HTML...",
"constructor.file_menu.close": "Закрыть",
"constructor.edit_menu": "Правка",
"constructor.edit_menu.undo": "Отменить (к сохранению)",
"constructor.edit_menu.find": "Найти...",
"constructor.edit_menu.delete": "Удалить выбранные",
"constructor.view_menu": "Вид",
"constructor.view_menu.preview": "Preview",
"constructor.view_menu.validate": "Проверка целостности",
"constructor.save_button": "💾 Сохранить",
"constructor.load_error": "Ошибка загрузки",
"constructor.load_error_body": "Не удалось открыть конструктор:\n{exc}",
"constructor.window_title": "Конструктор справочника",
"constructor.unsaved_title": "Несохранённые изменения",
"constructor.unsaved_body": "Есть несохранённые изменения. Сохранить перед закрытием?",
"constructor.save_as_title": "Сохранить как",
"constructor.minimize": "Свернуть",
"constructor.maximize": "Развернуть",
"constructor.close": "Закрыть",
"constructor.dialogs.open_file": "Открыть файл",
"constructor.dialogs.open_files": "Открыть файлы",
"constructor.dialogs.save_file": "Сохранить файл",
"constructor.dialogs.select_folder": "Выберите папку",
"constructor.dialogs.all_files": "Все файлы (*)"
```

Append to `en.json`:

```json
"constructor.search_placeholder": "Search parameter, pathology, topic...",
"constructor.validation_errors": "Validation Errors",
"constructor.validation_error_count": "Found {count} errors:\n\n{msg}",
"constructor.validation_no_errors": "No errors found ✓",
"constructor.cancel_title": "Cancel",
"constructor.cancel_body": "Discard all changes since last save?",
"constructor.import_excel": "Import Excel",
"constructor.export_pdf": "Export PDF",
"constructor.export_html": "Export HTML",
"constructor.import_error": "Import Error",
"constructor.export_error": "Export Error",
"constructor.file_menu": "File",
"constructor.file_menu.save": "Save",
"constructor.file_menu.save_as": "Save As...",
"constructor.file_menu.import_excel": "Import Excel...",
"constructor.file_menu.export_pdf": "Export PDF...",
"constructor.file_menu.export_html": "Export HTML...",
"constructor.file_menu.close": "Close",
"constructor.edit_menu": "Edit",
"constructor.edit_menu.undo": "Undo (to last save)",
"constructor.edit_menu.find": "Find...",
"constructor.edit_menu.delete": "Delete Selected",
"constructor.view_menu": "View",
"constructor.view_menu.preview": "Preview",
"constructor.view_menu.validate": "Validate Integrity",
"constructor.save_button": "💾 Save",
"constructor.load_error": "Load Error",
"constructor.load_error_body": "Failed to open constructor:\n{exc}",
"constructor.window_title": "Reference Constructor",
"constructor.unsaved_title": "Unsaved Changes",
"constructor.unsaved_body": "You have unsaved changes. Save before closing?",
"constructor.save_as_title": "Save As",
"constructor.minimize": "Minimize",
"constructor.maximize": "Maximize",
"constructor.close": "Close",
"constructor.dialogs.open_file": "Open File",
"constructor.dialogs.open_files": "Open Files",
"constructor.dialogs.save_file": "Save File",
"constructor.dialogs.select_folder": "Select Folder",
"constructor.dialogs.all_files": "All files (*)"
```

- [ ] **Step 3: Add constructor editor keys**

Append to `ru.json`:

```json
"constructor.topic.header": "Анатомия",
"constructor.topic.add": "Добавить тему",
"constructor.topic.delete": "Удалить тему",
"constructor.topic.duplicate": "Дублировать",
"constructor.topic.new": "Новая тема {idx}",
"constructor.topic.delete_confirm": "Удалить тему «{name}»?",
"constructor.topic.copy_suffix": " (копия)",
"constructor.image.header": "Изображения",
"constructor.image.drop_hint": "Перетащите изображения сюда",
"constructor.image.file_not_found": "Файл не найден: {name}",
"constructor.image.load_failed": "Не удалось загрузить: {name}",
"constructor.image.invalid_svg": "Невалидный SVG: {name}",
"constructor.image.svg_error": "Ошибка SVG: {name}",
"constructor.image.add": "Добавить изображение...",
"constructor.image.delete": "Удалить выбранное",
"constructor.image.open_external": "Открыть во внешнем просмотрщике",
"constructor.image.add_dialog": "Добавить изображения",
"constructor.image.image_filter": "Изображения (*.png *.jpg *.jpeg *.gif *.bmp *.svg)",
"constructor.image.delete_title": "Удалить изображение",
"constructor.image.delete_confirm": "Удалить «{name}» из справочника?",
"constructor.param.header": "Параметры",
"constructor.param.font_label": "Шрифт:",
"constructor.param.size_label": "Размер:",
"constructor.param.add_param": "+ Параметр",
"constructor.param.add_column": "+ Столбец",
"constructor.param.delete_column": "Удалить столбец",
"constructor.param.show_label": "Показать:",
"constructor.param.column_indicator_empty": "Столбец: — | Перетащите заголовок для перемещения",
"constructor.param.column_indicator_active": "Столбец: {name} (номер {num}) | Перетащите заголовок для перемещения",
"constructor.param.new_param": "Новый параметр",
"constructor.param.new_column_title": "Новый столбец",
"constructor.param.new_column_label": "Имя столбца:",
"constructor.param.delete_column_error": "Кликните на столбец для удаления",
"constructor.param.delete_column_protected": "Нельзя удалить обязательные столбцы",
"constructor.param.delete_column_confirm": "Удалить столбец «{label}»?",
"constructor.param.column_indicator_none": "Столбец: —",
"constructor.param.delete_selected_confirm": "Удалить {count} параметров?",
"constructor.param.context_add_param": "Добавить параметр",
"constructor.param.context_add_column": "Добавить столбец",
"constructor.param.context_delete_column": "Удалить столбец",
"constructor.param.context_delete_selected": "Удалить выбранные",
"constructor.param.col_name": "Название",
"constructor.param.col_unit": "Ед.",
"constructor.param.col_norm_male_low": "Норм М (от)",
"constructor.param.col_norm_male_high": "Норм М (до)",
"constructor.param.col_norm_female_low": "Норм Ж (от)",
"constructor.param.col_norm_female_high": "Норм Ж (до)",
"constructor.param.col_desc": "Описание",
"constructor.param.col_source": "Источник",
"constructor.param.col_desc_full": "Описание патологии",
"constructor.pathology.header": "Патологии",
"constructor.pathology.add": "Добавить патологию",
"constructor.pathology.delete": "Удалить выбранные",
"constructor.pathology.duplicate": "Дублировать",
"constructor.pathology.new": "Новая патология {idx}",
"constructor.pathology.delete_title": "Удалить патологии",
"constructor.pathology.delete_confirm": "Удалить {count} патологий?\n{names}",
"constructor.pathology.copy_suffix": " (копия)",
"constructor.meta.sex_label": "Пол:",
"constructor.meta.sex_male": "М",
"constructor.meta.sex_female": "Ж",
"constructor.meta.sex_both": "Оба",
"constructor.meta.age_label": "Возраст:",
"constructor.meta.source_label": "Источник:",
"constructor.meta.desc_label": "Описание:",
"constructor.meta.desc_placeholder": "Описание патологии...",
"constructor.preview.title": "Preview — Справочник",
"constructor.preview.col_name": "Название",
"constructor.preview.col_unit": "Ед.",
"constructor.preview.col_norm_male": "Норм М",
"constructor.preview.col_norm_female": "Норм Ж",
"constructor.preview.col_desc": "Описание",
"constructor.preview.col_source": "Источник",
"constructor.preview.header_param": "Параметр",
"constructor.export.pdf_error": "Требуется PySide6.QtPrintSupport",
"constructor.export.col_name": "Название",
"constructor.export.col_unit": "Ед.",
"constructor.export.col_norm_male": "Норм М",
"constructor.export.col_norm_female": "Норм Ж",
"constructor.export.col_desc": "Описание",
"constructor.export.col_source": "Источник",
"constructor.export.html_title": "Справочник эхокардиографии",
"constructor.export.html_search": "Поиск...",
"constructor.export.html_not_found": "(не найден)"
```

Append to `en.json`:

```json
"constructor.topic.header": "Anatomy",
"constructor.topic.add": "Add Topic",
"constructor.topic.delete": "Delete Topic",
"constructor.topic.duplicate": "Duplicate",
"constructor.topic.new": "New Topic {idx}",
"constructor.topic.delete_confirm": "Delete topic \"{name}\"?",
"constructor.topic.copy_suffix": " (copy)",
"constructor.image.header": "Images",
"constructor.image.drop_hint": "Drop images here",
"constructor.image.file_not_found": "File not found: {name}",
"constructor.image.load_failed": "Failed to load: {name}",
"constructor.image.invalid_svg": "Invalid SVG: {name}",
"constructor.image.svg_error": "SVG error: {name}",
"constructor.image.add": "Add Image...",
"constructor.image.delete": "Delete Selected",
"constructor.image.open_external": "Open in External Viewer",
"constructor.image.add_dialog": "Add Images",
"constructor.image.image_filter": "Images (*.png *.jpg *.jpeg *.gif *.bmp *.svg)",
"constructor.image.delete_title": "Delete Image",
"constructor.image.delete_confirm": "Remove \"{name}\" from reference?",
"constructor.param.header": "Parameters",
"constructor.param.font_label": "Font:",
"constructor.param.size_label": "Size:",
"constructor.param.add_param": "+ Parameter",
"constructor.param.add_column": "+ Column",
"constructor.param.delete_column": "Delete Column",
"constructor.param.show_label": "Show:",
"constructor.param.column_indicator_empty": "Column: — | Drag header to move",
"constructor.param.column_indicator_active": "Column: {name} (#{num}) | Drag header to move",
"constructor.param.new_param": "New Parameter",
"constructor.param.new_column_title": "New Column",
"constructor.param.new_column_label": "Column name:",
"constructor.param.delete_column_error": "Click a column to delete",
"constructor.param.delete_column_protected": "Cannot delete required columns",
"constructor.param.delete_column_confirm": "Delete column \"{label}\"?",
"constructor.param.column_indicator_none": "Column: —",
"constructor.param.delete_selected_confirm": "Delete {count} parameters?",
"constructor.param.context_add_param": "Add Parameter",
"constructor.param.context_add_column": "Add Column",
"constructor.param.context_delete_column": "Delete Column",
"constructor.param.context_delete_selected": "Delete Selected",
"constructor.param.col_name": "Name",
"constructor.param.col_unit": "Unit",
"constructor.param.col_norm_male_low": "Norm M (low)",
"constructor.param.col_norm_male_high": "Norm M (high)",
"constructor.param.col_norm_female_low": "Norm F (low)",
"constructor.param.col_norm_female_high": "Norm F (high)",
"constructor.param.col_desc": "Description",
"constructor.param.col_source": "Source",
"constructor.param.col_desc_full": "Pathology Description",
"constructor.pathology.header": "Pathologies",
"constructor.pathology.add": "Add Pathology",
"constructor.pathology.delete": "Delete Selected",
"constructor.pathology.duplicate": "Duplicate",
"constructor.pathology.new": "New Pathology {idx}",
"constructor.pathology.delete_title": "Delete Pathologies",
"constructor.pathology.delete_confirm": "Delete {count} pathologies?\n{names}",
"constructor.pathology.copy_suffix": " (copy)",
"constructor.meta.sex_label": "Sex:",
"constructor.meta.sex_male": "M",
"constructor.meta.sex_female": "F",
"constructor.meta.sex_both": "Both",
"constructor.meta.age_label": "Age:",
"constructor.meta.source_label": "Source:",
"constructor.meta.desc_label": "Description:",
"constructor.meta.desc_placeholder": "Pathology description...",
"constructor.preview.title": "Preview — Reference",
"constructor.preview.col_name": "Name",
"constructor.preview.col_unit": "Unit",
"constructor.preview.col_norm_male": "Norm M",
"constructor.preview.col_norm_female": "Norm F",
"constructor.preview.col_desc": "Description",
"constructor.preview.col_source": "Source",
"constructor.preview.header_param": "Parameter",
"constructor.export.pdf_error": "PySide6.QtPrintSupport required",
"constructor.export.col_name": "Name",
"constructor.export.col_unit": "Unit",
"constructor.export.col_norm_male": "Norm M",
"constructor.export.col_norm_female": "Norm F",
"constructor.export.col_desc": "Description",
"constructor.export.col_source": "Source",
"constructor.export.html_title": "Echocardiography Reference",
"constructor.export.html_search": "Search...",
"constructor.export.html_not_found": "(not found)"
```

- [ ] **Step 4: Add presentation layer keys**

Append to `ru.json`:

```json
"mmode.vertical": "▼ Вертикаль",
"mmode.horizontal": "◄ Горизонталь",
"mmode.arbitrary": "↗ Произвольное",
"mmode.teichholz_ed": "📐 Тейхольц ED",
"mmode.teichholz_es": "📐 Тейхольц ESV",
"mmode.clear": "Очистить",
"mmode.label_hr": "ЧСС",
"mmode.teich_ed_labels.0": "МЖП",
"mmode.teich_ed_labels.1": "КДР",
"mmode.teich_ed_labels.2": "ЗСЛЖ",
"mmode.label_es": "КСР",
"styled_dialogs.open_file": "Открыть файл",
"styled_dialogs.open_files": "Открыть файлы",
"styled_dialogs.save_file": "Сохранить файл",
"styled_dialogs.select_folder": "Выберите папку",
"styled_dialogs.all_files": "Все файлы (*)",
"system_bar.load_server": "Загрузить с сервера…",
"system_bar.settings_tooltip": "Параметры измерений и отображения",
"system_bar.references_tooltip": "Справочник нормативных значений ASE",
"ase_ref.structured_tab": "Справочник",
"ase_ref.constructor_menu": "Конструктор",
"ref_topic.left_ventricle": "ЛЖ",
"ref_topic.left_atrium": "ЛП",
"ref_topic.right_ventricle": "ПЖ",
"ref_topic.right_atrium": "ПП",
"ref_topic.mitral_valve": "МК",
"ref_topic.aortic_valve": "АК",
"ref_topic.tricuspid_valve": "ТК",
"ref_topic.pulmonary_valve": "ЛК",
"ref_topic.aorta": "Аорта",
"ref_topic.prosthetic_valves": "Протезы",
"ref_topic.other": "Прочее",
"ref_topic.full_left_ventricle": "Левый\nжелудочек",
"ref_topic.full_left_atrium": "Левое\nпредсердие",
"ref_topic.full_right_ventricle": "Правый\nжелудочек",
"ref_topic.full_right_atrium": "Правое\nпредсердие",
"ref_topic.full_mitral_valve": "Митральный\nклапан",
"ref_topic.full_aortic_valve": "Аортальный\nклапан",
"ref_topic.full_tricuspid_valve": "Трикуспидальный\nклапан",
"ref_topic.full_pulmonary_valve": "Лёгочный\nклапан",
"ref_topic.full_aorta": "Аорта",
"ref_topic.full_prosthetic_valves": "Протезы\nклапанов",
"ref_topic.full_other": "Прочее",
"ref_table.header_param": "Показатель",
"ref_table.header_value": "Значение",
"ref_table.pathology_header": "Патология",
"ref_table.search_placeholder": "Поиск параметра...",
"ref_table.sex_male": "Муж",
"ref_table.sex_female": "Жен",
"ref_table.sex_label": "Пол:",
"ref_table.age_label": "Возраст:",
"ref_table.age_placeholder": "л",
"ref_table.col_param": "Параметр",
"ref_table.col_norm_male": "Норм М",
"ref_table.col_norm_female": "Норм Ж",
"ref_table.image_label": "Изображение: {path}",
"prefs.show_strain": "Показать Стрейн",
"prefs.show_diastolic": "Показать Диастолическую функцию",
"prefs.show_doppler_mk_av": "Показать Doppler МК/АК",
"prefs.show_doppler_tk_lk": "Показать Doppler ТК/ЛК",
"prefs.show_rv_s_prime": "Показать s' ПЖ",
"prefs.tab_experimental": "Экспериментальные"
```

Append to `en.json`:

```json
"mmode.vertical": "▼ Vertical",
"mmode.horizontal": "◄ Horizontal",
"mmode.arbitrary": "↗ Arbitrary",
"mmode.teichholz_ed": "📐 Teichholz ED",
"mmode.teichholz_es": "📐 Teichholz ESV",
"mmode.clear": "Clear",
"mmode.label_hr": "HR",
"mmode.teich_ed_labels.0": "IVSd",
"mmode.teich_ed_labels.1": "LVIDd",
"mmode.teich_ed_labels.2": "LVPWd",
"mmode.label_es": "LVIDs",
"styled_dialogs.open_file": "Open File",
"styled_dialogs.open_files": "Open Files",
"styled_dialogs.save_file": "Save File",
"styled_dialogs.select_folder": "Select Folder",
"styled_dialogs.all_files": "All files (*)",
"system_bar.load_server": "Load from server…",
"system_bar.settings_tooltip": "Measurement and display settings",
"system_bar.references_tooltip": "ASE reference values",
"ase_ref.structured_tab": "Reference",
"ase_ref.constructor_menu": "Constructor",
"ref_topic.left_ventricle": "LV",
"ref_topic.left_atrium": "LA",
"ref_topic.right_ventricle": "RV",
"ref_topic.right_atrium": "RA",
"ref_topic.mitral_valve": "MV",
"ref_topic.aortic_valve": "AV",
"ref_topic.tricuspid_valve": "TV",
"ref_topic.pulmonary_valve": "PV",
"ref_topic.aorta": "Aorta",
"ref_topic.prosthetic_valves": "Prosthetics",
"ref_topic.other": "Other",
"ref_topic.full_left_ventricle": "Left\nVentricle",
"ref_topic.full_left_atrium": "Left\nAtrium",
"ref_topic.full_right_ventricle": "Right\nVentricle",
"ref_topic.full_right_atrium": "Right\nAtrium",
"ref_topic.full_mitral_valve": "Mitral\nValve",
"ref_topic.full_aortic_valve": "Aortic\nValve",
"ref_topic.full_tricuspid_valve": "Tricuspid\nValve",
"ref_topic.full_pulmonary_valve": "Pulmonary\nValve",
"ref_topic.full_aorta": "Aorta",
"ref_topic.full_prosthetic_valves": "Prosthetic\nValves",
"ref_topic.full_other": "Other",
"ref_table.header_param": "Indicator",
"ref_table.header_value": "Value",
"ref_table.pathology_header": "Pathology",
"ref_table.search_placeholder": "Search parameter...",
"ref_table.sex_male": "Male",
"ref_table.sex_female": "Female",
"ref_table.sex_label": "Sex:",
"ref_table.age_label": "Age:",
"ref_table.age_placeholder": "y",
"ref_table.col_param": "Parameter",
"ref_table.col_norm_male": "Norm M",
"ref_table.col_norm_female": "Norm F",
"ref_table.image_label": "Image: {path}",
"prefs.show_strain": "Show Strain",
"prefs.show_diastolic": "Show Diastolic Function",
"prefs.show_doppler_mk_av": "Show Doppler MV/AV",
"prefs.show_doppler_tk_lk": "Show Doppler TV/PV",
"prefs.show_rv_s_prime": "Show RV s'",
"prefs.tab_experimental": "Experimental"
```

- [ ] **Step 5: Add domain layer keys**

Append to `ru.json`:

```json
"domain.lvef.check_contour": "{chamber} {view} {phase}: проверьте контур (ASE) · R — уточнить · Enter — принять",
"domain.lvef.status_empty": "{chamber} {view} {phase} · Длина: — · Объём: —",
"domain.lvef.status_partial": "{chamber} {view} {phase} · Длина: {length} · Объём: {volume}",
"domain.lvef.no_contour": "контур не построен",
"domain.lvef.mask_collapsed": "контур маски схлопнулся при построении (маска есть, но граница не извлечена — сообщите разработчику)",
"domain.lvef.no_annulus": "не найдено митральное кольцо (проверьте вид A4C и кадр ED/ES)",
"domain.lvef.lv_axis_too_short": "короткая ось ЛЖ слишком мала — выберите другой кадр",
"domain.lvef.annulus_too_small": "митральное кольцо слишком мало ({annulus_mm:.1f} мм < {min_mm} мм) — проверьте вид A4C и калибровку",
"domain.lvef.contour_too_flat": "контур слишком плоский (глубина {depth}px / кольцо {annulus}px < {ratio:.0%}) — возможно ES или не тот view",
"domain.lvef.center_outside_roi": "центр контура вне ROI — проверьте выделение сектора",
"domain.lvef.self_intersecting": "контур самопересекается — попробуйте другой кадр или перерисуйте",
"domain.rv_fac.no_area": "RV FAC {phase}: площадь —",
"domain.planimeter.area_label": "Площадь{count}",
"domain.planimeter.volume_label": "Объем{count}",
"domain.planimeter.default_area": "Площадь",
"domain.planimeter.default_volume": "Объем",
"domain.la_seg.no_contour": "контур ЛА не построен",
"domain.la_seg.no_annulus": "митральное кольцо не найдено (проверьте вид A4C ES)",
"domain.la_seg.annulus_too_small": "митральное кольцо слишком мало ({mv_span_mm:.1f} мм < {min_mm} мм) — проверьте вид A4C и калибровку",
"domain.la_seg.inverted": "геометрия ЛА инвертирована (крышка ниже митрального кольца)",
"domain.la_seg.axis_too_short": "ось ЛА слишком короткая — выберите другой кадр",
"domain.la_seg.cavity_too_small": "полость ЛА слишком мала ({pixels} px < {min_px} px) — выберите другой кадр",
"domain.la_seg.mask_irregular": "маска ЛА слишком нерегулярна для эллиптического контура (остаток {residual:.2f} > {max_residual})",
"domain.la_seg.center_outside_roi": "центр контура ЛА вне ROI — проверьте выделение сектора",
"domain.cine_diag.no_roi": "ROI не определён — эвристика панелей не сработала",
"domain.cine_diag.mask_too_small": "маска ONNX слишком мала ({pixels} px)",
"domain.cine_diag.mask_shifted": "маска смещена в правую UI-полосу — проверьте lateral trim ROI",
"domain.cine_diag.centroid_outside": "центроид маски вне B-mode ROI",
"domain.cine_diag.annulus_inverted": "инвертирован annulus/apex (annulus_y={annulus:.0f} < apex_y={apex:.0f})",
"domain.cine_diag.contour_collapsed": "контур схлопнут в линию (глубина дуги {depth:.1f} px)",
"domain.cine_diag.mask_narrow": "маска узкая ({width:.0f}px при ROI {roi:.0f}px) — проверьте sector trim",
"domain.report.no_measurements": "Нет измерений.",
"domain.report.title": "Результаты измерений",
"domain.report.doppler": "Допплер",
"domain.report.lv_simpson": "Объёмы ЛЖ (Симпсон)",
"domain.report.lv_length": "Длина ЛЖ {view}",
"domain.report.kdo_lv": "КДО ЛЖ {view}",
"domain.report.kso_lv": "КСО ЛЖ {view}",
"domain.report.lvef": "ФВ ЛЖ",
"domain.report.method": "  Метод: {method}",
"domain.report.lv_teichholz": "Объёмы ЛЖ (Teichholz)",
"domain.report.kdo": "КДО",
"domain.report.kso": "КСО",
"domain.report.fv": "ФВ",
"domain.report.la": "Левое предсердие",
"domain.report.s_la": "S ЛП",
"domain.report.ra": "Правое предсердие",
"domain.report.s_ra": "S ПП",
"domain.report.rv": "Правый желудочек",
"domain.report.rv_volume": "Объём ПЖ",
"domain.report.lvm": "Масса ЛЖ",
"domain.report.rwt": "ОТС",
"domain.report.diastolic": "Диастолическая функция",
"domain.report.planimetry": "Планиметрия",
"domain.report.linear": "Линейные измерения",
"domain.report.indexed": "Индексированные (BSA)",
"domain.report.height_weight": "  Рост: {height:.0f} cm, Вес: {weight:.0f} kg",
"domain.report.kdo_idx": "КДО idx (Simpson)",
"domain.report.kso_idx": "КСО idx (Simpson)",
"domain.report.no_pixel_spacing": "  (нет PixelSpacing — длина в px, объём в px³)"
```

Append to `en.json`:

```json
"domain.lvef.check_contour": "{chamber} {view} {phase}: review contour (ASE) · R — refine · Enter — accept",
"domain.lvef.status_empty": "{chamber} {view} {phase} · Length: — · Volume: —",
"domain.lvef.status_partial": "{chamber} {view} {phase} · Length: {length} · Volume: {volume}",
"domain.lvef.no_contour": "contour not built",
"domain.lvef.mask_collapsed": "contour mask collapsed during construction (mask exists but boundary not extracted — report to developer)",
"domain.lvef.no_annulus": "mitral annulus not found (check A4C view and ED/ES frame)",
"domain.lvef.lv_axis_too_short": "LV short axis too small — select another frame",
"domain.lvef.annulus_too_small": "mitral annulus too small ({annulus_mm:.1f} mm < {min_mm} mm) — check A4C view and calibration",
"domain.lvef.contour_too_flat": "contour too flat (arc depth {depth}px / annulus {annulus}px < {ratio:.0%}) — possibly ES or wrong view",
"domain.lvef.center_outside_roi": "contour center outside ROI — check sector selection",
"domain.lvef.self_intersecting": "contour self-intersects — try another frame or redraw",
"domain.rv_fac.no_area": "RV FAC {phase}: area —",
"domain.planimeter.area_label": "Area{count}",
"domain.planimeter.volume_label": "Volume{count}",
"domain.planimeter.default_area": "Area",
"domain.planimeter.default_volume": "Volume",
"domain.la_seg.no_contour": "LA contour not built",
"domain.la_seg.no_annulus": "mitral annulus not found (check A4C ES view)",
"domain.la_seg.annulus_too_small": "mitral annulus too small ({mv_span_mm:.1f} mm < {min_mm} mm) — check A4C view and calibration",
"domain.la_seg.inverted": "LA geometry inverted (lid below mitral annulus)",
"domain.la_seg.axis_too_short": "LA axis too short — select another frame",
"domain.la_seg.cavity_too_small": "LA cavity too small ({pixels} px < {min_px} px) — select another frame",
"domain.la_seg.mask_irregular": "LA mask too irregular for elliptical contour (residual {residual:.2f} > {max_residual})",
"domain.la_seg.center_outside_roi": "LA contour center outside ROI — check sector selection",
"domain.cine_diag.no_roi": "ROI not defined — panel heuristic failed",
"domain.cine_diag.mask_too_small": "ONNX mask too small ({pixels} px)",
"domain.cine_diag.mask_shifted": "mask shifted to right UI strip — check lateral trim ROI",
"domain.cine_diag.centroid_outside": "mask centroid outside B-mode ROI",
"domain.cine_diag.annulus_inverted": "annulus/apex inverted (annulus_y={annulus:.0f} < apex_y={apex:.0f})",
"domain.cine_diag.contour_collapsed": "contour collapsed to line (arc depth {depth:.1f} px)",
"domain.cine_diag.mask_narrow": "mask too narrow ({width:.0f}px vs ROI {roi:.0f}px) — check sector trim",
"domain.report.no_measurements": "No measurements.",
"domain.report.title": "Measurement Results",
"domain.report.doppler": "Doppler",
"domain.report.lv_simpson": "LV volumes (Simpson)",
"domain.report.lv_length": "LV length {view}",
"domain.report.kdo_lv": "LV EDV {view}",
"domain.report.kso_lv": "LV ESV {view}",
"domain.report.lvef": "LVEF",
"domain.report.method": "  Method: {method}",
"domain.report.lv_teichholz": "LV volumes (Teichholz)",
"domain.report.kdo": "EDV",
"domain.report.kso": "ESV",
"domain.report.fv": "EF",
"domain.report.la": "Left Atrium",
"domain.report.s_la": "S LA",
"domain.report.ra": "Right Atrium",
"domain.report.s_ra": "S RA",
"domain.report.rv": "Right Ventricle",
"domain.report.rv_volume": "RV Volume",
"domain.report.lvm": "LV Mass",
"domain.report.rwt": "RWT",
"domain.report.diastolic": "Diastolic Function",
"domain.report.planimetry": "Planimetry",
"domain.report.linear": "Linear Measurements",
"domain.report.indexed": "Indexed (BSA)",
"domain.report.height_weight": "  Height: {height:.0f} cm, Weight: {weight:.0f} kg",
"domain.report.kdo_idx": "iEDV (Simpson)",
"domain.report.kso_idx": "iESV (Simpson)",
"domain.report.no_pixel_spacing": "  (no PixelSpacing — length in px, volume in px³)"
```

- [ ] **Step 6: Add infrastructure and application keys**

Append to `ru.json`:

```json
"pdf.report_title": "Результаты измерений",
"orthanc.downloaded": "Загружено {done}/{total}",
"orthanc.downloaded_with_errors": "Загружено {saved}/{total}. Ошибки: {detail}",
"app.speckle_reload_cine": "Speckle tracking: загрузите полную cine-последовательность"
```

Append to `en.json`:

```json
"pdf.report_title": "Measurement Results",
"orthanc.downloaded": "Downloaded {done}/{total}",
"orthanc.downloaded_with_errors": "Downloaded {saved}/{total}. Errors: {detail}",
"app.speckle_reload_cine": "Speckle tracking: reload full cine sequence"
```

- [ ] **Step 7: Verify locale files are valid JSON**

Run:
```bash
python -c "import json; json.load(open('src/echo_personal_tool/infrastructure/locales/ru.json')); json.load(open('src/echo_personal_tool/infrastructure/locales/en.json')); print('OK')"
```
Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add src/echo_personal_tool/infrastructure/locales/ru.json src/echo_personal_tool/infrastructure/locales/en.json
git commit -m "i18n: add all missing locale keys for full English translation"
```

---

## Task 2: Fix Strain Window and Strain Curves View

**Files:**
- Modify: `src/echo_personal_tool/ui/strain_window.py`
- Modify: `src/echo_personal_tool/ui/strain_curves_view.py`

**Interfaces:**
- Consumes: All `strain.*` locale keys from Task 1
- Produces: Both files use `tr()` for all user-visible strings

- [ ] **Step 1: Fix strain_curves_view.py**

Replace hardcoded segment names and axis label. Add `from echo_personal_tool.infrastructure.i18n import tr` at top.

Replace the `SEGMENT_NAMES_RU` dict usage with locale-aware lookup, and replace `self._plot.setLabel("bottom", "Время(ms)")` with `tr("strain.time_axis")`.

- [ ] **Step 2: Fix strain_window.py**

Replace all hardcoded strings: group boxes, radio buttons, push buttons, QFileDialog titles, segment name dicts, table headers, units. Add `from echo_personal_tool.infrastructure.i18n import tr` at top.

Key replacements:
- `QGroupBox("Вид")` → `QGroupBox(tr("strain.view_mode"))`
- `QRadioButton("Cine + контур")` → `QRadioButton(tr("strain.mode_cine_contour"))`
- `QPushButton("Закрыть")` → `QPushButton(tr("strain.btn_close"))`
- etc.

- [ ] **Step 3: Verify no hardcoded Russian remains**

Run:
```bash
grep -n '[а-яА-ЯёЁ]' src/echo_personal_tool/ui/strain_window.py src/echo_personal_tool/ui/strain_curves_view.py
```
Expected: only comments, not string literals

- [ ] **Step 4: Commit**

```bash
git add src/echo_personal_tool/ui/strain_window.py src/echo_personal_tool/ui/strain_curves_view.py
git commit -m "i18n: translate strain window and curves to English"
```

---

## Task 3: Fix Constructor Module (widget, dialog, editors, exporters, preview)

**Files:**
- Modify: `src/echo_personal_tool/constructor/constructor_widget.py`
- Modify: `src/echo_personal_tool/constructor/constructor_dialog.py`
- Modify: `src/echo_personal_tool/constructor/dialogs.py`
- Modify: `src/echo_personal_tool/constructor/editors/topic_editor.py`
- Modify: `src/echo_personal_tool/constructor/editors/image_editor.py`
- Modify: `src/echo_personal_tool/constructor/editors/parameter_table_editor.py`
- Modify: `src/echo_personal_tool/constructor/editors/pathology_editor.py`
- Modify: `src/echo_personal_tool/constructor/editors/metadata_editor.py`
- Modify: `src/echo_personal_tool/constructor/preview/reference_preview.py`
- Modify: `src/echo_personal_tool/constructor/exporters/pdf_exporter.py`
- Modify: `src/echo_personal_tool/constructor/exporters/html_exporter.py`

**Interfaces:**
- Consumes: All `constructor.*` locale keys from Task 1
- Produces: All constructor files use `tr()` for all user-visible strings

- [ ] **Step 1: Fix constructor_widget.py**

Replace: `setPlaceholderText`, `QMessageBox` titles/bodies, `styled_open_file`/`styled_save_file` titles. Add `tr` import.

- [ ] **Step 2: Fix constructor_dialog.py**

Replace: `setWindowTitle`, menu items (`"Файл"`, `"Правка"`, `"Вид"`), action labels, save button text, window title buttons, confirm dialog. Add `tr` import.

- [ ] **Step 3: Fix dialogs.py**

Replace default parameter values: `title="Открыть файл"` → `title=tr("constructor.dialogs.open_file")`, etc.

- [ ] **Step 4: Fix topic_editor.py**

Replace: header label, context menu actions, new topic name, delete confirm. Add `tr` import.

- [ ] **Step 5: Fix image_editor.py**

Replace: header label, drop hint, error messages, context menu, file dialog, delete confirm. Add `tr` import.

- [ ] **Step 6: Fix parameter_table_editor.py**

Replace: header label, font/size labels, button texts, column indicator text, column header dicts, dialog titles/messages. Add `tr` import.

- [ ] **Step 7: Fix pathology_editor.py**

Replace: header label, context menu, new pathology name, delete confirm. Add `tr` import.

- [ ] **Step 8: Fix metadata_editor.py**

Replace: sex labels, age/source/description labels, placeholder. Add `tr` import.

- [ ] **Step 9: Fix reference_preview.py**

Replace: window title, HTML table headers. Add `tr` import.

- [ ] **Step 10: Fix pdf_exporter.py**

Replace: import error message, HTML table headers. Add `tr` import.

- [ ] **Step 11: Fix html_exporter.py**

Replace: `<title>`, `<h1>`, search placeholder, table headers, missing image text. Add `tr` import.

- [ ] **Step 12: Verify no hardcoded Russian remains**

Run:
```bash
grep -rn '[а-яА-ЯёЁ]' src/echo_personal_tool/constructor/ --include="*.py" | grep -v '#' | grep -v '"""' | grep -v "docstring"
```
Expected: no string literals with Russian (only comments/docstrings)

- [ ] **Step 13: Commit**

```bash
git add src/echo_personal_tool/constructor/
git commit -m "i18n: translate constructor module to English"
```

---

## Task 4: Fix Presentation Layer (mmode, dialogs, system_bar, ase_ref, structured_ref, prefs)

**Files:**
- Modify: `src/echo_personal_tool/presentation/mmode_widget.py`
- Modify: `src/areatu/ECHO2026/src/echo_personal_tool/presentation/styled_dialogs.py`
- Modify: `src/echo_personal_tool/presentation/main_window.py` (lines 926-997)
- Modify: `src/echo_personal_tool/presentation/system_bar.py`
- Modify: `src/echo_personal_tool/presentation/mmode_measurement.py`
- Modify: `src/echo_personal_tool/presentation/ase_reference_dialog.py`
- Modify: `src/echo_personal_tool/presentation/structured_reference_widget.py`
- Modify: `src/echo_personal_tool/presentation/user_preferences_dialog.py`

**Interfaces:**
- Consumes: All `mmode.*`, `styled_dialogs.*`, `system_bar.*`, `ase_ref.*`, `ref_*`, `prefs.*` locale keys from Task 1
- Produces: All presentation files use `tr()` for all user-visible strings

- [ ] **Step 1: Fix mmode_widget.py**

Replace: button labels (`"▼ Вертикаль"`, `"📐 Тейхольц ED"`, `"Очистить"`), measurement mode dict keys. Add `tr` import if not present.

- [ ] **Step 2: Fix styled_dialogs.py**

Replace default parameter values with `tr()` calls. Since defaults are evaluated at import time, use a helper pattern:
```python
def _default_title():
    return tr("styled_dialogs.open_file")
```
Or replace at call sites.

- [ ] **Step 3: Fix main_window.py lines 926-997**

Replace: Teichholz status strings with `tr()` calls. These are f-strings with medical abbreviations — use `tr()` with `{variable}` placeholders where appropriate.

- [ ] **Step 4: Fix system_bar.py**

Replace: `QPushButton("Загрузить с сервера…")`, `setToolTip(...)` calls. Add `tr` import if not present.

- [ ] **Step 5: Fix mmode_measurement.py**

Replace: `_TEICHHOLZ_ED_LABELS` list, `label = "КСР"`, `"ЧСС {hr:.0f}"`. Add `tr` import.

- [ ] **Step 6: Fix ase_reference_dialog.py**

Replace: `QPushButton("Справочник")`, `file_menu.addAction("Конструктор", ...)`. Add `tr` import if not present.

- [ ] **Step 7: Fix structured_reference_widget.py**

Replace: `_TOPIC_LABELS` dict, `_TOPIC_FULL_NAMES` dict, table headers, search placeholder, sex/age labels, placeholder text, image label. Add `tr` import if not present.

- [ ] **Step 8: Fix user_preferences_dialog.py**

Replace: `addRow(...)` label strings, `addTab(...)` tab name. Add `tr` import if not present.

- [ ] **Step 9: Verify no hardcoded Russian remains**

Run:
```bash
grep -rn '[а-яА-ЯёЁ]' src/echo_personal_tool/presentation/ --include="*.py" | grep -v '#' | grep -v '"""' | grep -v "docstring" | grep -v "comment"
```

- [ ] **Step 10: Commit**

```bash
git add src/echo_personal_tool/presentation/
git commit -m "i18n: translate presentation layer to English"
```

---

## Task 5: Fix Domain Layer and Infrastructure/Application

**Files:**
- Modify: `src/echo_personal_tool/domain/calculations/lvef_simpson.py`
- Modify: `src/echo_personal_tool/domain/calculations/rv_fac.py`
- Modify: `src/echo_personal_tool/domain/calculations/planimeter.py`
- Modify: `src/echo_personal_tool/domain/services/la_segmentation_service.py`
- Modify: `src/echo_personal_tool/domain/services/cine_segment_diagnostics.py`
- Modify: `src/echo_personal_tool/domain/services/measurement_report_formatter.py`
- Modify: `src/echo_personal_tool/infrastructure/measurement_report_pdf.py`
- Modify: `src/echo_personal_tool/application/workers/orthanc_download_worker.py`
- Modify: `src/echo_personal_tool/application/app_controller.py`

**Interfaces:**
- Consumes: All `domain.*`, `pdf.*`, `orthanc.*`, `app.speckle_reload_cine` locale keys from Task 1
- Produces: Domain and infrastructure files use `tr()` for all user-visible strings

- [ ] **Step 1: Fix lvef_simpson.py**

Replace all validation/status messages with `tr()` calls. These are error strings returned to the UI. Add `tr` import.

- [ ] **Step 2: Fix rv_fac.py**

Replace: `"площадь —"` status strings. Add `tr` import.

- [ ] **Step 3: Fix planimeter.py**

Replace: `"Площадь"`, `"Объем"` default labels and `f"Площадь{count}"` / `f"Объем{count}"` patterns. Add `tr` import.

- [ ] **Step 4: Fix la_segmentation_service.py**

Replace all LA validation error messages. Add `tr` import.

- [ ] **Step 5: Fix cine_segment_diagnostics.py**

Replace all diagnostic issue strings. Add `tr` import.

- [ ] **Step 6: Fix measurement_report_formatter.py**

Replace all section headers and label strings. These are report section titles — use `tr()` with format variables. Add `tr` import.

- [ ] **Step 7: Fix measurement_report_pdf.py**

Replace: `pdf.setTitle("Результаты измерений")`. Add `tr` import.

- [ ] **Step 8: Fix orthanc_download_worker.py**

Replace: `f"Загружено {done}/{total}"` status messages. Add `tr` import if not present.

- [ ] **Step 9: Fix app_controller.py**

Replace: `"Speckle tracking: загрузите полную cine-последовательность"`. Add `tr` import if not present.

- [ ] **Step 10: Verify no hardcoded Russian remains**

Run:
```bash
grep -rn '[а-яА-ЯёЁ]' src/echo_personal_tool/domain/ src/echo_personal_tool/infrastructure/measurement_report_pdf.py src/echo_personal_tool/application/ --include="*.py" | grep -v '#' | grep -v '"""' | grep -v "docstring" | grep -v "comment"
```

- [ ] **Step 11: Commit**

```bash
git add src/echo_personal_tool/domain/ src/echo_personal_tool/infrastructure/measurement_report_pdf.py src/echo_personal_tool/application/
git commit -m "i18n: translate domain layer and infrastructure to English"
```

---

## Task 6: Final Verification

- [ ] **Step 1: Run full Russian text scan**

```bash
grep -rn '[а-яА-ЯёЁ]' src/echo_personal_tool/ --include="*.py" | grep -v '#' | grep -v '"""' | grep -v "docstring" | grep -v "__pycache__" | head -50
```
Expected: no string literals with Russian (only comments, docstrings, variable names like `SEGMENT_NAMES_RU` which are internal)

- [ ] **Step 2: Run type checker**

```bash
uv run mypy src/echo_personal_tool/ --ignore-missing-imports
```

- [ ] **Step 3: Run linter**

```bash
uv run ruff check src/echo_personal_tool/
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/ -q --tb=short
```

- [ ] **Step 5: Update russian_nope.md**

Mark all items as resolved or note any remaining items.

- [ ] **Step 6: Commit**

```bash
git add russian_nope.md
git commit -m "docs: mark i18n issues as resolved in russian_nope.md"
```
