# Structured Reference Browser — Design Spec

## Overview

Enhance the existing `AseReferenceDialog` with a new first tab providing structured navigation of echocardiography reference values: topic → pathology → parameter table with sex-specific norms. Parameters from all gradations are flattened into a single table (gradation names appear as prefixes in the pathology description column). Support image placement per topic/pathology with a fixed-width image panel.

## Topics (11)

Left anatomical menu:

| # | Topic | Pathologies | Images |
|---|-------|-------------|--------|
| 1 | Левый желудочек | Масса миокарда, Размеры, Геометрия/гипертрофия, Фракция выброса, Диастолическая функция, Сегменты и кровоснабжение | diastolic_function.png, coronary.jpeg |
| 2 | Левое предсердие | Объём ЛП, Индекс объёма, Линейные размеры | — |
| 3 | Правый желудочек | Размеры, Систолическая функция, Диастолическая функция, Площадь/объём, Давление в ЛА, Вероятность лёгочной гипертензии | — |
| 4 | Правое предсердие | Размеры, Давление | — |
| 5 | Митральный клапан | Первичная МР, Вторичная МР, МС, Сегменты МК | pisa_mr.png |
| 6 | Аортальный клапан | АС, АР | aortic_insuf.jpeg |
| 7 | Трикуспидальный клапан | ТР, ТС | — |
| 8 | Лёгочный клапан | ЛР, ЛС, Лёгочный ствол | — |
| 9 | Аорта | Размеры, Расслоение | — |
| 10 | Прочее | Общие показатели, Параметры протезов, Методика измерений | test.svg |
| 11 | Протезы клапанов | МК позиция, АК позиция | prosthetic_valves.png |

## Data Model

### `ReferenceDataStore` — `src/echo_personal_tool/domain/services/reference_data_store.py`

```python
@dataclass
class NormRange:
    low: float | None
    high: float | None

@dataclass
class ParameterRef:
    id: str
    name: str
    unit: str
    norm_male: NormRange | None
    norm_female: NormRange | None
    pathology_desc: str | None
    source: str | None

@dataclass
class GradationRef:
    name: str
    parameters: list[ParameterRef]

@dataclass
class PathologyRef:
    name: str
    slug: str
    description: str | None
    image_path: str | None
    gradations: list[GradationRef] | None
    parameters: list[ParameterRef] | None

@dataclass
class TopicRef:
    name: str
    slug: str
    pathologies: list[PathologyRef]
```

### Methods
- `get_topics() -> list[TopicRef]`
- `get_topic(slug) -> TopicRef`
- `get_pathology(topic_slug, pathology_slug) -> PathologyRef`
- `lookup(param_id: str) -> (TopicRef, PathologyRef, GradationRef | None)`
- `search(query: str) -> list[ParameterRef]`

### Data file: `src/echo_personal_tool/resources/references/references_structured.yaml`

```yaml
topics:
  - name: Аортальный клапан
    slug: aortic_valve
    pathologies:
      - name: Аортальная регургитация
        slug: aortic_regurgitation
        image_path: aortic_insuf.jpeg
        gradations:
          - name: Лёгкая
            parameters:
              - id: ar_eroa
                name: EROA
                unit: см²
                norm_male: { low: null, high: 0.10 }
                pathology_desc: "<0.10"
                source: "ASE 2017"
```

## UI Layout

### New first tab: `StructuredReferenceWidget`

```
┌──────────────────────────────────────────────────────────────┐
│  [🔍 Поиск параметра..._______________]                      │
├────────┬───────────────────────────────────┬─────────────────┤
│        │                                    │                 │
│ ● ЛЖ   │  Патология:                        │  [картинка]     │
│ ○ ЛП   │  ○ Первичная МР                    │  фикс. 320px   │
│ ○ ПЖ   │  ○ Вторичная МР                    │                 │
│ ○ ПП   │  ● МС                              │                 │
│ ○ МК   │                                    │                 │
│ ○ АК   ├────────────────────────────────────┤                 │
│ ○ ТК   │  Параметр     Ед.   Норма  Патол. │                 │
│ ○ ЛК   │  EROA         см²   <0.10  Лёгкая:│                 │
│ ○ Аорта│  EROA         см²   <0.10  Тяжёлая:│                 │
│ ○ Проч.│                                    │                 │
│        │  Источники: ASE 2017               │                 │
├────────┴────────────────────────────────────┴─────────────────┤
│ Пол: ● Муж / ○ Жен   │  Возраст: [__]                       │
└──────────────────────────────────────────────────────────────┘
```

### Components

| Section | Widget | Behavior |
|---------|--------|----------|
| Search | `QLineEdit` | Фильтр строк таблицы по имени параметра |
| Topic nav | `QPushButton` in `QButtonGroup` | 11 тем; клик → обновить список патологий |
| Pathology list | `QListWidget` | Патологии для выбранной темы |
| Parameter table | `QTableWidget` (4 колонки: Параметр, Ед.изм, Норма, Патология) | При градациях — все градации в одной таблице с префиксами |
| Source | `QLabel` | Ссылки на источники |
| Image panel | `QLabel` в контейнере (max-width: 320px) | Фиксированная ширина, не растягивает таблицу |
| Sex selector | `QButtonGroup` (2 radio) | Переключает нормы |
| Age field | `QLineEdit` | Для будущего (диастолическая функция) |

### Behavior

1. Нет темы → placeholder "Выберите тему"
2. Клик темы → populate список патологий, clear таблицу
3. Клик патологии → если есть градации → объединить все в одну таблицу с префиксами градаций; если нет → показать таблицу
4. Смена пола → пересчёт норм
5. Поиск → фильтр видимых строк (case-insensitive по имени параметра)
6. Изображения — фиксированная ширина панели (320px), не растягивает layout

## Gradation Handling

При патологиях с градациями (например, Аортальный стеноз: Лёгкий / Умеренный / Тяжёлая):
- Все параметры из всех градаций объединяются в одну таблицу
- Дублирующиеся параметры (один ID в разных градациях) дедуплицируются
- Описание патологии содержит префиксы градаций: `"Лёгкая: <0.10 / Тяжёлая: ≥0.30"`
- Нормы берутся из первой градации (нормы одинаковы между градациями)
- Панель выбора градации (radio buttons) отсутствует

## Image Assets

| Slug | File | Description |
|------|------|-------------|
| `pisa_mr` | `images/pisa_mr.png` | PISA measurement for mitral regurgitation |
| `aortic_insuf` | `images/aortic_insuf.jpeg` | Aortic insufficiency grading |
| `coronary` | `images/coronary.jpeg` | Coronary artery supply to LV segments |
| `diastolic_function` | `images/diastolic_function.png` | ASE 2016 diastology algorithm |
| `prosthetic_valves` | `images/prosthetic_valves.png` | Prosthetic valve types and measurements |
| `heart_segments` | `images/heart_segments.svg` | Heart segment anatomy |
| `test` | `images/test.svg` | Test SVG asset |

Images stored in `src/echo_personal_tool/resources/references/images/`.

## Integration with `AseReferenceDialog`

### Changes
1. `StructuredReferenceWidget` — новый виджет, первый в стэке контента
2. Метка таба: "Справочник" (первый, не закрываемый)
3. `_load_default_documents()` — без изменений, доки после таба 1
4. Новый метод: `navigate_to_param(param_id: str)` — выбор темы/патологии по ID параметра

## Future: Overlay Links (Phase 2)

- `format_results_overlay_html()` — rich text с `<a href="ref://{param_id}">`
- `ResultsOverlayLabel` → `setHtml()` + `linkActivated` → signal `reference_requested`
- `MainWindow` → connect → open/navigate `AseReferenceDialog`

## Files

### New:
- `src/echo_personal_tool/domain/services/reference_data_store.py`
- `src/echo_personal_tool/resources/references/references_structured.yaml`
- `src/echo_personal_tool/presentation/structured_reference_widget.py`
- `src/echo_personal_tool/resources/references/images/` (directory with 7 assets)

### Modified:
- `src/echo_personal_tool/presentation/ase_reference_dialog.py`

### Phase 2:
- `measurement_results_formatter.py`
- `viewer_widget.py`
- `app_controller.py`
- `main_window.py`

## Implementation Order

1. Data model + YAML loader + `references_structured.yaml`
2. Image directory with assets
3. `StructuredReferenceWidget` (UI)
4. Integration into `AseReferenceDialog`
5. Fill YAML data (all 11 topics)
6. Phase 2: overlay links
