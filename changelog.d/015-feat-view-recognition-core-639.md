- `feat(view-recognition)`: #639 шаг 3 / PR-A — доменный каркас авто-распознавания вида клипа без Qt и IO.
  - `domain/models/view_recognition.py`: канонические ID видов (`A4C/A2C/A3C/PLAX/SAX/PSAX/TEE`),
    `RecognizedView` (view + confidence, `is_confident` по порогу 0.6), `ViewRecognitionSample` /
    `ViewRecognitionManifest` (round-trip JSON), `clip_label_index`, `as_clip_array`,
    `view_category` (apical / parasternal_long / parasternal_short / tee / unknown).
  - `domain/ports.py`: порт `IViewRecognizer.recognize(frames) -> RecognizedView` — единственный шов,
    по которому домен использует классификатор; прототип ONNX-адаптера появится в шаге 2.
  - `domain/services/view_recognition.py`: `ViewRecognitionService` — тонкая оркестрация порта с
    `recognize` / `recognize_clip` / `describe` (UI-ready summary для шага 4).
  - `infrastructure/view_recognition_dataset.py`: загрузчик корпуса по манифесту — `normalize_clip`
    (float32 [0,1]), `ViewRecognitionDataset` (split-фильтр, `(clip, label)` индексация),
    `load_manifest` (JSON), `build_dicom_clip_provider` (ClipProvider по `IDicomReader`,
    n_frames клипа).
  - 10 unit-тестов на stub-модели (StubRecognizer / FakeDicomReader) без Qt; файл добавлен в
    pure-core manifest (`tests/pure_core_manifest.json`). Ruff / mypy чистые.
  - Это **не классификатор и не UI**: реальный ONNX-адаптер (шаг 2), UI-хук с бейджем confidence и
    override (шаг 4), bench и coverage-гейты (шаг 5) остаются.
