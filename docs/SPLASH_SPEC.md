# Спецификация: Сплэш-скрин SonoForge (V4.1 compact)

**Файл**: `src/echo_personal_tool/presentation/splash.py`
**Тесты**: `tests/unit/test_splash_screen.py`
**Запуск**: `ECHO_SPLASH_COMPACT=1 uv run sonoforge`

---

## 1. Общая концепция

Сплэш — чёрная карточка по центру экрана (frameless, always-on-top, no taskbar).
Внутри: логотип (белое сердце с "SF"), крупный процент, строка загрузки модулей.
Карточка: **620×580 px** (масштабируется на маленьких экранах, factor ≥ 0.55).

---

## 2. Логотип

- Размер: **55% ширины карточки** (`self.width() * 0.55`), min 200px
- Позиция: по центру горизонтально, со смещением вверх (верхний край ≈ 88px от верха карточки)
- Заполнение: белый логотип проявляется снизу вверх через анимированную волнообразную маску (wavy mask, sine)
- При progress=100%: логотип полностью белый

---

## 3. Текст процентов ("100%")

- Шрифт: **DemiBold, 66pt reference** (масштабируется с логотипом: `66 * scale`, min 28pt)
- Позиция: **10px под нижним краем логотипа**, по центру
- Цвет: белый `rgba(255,255,255, alpha)`, где alpha растёт от 140 до 255 с прогрессом
- **КРИТИЧНО**: НЕ использовать `setStyleSheet()` для цвета — он сбрасывает шрифт на Linux. Использовать `QPalette` + `setPalette()`:
  ```python
  pal = label.palette()
  pal.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255, alpha))
  pal.setColor(QPalette.ColorRole.Window, Qt.transparent)
  label.setPalette(pal)
  ```
- **Фон метки**: ДОЛЖЕН быть прозрачным. Установить `Qt.WA_TranslucentBackground` на QLabel или `pal.setColor(QPalette.ColorRole.Window, Qt.transparent)`. Проверить визуально — никаких тёмных прямоугольников вокруг текста!

---

## 4. Текст загрузки модулей

- Шрифт: regular, 14pt reference (масштабируется: `14 * scale`, min 10pt)
- Позиция: **15px под процентами**, по центру, ширина 80% карточки
- Цвет: белый `rgba(255,255,255,115)`, фон прозрачный
- Текст: меняется каждые 600мс, циклически по списку:
  ```
  Loading models...
  Initializing DICOM engine...
  Loading ASE reference...
  Preparing viewer...
  Initializing calculators...
  Loading segmentation models...
  Preparing Doppler module...
  Building UI...
  ```
- Только английский, независимо от языка интерфейса

---

## 5. Заполнение логотипа (fill animation)

- Progress от 0 до 100% отражает реальную загрузку
- Авто-шаги: `(8, 18, 30, 44, 58, 72, 84, 92)` с интервалом 420мс
- Easing: `OutQuad`, длительность шага 650мс
- Fill и проценты **синхронизированы** — одно значение для обоих

---

## 6. Flash-эффект при 100%

**Проблема**: Белый логотип на чёрном фоне уже максимальной яркости. Невозможно сделать "ярче белого" через alpha compositing.

**Решение**: Flash — это **белый полупрозрачный оверлей** поверх **всего виджета SplashScreen** (не логотипа).

Реализация в `SplashScreen.paintEvent`:
```python
# В конце paintEvent, ПОСЛЕ всего остального:
if self._flash_overlay > 0.01:
    painter.setOpacity(self._flash_overlay * 0.45)  # max 45% белого
    painter.fillRect(self.rect(), QColor("#ffffff"))
```

Анимация flash (в `_trigger_flash`):
```python
anim = QVariantAnimation(self)
anim.setStartValue(0.0)
anim.setKeyValueAt(0.2, 1.0)   # пик через 20% времени
anim.setEndValue(0.0)
anim.setDuration(300)           # 300мс всего
anim.setEasingCurve(QEasingCurve.Type.OutCubic)
anim.valueChanged.connect(self._set_flash_overlay)
```

Ключевые атрибуты:
- `self._flash_overlay: float = 0.0` — в `__init__`
- `_set_flash_overlay(value)` — сеттер + `self.update()`
- `_flash_anim: QVariantAnimation | None = None` — предотвращает повторный запуск

Тайминг: flash стартует когда percent ≥ 100, reveal через `wait_ms + 1000` (ease 650мс + flash 300мс + пауза 50мс).

---

## 7. Закрытие сплэша

- `complete_with(main_window, on_complete)` — прыжок к 100%, затем reveal
- reveal: `QPropertyAnimation(windowOpacity)` 420мс → `_close_splash` → `deleteLater`
- Время жизни: ~3.5с (MIN_VISIBLE_MS = 3400)

---

## 8. Известные ловушки (ОБЯЗАТЕЛЬНО ПРОВЕРИТЬ)

1. **setStyleSheet сбрасывает шрифт** — НИКОГДА не вызывать `label.setStyleSheet()` в `_on_progress_tick`. Только `QPalette`.
2. **Белый по белому не виден** — flash через double-paint бесполезен. Только white overlay.
3. **Фон QLabel** — если `QPalette.ColorRole.Window` не установлен в `Qt.transparent`, метка рисует тёмный прямоугольник. Проверять визуально!
4. **`.pyc` кэш** — после правок удалять `__pycache__`:
   ```bash
   find . -path "*__pycache__*" -delete
   ```

---

## 9. Чеклист перед коммитом

- [ ] `uv run ruff check src/echo_personal_tool/presentation/splash.py tests/unit/test_splash_screen.py`
- [ ] Удалены `.pyc` файлы
- [ ] Визуально: текст "0%" крупный, без тёмного фона
- [ ] Визуально: логотип ~55% ширины карточки
- [ ] Визуально: при 100% — белая вспышка на 300мс, затем пауза, затем закрытие
- [ ] Визуально: "Loading models..." и т.д. мелким шрифтом внизу, без тёмного фона
- [ ] Тесты проходят: `uv run pytest tests/unit/test_splash_screen.py -q`
