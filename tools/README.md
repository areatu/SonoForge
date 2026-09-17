# Tools

Вспомогательные инструменты разработки и CI (не часть приложения).

| Файл | Описание |
|------|----------|
| `ste_fixture_export.py` | Экспорт компактных фикстур из реальных STE-клипов в `tests/fixtures/for_pero/` (кадры в JPEG + обезличенные заголовки). Запускается воркфлоу [`ste-fixtures.yml`](../.github/workflows/ste-fixtures.yml) |
| `migrate_for_pero.sh` | Одноразовая миграция клипов `data/dicom/For_pero` из публичного репозитория в закрытый `areatu/Sonoforge_data` (см. [`../data/README.md`](../data/README.md)) |
| `qtstub/mkstub.py` | Генерация заглушек GL/EGL/dbus-библиотек для запуска PySide6 в «голых» контейнерах без GPU (заготовленные библиотеки — локально, `qtstub/lib/` в `.gitignore`) |
