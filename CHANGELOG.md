# CHANGELOG — SonoForge

Все значимые изменения в хронологическом порядке. Формат: `[feat/fix/refactor/perf/docs/chore]: описание` (コミット-конвенция).

---

## 2026-09-11 — STE: почему доверие подтверждает замыкание, а не NCC (и восстановление после перезапуска)

### Bench
- `bench(ste)`: новый харнесс `bench/ste_trust_flags.py` сталкивает двух кандидатов в «флаги доверия» —
  круговой проход и NCC — против точной кинематики фантома. Результат (окно ЭД–ЭС, 0.45 мм/px):
  **собственный порог недействительности NCC (0.3) не срабатывает ни разу** на 40/20/10 дБ, а более
  строгий 0.7 на 20 дБ даёт p95 3.42 мм у «доверенных» против 3.64 мм у помеченных (не разделяет
  группы); замыкание разделяет на всех уровнях (1.06 против 4.57 мм на 40 дБ; 19.44 против 34.29 мм
  на 10 дБ при recall 0.77 к ошибке >2 мм). Харнесс воспроизводит долю QC до десятых (4.8/6.2/80.7 %),
  т.е. измеряет именно тот флаг, что стоит в отчёте. Вывод зафиксирован в
  `docs/STE_TRACKING_VERIFICATION.md` §3: NCC в отчёте — fidelity, а не подтверждение слежения.

### Fix
- `fix(env)`: в пересобранном окружении `pip install pylibjpeg*` подтянул numpy 2.x, вопреки
  `pyproject.toml` (`numpy>=1.26,<2.0`). Симптом: числа бенчей «поехали» без единой правки кода —
  ошибка эндокарда p95 на 20 дБ читалась как 4.55 мм вместо 3.38 мм. Причина устранена подбором
  версий декодеров, совместимых с numpy 1.26 (`pylibjpeg-libjpeg 2.2.0`, `pylibjpeg-openjpeg 2.2.1`);
  `pip check` чист, все три бенча после починки воспроизводят прежние значения буквально.
  Версии окружения, при которых числа в `docs/STE_TRACKING_VERIFICATION.md` воспроизводимы,
  зафиксированы в документе.

### Chore
- Восстановление после перезапуска песочницы: репозиторий откатывался к базе — все 20 STE-коммитов
  восстановлены из origin, дерево сверено по хешам файлов. Потеряно было только неотслеживаемое:
  `.venv` (пересобран и доукомплектован по `pyproject.toml`, включая `pylibjpeg*`, `jsonschema`,
  `openpyxl`, `keyring`, `pytest-qt`, `pytest-benchmark`), `bench/reports/*.json` (в `.gitignore`,
  перегенерированы) и скрипты в `/tmp` — вывод калибровки про NCC жил только там, поэтому он
  восстановлен **как отслеживаемый харнесс**, а не как заметка.

---

## 2026-09-11 — STE: соответствие EACVI/ASE и метки недостоверного слежения

### Feat
- `feat(ste)`: **недостоверное слежение видно на изображении** (клинический вариант 1).
  Для кадра на экране узлы, которые круговой проход не подтвердил, помечаются красным крестом,
  узлы без вердикта — жёлтым кружком; в углу — счётчик. Подтверждённые узлы не помечаются, так что
  метки читаются как «здесь числу нельзя верить», а не как фон: на 40 дБ это 7 меток из 144 узлов
  на кадре, на 10 дБ — 52. Порог метки берётся из `StrainResult.closure_gate_px` (тот же, которым
  пользовался отчёт), поэтому overlay не может разойтись с QC. Скриншоты:
  `docs/screenshots/ste-tracking-verification-{clean,noisy}.png`.
- `feat(ste)`: **отчёт объявляет то, без чего GLS не сопоставим** (Voigt 2015, EACVI/ASE):
  протяжённость ROI (`sampling_kernel_mm`, `sampling_node_spacing_mm`), компенсация трансляции ЛЖ
  (`translation_compensation_applied`), применённая регуляризация (`regularization`: метод,
  пространственное/временное окно, фильтр Савицкого–Голея) и частота кадров (`frame_rate_hz`).
  Всё это уходит в `StrainAnalysis.sampling`, в JSON исследования (`definitions.comparability`)
  и в CSV (`# ROI sampling`, `# Regularization`, `# LV translation compensation`, `# Frame rate`).
- `feat(ste)`: глобальные `# ESS` и `# Peak strain` добавлены в CSV (раньше ESS был только
  по сегментам); при частоте кадров вне рекомендованных 40–100 Гц отчёт добавляет примечание
  («frame rate N Hz is outside the recommended 40-100 Hz for deformation imaging»).
- `docs(ste)`: в `docs/STE_TRACKING_VERIFICATION.md` добавлена матрица соответствия
  рекомендациям EACVI/ASE Task Force: 14 пунктов закрыто, 3 открыто (правка границ сегментов,
  инверсия/флип изображения, пользовательский контроль окна сглаживания), 1 — принципиальное
  ограничение 2D (через-плоскостное движение).

### Fix
- `fix(ste)`: `TextItem.setText(..., size=...)` — неверный API pyqtgraph; шрифт подписи задаётся
  через `setFont` (поймано тестом до коммита).

---

## 2026-09-11 — STE: достоверность межкадрового слежения за контурами (вопрос 6)

### Feat
- `feat(ste)`: **доказательство вместо просьбы о доверии.** Новый проход
  `speckle_tracking.verify_trajectory_closure()` сопоставляет каждый анализируемый кадр
  **итоговой** траектории (после интерполяции, ремонта выбросов и сглаживания — то есть той,
  которую рисует overlay и по которой считается strain) назад к конечно-диастолическому кадру;
  расстояние, на которое круговой проход не замыкается на нарисованный контур, — это собственная
  оценка ошибки трекера, не требующая истины. Раньше такая проверка существовала только внутри
  `track_cine_bidirectional`, только на сырых совпадениях и только как флаг валидности, а не как
  число в отчёте. Решение отклонённого прохода **не меняет позиции и NCC** (проверено A/B:
  обнуление NCC заставляло worker интерполировать отклонённые кадры и стоило 2.5 п.п. смещения
  при 20 дБ) — флаг остаётся экраном достоверности.
- `feat(ste)`: единая константа `verification_gate_px()` = `0.5 × max(search_radius, 24)`:
  worker, bench-харнесс и сам проход судят замыкание по одному правилу (до правки гейт зависел от
  выбранного режима трекинга: 4 px на `sequential` против 12 px на `bidirectional`).
- `feat(ste)`: отчёт получил `qc_closure_median_mm`, `qc_closure_p95_mm`, `qc_rejected_fraction`,
  `qc_unverified_fraction`; ворота — >10 % отклонённых или >30 % кадров без вердикта → `review`,
  >25 % отклонённых → `invalid`; `confidence` умножается на `1 − 0.5·min(max(rej, unver)/0.5, 1)`.
  Ключ `strain.qc.reason.tracking_verification` (ru+en) и строка в meta strain-окна
  «проверка: подтверждено X % точек контура, замыкание Y мм».
- `fix(ste)`: QC перечисляет **все** найденные причины, а не только жёсткие — раньше hard failure
  скрывал остальные (клип, который и не подтверждается, и противоречив внутри себя, показывал одну
  причину).

### Измерения (фантом, `bench/ste_contour_tracking.py`)
- Точность контура относительно точной кинематики (endo, p50/p95/max мм): 40 дБ 0.43/1.72/2.36,
  20 дБ 0.72/3.38/4.10, 10 дБ 8.19/30.33/39.13; `long_axis` 20 дБ 0.41/1.06/2.58; `gradient` 20 дБ
  0.73/1.56/2.15. Отклонено круговым проходом 3.4–6.1 % кадров-узлов на чистых вариантах и
  65.6–80.6 % на 10 дБ.
- Качество самого флага (precision/recall к истинной ошибке): на 10 дБ >2 мм — 0.95/0.69,
  >5 мм — 0.86–0.89/0.77–0.95; на 20/40 дБ recall низкий (0.10), потому что ошибки там в основном
  ниже разрешения гейта (~5 мм). Флаг — **высокоточный экран, а не полный детектор**.
- Ограничение (важно для клиники): проверка использует нарисованный контур КД как эталон, поэтому
  она **слепа к ошибке самой ручной обводки**. Сдвиг эндокардиального контура на ±2 мм даёт
  −2.1/+6.6 п.п. смещения GLS при `review`, на +4 мм — +8.1 п.п. **при `valid`**: качество
  межкадрового слежения и правильность обводки КД — разные вещи, и отчёт не должен их смешивать.

---

## 2026-09-11 — STE: честность при потере видимости стенки (вопрос 4)

### Fix
- `fix(ste)`: **часть миокарда вне сектора больше не измеряется молча.** Если верхушка (или любая стенка)
  уходит из видимой области, блок-матчинг не «теряет» узел: он прижимается к границе данных, где пустой
  патч даёт NCC 1.0 — поэтому ни NCC, ни «покрытие» потери не замечали. Замер на фантоме (истина −19.51 %):
  срез верхушки на строке ≥136 давал GLS **−11.45 %** (смещение +8.1 п.п.) при `qc_status='valid'` и
  coverage 1.00; 1.7 % кадров-узлов вне поля зрения смещали GLS на +4…+8 п.п.
  Новый модуль `domain/services/wall_visibility.py` считает для каждого узла и кадра, видна ли под ним
  ткань: патч должен целиком лежать в кадре, медиана патча — быть выше порога данных (2 % от максимума
  клипа, что отличает пустую зону вне сектора от тёмных минимумов спекла), текстура — не падать ниже
  0.35 от её значения на КД. Узлы, потерянные более чем в 10 % кадров, **исключаются из измерения**
  (глобальная кривая, узловые и сегментные кривые считаются по одной и той же видимой части стенки), а в
  отчёт добавлены `qc_visibility_loss`, `qc_excluded_nodes`, `qc_excluded_segments` и ключ
  `strain.qc.reason.edge_visibility`.
- `fix(ste)`: ворота отчёта — любое исключение или >2 % кадров-узлов без ткани → `review` (число выводится
  в QC), более одного исключённого сегмента вида (лимит EACVI/ASE) или >10 % → `invalid`. Оценка шума
  слежения (`qc_noise_to_signal`) по-прежнему считается по всей эндокардиальной линии, чтобы шумовой
  вердикт не зависел от фильтра видимости.
- Точность на фантоме после правки: чисто — 0.00 % потерь, `valid`; срез ≥143 → −15.88 % (2.0 %, `review`);
  ≥136 → −15.91 % (6.0 %, `review`, было −11.45 и `valid`); ≥120 → −8.55 % (`invalid`, сегмент исключён).
  20 дБ/чистые варианты не изменились (GLS −19.51/−19.53, `valid` 0.89/0.90), bench: 15 KPI-провалов, все на
  строках, уже помеченных `invalid`/`review`.

---

## 2026-09-11 — STE: ручной эпикард как у Simpson LV, толщина миокарда при гипертрофии

Ветка `arena/01a08cb0-sonoforge`. Разбор вопросов клинического ревью, срез 1.

### Fix
- `fix(ste)`: автосозданный эпикардиальный контур (`ensure_lv_epicardial_contours`) больше не
  «безымянный» замкнутый контур, а **открытая дуга со своими landmark'ами** (mitral annulus +
  apex). Из-за отсутствия landmark'ов он считался закрытым, и общая механика редактирования
  молча пропускала всё: узел после перетаскивания оставался на новом месте, соседние узлы не
  подтягивались, шаг узлов становился неравномерным (измерено: 1 из 32 узлов двигался, шаг
  2.82/7.56 px, ratio 2.69) и контур рисовался 256-точечным сплайном, замкнутым через хорду
  митрального кольца. Теперь как у контура ЛЖ при Simpson: 30/32 узлов следуют за узлом
  (ratio шага 1.01), концы кольца закреплены, после перетаскивания выполняется переразбиение
  дуги и магнитный snap. Экспорт/зона это не меняет: `create_myocardial_zone` и трекер границ
  и так трактуют эпикард как открытую дугу.
- `fix(ste)`: толщина миокарда в настройках STE — диапазон **5.0…25.0 мм** (было 6.0…12.0),
  с подсказкой: фокальную гипертрофию (сигмовидная перегородка) задают, перетаскивая узлы
  эпикарда, потому что зона измеряется по нарисованному эпикарду поузлово. Последняя
  подтверждённая в диалоге толщина запоминается и используется для автоэпикарда новых видов.

### Notes
- Проверено измерением на фантоме, что такое поведение эпикарда воспроизводится и что
  трекер/зона не зависят от признака `is_open_arc` (зона строится из точек контура).

---

## 2026-09-11 — STE UI (фаза 4): мишень AHA в стандартной ориентации, палитры, цветовая шкала, состояния сегментов

Ветка `arena/01a08cb0-sonoforge`. Первый срез UI-трека плана §6.5: мишень сегментов приведена
к виду референсов GE/EchoPAC — на ориентир, а не «как получилось» (до этого anterior стоял не
на вершине, значения уезжали под цифры, шкалы не было вовсе, а невычисленные сегменты
закрашивались правдоподобным цветом).

### Features
- `feat(ste-ui)`: **стандартная ориентация AHA** — segment 1 (basal anterior) по центру 12 часов,
  кольца по часовой стрелке; подписи стен привязаны к тем же центрам сегментов и не наезжают
  друг на друга и на шкалу
- `feat(ste-ui)`: **палитры мишени** `palette.ge` (по умолчанию, пороги GE: насыщенный красный
  |ε|>16 %, светло-красный 16–11, розовый 10–6, бледно-розовый 5–0, синий — положительный
  ε), `palette.deformation_plus` (одноцветная, различима при дальтонизме), `palette.rainbow`,
  `palette.monochrome`; переключение клавишей `C` и выпадающим списком в панели (оба всегда
  синхронизированы)
- `feat(ste-ui)`: **colorbar** −20…+20 % с делениями 20/0/−5/−10/−15/−20, синий сверху
  (референс GE); для TTP-мишени шкала масштабируется по исследованию с «круглыми» делениями
- `feat(ste-ui)`: **состояния сегментов по плану §6.5** — диагональная штриховка «нет данных»
  (сегмент, который не измеряли, больше не закрашивается), белый слэш «исключён QC»,
  пунктирная рамка «низкая уверенность» (NCC < 0,5)
- `feat(ste-ui)`: наведение курсора — подсветка сегмента, всплывающая подсказка
  «сегмент / значение / NCC / TTP»; исправлены обрезанные минусы и наложение чисел на вершине

### Fix
- `fix(ste-ui)`: градиентная кисть colorbar протекала в последующую отрисовку — «концентрические
  окружности» заливали всю мишень вертикальным радужным градиентом (мишень, нарисованная
  поверх цветов сегментов, выглядела как неоновая заливка без связи со значениями)

### Tests
- `test(ste-ui)`: ориентация (anterior сверху по центру, кольцо по часовой), палитры и
  циклическое переключение с возвратом, метки colorbar и диапазон, hit-test/подсказки,
  штриховка/слэш/пунктир, синхронизация комбо ↔ мишень ↔ горячая клавиша `C`

---

## 2026-09-11 — STE: честная граница измеримости (F6), шумной клип больше не «измерение»

Ветка `arena/01a08cb0-sonoforge`. Закрывает шумовую часть плана §7.5: на 0–10 дБ фантома
пайплайн выдавал правдоподобное число («GLS −7 % при истине −19.9 и NCC 0.85»). Причина —
не ошибка агрегации, а физика: шум позиций удлиняет любую ломаную (`E|Δp+n| > |Δp|`), поэтому
раздувание длины дуги идёт в обе опорные длины и «уплощает» кривую деформации.

### Features
- `feat(ste)`: `arc_length_inflation_mm()` — прямая метрика раздувания длины дуги (медиана
  «сырая − сглаженная» траектория) и `arc_contraction_mm()` — измеряемое сокращение; их
  отношение `qc_noise_to_signal` показывает, во сколько раз смещение от шума меньше/больше сигнала
- `feat(ste)`: ворота честности в `assess_tracking_quality` — `noise_to_signal > 1.0` ⇒ `invalid`,
  `> 0.35` ⇒ `review`, ключ `strain.qc.reason.tracking_noise` (ru+en); метрика видна в UI/экспорте
  (`qc_noise_mm`, `qc_noise_to_signal` в `StrainResult` и `StrainAnalysis`)
- `feat(bench)`: отчёт фантома разделяет «ворота не пройдены на клипе, который помечен
  невалидным» и «ворота не пройдены на клипе, который выдан за измерение» (SILENT) — второе
  и есть дефект

### Results (быстрая матрица, 20 вариантов)
| SNR | uniform | long_axis | gradient | rigid | zero |
|---|---|---|---|---|---|
| 20 дБ | valid 0.89 (bias +0.39) | valid 0.91 (−0.02) | valid 0.87 (−1.50) | review 0.75 | review 0.75 |
| 10 дБ | **invalid** (ratio 3.5) | review (0.95) | **invalid** (14.7) | invalid | invalid |
| 5 дБ | **invalid** (4.7) | invalid | invalid | invalid | invalid |
| 0 дБ | **invalid** | invalid | invalid | invalid | invalid |

Прогон: `variants 20 | evaluated 20 | KPI failures 15 | gate failures on results reported as valid: 0`.
Чистые клипы проходят все ворота §3.7; шумные — больше не выдаются за измерения. Улучшение
самих SNR оставлено как отдельная задача (§8 плана, многошкальное совмещение).

## 2026-09-11 — STE: закрытие F2/F4/F7/F8/F9/F10, фантом проходит ворота §3.7

Ветка `arena/01a08cb0-sonoforge`. План: `docs/STE_IMPROVEMENT_PLAN.md` §7.2 (состояние), §7.5 (F1–F10).
Первый прогон, где **чистая** быстрая матрица фантома выполняет все ворота §3.7, а QC честно оценивает
шумные клипы.

### Features
- `feat(ste)`: **клинический пик** — `compute_strain_metrics` ищет пик систолического укорочения
  (ED … AVC + 50 мс), а не экстремум всего цикла: диастолический артефакт слежения больше не выдаётся за
  GLS/сегмент (жёсткий фантом: сегментный RMS 8.61 → 2.13 п.п.). Постсистолическое укорочение выделено в
  отдельные поля `post_systolic_peak` / `post_systolic_index` / `is_post_systolic`
- `feat(ste)`: **узловая база — физическая длина** (`compute_node_longitudinal_curves(target_length_mm=10)`):
  окно узла растёт до 10 мм по ED и фиксируется на все кадры, вместо фиксированного числа узлов (у аннулуса
  соседи стояли в ~1.5 мм, где шум в 0.3 px даёт проценты деформации)
- `feat(ste)`: **временной ФНЧ кривых** — `smooth_curves_time()` (Savitzky–Golay, `SpeckleConfig.curve_smoothing_frames=9`):
  метрики читаются со сглаженной кривой, форма внутри систолы сохраняется
- `feat(ste)`: **честная физиология** в `assess_strain_plausibility` — жёсткий отказ только там, где кривая
  *растягивается* в систолу (удлинение/истончение), а «нет укорочения» (акинезия, жёсткий фантом) —
  мягкое замечание с переводом результата в `review`, а не в `invalid`

### Bug Fixes
- `fix(ste)`: **окно поиска не расширялось на бордер-путь** (F9): `search_radius ≥ 24` применялся только к
  `incremental`/`bidirectional`, поэтому фантом шёл по ветке `border` → bidirectional с радиусом 8 и
  аннулярное смещение обрезалось (GLS терял ~11 п.п.). Введён `tracking_path` до расширения радиуса
- `fix(ste)`: **стационарный кламп стенки** (F2) — `SpeckleConfig.wall_clamp=False` по умолчанию (полоса
  строится по ED-геометрии и срезает систолическое смещение эндокарда: bias +5.6 → +0.4 п.п.); функция и
  её тесты сохранены для A/B
- `fix(ste)`: **устойчивость длины дуги к одиночным выбросам** (F8) — `repair_outlier_columns()` (медиана ±2
  соседей, порог media + 4·1.4826·MAD, ≤3 замены на кадр) после интерполяции; отрыв одной колонки при
  NCC 1.00 давал +75.97 п.п.
- `fix(ste)`: `window_node_curves` инициализируется до ветки расчёта — устранён `UnboundLocalError` в
  отчётах, где сегментные кривые не строились

### Tests
- `test(ste)`: ворота KPI ужесточены до плана §3.7 — `|ΔGLS| ≤ 1.0 п.п.` (было 7.0), строгие `xfail`
  переведены в обычные проверки («жёсткое движение», «QC не скрывает большую ошибку»), добавлены
  `test_quality_is_valid_when_the_measurement_is_good`, `test_incoherent_estimates_are_flagged`,
  `test_diastolic_dive_is_not_the_peak`, `test_flat_curve_is_reported_but_not_impossible`,
  `test_material_window_has_a_physical_length`
- `test(ste)`: устаревшие моки `compute_aha_segment_strain` удалены из `test_worker_speckle.py` и
  `test_ste_qc_honesty.py` (символ больше не вызывается воркером)

### Results (быстрая матрица, `bench/reports/ste_phantom_quick.json`)
| вариант (20 дБ) | GLS | истина | bias | сегментный RMS | QC |
|---|---|---|---|---|---|
| uniform | −19.51 | −19.90 | +0.39 | 1.72 | valid 0.90 |
| long_axis | −19.53 | −19.51 | −0.02 | 1.07 | valid 0.91 |
| gradient 0.9 | −10.55 | −9.04 | −1.50 | 2.00 | valid 0.90 |
| rigid 10°+(15,−15) | −0.41 | 0 | −0.41 | 1.84 | review 0.75 |
| zero (decor 0.6) | −0.44 | 0 | −0.44 | 2.39 | review 0.75 |

Все ворота §3.7 на чистом уровне выполнены (GLS 1.0/2.0/0.5, сегменты 2.5, TTP 1 кадр). Шум 0–10 дБ:
GLS/сегменты деградируют (0 дБ — клип неотслеживаем), статус честно `invalid`/`review`.

## 2026-09-11 — STE: фантомная валидация (перед UI-фазой 4)

Ветка `arena/01a08cb0-sonoforge`. План: `docs/STE_IMPROVEMENT_PLAN.md` (§7.1–7.2 — фантом и инварианты,
§7.5 — находки, §5.2 — состояние).

### Features
- `feat(ste-phantom)`: `tests/fixtures/ste_phantom.py` — кинематический фантом с точным эталоном:
  апикальная позиция (апекс закреплён, кольцо опускается), фон статичен, деформация двух видов
  (`uniform` — точная однородная, `long_axis` — физиологичная с градиентом apex↔base и окружным
  компонентом), режимы `rigid`/`zero` для проверки инвариантов; имитация изображения — спеклы (Rayleigh),
  яркость стенки/полости/фона, спекулярные линии эндокарда/эпикарда/кольца, прогрессирующая декорреляция,
  out-of-plane, шум 0/5/10/20 дБ. Эталон: узловые/сегментные кривые, ESS, пик, TTP, дрейф, траектории,
  карта сегментов; `to_dict()` для отчётов
- `feat(ste-phantom)`: `bench/ste_phantom.py` — прогон матрицы (режим × шум) через реальный
  `SpeckleTrackingWorker` с проверкой ворот §3.7 и JSON-отчётом (`bench/reports/ste_phantom_quick.json`)
- `test(ste-phantom)`: `tests/unit/test_ste_phantom.py` — 18 инвариантов (round-trip карты изображения,
  точность однородного режима, нулевая деформация при жёстком движении, физиологичность профиля,
  apex↔base градиент, независимость от якоря, детерминизм, следование спеклов за материалом) + KPI-прогон
  через worker; 2 строгих `xfail` фиксируют открытые дефекты (жёсткое движение вне окна поиска, QC `valid`
  при ошибке 15 п.п.)

### Bug Fixes
- `fix(ste)`: **окно поиска блока было меньше самого ядра** — `block_match_single` вырезал окно
  `center ± search_radius`, поэтому реальный диапазон составлял ±(search_radius − kernel_size/2), т.е.
  ±2 px при дефолтных 8 px; движения быстрее 2 px/кадр обрезались по краю окна при умеренно высоком NCC
  (это и есть «качество высокое, GLS неверен»). Окно расширено на половину ядра; на фантоме истинное
  смещение (−9.8, 8.0) px теперь находится как (−9.8, 7.7) вместо (1.2, −1.3)
- `fix(ste)`: **клиническое определение деформации** — все кривые считаются как Lagrange strain
  `(L−L₀)/L₀·100 %` (`lagrangian_strain_pct()`), прежний Green–Lagrange `0.5((L/L₀)²−1)` занижал |ε| на
  ~2 п.п. при −20 % (истинно аномальные −16 % читались как −14.7 %, т.е. «норма»); нулевая/NaN-длина даёт
  NaN, а не выдуманный ноль

### Tests
- `test(ste)`: устаревшие ожидания приведены к клинической модели — `test_strain_node_curves.py`
  (значения Green–Lagrange → Lagrange, инвариант согласованности определений A/B уточнён: они совпадают
  при однородном масштабировании и расходятся при локальной деформации) и `test_strain_window.py`
  (палитра GE/EchoPAC вместо «красный/белый/синий», 18 сегментов вместо 17, добавлена проверка палитры TTP)

### Findings (открытые, §7.5 плана)
- `docs(ste)`: стационарный кламп стенки (`inward_slack=1.4`, ED-геометрия) срезает ~28 % измеренной
  деформации (bias +5.60 п.п. на однородном фантоме −19.9), при этом 41 % кадро-ядер всё равно выходят
  за истинную стенку
- `docs(ste)`: жёсткое движение, выходящее за окно поиска, превращается в деформацию (+12.6 п.п. при
  трансляции 30 px, +26.8 п.п. при ротации 25° + сдвиге 25 px, истина 0.0)
- `docs(ste)`: QC может сообщить `valid` при ошибке GLS 15.3 п.п. (10 дБ + декорреляция) — проверка
  качества должна смотреть метрики, а не только NCC
- `docs(ste)`: сегментные значения расходятся сильнее глобального (RMS 9.0 п.п. при 20 дБ), ворота §3.7
  (2.5 п.п.) пока не выполняются

---

## 2026-09-10 — STE: вывод модуля на клинический уровень (фазы 0–3)

Ветка `arena/01a08cb0-sonoforge`. План: `docs/STE_IMPROVEMENT_PLAN.md` (rev.4, §5.2 — состояние реализации).

### Features
- `feat(ste)`: единое определение деформации — узловые кривые Green–Lagrange по поддуге узла
  (`compute_node_longitudinal_curves`), сегментные кривые как среднее **в одном кадре**
  (`aggregate_segment_curves`), глобальная кривая из узловых (`global_curve_from_node_curves`)
- `feat(ste)`: честный QC — `domain/services/quality.py` со статусами `valid/review/invalid`,
  причинами (i18n) и confidence; NCC-достоверность отделена от валидности измерения
- `feat(ste)`: открытая апикальная дуга — `resample_open_arc()`/`resample_along_arc()`, хорда митрального
  кольца исключена из материальной линии (C1), arc-aware сглаживание и кламп
- `feat(ste)`: 18-сегментная AHA-карта по длине дуги и виду (`domain/services/segment_map.py`),
  A4C 3/9/15+6/12/18, A2C 1/7/13+4/10/16, A3C 2/8/14+5/11/17; вид протянут worker → controller → UI
- `feat(ste)`: клинические метрики полного цикла (`domain/services/strain_metrics.py`) — окно ED→следующий ED,
  AVC с источником (ЭКГ → площадь Симпсона → пик strain → ES), GLS = пик глобальной кривой, ESS, TTP, PSI,
  измеренный дрейф базовой линии
- `feat(ste)`: модель результата с провенансом (`domain/models/ste_analysis.py`) — `StrainAnalysis` (JSON-схема,
  определения, якоря кадров, QC, сегменты, кривые) и `StrainStudy` (per-view GLS, `GLS_AV`, слияние 18 сегментов)
- `feat(ste-ui)`: мишень 18 сегментов в стандартной раскладке с палитрой GE/EchoPAC (ярко-красный = норма),
  переключатель на карту TTP, «нет данных» вместо выдуманных секторов, таблица с ESS/TTP/PSI/дрейфом,
  строка GLS AV, мета-строка с видом, источником AVC и предупреждениями
- `feat(ste-export)`: экспорт JSON/CSV с блоком провенанса (определения, якоря, QC, значения сегментов,
  TTP/ESS, источник вида, GLS и GLS_AV)

### Tests
- `test(ste)`: `test_strain_node_curves.py`, `test_ste_quality.py`, `test_ste_single_source.py`,
  `test_ste_segment_map.py`, `test_ste_strain_metrics.py`, `test_ste_study_analysis.py`

---

## 2026-08-23

### Features
- `feat(tools)`: vessel stenosis measurements — %D (by diameter) and %S (by area) tools in Vessels section; tool panel fixes: BSA label alignment, custom tab scroll arrows with visibility logic, Properties tab translated to RU, stenosis label preview shows D1/D2, %S recalculation on contour edit, results renamed to `%D стеноз`/`%S стеноз`
- `feat(interface)`: Qt interface animations module — accordion chevrons, panel slides, tab crossfade, button feedback, status bar slide, skeleton pulse (`ui_animations.py`)
- `feat(reference)`: hover micro-interactions + lightbox scale animation
- `feat(reference)`: smooth pathology viewer animations — tab fade transitions, active state sync

### Fixes
- `fix(reference)`: white flash eliminated, tab-switch flicker reduced, theme sync, image zoom, contrast, transition timing
- `fix(dark-theme)`: VS Code Dark selection color preserved; new `accent_selected` color for selected menu items
- `fix(tool_panel)`: simplified tab crossfade prevents widgets stuck at opacity 0
- `fix(measures_menu)`: broken chevronRotation Q_PROPERTY animation replaced with simple chevron text swap
- `fix(dialog)`: RuntimeError guarded when emitting signals on deleted QObject
- `fix(ui_animations)`: missing QStatusBar import

---

## 2026-08-22

### Features
- `feat(reference)`: new parameter groups — vascular, thyroid, kidney, abdominal aorta, lymph nodes (+1073 lines, `docs/new_reference_parameters.yaml`)

### Refactor
- `refactor(reference)`: pathology gradations removed for anatomy sections, duplicate labels fixed

### Tests
- `fix(test)`: GC frozen during each test to prevent coverage segfault; stale `get_theme_palette` mock removed; BSA overlay tests updated
- `style`: ruff format (7 files)

---

## 2026-08-21

### Features
- `feat(design)`: DESIGN.md VUNO palette applied to main window
- `feat(viewer)`: vessel sensitivity overlay for auto-trace preset control
- `feat(reference)`: regurgitant fraction for MR/AR, pulmonary hypertension echo signs, 3D LVEF/SVi norms; preload dialog, full-name tooltips, norm columns hidden when gradations present
- `feat`: constructor light theme, web refs 4-theme CSS, BSA restore, STE smoothing overlay

### Refactor
- `refactor(references)`: LV mass + geometry merged, empty-parameter rows removed, pathology_desc rows dropped, missing gradations added

### Fixes
- `fix(reference)`: AS/AR/TR/PR gradations restructured, single norm column, diastolic name duplication fixed
- `fix(presentation)`: broken tables, tab contrast, theme refresh (web view palette)
- `fix(playback)`: short cines prefetched fully — looping and rewind restored
- `fix(doppler)`: 2-click manual calibration wizard restored, time scale kept on reset

---

## 2026-08-20

### Releases
- `feat(release)`: v0.2.4 — `--version` flag and status bar version label

---

## 2026-08-19

### Features
- `feat(reference)`: web-first dialog with inline edit mode
- `feat(reference)`: web view redesign — lightbox modal, tooltips, live reload

### Fixes
- `fix(reference)`: OpenGL contexts shared with QtWebEngine, double-click interval restored

---

## 2026-08-18

### Features
- `feat(ui)`: BSA row in measurement panel, context menu Edit, hover animations, i18n fixes
- `feat(reference)`: inline editing in Qt view + web view loading fix

### Fixes
- `fix(playback)`: frame-skip jumps on large RGB cines prevented (forward-arc eviction, continuous prefetch tail)
- `fix(doppler)`: manual velocity calibration takes priority over auto-detection
- `fix(roi)`: false-positive Doppler ROI rejected on bright B-mode frames
- `fix(area)`: completed contour persisted in area-compare mode
- `fix(ui)`: shorter double-click interval for faster contour point placement
- `chore(logs)`: startup debug print and multi-study warning dropped

---

## 2026-08-17

### Features
- `feat(reference)`: web-based structured reference viewer (QWebEngineView) with Qt fallback — bridge polling, retry-loop init, `setUrl` qrc loading, full content + interactions
- `feat(reference)`: interactive column resizing for all tables

### Fixes
- `fix(reference)`: signal emitted in `setCurrentRow`, test attribute name fixed

### CI/CD
- `ci`: ruff pinned to 0.16.0; format fixes after main merge

---

## 2026-08-16

### Features
- `feat(reference)`: unified table with color-coded gradations, no-scroll layout; sex radio buttons removed — both norm columns always shown
- `feat(constructor)`: Excel-like context menu (insert/delete/merge/split cells), gradation-aware preview, toolbar consolidation
- `feat(data)`: `ParameterGradationRef` model + gradation data for all parameters in YAML
- `feat(lav)`: LA volume auto-segmentation and contour edge snap (#51)
- `feat(doppler)`: velocity scale auto-calibration on single baseline click (#45/#50)
- `perf`: adaptive FrameCache memory budget + async `release_stale_sessions` (#40/#43/#49)
- `fix(orthanc)`: download reliability — error propagation, thread-local clients, exponential backoff, interruptible sleeps (#44/#48)
- `fix(ci)`: orthanc dialog teardown segfault + properties panel fixes (#46/#47)

### Refactor
- `refactor(reference)`: two-column pathology panel, fixed row height, thumbnails restored, gradation names shortened, table panel expanded, column widths saved

### Docs
- `docs`: reference redesign design spec + implementation plan

---

## 2026-08-14

### Features
- `feat(measure)`: Simpson biplane from combined 4C+2C contours; buttons renamed, E/e′ mean label

### Fixes
- `fix(roi)`: Doppler ROI validation unified — recurring false positives prevented
- `fix(ci)`: ruff format, import sorting, flaky baseline test

---

## 2026-08-13

### Tests
- `test`: end-to-end integration tests for `autovti_region` flow

### Fixes
- `fix`: rolling median spike filter replaces fixed-threshold filter
- `fix(ci)`: FileNotFoundError and Qt event loop pollution in unit tests resolved
- `fix(autovti)`: band clear deferred, tuple return type fixed
- `fix(i18n)`: missing `layout.status_bar_mode` translation added

---

## 2026-08-12

### Features
- `feat(doppler)`: new Auto VTI (1 cycle) — two-click region selection + click-side direction detection
- `feat(doppler)`: spike filtering for Auto VTI envelope traces (clamp ±400 cm/s)
- `feat(doppler)`: inter-file measurement persistence within a study — E peak on mitral inflow file + e′ peaks on TDI file → mean E/e′ in overlay
- `feat(doppler)`: ROI skipped on B-mode without grid lines; vessel direction Up/Down toggle
- `feat`: Doppler PGmean fix + experimental features flag

### Fixes
- `fix(doppler)`: s′ПЖ (RV s′ prime) tissue Doppler measurement implemented end-to-end
- `fix(vti)`: VTI always returns absolute value
- `fix(doppler)`: auto time scale flag kept through manual velocity recalibration
- `fix`: M-mode Time/HR caliper, interval line thickness, TRpeak label, «Insufficient data» overlay removed

---

## 2026-08-11

### Features
- `feat(samsung)`: linear tick calibration for sweep speed (spacing = frequency/5), K-constant calibration builder, tick fallback auto-enables time scale for mis-tagged PW/CW
- `feat(doppler)`: baseline doubles as first velocity point — 2-click wizard
- `feat`: vendor profiles architecture + download to disk

### Fixes
- `fix(samsung)`: color-space handling, input validation, named constants
- `fix(mmode)`: auto time scale used, ms dialog skipped when present
- `fix(doppler)`: lowest dark band preferred for spectral ROI detection
- `i18n`: doppler calibration wizard hints clarified

### Docs
- `docs`: Samsung tick calibration design spec + implementation plan

---

## 2026-08-10

### Fixes
- `fix(ci)`: doppler/cache regressions from Phase A resolved, SF=1 physics guard ordering
- `test(ci)`: global QThreadPool drained after each test — Qt SIGSEGV race eliminated
- `style(lint)`: repo-wide `ruff check --fix` + `ruff format`

---

## 2026-08-07

### Fixes
- `fix`: Time/HR button starts horizontal caliper in current viewer window (no anatomical M-mode panel activation); eventFilter guard against uninitialized `_graphics`

---

## 2026-08-06

### Features
- `feat`: Orthanc study dialog — date filter (All/1/3/30 days), DD.MM.YYYY format, themed checkbox indicators, single-click expand
- `perf`: async study/series loading in Orthanc dialog — instant open, background queries (QRunnable/QThreadPool)
- `feat`: Settings dialog restructured — consolidated tabs into grouped blocks
- `feat`: ✓/✗ icons on OK/Cancel buttons + theme-contrast shortcut labels (all dialogs)
- `feat`: simplified manual Doppler calibration — baseline-first flow, ROI step skipped

### Fixes
- `fix`: file duplication prevented when loading study from Orthanc server
- `perf`: CPU usage during video playback and Windows 10 memory consumption reduced
- `perf(dicom)`: full cine released from thread-local sessions — multi-GB memory growth fixed
- `fix`: np.trapezoid compatibility, formula audit fixes, download diagnostics
- `fix`: display_form UnboundLocalError, styled_dialogs QSize bug, «Серии» error on study click
- `fix`: HTTP timeout 30→10 s; query errors surfaced instead of silent empty results

---

## 2026-08-05

### Features
- `feat(doppler)`: ECG-free cardiac cycle detection from envelope; EDV as adaptive window before systolic upstroke; median PSV/EDV averaging with per-cycle candidates
- `feat(doppler)`: cycle-selection highlight for manual PSV correction (←/→, Enter/Esc)
- `feat(doppler)`: below-baseline vessel envelopes auto-detected and traced

### Fixes
- `fix`: instance downloads retried up to 3× on transient failures
- `fix`: DICOM filename fallback decode after raw bytes freed; vessel state cleared on measurement clear
- `fix`: ECG strip height capped; ECG-sync doppler refinement, VTI units, trace label output

---

## 2026-08-04

### Features
- `feat`: vessel envelope auto-trace with sensitivity presets
- `feat`: EDV searched at diastolic minimum in Doppler auto-trace
- `feat`: ECG cardiac-cycle service + ECG-snapped PSV/EDV in vessel auto-trace
- `feat`: ECG-first CINE ED/ES detection with image fallback

### Fixes
- `fix`: on-screen text ignored in Doppler envelope auto-trace

---

## 2026-08-03

### Features
- `feat`: Vessels measurement section — PSV/EDV manual workflow: `VesselMeasurement` model, RI/S/D/MV metrics, study-session merge/filter, Measures menu section, hotkeys, report/panel integration
- `feat(doppler)`: baseline detected via visible color line (priority: line → tag → intensity)

### Fixes
- `fix`: carotid Doppler auto-calibration from Samsung correct tags
- `fix`: file extension appended in constructor/custom save dialogs
- `fix`: pixel bytes reloaded when re-opening released DICOM session
- `fix`: explicit error reported when frame save fails (silent failure on Windows)

---

## 2026-08-01

### Features
- `feat(mmode)`: maximum calibration chain — ROI tick depth detection, FrameTime fallback, parallel API to Doppler, banner with actual values + sources, M-mode group buttons in Measures menu (Time/HR, Teichholz ED/ES)
- `feat(doppler)`: Phase A — time axis first-class, no silent 1000 ms default
- `feat`: Samsung Doppler mis-tagging fix + M-mode vertical caliper

### Fixes
- `fix`: Samsung B-mode regions rejected as Doppler fallback
- `fix(viewer)`: DICOM flags preserved when rebuilding MmodeCalibrationState
- `fix(physics)`: SPATIAL_2D constant replaces magic number

### Tests
- `test(regression)`: 16 tests for maximum calibration

---

## 2026-07-31

### Performance
- `perf`: double setImage fixed, OpenGL improvements, Windows timer + playback diagnostics

---

## 2026-07-30

### Fixes
- `fix(macos)`: split Intel/Apple Silicon builds + DMG instead of zip — separate CI jobs for `macos-13` (Intel) and `macos-latest` (ARM64), `.app` bundle via BUNDLE, DMG via `hdiutil`
- `fix(ci)`: resolve CI failures — ruff F401, pixel cache test, release-drafter permissions
- `fix(i18n)`: remove dead `layout.swap` key and duplicate `research_use_only` from `en.json`

### Performance
- `perf`: memory optimization + video FPS improvements
- `perf(playback)`: fix LOW_END misclassification + optimize frame cache with bisect

---

## 2026-07-29

### Features
- `feat(measure)`: implement Area Compare tool — `%S` contour comparison с click/freehand modes

### Fixes
- `fix(measure)`: area compare — store `%S` in linear measurements, freehand/click-mode visualization fixes
- `fix(measure)`: diameter compare bugs — `%D` in overlays, `display_text`, cancel safety
- `fix(measure)`: freehand point filtering, area-compare S1/S2 vs Площадь dedup, overlay fixes

---

## 2026-07-28

### Features
- `feat(measure)`: diameter/area compare — `DIAMETER_COMPARE` и `AREA_COMPARE` в `MeasurementAction`, buttons в `MeasurementToolsPanel`, menu entries в `MeasuresMenu`
- `feat(measure)`: diameter comparison logic в `ViewerWidget` + unit tests
- `feat(measure)`: Area Compare tool — `%S` contour comparison, wire actions в `MainWindow`
- `feat(measure)`: area tool mode — `click`/`freehand` selector в preferences dialog, `area_tool_mode` preference field
- `feat(measure)`: magnetic snap для closed polygon contours (AREA/VOL) — `snap_closed_polygon` utility, Douglas-Peucker point reduction

### Fixes
- `fix(measure)`: comparison label, measurement preservation, constraint bypass
- `fix(measure)`: connect `area_compare_requested` signal к action dispatch chain
- `fix(measure)`: enable Area Compare в MeasuresMenu и revert broken signal bridge

### CI/CD
- `ci`: bump `actions/dependency-review-action` 4 → 5
- `ci`: bump `actions/upload-artifact` 4 → 7
- `ci`: bump `github/codeql-action` 3 → 4
- `ci`: bump `release-drafter/release-drafter` 6 → 7
- `ci`: bump `actions/setup-python` 5 → 7

### Style
- `style`: fix ruff formatting в 12 files

### Tests
- `test`: unit tests для diameter comparison logic

---

## 2026-07-27

### Docs
- `docs`: add demo videos и updated screenshots
- `docs`: add Disclaimer, update Installation, add status bar warning
- `docs`: fix screenshot placement в Cardiac Measurements table
- `docs`: remove screenshots из README_RU.md

---

## 2026-07-26

### Releases
- `chore(release)`: v0.2.3 — CI fixes (Windows unit tests, ruff format), macOS build + source tarball in Release workflow

### i18n
- `i18n`: translate domain layer and infrastructure to English
- `i18n`: translate presentation layer to English
- `i18n`: translate constructor module to English
- `i18n`: translate strain window and curves to English
- `i18n`: add all missing locale keys для full English translation

### Docs
- `docs`: add CODE_OF_CONDUCT.md и issue template config
- `docs`: update README и SECURITY с new features

### Features
- `feat(test)`: comprehensive verification test suite — 8 new test categories (security, regression, migration, acceptance, system, exploratory, compat, bench) с 520+ тестами
- `feat(test)`: security fuzzing — DICOM input fuzzing (truncated, corrupt, nested sequences), API response fuzzing (malformed JSON, SQL injection, XSS payloads)
- `feat(test)`: security verification — credential storage audit, HTTPS enforcement, ONNX model integrity (SHA256), PHI anonymization, network timeouts
- `feat(test)`: acceptance tests — E2E workflows: open/measure/export, Orthanc, auto-segment, strain, constructor, preferences
- `feat(test)`: regression baselines — contour, Doppler, M-mode, pixel spacing, report formatting exact-match tests
- `feat(test)`: data migration tests — gold schema versioning, backward compatibility, repair script, manifest generation, annotation merge
- `feat(test)`: exploratory testing — hypothesis property-based tests (planimeter, BSA, Simpson), input fuzzing for DICOM UIDs
- `feat(test)`: OS compatibility tests — Windows paths (Cyrillic, UNC, spaces), display server (offscreen, xcb)
- `feat(test)`: benchmark expansion — ONNX inference latency, full pipeline, gold store I/O benchmarks
- `feat(test)`: 7 new pytest markers (acceptance, security, regression, migration, system, compat, bench)
- `feat(test)`: pytest-timeout 60s per-test timeout to prevent CI hangs
- `feat(ci)`: restored full GUI test coverage in CI (removed `-m 'not gui'` from coverage workflow)

### Fixes
- `fix(ui)`: tab scroll arrows now visible in settings dialog and tool panel — replaced Unicode ◀▶ with ASCII < >, set minimumWidth(28) on QToolButton scroll buttons
- `fix(security)`: DICOM UID validator now rejects pure-dot UIDs (`...`), strings >64 chars, and dot-prefixed/suffixed UIDs per PS3.5 §6.1
- `fix(security)`: ONNX `_verify_model_integrity` now raises `ModelIntegrityError` on SHA256 mismatch instead of just logging a warning — corrupted models are no longer loaded
- `fix(test)`: ConstructorDialog.closeEvent uses `_skip_close_prompt` flag to prevent blocking QMessageBox during programmatic close (pytest-qt teardown)
- `fix(test)`: restore i18n translations after locale-loading tests to prevent suite-wide pollution (`Unknown language 'ru'` cascade)
- `fix(ci)`: macOS/Windows CI runs exclude GUI tests (`-m 'not gui'`) — no xvfb, Qt crashes with SIGABRT
- `fix(test)`: ruff formatting — 75 files auto-formatted, 185 lint errors fixed
- `fix(test)`: smoke test version mismatch (0.2.1 → 0.2.2), comprehensive import smoke tests for all modules

### Chore
- `chore`: added dev dependencies: bandit, safety, syrupy, hypothesis, pytest-timeout
- `chore`: created test directory structure: tests/{acceptance,security,regression,migration,system,exploratory,compat}/

---

## 2026-07-18

### Features
- `feat(mmode)`: Teichholz LV function calculation from M-mode calipers — 3 sequential calipers (МЖП→КДР→ЗСЛЖ) с chain-логикой, ESV measurement после подсветки, results в overlay (КДО, КСО, ФВ, ОТС, ММЛЖ, ИММЛЖ)

### Fixes
- `fix(mmode)`: fix Teichholz overlay integration — use `app_controller._current_study_uid`, store measurements as LinearMeasurement objects

### Refactor
- `refactor`: replace commercial brand names (Standard, Research, Device, GE, Clinical) с generic-названиями в коде и документации
- `refactor`: rename `echopac_theme.py` → `dark_theme.py`, functions → `apply_clinical_theme`, `build_clinical_stylesheet`, `preset_standard`, `preset_research`

### Chore
- `chore`: project cleanup for trial release — удалены debug-логи, old/, orphan-директории, backup-файлы, кэши
- `chore`: dependencies fix — добавлены pyyaml, jsonschema, onnxruntime, reportlab, openpyxl в required; убран black; hatch version source
- `docs`: update README — актуализация возможностей, требований, установки
- `docs`: update ROADMAP — хронология major changes (июнь–июль 2026)
- `fix`: update tests for renamed methods (preset_standard → preset_standard, preset_research → preset_research)

---

## 2026-07-17

### Fixes
- `fix(constructor)`: save/reload + focus + validation + Enter key

---

## 2026-07-16

### Features
- `feat(mmode)`: smooth expand/collapse animation + 50% taller panel

### Fixes
- `fix(mmode)`: rebuild layout on deactivation + sweep speeds 25/37.5/50
- `fix(mmode)`: restart scan line placement after file switch
- `fix(mmode)`: reset M-mode on file switch — stop playback, clear scan line, clear buffer

### Docs
- `docs`: add LV-geometry, LA_volume, LV_linear_sizes images to references

---

## 2026-07-15

### Features
- `feat(mmode)`: post-processing pipeline — brightness, gamma, stronger smoothing (reverted)
- `feat(mmode)`: post-processing on frozen frames + sliders control M-mode strip (reverted)

### Fixes
- `fix(mmode)`: ensure tool_panel visible after M-mode deactivation
- `fix(mmode)`: find viewer index before reparenting to vertical splitter
- `fix`: remove stale vertical_lock_toggled connection + downgrade diagnostic logs to debug

---

## 2026-07-14

### Features
- `feat(mmode)`: heart rate (ЧСС) в horizontal measurement label
- `feat(mmode)`: horizontal lock для horizontal measurement + guide lines preview
- `feat(mmode)`: vertical lock + guide lines для vertical measurement
- `feat(mmode)`: perpendicular guide lines во время vertical lock mode
- `feat(mmode)`: vertical lock toggle button к MModeWidget

### Fixes
- `fix(mmode)`: simplify deactivate — directly manipulating splitter вместо full rebuild
- `fix(mmode)`: use detected depth ticks (5cm intervals) для depth calibration
- `fix(mmode)`: use vertical depth (dy × row_spacing) вместо Euclidean distance

---

## 2026-07-13

### Features
- `feat(mmode)`: measurement tools — vertical (depth), horizontal (time), arbitrary с guide lines к axes
- `feat(mmode)`: smart smoothing — log compression + spatial Gaussian + temporal EMA

### Fixes
- `fix(mmode)`: scale ImageItem к physical units чтобы axes показывали реальные mm/ms
- `fix(mmode)`: update image rect когда sweep speed меняется чтобы X axis rescale
- `fix(mmode)`: use M-mode specific calibration для depth axis
- `fix(mmode)`: use both X и Y pixel spacing для depth calibration
- `fix(mmode)`: store view ref чтобы properly remove old caliper nodes

---

## 2026-07-12

### Features
- `feat(mmode)`: show first caliper point с preview, allow multiple calipers в session
- `feat(mmode)`: close button (×) к M-mode panel
- `feat(mmode)`: DICOM calibration — vertical axis cm (from pixel_spacing), horizontal ms (from frame_time)
- `feat(mmode)`: status bar hints для M-mode activation и scan line placement

### Fixes
- `fix(mmode)`: complete anatomical M-mode implementation с integration tests
- `fix(mmode)`: C++ object lifecycle в activate/deactivate
- `fix(mmode)`: extract columns durante playback (show_frame_fast)
- `fix(mmode)`: use _rebuild_layout() на deactivate

---

## 2026-07-11

### Features
- `feat(mmode)`: MModeCaliperTool для distance/time measurements
- `feat(mmode)`: connect M-mode extraction pipeline в AppController и MainWindow
- `feat(mmode)`: scan line tool и column extraction к ViewerWidget
- `feat(mmode)`: vertical splitter layout toggle в MainWindow
- `feat(mmode)`: MModeWidget PyQtGraph panel с sweep display
- `feat(mmode)`: M-mode column extractor через bilinear interpolation
- `feat(mmode)`: domain models для anatomical M-mode

---

## 2026-07-10

### Features
- `feat`: StructuredReferenceWidget теперь использует tables вместо cards
- `feat`: column visibility toggles + units combined с values в reference viewer
- `feat`: reference constructor — visual editor для structured reference handbook
- `feat`: reference guide — default section, smart scaling, card layout

### Fixes
- `fix`: styled file dialogs с dark theme для navigation buttons
- `fix`: replace Unicode arrows с ASCII для лучшей font compatibility
- `fix`: validation — allow same param через gradations
- `fix`: image copy SameFileError + merge LA pathologies + restructure RV

---

## 2026-07-09

### Features
- `feat`: Properties panel показывает height, weight, BMI, frame time, frames count
- `feat`: auto-detect spectrogram ROI для Doppler fallback
- `feat`: overlay — color-coded out-of-range values + click-to-reference navigation

### Fixes
- `fix`: per-instance measurements, overlay isolation, playback reset
- `fix`: auto-fill height/weight от DICOM tags на каждом file switch
- `fix`: reference widget image scaling, context menu, gradation table
- `fix`: critical bugs + Doppler calibration overhaul

---

## 2026-07-08

### Features
- `feat(la)`: LA-2 finetune + LA-3 controller/UI + LA-4 bench
- `feat(la)`: LA-0 gold UX + LA-1 la_mask_to_contour + quality gate
- `feat(gold)`: per-instance deduplication + multi-DICOM study support
- `feat(gold)`: UI tab в preferences + ECHO_GOLD_EXPORT env var override
- `feat(lv-auto)`: commercial parity v2 — bench infra + pipeline upgrades (Phase 2a+2b)
- `feat(lv-auto)`: diagnostics generalization + temporal fusion v2 (Phase 2b.6 + 2e)
- `feat(onnx)`: debug ROI overlay — §1.4 spec

### Fixes
- `fix(gold)`: auto-update manifest.json на Save Gold
- `fix(gold)`: show 1-based frame number в save message
- `fix(gold)`: per-frame instance_path + update on merge от different file
- `fix(onnx)): temporal fusion P0+P1 — hang, wrong annulus ref, missing refine
- `fix(onnx)`: temporal fusion P2+P3 — apex ratio, alignment, i18n, G key
- `fix(onnx)`: fusion_result sync, partial early-exit, new tests
- `fix(onnx)`: cine ROI cached от first loaded frame, не только frame 0
- `fix(onnx)`: revert crop_mode к center_square + per_frame normalization

---

## 2026-07-07

### Features
- `feat(onnx)`: temporal fusion — neighbor-aware contour на frame N
- `feat(onnx)`: LV Auto quality v1.5 — per-frame segmentation improvements

### Fixes
- `fix(onnx)`: temporal fusion callback signature — mask как first positional arg
- `fix(onnx)`: v1.5 deviations — long_axis_hint, upscale_mask, spec notes

---

## 2026-07-06

### Features
- `feat`: add structured reference browser к AseReferenceDialog
- `feat`: add images для AK и LV pathologies, improve image scaling
- `feat`: multi-image support, image navigation, и real pathology images
- `feat(ste)`: Phase 11 — Save/Export Deformation Data
- `feat(ste)`: Phase 10 — Manual Kernel Correction
- `feat(ste)`: Phase 9 — Quality Control Checkboxes
- `feat(ste)`: Phase 8 — Display Mode Toggle (Deformation/SR/Peak)
- `feat(ste)`: Phase 7 — Strain Curves View
- `feat(ste)`: Phase 6 — Summary Table (clinical-style)
- `feat(ste)`: Phase 5 — Bull's Eye Plot (17-segment polar map)
- `feat(ste)`: Phase 4 — Myocardial Contour + Kernels + Labels + ECG
- `feat(ste)`: Phase 3 — Strain Window Shell + Quad-View Layout
- `feat(ste)`: Phase 2 — Quality-Weighted GLS Computation
- `feat(ste)`: Phase 1 — Quality Threshold Gate

### Fixes
- `fix(ste)`: critical blockers — n_kernels + quality gate + QC checkboxes
- `fix(ste)`: QC checkboxes — make _qc_group и _qc_layout proper attributes
- `fix(ste)`: spline degree check — prevent crash с few frames
- `fix(ste)`: use cached frames directly — avoid main thread blocking
- `fix(ste)`: auto-load all frames перед speckle tracking

---

## 2026-07-05

### Fixes
- `fix`: contextMenuEvent wrong super call + finetune experiments
- `fix`: bench — exclude 7 bad gold files + fix finetune normalisation + engine crop_mode
- `fix`: invisible checkboxes в tree widgets через все themes
- `fix`: controls slider desync + overlay persistence на file switch

### Bench
- `bench`: Add temporal smoothing к bench contour pipeline
- `bench`: Add bench report — temporal smoothing results (105 instances)
- `bench`: Add LVEF reject gate (|ΔLVEF| > 15%)
- `bench`: Add LV segmentation fine-tune script (decoder head training)
- `bench`: Improve annulus boundary snap — use MA midpoint split + wider search radius

---

## 2026-07-04

### Features
- `feat(micro-UX)`: focus/disabled QSS, reduce_motion, caliper chain, gray frame fix
- `feat`: properties panel, i18n, multiview fixes
- `feat`: DIMSE Phase 2 — C-GET, C-MOVE, DIMSE-only, TLS

### Fixes
- `fix`: DIMSE Phase 2 minor gaps — wiring, auto ping, C-MOVE SCP
- `fix`: critical issues K1-K6, properties panel, i18n, multiview

---

## 2026-07-03

### Features
- `feat`: comprehensive benchmark suite — 52 benchmarks через 6 categories
- `feat`: server profiles — save/load/delete named connection presets
- `feat`: STOW/DIMSE upload UI, live Orthanc tests, query_source persist

### Fixes
- `fix`: auto-check series на study expand — load button now enables immediately
- `fix`: DICOM Rows error, activity bar text buttons с i18n
- `fix`: benchmark cache-hit bug, add Linux/Windows comparison

---

## 2026-07-02

### Features
- `feat`: Ctrl+Scroll zoom, reference tab close, STOW batch upload, FPS benchmarks
- `feat`: i18n complete — measurement_tools, system_bar, activity_bar, tool_panel, doppler, indexed
- `feat`: references dialog rewrite, caliper fixes, auto-play guard

### Fixes
- `fix`: i18n keys — measures_menu stores keys не strings
- `fix`: references dialog — visible title bar buttons, keyboard nav, ctrl+scroll zoom

---

## 2026-07-01

### Features
- `feat`: frameless Load from Server dialog, connected caliper sequence для IVSd-LVEDD-LVPWd
- `feat`: profiling instrumentation, playback optimizations, color Doppler fix

### Performance
- `perf`: Phase 1 micro-optimizations — deque ring buffer, memoize frames, faster eviction
- `perf`: Phase 2 — RGB identity cache для color Doppler, double-next skip
- `perf`: Phase 3 — parallel DICOM batch decode, adaptive prefetch batch sizing
- `perf`: Phase 4 — small-loop full prefetch, directional scroll neighbors
- `perf`: Phase 5 — zero-copy uncompressed DICOM frame decode

---

## 2026-06-30

### Features
- `feat`: activity bar icons, auto-play, overlay context menu
- `feat`: caliper drag/release, Windows geometry, playback warm-up, overlay study-pin
- `feat`: display quality — debug overlay, smooth scaling, zoom modes
- `feat`: i18n infrastructure + partial UI translation
- `feat`: i18n bulk translation — viewer, main_window, dialogs, formatters
- `feat`: i18n app_controller speckle status messages

### Fixes
- `fix`: caliper drag correction, i18n, monochrome themes, UI fixes
- `fix`: emit decode_finished на first frame, use DicomSession в FrameLoaderWorker
- `fix`: viewer2 — independent frame navigation через FrameCache

---

## 2026-06-29

### Features
- `feat`: DICOM auto-fill patient height/weight, Play/Pause fixed width
- `feat`: frameless window — VS Code style title bar
- `feat`: VS Code layout system — 5 toggleable modes

### Performance
- `perf(dicom)`: P0 scroll — debounce, two-phase load, fast display
- `perf(dicom)`: P1 BOT index через pydicom.encaps для JPEG multiframe
- `perf(dicom)`: JPEG-2000 frame index с openjpeg и EOT support
- `perf(mp4)): keyframe index и scroll min_buffer prefetch

---

## 2026-06-28

### Features
- `feat`: context menus — save frame как JPEG/PNG с overlays, thumbnail export DICOM/MP4

### Performance
- `perf`: skip DICOM I/O durante playback, pin current frame

### Fixes
- `fix`: measurement overlay accumulation

---

## 2026-06-27

### Features
- `feat`: caliper inline labels, B-mode snap, auto depth calibration
- `feat`: cine playback prefetch pipeline — adaptive buffer, timing compensation, loop wrap

---

## 2026-06-26

### Performance
- `perf`: DICOM decode 86x faster first-frame — raw-byte extraction, cv2 fast path

### Features
- `feat`: lazy DICOM/MP4 frame decoding — instant first frame, on-demand scroll, adaptive playback

---

## 2026-06-25

### Features
- `feat`: UI improvements — theme support, STE popup, cine contour fixes
- `feat`: STE quality improvements — iterative refinement, weighted smoothing, motion model
- `feat`: STE clinical parity — progressive zone deformation, preprocessing, outlier interpolation

### Fixes
- `fix`: Orthanc multi-study download, play freeze, DICOM/MP4 performance

---

## 2026-06-24

### Features
- `feat`: NCC block-matching speckle tracking с dual-contour zone и strain computation
- `feat`: speckle tracking result storage, launch menu, overlay improvements
- `feat`: per-instance WADO-RS downloads, parallel loading, progressive decode

### Refactor
- `refactor`: replace Lamé LV contour с Bézier cubic spline (ED S-shape, ES smooth)

---

## 2026-06-23

### Features
- `feat`: DICOMweb Orthanc integration — QIDO-RS, WADO-RS, session cache, mock offline
- `feat`: Orthanc download worker, study browser dialog, server settings
- `feat`: RV FAC workflow с crescent template

### Fixes
- `fix`: Orthanc download cancel, cumulative progress, client lifecycle
- `fix`: parse series instance count от QIDO tag 00201209

---

## 2026-06-22

### Features
- `feat`: measurement workflow sprint — planimeter, ASE norms, PDF report, cine ROI
- `feat`: Orthanc DICOMweb domain DTOs и port

---

## 2026-06-21

### Features
- `feat`: merge Clinical UI в ONNX LV Auto branch
- `feat`: stabilize ONNX LV auto-contour pipeline для DICOM A4C

---

## 2026-06-20

### Features
- `feat`: measurement workflow sprint — planimeter, ASE norms, PDF report, cine ROI

---

## 2026-06-19

### Features
- `feat`: ONNX auto-segment pipeline с review_pending и LV Auto gating
- `feat`: LV Auto buttons trigger ONNX; Enter accepts AI contour
- `feat`: optional auto R-refine после ONNX segment
- `feat`: ASE papillary concavity exclusion на open arc
- `feat`: papillary mask cleanup для ONNX LV segment
- `feat`: gate Simpson на accepted AI contours через review_pending

---

## 2026-06-18

### Features
- `feat`: Phase 2 Clinical UI, ASE metrics, gradient refine, ONNX e2e

---

## 2026-06-17

### Features
- `feat`: Phase 1 MVP (#3) — viewer, ручные измерения

---

## 2026-06-16

### Features
- `chore`: record EchoNet ONNX export в model manifest

---

## 2026-06-15

### Features
- `feat`: bootstrap echo_personal_tool и DICOM viewer PoC (Phase 0 + S1)

---

## 2026-06-14

### Features
- `feat`: Initial commit
