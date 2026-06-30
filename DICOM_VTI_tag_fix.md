Spec: DICOM Doppler VTI Calibration Fix
Дата: 2026-06-24 Статус: Черновик Связанные файлы: ultrasound_region_physics.py, frame_panel_parser.py, dicom_doppler_calibration.py, doppler_calibration.py, doppler_overlay.py, measures_menu.py, measurement_panel.py

Проблема
Баг детекции Doppler: RegionDataType = 2 (стандартный DICOM код Spectral Doppler) не входит в DOPPLER_DATA_TYPES = {0x10, 0x11, 16, 17}. В результате спектральные регионы не распознаются как Doppler, калибровка из DICOM не срабатывает.
Ручной ввод времени: Для VTI требуется время (ms), но ручная калибровка даёт погрешность, особенно на CW.
PhysicalDeltaX = 3 (секунды): Ошибочная константа: PHYSICAL_UNIT_CM = 3, а PHYSICAL_UNIT_SEC = 4 — перепутаны местами.
Факты из DICOM
PhysicalDeltaX присутствует во всех файлах (56/56)
PhysicalUnitsXDirection = 3 (seconds по DICOM PS3.3 C.8.5.5)
Значения: 0.024–0.075 с/пиксель
RegionDataType = 2 — Spectral Doppler (12 файлов в исследовании)
ReferencePixelPhysicalValueX/Y = 0 (нет zero-offset)
Решение
1. Исправить константы единиц измерения
Файл: ultrasound_region_physics.py:8-9

# Сейчас (неправильно):
PHYSICAL_UNIT_CM = 3
PHYSICAL_UNIT_SEC = 4

# DICOM PS3.3 C.8.5.5:
# 1 = cm, 2 = mm, 3 = seconds, 4 = Hz, 5 = dB, 6 = cm/s
PHYSICAL_UNIT_CM = 1     # не используется, но для консистентности
PHYSICAL_UNIT_MM = 2
PHYSICAL_UNIT_SEC = 3     # <-- исправлено
PHYSICAL_UNIT_HZ = 4
PHYSICAL_UNIT_DB = 5
PHYSICAL_UNIT_CM_PER_SEC = 6
Влияние: horizontal_ms_per_pixel() и velocity_span_cm_s_from_region() начнут корректно работать — они проверяют units_x == PHYSICAL_UNIT_SEC и units_y == PHYSICAL_UNIT_CM_PER_SEC.

2. Добавить RegionDataType = 2 в DOPPLER_DATA_TYPES
Файлы: ultrasound_region_physics.py:17, frame_panel_parser.py:21

_DOPPLER_DATA_TYPES = frozenset({0x0002, 0x0010, 0x0011})
3. Убрать ручной ввод времени для VTI
VTI считается только если dicom_trusted и есть PhysicalDeltaX со значением units_x == 3.

Если DICOM не дал время — VTI trace кнопки серые, с тултипом «VTI недоступен: нет калибровки времени из DICOM»
Peak-метки (E, A, e', TR Vmax) и интервалы (DT, IVRT, AT) оставить — они работают без времени
Velocity (Y-ось) оставить ручную калибровку — на некоторых аппаратах PhysicalUnitsY ≠ 6
Файлы: doppler_overlay.py, doppler_widget.py, measures_menu.py, measurement_panel.py

4. Учесть ReferencePixelPhysicalValue = 0
Сейчас ReferencePixelPhysicalValueX = 0 и ReferencePixelPhysicalValueY = 0 во всех файлах. Это значит, что zero-offset не указан — baseline считать по середине ROI (как сейчас и делается). Ничего менять не нужно.

Pipeline
DICOM → SequenceOfUltrasoundRegions
  → RegionDataType == 2|0x10|0x11  ✓ распознаётся как Doppler
  → PhysicalDeltaX (+ units=3)      ✓ время на пиксель
  → PhysicalDeltaY (+ units=6)       ? скорость (если нет — ручная)
  → DopplerAxisMapping               ✓ автоматическая калибровка
  → VTI trace → np.trapz             ✓ точное время из DICOM
Файлы для изменения
Файл	Изменение
domain/services/ultrasound_region_physics.py	Константы units, DOPPLER_DATA_TYPES
domain/services/frame_panel_parser.py	DOPPLER_DATA_TYPES
infrastructure/dicom_doppler_calibration.py	(возможно) проверка RegionDataType=2
presentation/doppler_overlay.py	VTI только при DICOM-калибровке времени
presentation/measures_menu.py	VTI кнопки серые без времени
presentation/measurement_panel.py	VTI/Vmean/PGmean скрыты без времени
tests/unit/test_ultrasound_region_physics.py	Test with DataType=2
Что НЕ меняется
Ручная калибровка velocity (Y-ось) — оставить для аппаратов без units=6
Peak-маркеры, DT/IVRT/AT — работают без времени
B-режим контуры, LV Auto, Simpson — не затрагиваются
UI калибровки в system_bar — остаётся (для velocity)
