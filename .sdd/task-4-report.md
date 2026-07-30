## Task 4 Report: Presentation Layer i18n

**Status:** DONE
**Commit:** 7b7ed6c

### Changes Made

1. **mmode_widget.py** — Replaced 7 Russian strings with `tr()` calls:
   - Button labels (vertical, horizontal, arbitrary, Teichholz ED/ESV, clear)
   - Dict keys updated to match translated labels

2. **styled_dialogs.py** — Added `tr` import and replaced 5 default parameter strings:
   - Open file, open files, save file, select folder, all files filter

3. **main_window.py** (lines ~926-997) — Replaced Teichholz status strings:
   - ED status: МЖП, КДР, ЗСЛЖ, КДО, ОТС, ММЛЖ labels
   - ESV status: Full set with КСР, КСО, ФВ, ИММЛЖ
   - Units: мл→ml, г→g

4. **system_bar.py** — Replaced 3 strings:
   - "Загрузить с сервера…" button text
   - Settings tooltip
   - References tooltip

5. **mmode_measurement.py** — Added `tr` import, replaced 3 strings:
   - _TEICHHOLZ_ED_LABELS dict values
   - КСР label
   - ЧСС (heart rate) prefix

6. **ase_reference_dialog.py** — Replaced 2 strings:
   - "Справочник" tab button
   - "Конструктор" menu action

7. **structured_reference_widget.py** — Replaced 14+ strings:
   - _TOPIC_LABELS dict (11 values)
   - _TOPIC_FULL_NAMES dict (11 values)
   - Table headers (Показатель, Значение, Норм М/Ж, Параметр)
   - UI labels (Патология, Поиск, Пол, Возраст, Муж/Жен, л)
   - Image label with path interpolation

8. **user_preferences_dialog.py** — Replaced 6 strings:
   - Experimental tab: Показать Стрейн, Диастолическую функцию, Doppler МК/АК, ТК/ЛК, s' ПЖ
   - Tab title: Экспериментальные

### Verification
- Grep for Cyrillic characters found only in docstrings/comments (3 occurrences in structured_reference_widget.py)
- No user-facing Russian strings remain
