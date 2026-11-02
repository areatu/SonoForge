# QH-1c / QH-1d: persistence safety slices

> **Снимок на 2026-10-14.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

**Дата:** 2026-10-14  
**Scope:** QH-1c (fault matrix, barriers delete/reset/import, import preview) и QH-1d
(ручные calculator inputs). Это не закрытие всего WP4/G1 и не clinical acceptance.

## Что реализовано

### QH-1c — операции и import

- `MeasurementPersistence.barrier()` ведёт per-study generation. Подтверждение старого
  save не может повторно поставить в очередь snapshot, который был заменён через reset,
  delete или import. Барьер выполняется до reset в `AppController`, до delete/delete-all
  и до replace-import.
- Delete failures больше не выдают silent success: delete-one снимает временное suppression
  и возвращает текущую RAM-проекцию в retry; delete-all возвращает прежнюю policy и dirty
  snapshots. Успешный delete-all по-прежнему выключает autosave, чтобы RAM не воскресил
  удалённые записи.
- Новый read-only `ImportPreview`: до изменения RAM/disk проверяет формат, study identity,
  source descriptors и показывает только allowlisted категории/counts (без UID/path/labels).
  Несовместимые/недоступные source блокируют Replace.
- Replace является full-record replacement, включая явный пустой record: merge с текущим
  RAM или старым JSON не выполняется. SHA-256 checked bytes включён в preview; если export
  подменён между preview и подтверждением, import возвращает `conflict`.
- Дополнен fault-matrix evidence: write admission/quota, permission/open, replace, file
  fsync и revision conflict. Failed write держит RAM/Retry contract; old committed file
  доказуемо сохраняется для failure до replace.

### QH-1d — ручные inputs

- Добавлен wire **v4** (`measurement-storage-v4.schema.json`) и явный disk allowlist
  `manual_calculator_inputs`. Каждый DTO содержит `input_id`, canonical numeric `value`,
  `origin=manual` и per-input `revision`.
- Codec проверяет registry allowlist, editor bounds, finite number, unique IDs, fixed origin
  и revision. В record не записываются текст виджета, display-cache, SOP/frame или
  выдуманная measurement reference.
- Legacy v1/v2/v3 records мигрируют с пустым списком: ручный override не угадывается.
  `MeasurementPersistence.restored` гидратирует `CalculatorInputStore` до recompute;
  калькулятор показывает `manual`, а measured/derived candidate остаётся его fallback.
- Clear снимает DTO и возвращает resolver к candidate. Reset создаёт authoritative empty
  manual list и одновременно ставит persistence barrier. Full-record import заменяет list.
  Manual-only calculator state считается live measurement для tab lifecycle и как
  privacy-minimised count в saved-record projection.

## QH-4a в этом срезе

- Storage callbacks и preview пропускают storage code через `safe_failure_code`; произвольный
  `exc.code` не попадёт в status/log как UID/path/payload fragment.
- Legacy listing теперь читает bounded payload (`MAX_DOCUMENT_BYTES + 1`), а source I/O
  (`io`) отделён от checked descriptor mismatch (`source`) на load boundary.
- `close()` не сообщает успех при failed repository cleanup.

Это уменьшает ER-03/04/05/06 scope, но не закрывает весь QH-4a: producer allowlist/raw
crash-log boundary, полный lifecycle deleted-receiver evidence и hash-remap остаются OPEN.

## Evidence

- `tests/unit/test_measurement_repository.py`
  - `test_failed_file_fsync_leaves_last_committed_record`;
  - replace/permission/quota/conflict tests;
  - v4 schema, allowlist and v3 migration tests.
- `tests/unit/test_measurement_persistence_disk.py`
  - preview → full replacement/manual provenance;
  - incompatible source no-change;
  - digest change → conflict;
  - reset barrier against late pre-reset save callback.
- `tests/unit/test_measurement_storage_dialog.py` — incompatible preview does not offer
  Replace; compatible preview is passed to full import.
- `tests/unit/test_calculator_inputs.py` — restore before resolver and legacy-empty clear.

Локально выполнены `ruff check`, `ruff format --check`, `compileall`, JSON locale parity и
JSON-schema validation v1–v4. Полный Qt pytest run в текущем agent container заблокирован
отсутствующей системной библиотекой `libGL.so.1` при импорте PySide6; это ограничение
среды проверки, не PASS-утверждение для GUI tests.

## Явно оставлено отдельными slices

- **Hash-remap moved non-DICOM**: не реализован здесь. Существующая identity/source
  проверка importer не ослаблялась; auto-remap по имени файла не добавлялся.
- Полная fault matrix directory fsync-after-replace, disk-full native harness и multi-process
  timing остаются отдельным platform evidence.
- Нет persisted calculator *results* и нет clinical declaration: этот slice сохраняет только
  checked primary manual input/provenance, затем calculator пересчитывается.
