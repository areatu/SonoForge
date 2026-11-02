# Профили вендоров для калибровки УЗИ в DICOM

> [English version](README.md)

## Обзор

Модуль предоставляет вендор-специфичные профили для учёта различий калибровки
УЗИ-изображений DICOM между производителями сканеров (GE, Philips, Samsung).

Каждый вендор по-своему кодирует калибровку допплера, тайминг M-mode и семантику
референсных пикселей внутри DICOM `SequenceOfUltrasound Regions` (0018,6011).
Модуль нормализует эти различия в единый интерфейс для пайплайна калибровки.

## Архитектура

```
vendor_profiles/
├── __init__.py          # Экспорт пакета
├── base.py              # Абстрактный базовый класс (VendorProfile)
├── ge.py                # Реализация GE Vingmed Ultrasound
├── detector.py          # Определение вендора по DICOM-тегам
└── registry.py          # Реестр профилей и поиск
```

## Использование

### Базовое использование

```python
from echo_personal_tool.infrastructure.vendor_profiles import detect_vendor, get_profile

# Определить вендора по датасету
vendor = detect_vendor(dataset)

# Получить профиль вендора
profile = get_profile(vendor)

# Использовать профиль для калибровки
baseline = profile.compute_baseline(region, frame_height)
velocity = profile.compute_velocity_span(region, region_height)
time = profile.compute_time_span(region, region_width)
```

### Интеграция с пайплайном калибровки

```python
from echo_personal_tool.infrastructure.vendor_calibration_bridge import (
    try_parse_with_vendor_profile,
)

# Калибровка с учётом вендора (заменяет общий подход)
calibration = try_parse_with_vendor_profile(dataset, frame_pixels)
```

## Профиль GE Vivid E95

Профиль GE обрабатывает следующие особенности:

### 1. Инвертированная формула скорости

GE использует: `v(y) = (RefY - y) × deltaY` (положительная скорость = вверх)

Стандарт DICOM: `v(y) = (y - RefY) × deltaY` (положительная скорость = вниз)

### 2. ReferencePixelY0 может быть вне региона

Иногда GE записывает значения `ReferencePixelY0`, которые:
- внутри региона (baseline в видимой полосе);
- выше региона (baseline за экраном, смещённый baseline);
- отрицательные (baseline выше верха изображения).

Это сделано намеренно для измерения высокоскоростных потоков.

### 3. PhysicalUnitsY = 7 (см/сек)

GE корректно использует `cm/sec` по стандарту DICOM, но соглашение о знаке
скорости отличается от стандартного.

### 4. Приватные теги

GE использует приватные группы:
- `6003` (GEMS_Ultrasound_ImageGroup) — метаданные изображения;
- `7FE1` (GEMS_Ultrasound_MovieGroup) — параметры сканирования.

## Профиль Philips

Philips в целом следует стандартным соглашениям DICOM:
- отрицательный PhysicalDeltaY для положительной скорости = вверх;
- ReferencePixelY0 относительно начала региона;
- приватные группы: 0033, 0029, 0071.

## Профиль Samsung

У Samsung особенности, похожие на GE, но требуется валидация:
- допплеровские регионы иногда неверно помечены как SF=1 (2D);
- ReferencePixelY0 может быть относительно региона;
- пониженная уверенность до валидации на реальных данных.

## Добавление нового вендора

Чтобы добавить профиль нового вендора:

1. Создайте новый файл `vendor_profiles/{vendor}.py`
2. Реализуйте абстрактный класс `VendorProfile`
3. Зарегистрируйте профиль в `vendor_profiles/registry.py`

Пример:

```python
from echo_personal_tool.infrastructure.vendor_profiles.base import (
    Vendor,
    VendorProfile,
    BaselineResult,
)


class PhilipsProfile(VendorProfile):
    @property
    def vendor(self) -> Vendor:
        return Vendor.PHILIPS

    @property
    def vendor_keywords(self) -> list[str]:
        return ["philips"]

    def compute_baseline(self, region, frame_height, frame_pixels=None):
        # Philips использует стандартное соглашение DICOM
        ref_y = region.get("ReferencePixelY0")
        if ref_y is None:
            return BaselineResult(
                baseline_y=frame_height / 2.0,
                confidence=0.0,
                source="Philips: ReferencePixelY0 missing",
                velocity_sign=1,  # стандартное соглашение
            )
        return BaselineResult(
            baseline_y=float(ref_y),
            confidence=0.9,
            source="Philips: ReferencePixelY0 (standard convention)",
            velocity_sign=1,
        )
```

## Тестирование

Запуск набора тестов:

```bash
python3 -m pytest tests/test_vendor_profiles.py -v
```

## Сравнение вендоров

| Аспект | GE | Philips | Samsung |
|--------|-----|---------|---------|
| Формула скорости | Инвертированная | Стандартная | Смешанная |
| Знак PhysicalDeltaY | Положительный | Отрицательный | Переменный |
| Координаты ReferencePixel | Абсолютные | Абсолютные | Относительно региона |
| Приватные группы | 6003, 7FE1 | 0033, 0029 | 0009, 0019 |
| Формат изображения | Однокадровый SC | Многокадровый | Многокадровый |
