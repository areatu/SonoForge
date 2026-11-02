# S1-05 — инвентаризация мёртвого кода и дублей

> **Снимок на 2026-10-25.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

**Дата:** 2026-10-25  
**Связь:** issue #304, S1-05 из `docs/superpowers/specs/2026-10-23-audit-2026-10-22-three-sprint-plan-ru.md`  
**Область:** проверка статических импортов приложения, удаление изолированных UI/сервисов и тестов, фиксация владельцев активных путей. Клинические формулы и их поведение не менялись.

## Итог

Из 18 модулей исходного списка два developer-инструмента перенесены в `bench/`, остальные 16 удалены как не подключённые к приложению. Добавленный AST-аудит обнаружил ещё три изолированных presentation-модуля; после проверки их активных замен они также удалены. Финальный `scripts/audit_unreferenced_modules.py` сообщает: **No unreferenced runtime modules found.**

**unique reportable strain context moved into `ReportGroup.notes`**: QC-метка и статус по видам, метод/сегментация, AVC source по видам, признак чернового контура, число неизмеренных сегментов и явное пояснение, если валидных видов для среднего нет. Подпись среднего GLS включает количество валидных видов. Structured report строится через `report_builder` → `ReportDocument` и экспортируется через `measurement_report_pdf`; старый текстовый formatter удалён.

## Решения по исходным 18 модулям

| Модуль | Решение | Активный путь / судьба тестов |
|---|---|---|
| `application/workers/dicom_loader_worker.py` | Удалён | Нет production-importers; изолированный worker-тест удалён. Активные decode/scan workers остаются на месте. |
| `domain/services/measurement_report_formatter.py` | Удалён | Отчёт исследования принадлежит `domain/services/report_builder.py`; PDF — `infrastructure/measurement_report_pdf.py`. STE-проверки перенесены на `ReportDocument` и PDF. |
| `domain/services/multi_beat_average.py` | Удалён | Нет production-importers; отдельный тест удалён. |
| `domain/services/provenance_dependencies.py` | Удалён | Нет production-importers; актуальность результата вычисляют профильные freshness-сервисы. DTO/codec/migration проверки сохранены в `test_result_provenance.py`; freshness — в специализированных тестах. |
| `domain/services/vti_cycle_service.py` | Удалён | Нет production-importers; изолированный тест удалён, используемые расчёты остаются в активном Doppler-контуре. |
| `infrastructure/stow_upload_adapter.py` | Удалён | STOW реализован в `orthanc_client.py`; DIMSE upload остаётся в `dimse_upload_adapter.py`. Изолированный адаптерный тест удалён. |
| `presentation/doppler_widget.py` | Удалён | Активный спектральный UI — `doppler_overlay.py`, `measures_menu.py` и `viewer_widget.py`; тесты старого виджета удалены. |
| `presentation/local_browser.py` | Удалён | Браузер исследования — `study_browser.py` и `thumbnail_gallery.py`; изолированные тесты удалены. |
| `presentation/measurement_panel.py` | Удалён | Активные измерения — `measures_menu.py` и `tool_panel.py`; изолированный тест удалён. |
| `presentation/measurement_tools_panel.py` | Удалён | Активный владелец — `tool_panel.py` с меню действий; бывший тест панели переименован и оставлен как проверки действий `MainWindow`. |
| `presentation/measurement_worksheet.py` | Удалён | Исследовательский отчёт — `ReportDialog` + структурированный PDF; изолированный тест удалён. |
| `presentation/mmode_caliper.py` | Удалён | Единственный интерактивный M-mode measurement tool — `presentation/mmode_measurement.py`, подключённый из `mmode_widget.py`; доменная запись — `domain/models/mmode.py`. Тесты сосредоточены на активном M-mode пути. |
| `presentation/settings_widgets.py` | Удалён | Настройки реализованы в `user_preferences_dialog.py` и `tool_settings_2.py`; изолированный тест удалён. |
| `presentation/ste_results_dialog.py` | Удалён | Strain study отображается в `ui/strain_window.py`; репортируемые результаты входят в общий `ReportDocument`. Изолированный тест удалён. |
| `presentation/theme_tokens.py` | Удалён | Поддерживаемые токены — пакет `presentation/theme/`; совместимый theme facade — `dark_theme.py`. Обновлены тесты и цветовой baseline. |
| `presentation/tool_panel_settings.py` | Удалён | Единственный редактор раскладки инструментов — `presentation/tool_settings_2.py`; тесты старого виджета удалены, покрытие активных настроек оставлено. |
| `application/services/bench_lvef.py` | Перенесён в `bench/bench_lvef.py` | Developer-only LVEF benchmark больше не находится в runtime-пакете; тесты и документация bench обновлены. |
| `application/services/cine_segment_diagnostics.py` | Перенесён в `bench/cine_segment_diagnostics.py` | Developer-only диагностика cine больше не находится в runtime-пакете; тесты и документация bench обновлены. |

## Дополнительные orphan-модули, найденные AST-аудитом

| Модуль | Решение | Причина / замена |
|---|---|---|
| `presentation/browser_item_delegate.py` | Удалён | Оставшийся компонент прежнего `local_browser`; активный браузер его не импортировал. Тесты удалены вместе с ним. |
| `presentation/segment_quality_panel.py` | Удалён | Не имел production-importers; изолированные тесты не проверяли активный strain/UI путь. |
| `presentation/strain_curve_widget.py` | Удалён | Не имел production-importers; текущие кривые отображает `ui/strain_curves_view.py`. Standalone-тесты удалены. |

## Единые владельцы

- **Диалоги:** `presentation/styled_dialogs.py`; дублировавший стилизацию `constructor/dialogs.py` удалён.
- **M-mode-калиперы:** `presentation/mmode_measurement.py` владеет интерактивным инструментом, `mmode_widget.py` подключает его к экрану; второй presentation-калипер удалён.
- **Результаты и отчёты:** `measurement_results_formatter.py` форматирует per-measurement результат; `report_builder.py` строит structured study report; `measurement_report_pdf.py` рендерит PDF. Старый `measurement_report_formatter.py` удалён.
- **Simpson contour grouping:** общая фильтрация по камере/виду/фазе и преобразование геометрии вынесены в `domain/calculations/simpson_contours.py`; LVEF и chamber calculations используют общий helper.

## Проверки

- Все **24 изменённых unit-test файла** из S1-05 — пройдены, включая active report/PDF + STE, LVEF/chamber Simpson, M-mode, тему, настройки и AST-аудит.
- `ruff check src tests` — чисто; `ruff format --check src tests` — чисто (969 файлов).
- `scripts/audit_unreferenced_modules.py` — **No unreferenced runtime modules found.**
- `update_pytest_baseline.py --check` — чисто. Эффект S1-05: **9 065 → 8 834** eligible tests; после интеграции актуального `main` (PR #321 добавил 9 logic-тестов, PR #322 — 17 GUI-тестов) общий baseline ветки — **8 860**. Удаление изолированных тестов не маскируется старым baseline.
- Цветовой baseline обновлён: **194 → 192** литерала.
- Полный `tests/unit` запуск был остановлен ограничением времени инструмента на 30 мин при отображении 55% прогресса; итоговая сводка pytest не получена. Полный прогон считается **неподтверждённым**, а не зелёным.

## Основные обновлённые карты

`ROADMAP.md`, `src/echo_personal_tool/README{,_RU}.md`, `docs/web_build_feasibility.md`, `docs/ui_tokens{,_ru}.md`, `docs/STE_IMPROVEMENT_PLAN.md`, `docs/DICOM_VTI_tag_fix.md` и связанные UI/Doppler спеки. Исторические описания помечены как исторические там, где они называют уже удалённый путь.
