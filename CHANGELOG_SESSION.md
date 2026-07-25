# Changelog — Текущая сессия

## [2026-07-24] Тестовое покрытие: +275 тестов, 35% → 37%
- **Тип:** test
- **Файлы:** `tests/unit/test_optical_flow_refine.py`, `tests/unit/test_doppler_envelope.py`, `tests/unit/test_doppler_trace_and_baseline.py`, `tests/unit/test_doppler_calibration.py`, `tests/unit/test_doppler_axis.py`, `tests/unit/test_mmode_calibration.py`, `tests/unit/test_heart_rate_worker.py`, `tests/unit/test_optical_flow_refine_worker.py`, `tests/unit/test_strain_computation.py`, `tests/unit/test_tracking_smoothing_v2.py`, `tests/unit/test_planimeter.py`, `tests/unit/test_planimeter_formatter.py`, `tests/unit/test_measurement_report_formatter_v2.py`, `tests/unit/test_measurement_results_formatter_v2.py`, `tests/unit/test_frame_panel_parser.py`, `tests/unit/test_linear_measurement.py`, `tests/unit/test_profiler.py`, `tests/unit/test_gui_presentation.py`
- **Суть:** Добавлены unit-тесты для domain services (optical_flow_refine, doppler, strain, tracking_smoothing, planimeter, formatters), workers (heart_rate, optical_flow_refine), presentation (mmode_caliper, ui_animations, caliper_label_item). Ключевые модули доведены до 90-100% покрытия. Скоммичено и запушено в main.
