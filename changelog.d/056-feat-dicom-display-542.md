- `feat(dicom)`: #542 — отдельный тракт отображения DICOM: сохранённые значения → модальность (Modality LUT или RescaleSlope/Intercept) → VOI (VOI LUT, окна заголовка, LINEAR/LINEAR_EXACT/SIGMOID) → presentation (MONOCHROME1/INVERSE) → 8-битный экран.

**Что добавлено**

- `domain/models/dicom_display.py` хранит факты заголовка без пикселей и Qt: `DicomDisplay`, `WindowPreset`, `LookupTable`. `value_unit` становится `HU` только для CT, где rescale реально доказан; MR и УЗИ никогда не подписываются как HU.
- `imaging/dicom_display.py` — чистые функции `stored_to_modality`, `modality_value`, `padding_mask`, `resolve_window`, `render_dicom_frame`. Несколько пар `WindowCenter`/`WindowWidth` доступны по порядку; числовое окно побеждает окно заголовка; VOI LUT используется, пока слайдеры W/L не тронуты. Pixel Padding исключается из статистики авто-окна и красится в 0. Инверсия применяется к presentation-значениям, исходный массив не меняется.
- Mapper читает `PhotometricInterpretation`, `PresentationLUTShape`, rescale, `WindowCenter/Width/Explanation`, `VOILUTSequence`, `ModalityLUTSequence`, `PixelPaddingValue/RangeLimit`, `VOILUTFunction`. `LUTDescriptor` разбирается по стандарту: количество записей, первое входное значение, биты на запись; это проверено тестом с ненулевым `first_input`. Обычное УЗИ без этих тегов сохраняет прежний путь W/L: `display is None`.
- `ViewerDisplay` получил `display_provider`; при наличии цепочки `update_levels` рендерит через неё, а не через 8-битную LUT. Контекстное меню viewer показывает подменю `Окно DICOM` со списком окон заголовка, командой `Числовые W/L…` (центр и ширина в единицах модальности) и возвратом к окну заголовка. Слайдеры W/L/DR после ручного движения заменяют выбранное окно; числовое окно запоминается для клипа.
- Для будущих/внутренних измерений интенсивности предусмотрен `modality_value`: он возвращает значение модальности (HU после доказанного rescale), а не квантованное значение экранной картинки. Отдельного инструмента измерения интенсивности в приложении сейчас нет, поэтому приёмка проверена на уровне API и рендера.
- Справка RU/EN: абзац про подменю окон и порядок цепочки; локали RU/EN — 6 ключей `viewer.window_*`.

**Почему так**

Аудит #542 требует разделить стадии, а не латать dtype. Поэтому LUT/окно/инверсия живут в Qt-free функциях и переиспользуются рендером, а `InstanceMetadata` остаётся единственной точкой сборки заголовка. Реальные vendor/PACS наборы и GUI-сценарий на живом CT в этой сессии не проверялись: в тестах — синтетические датасеты и offscreen Qt.

**Прогоны**

- `tests/unit/test_dicom_display_pipeline.py` — 16 тестов цепочки (отрицательные CT, LINEAR/LINEAR_EXACT, MONOCHROME1/INVERSE, VOI LUT, numeric window, padding, mapper).
- `tests/unit/test_viewer_display.py` — 9 новых GUI-тестов рендера, инверсии, пресетов, numeric override и контекстного меню; `test_dicom_metadata_mapper.py` — 4 новых теста CT/MR/padding/US.
- `ruff check`/`format`, `mypy`, ратчеты class-size/типы/локали/справка — по результатам CI.
