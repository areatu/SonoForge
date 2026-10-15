# QH-4a ER-07 / QH-1d RAP — первый срез

Дата: 2026-10-15. Связанные issues: #186, #177. Не закрывает весь G1/G4.

## Изменения

- Оба measurement PDF exporters пишут во временный файл в каталоге назначения и публикуют его через os.replace только после успешного render. При font/render/replace failure прежний PDF сохраняется, временный файл удаляется (best effort).
- Вся export boundary, включая font lookup, mkdir и render, возвращает PdfExportError со стабильным кодом pdf_export_failed. Raw exception message не переносится в публичное сообщение; traceback chaining подавлен. Это не глобальная очистка crash dumps (ER-10/11 остаются открытыми).
- ReportDialog показывает локализованное безопасное сообщение вместо str(exc). В ветке ошибки по-прежнему не открывает PDF.
- Regression проверяет восстановленный ручной RAP=8 mmHg: три пересчёта TR Vmax меняют PASP, но сохраняют RAP и manual provenance. Clear удаляет override. Это проверка store/resolver/engine, не доказательство restart через disk/UI.

## Evidence и ограничения

- Ruff check / format для изменённых Python-файлов.
- 35 pure-Python tests passed: test_measurement_report_pdf.py и test_calculator_inputs.py, с PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, PYTHONPATH=src, --noconftest. Это намеренно изолированный запуск без общих Qt fixtures, а не штатный unit/GUI suite. PDF включает реальный reportlab render.
- Штатный pytest заблокирован отсутствующей libGL.so.1 при загрузке PySide6.QtGui. Изменённый GUI sentinel test ещё требует CI/native run.
- Directory fsync / crash durability PDF не заявлены. Cleanup временного файла при отказе unlink — best effort.
- #175: оставшиеся Simpson/Doppler/derived freshness и общая проекция не изменены.
- #176: hash-remap и native disk-full/directory-fsync harness не изменены.
- #177: restart/disk/UI evidence для RAP ещё требуется; issue не закрыта.
- #186: ER-08..12 остаются открытыми; issue не закрыта.
