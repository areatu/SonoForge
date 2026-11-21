- `feat(view-recognition)`: #639 шаг 4 — UI-хук авто-распознавания вида клипа и схема манифеста датасета.
  - Манифест датасета/манифеста спроектирован так, чтобы обучение (шаг 2) встало без переделок:
    `ViewRecognitionManifest` v2 с блоком `metadata` (ProtocolName, vendor, view-tag, note) и
    консолидацией меток через `canonicalize_view` — единая нормализация мерков-терминов
    (ProtocolName / view-tag), на которую завязан и загрузчик корпуса шага 3. v1 без
    `schema_version`/`class_names` читается с дефолтами.
  - `domain/services/view_recognition_workflow.py`: suggest / override / restore — MANUAL-решение
    по серии сохраняется и восстанавливается (классификатор не повторяется), AUTO-решения
    пересобираются; порог уверенности `threshold` параметризуется.
  - `infrastructure/view_decision_store.py`: `JsonViewDecisionStore` (по одному JSON на исследование,
    защита от симлинков, деградация на сломанный файл), `domain/ports.py`: порт
    `IViewDecisionStore`.
  - UI: бейдж вида + уверенности в системной панели (`ViewBadgeWidget`), диалог ручного выбора вида
    (`ViewOverrideDialog`), хук загрузки серии в `AppController` — на первый декодированный кадр 2D-cine
    серии запускается `ViewRecognitionWorker` на пуле потоков; уверенное предложение показывает бейдж,
    ненадежное — открывает диалог override. Выбор сохраняется через workflow и переживает перезагрузку.
  - Локально: 492 pure-core tests (включая 47 новых по schema / workflow / store) + 12 GUI-тестов;
    ruff / mypy / format чистые. Не классификатор: ONNX-адаптер (шаг 2), bench и coverage-гейты (шаг 5) остаются.
