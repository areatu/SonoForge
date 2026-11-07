# SonoForge — аудит кода интерфейсных окон (UI audit)

**Дата:** 2026-11-02  
**Ветка:** `arena/f35f226d-sonoforge` (от `main @ 276ea23`)  
**Область:** `src/echo_personal_tool/presentation`, `src/echo_personal_tool/ui`, `src/echo_personal_tool/constructor`  
**Статический анализ:** `ruff` по конфигу проекта (`E, F, I, UP, S110, T201`) — все проверки пройдены, предупреждений нет.

---

## 1. Найденные ошибки (баги)

### 1.1 Потеря данных при закрытии конструктора справочника — КРИТИЧНО

**Файл:** `src/echo_personal_tool/constructor/constructor_dialog.py`, `ConstructorDialog.closeEvent` (строки 276–292)

```python
if reply == QMessageBox.StandardButton.Yes:
    self._constructor_widget.save()   # может не сохранить или выбросить исключение
elif reply == QMessageBox.StandardButton.Cancel:
    event.ignore()
    return
event.accept()   # выполняется ВСЕГДА — диалог закрывается даже при неудаче сохранения
```

Проблемы:
- `save()` может быть заблокирована ошибками валидации (показывает предупреждение и возвращается без сохранения) — диалог всё равно закрывается, изменения теряются.
- `save()` может выбросить исключение при ошибке записи на диск (read-only USB-носитель, права доступа). Необработанное исключение в виртуальном обработчике Qt `closeEvent` может привести к крашу приложения.
- Нет проверки результата сохранения и обработки ошибок записи.

**Рекомендация:** обернуть `save()` в `try/except`, проверять, что сохранение реально произошло, и закрывать диалог только при успехе (либо оставить открытым с индикацией ошибки).

---

### 1.2 Импорт Excel в конструктор не реализован — функциональный дефект

**Файл:** `src/echo_personal_tool/constructor/constructor_widget.py`, `ConstructorWidget.import_excel` (строки 260–273)

```python
for topic_data in imported.get("topics", []):
    existing = self._model.get_topic(topic_data.get("slug", ""))
    if existing:
        for patho_data in topic_data.get("pathologies", []):
            # Add pathology if not exists
            pass  # TODO: implement merge logic
    self._mark_dirty()
```

- Патологии из импортированного Excel не добавляются ни в существующие, ни в новые темы — тело слияния заменено на `pass` с пометкой `TODO`.
- `self._mark_dirty()` вызывается всегда, даже когда ничего не импортировалось — окно помечается «грязным» без реальных изменений.
- На уровне модели `src/echo_personal_tool/constructor/models/reference_model.py` отсутствуют методы `add_topic` / `add_pathology` — функция недоделана на двух слоях.

**Рекомендация:** реализовать слияние тем/патологий в `ReferenceModel` и `ConstructorWidget.import_excel`, убрать ложное `_mark_dirty()`.

---

### 1.3 Хрупкая логика перетаскивания окна конструктора

**Файл:** `src/echo_personal_tool/constructor/constructor_dialog.py`, `mousePressEvent` (строка ~296)

```python
title_bar = self.findChild(QWidget)
```

`findChild(QWidget)` без имени возвращает первый попавшийся дочерний виджет, а не обязательно строку заголовка. Логика перетаскивания окна за заголовок работает нестабильно при изменении порядка виджетов.

**Рекомендация:** находить строку заголовка по имени объекта/типу, а не через первый попадающийся дочерний виджет.

---

## 2. Незавершённые задачи

### Из кода (TODO / нереализованное)

| # | Задача | Файл / строка |
|---|--------|---------------|
| 1 | Слияние импорта Excel в конструктор (патологии → темы) | `constructor_widget.py:271` (`pass  # TODO: implement merge logic`) + отсутствуют методы в `ReferenceModel` |
| 2 | Завершить закрытие конструктора с проверкой сохранения | `constructor_dialog.py:closeEvent` |

### Из ROADMAP.md (неотмеченные UI-задачи)

| # | Задача | Источник |
|---|--------|----------|
| 3 | Полный блок ASE 2016 градации в UI | `ROADMAP.md` — `[ ]` |
| 4 | CSV / JSON export отчёта (`ReportService`, Этап 2) | `ROADMAP.md` — `[ ]` |
| 5 | Переключатель компоновки 2D \| Doppler в SystemBar | `ROADMAP.md` — `[ ]` |
| 6 | Doppler auto-trace | `ROADMAP.md` — `[ ]` |
| 7 | Автоматические цепочки производных Doppler | `ROADMAP.md` — `[ ]` |
| 8 | Side-by-side viewer + MasterClock | `ROADMAP.md` — `[ ]` |

---

## 3. Незначительные замечания (код-сенс, не баги)

- `src/echo_personal_tool/ui/summary_table.py:19-20` — изменяемые атрибуты класса `_ROW_VIEW`, `_STATUS_MARKS` (ruff `RUF012`). Сейчас не мутируют, дефект не вызывает, но стоит оформить как `typing.ClassVar`.

---

## 4. Что проверено и работает хорошо

- `ruff` с проектными правилами (`E, F, I, UP, S110, T201`) — ошибок нет.
- Нет `bare except` в коде интерфейса.
- Все лямбда-подписки на сигналы Qt используют корректный захват по умолчанию (`i=index`, `key=section`) — нет classique «поздней привязки» в циклах.
- `MainWindow.closeEvent` тщательно обрабатывает активные загрузки, M-mode, несохранённые измерения и корректное завершение работы.
- Код интерфейса документирован с ссылками на спецификацию UI-редизайна (UI-1 … UI-9, spec §4.1–§11).

---

## 5. Рекомендации по приоритетам

1. **Исправить `ConstructorDialog.closeEvent`** — проверять результат `save()`, оборачивать в `try/except`, не закрывать диалог при неудачном сохранении (риск потери данных клинического справочника).
2. **Доделать импорт Excel** — реализовать слияние тем/патологий в `ReferenceModel` + `ConstructorWidget.import_excel`, убрать ложное `_mark_dirty()`.
3. **Поправить `mousePressEvent` конструктора** — искать строку заголовка по имени/типу, а не через первый `findChild(QWidget)`.
4. **Внести в бэклог** невыполненные пункты ROADMAP (ASE 2016, экспорт отчётов CSV/JSON, переключатель 2D/Doppler, Doppler auto-trace).
