# Changelog — Текущая сессия

## [2026-07-30] macOS: Intel support + DMG вместо zip
- **Тип:** fix
- **Файлы:** `.github/workflows/release.yml`, `sonoforge-standalone.spec`
- **Суть:** Исправлена ошибка "bad CPU type in executable" — добавлена отдельная сборка для Intel Mac (`macos-13`). Заменены zip-архивы на DMG-диски с .app bundle и иконкой .icns. Конвертация .png → .icns через `sips` + `iconutil`.

## [2026-07-24] Тестовое покрытие: +275 тестов, 35% → 37%
- **Тип:** test
- **Файлы:** `tests/unit/test_optical_flow_refine.py`, `tests/unit/test_doppler_envelope.py`, `tests/unit/test_doppler_trace_and_baseline.py`, `tests/unit/test_doppler_calibration.py`, `tests/unit/test_doppler_axis.py`, `tests/unit/test_mmode_calibration.py`, `tests/unit/test_heart_rate_worker.py`, `tests/unit/test_optical_flow_refine_worker.py`, `tests/unit/test_strain_computation.py`, `tests/unit/test_tracking_smoothing_v2.py`, `tests/unit/test_planimeter.py`, `tests/unit/test_planimeter_formatter.py`, `tests/unit/test_measurement_report_formatter_v2.py`, `tests/unit/test_measurement_results_formatter_v2.py`, `tests/unit/test_frame_panel_parser.py`, `tests/unit/test_linear_measurement.py`, `tests/unit/test_profiler.py`, `tests/unit/test_gui_presentation.py`
- **Суть:** Добавлены unit-тесты для domain services (optical_flow_refine, doppler, strain, tracking_smoothing, planimeter, formatters), workers (heart_rate, optical_flow_refine), presentation (mmode_caliper, ui_animations, caliper_label_item). Ключевые модули доведены до 90-100% покрытия. Скоммичено и запушено в main.

## [2026-08-03] Doppler baseline: визуальный детектор линии вместо минимума яркости
- **Тип:** feature
- **Файлы:** `src/echo_personal_tool/domain/services/doppler_baseline.py`, `src/echo_personal_tool/infrastructure/dicom_doppler_calibration.py`, `tests/unit/test_doppler_baseline.py`, `tests/unit/test_dicom_doppler_calibration.py`
- **Суть:** Добавлен `detect_baseline_line_y` — поиск тонкой (≤8px) горизонтальной полосы одного цвета по методу оператора (цвет-агностичен, адаптивный порог `max(0.5, 0.75·пик)`). `detect_baseline_y` и калибровка переведены на приоритет «линия → тег → интенсивность». Ключевое: `ReferencePixelY0=0` (IM_0247/0252/0254) теперь корректен — база подтверждается видимой линией на верхней кромке ROI (343 vs прежние ~606). Верифицировано на 6 реальных Philips-файлах; +6 юнит-тестов.
