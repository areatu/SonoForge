# SonoForge Source

> [English version](README.md)

Исходный код SonoForge — десктопного инструмента для эхокардиографии.

## Архитектура (Clean Architecture)

```
src/echo_personal_tool/
├── domain/           # Бизнес-логика (без зависимостей от Qt)
│   ├── models/       # Data-классы: Contour, Doppler, Speckle, MMode
│   ├── calculations/ # Расчёты: Simpson, Bernoulli, Teichholz, BSA
│   ├── services/     # Сервисы: сегментация, трекинг, нормативы
│   └── ports.py      # Интерфейсы (абстракции)
├── infrastructure/   # Внешние интеграции
│   ├── dicom_*.py    # DICOM чтение/запись
│   ├── orthanc_*.py  # Orthanc DICOMweb клиент
│   ├── dimse_*.py    # DIMSE клиент
│   ├── onnx_engine.py # ONNX инференс
│   └── ...
├── application/      # Оркестрация и workflow
│   ├── app_controller.py # Главный контроллер
│   ├── workers/      # Фоновые задачи (11 шт.)
│   └── services/     # Сервисы приложения
├── presentation/     # GUI (PySide6)
│   ├── main_window.py
│   ├── viewer_widget.py
│   ├── doppler_widget.py
│   └── ...
├── constructor/      # Редактор справочника
├── resources/        # Шрифты, иконки, справочник ASE
└── ui/               # STE окна и графики
```

## Запуск

```bash
python -m echo_personal_tool
```
