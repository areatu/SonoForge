# QH-1c (#176): explicit local-media remap и fault evidence

Дата: 2026-10-16. Продолжение среза от 2026-10-14, не закрытие всего WP4/G1.

## Перемещённые локальные источники

- Только явный import → preview → подтверждение полной замены. Автоматическое
  восстановление и DICOM identity не меняются. Исходный record не удаляется.
- Между `local:` studies допускается только полное однозначное сопоставление:
  полный SHA-256 исходных байтов + decoded frames + spacing. В текущей схеме v4
  нет отдельных rows/columns/timing: hash связывает в том числе закодированные
  геометрию и timing, но не является отдельной проверкой версии декодера.
- Один hash в нескольких исходных или подходящих открытых источниках — отказ,
  не выбор первого. UI выбора дубликата нет. Пустой экспорт нельзя переносить
  между identities: нет содержимого, доказывающего принадлежность.
- Все per-instance записи (контуры, линейные, сосудистые, Doppler, калибровки,
  ROI, Simpson area) и структурированные ссылки provenance перепривязываются.
  Opaque measurement/result IDs, inputs/revisions, численные значения и QC не
  выдумываются заново. Неизвестная provenance dependency блокирует перенос.
- Источники повторно хешируются на preview и на Replace; digest привязывает
  подтверждение как к байтам экспорта, так и к проверенному целевому набору.
  Preview содержит counts/digests, не пути, имена или UID.
- Дополнительные live sources допустимы, но их измерения не объединяются с
  импортом. Количество показано до подтверждения, как и число remapped sources.

Evidence: `test_measurement_remap.py` (14 logic), новые cases в
`test_measurement_persistence_disk.py` (реальные synthetic PNG, move + rename,
preview без изменений, подтверждение, restart, изменённые bytes, дубликаты),
`test_measurement_storage_dialog.py` (сообщение о переносе, default No).
