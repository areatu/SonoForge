- `docs(reviews)`: #160 — чеклист сверен с error-register и текущим кодом. Строки ER-03…ER-12 подтверждены
  кодом и проходящими тестами (ER-03: legacy-путь `_summarize_entry`/`list_record_summaries` удалён, остался
  один `list_saved_records` → `saved_records.read_saved_records`; ER-07: `presentation/report_dialog.py` больше
  нет — экспорт идёт worker → `application/report_export.py` → `infrastructure/measurement_report_pdf.py`).
  Из «remaining packages» закрыты QH-1b.2 (#175), QH-1d, QH-2b (#183), QH-4b (#187), QH-5a (#188, с честно
  объявленными пробелами в `package-matrix.yml`); открытыми остались только пункты владельца и внешние
  блокировки (#176, #179, #181, #189, #418, #421) и остаток QH-3 в #420. Локально: 466 + 5 тестов зелёные.
  Доказательства — `docs/reviews/2026-11-06-160-error-register-reconciliation-ru.md`.
