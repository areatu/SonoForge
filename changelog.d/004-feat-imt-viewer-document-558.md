- `feat(imt)`: #558 — редактируемый research IMT overlay и документ v7.

- Меню приложения открывает немодальный редактор двух границ LI/MA прямо в
  основном viewer. Явные ROI, hints и physical/QC policy без clinical defaults;
  перетаскивание вершин пересчитывает evidence/geometry/QC и снимает acceptance.
- Типизированные IMT-записи сохраняются штатным dirty/autosave pipeline отдельно
  от линейных измерений: source/frame/calibration, обе границы, policy,
  mean/max/population SD, distances/indices, coverage inputs, revision/confirmation.
- Storage v7/schema: bounded nested codec, проверка согласованности геометрии и
  статистики, source membership/identity; старые документы читаются без IMT.
  Missing-source записи сохраняются, cross-identity IMT import отклоняется.
- Reload не получает live review lease: нужны явный пересчёт на текущем raw
  кадре и новое подтверждение. Source/frame/calibration change и read-only pane
  блокируют editing/confirmation/save. Автоматических PDF/диагнозов нет.
- Проверки: synthetic core, document/review/Qt overlay tests, mypy/Ruff и
  architecture/size/debt ratchets. Qt запуск со stub system libraries не заменяет
  нативную GUI-приёмку и независимую клиническую валидацию.
