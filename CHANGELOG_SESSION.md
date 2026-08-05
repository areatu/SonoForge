# Changelog — Текущая сессия

## [2026-08-06] Сосуды: усреднение PSV/EDV без ЭКГ + ручная коррекция PSV
- **Тип:** feature
- **Файлы:** `src/echo_personal_tool/domain/services/cardiac_cycle_service.py`, `src/echo_personal_tool/presentation/doppler_overlay.py`, `src/echo_personal_tool/presentation/viewer_widget.py`, `src/echo_personal_tool/infrastructure/locales/{ru,en}.json`, `tests/unit/test_cardiac_cycle_service.py`, `tests/unit/test_presentation_doppler_overlay.py`, `tests/unit/test_presentation_viewer_widget.py`, `tests/unit/test_i18n.py`
- **Суть:** Усреднение PSV/EDV теперь работает без ЭКГ: циклы детектируются из спектрального envelope (`detect_cycles_from_envelope`, fallback во всех ветках `get_cycles`). EDV — адаптивное окно (≤30 мс/10 точек) перед systolic upstroke с fallback на минимум; PSV/EDV усредняются медианой (не средним). Добавлен ручной режим коррекции PSV: полоса-подсветка текущего цикла-кандидата, ←/→ перебор циклов, Enter — принять PSV кандидата, Esc — отмена; i18n-ключи очищены от упоминаний ЭКГ, добавлен `viewer.vessel_cycle_candidate`. Реализовано через subagent-driven development (6 задач + финальное ревью, 9 коммитов на ветке `optimize/memory`, `d6c074b..d7467cf`).
- **Тип-заметка:** в рабочем дереве остаются чужие незакоммиченные in-flight правки `doppler_metrics.py`/`measurements.py` (не наши, не трогать).

## [2026-08-03] Сосуды: измерения PSV/EDV в панели Measurements
- **Тип:** feature
- **Файлы:** `src/echo_personal_tool/domain/calculations/vessel_metrics.py`, `src/echo_personal_tool/domain/models/vessel_measurement.py`, `src/echo_personal_tool/domain/models/measurements.py`, `src/echo_personal_tool/application/study_measurement_session.py`, `src/echo_personal_tool/application/app_controller.py`, `src/echo_personal_tool/presentation/doppler_overlay.py`, `src/echo_personal_tool/presentation/measures_menu.py`, `src/echo_personal_tool/presentation/viewer_widget.py`, `src/echo_personal_tool/presentation/measurement_action.py`, `src/echo_personal_tool/presentation/main_window.py`, `src/echo_personal_tool/presentation/tool_panel.py`, `src/echo_personal_tool/domain/services/measurement_report_formatter.py`, `src/echo_personal_tool/domain/services/measurement_results_formatter.py`, `src/echo_personal_tool/presentation/measurement_panel.py`, `src/echo_personal_tool/infrastructure/locales/{ru,en}.json`
- **Суть:** Добавлены ручные измерения сосудов на кадре спектрального допплера: клик на пике (PSV) и второй клик (EDV) → RI, S/D, MV≈ (суррогаты). Кнопка «PSV/EDV» запускает единый последовательный поток (кнопка EDV и хоткей E удалены как дубликат). Измерения сохраняются per (instance, frame), отображаются в overlay, отчёте (PDF) и правой панели.

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
