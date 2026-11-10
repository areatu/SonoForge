# Снимок выполнения #480 — корень композиции `build_app_services(profile)`

> **Снимок на 2026-11-10.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

Задача: `#480` (фаза 3 эпика `#485`, `docs/reviews/2026-11-09-weakness-analysis-ru.md`, §2.3)

## 1. Проблема до изменений

Конструкторы `AppController.__init__` и `MainWindow.__init__` самостоятельно собирали производственный граф объектов:

- `AppController.__init__` вызывал `load_user_preferences()`, `psutil.virtual_memory()`, `detect_playback_config()`, `measurements_dir()` и создавал `OnnxInferenceEngine()` независимо от активного профиля.
- `MainWindow.__init__` конструировал `self._controller = controller or AppController()`, читал `load_user_preferences()`, `make_recent_folder_store(...)`, `make_orthanc_session_cache()` и опрашивал глобальные функции профиля.

В результате юнит-тесты контроллера и окна требовали `monkeypatch` внутренних импортов для изоляции от `QSettings`, `$HOME` и `psutil`, а различия профиля Presenter размазывались по условным проверкам в UI.

## 2. Инвентаризация проверок профиля в `application/` и `presentation/`

| Участок | Было | Стало |
|---|---|---|
| `presentation/main_window.py` (7 мест: инициализация, хоткеи, справочник, `active_profile_name() == "full"` для авто-сегментации) | Прямые вызовы `active_profile_name()`, `get_profile_capabilities()`, `profile_display_name()` | Чтение `self._profile_name`, `self._profile_capabilities` и `display_name` из `WindowDependencies` / `AppServices` |
| `presentation/system_bar.py` | Безусловный `get_profile_capabilities()` | Явный параметр `profile_capabilities` от `MainWindow` (с fallback для изолированных виджет-тестов) |
| `presentation/start_page.py` | Уже принимал `profile_name` и `profile_capabilities` от `MainWindow` | Без глобальных вызовов при создании из `MainWindow` |
| `presentation/help_dialog.py`, `shortcut_settings.py`, `tool_settings_2.py` | Безусловный `active_profile_name()` | Явный параметр `profile: ProfileName \| None = None` |
| `application/app_controller.py` (`_la_segmenter_available`, `_default_models_dir`) | Прямое чтение `_default_models_dir()` (`$HOME`) без учёта возможностей сервиса | Чтение `services.capabilities.ai_segmentation` и `services.paths.models_dir` через `services_of(self)` |
| `application/package_smoke.py` | Smoke-проверка окружения пакета | Оставлена как диагностический smoke-раннер артефакта |

## 3. Решение

1. Добавлен `src/echo_personal_tool/application/composition.py` (без `PySide6.QtWidgets` и без импортов `presentation`):
   - `AppServices` (неизменяемый `@dataclass(frozen=True)`): профиль, `ProfileCapabilities`, `UserPreferences`, `AppPaths`, `StateManager`, `StudyMeasurementSessionStore`, `CalculatorInputStore`, `MeasurementPersistence`, `FrameCacheBudget`, `FrameCache`, `IOnnxSegmenter`, `AppIoFacades`.
   - `build_app_services(profile, *, preferences=None, paths=None, ...)` собирает полный граф для `"full"` и облегчённый граф для `"presenter"` (`DisabledOnnxSegmenter`, инертный `RecentFolderStore`, `measurement_persistence_enabled=False` по умолчанию).
   - `in_memory_app_services()` обслуживает вызов `AppController()` без аргументов в существующих юнит-тестах без обращения к `QSettings`, `psutil` и `$HOME`.
2. `main.py` и `__main_presenter__.py` стали единственными производственными точками вызова `build_app_services(` и `AppController(`.
3. В `tests/unit/test_architecture_boundaries.py` добавлены AST-проверки точек вызова `AppController(` / `build_app_services(`, отсутствия `PySide6.QtWidgets` в `composition.py` и отсутствия хост-зондов в `AppController.__init__`.
4. В `tests/unit/conftest.py` добавлены фикстуры `make_app_services` и `app_services`.
