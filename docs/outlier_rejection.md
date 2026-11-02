План: Outlier Rejection для LV контуров
1. Зачем это нужно
Текущий temporal fusion (app_controller.py:2345) сегментирует соседние ±N кадров и fuse через voting — это offline батч. Outlier rejection — online, на одном контуре: когда пользователь/авто-сегментация создаёт контур на кадре t, система сравнивает его площадь с контурами соседних кадров и предупреждает, если он аномальный.

2. Архитектура
Что меняется: Contour.phase = "ED" → Contour.phase = "ED" (без изменений).
Outlier rejection — это сервис, который получает текущий контур + коллекцию контуров соседних кадров и возвращает verdict.

3. Новый файл: domain/services/contour_outlier_detector.py
@dataclass
class OutlierVerdict:
    is_outlier: bool
    reason: str  # "area_anomaly", "shape_anomaly", "displacement"
    metric_value: float
    threshold: float
    neighbor_count: int

def detect_outlier(
    target: Contour,
    neighbors: list[Contour],
    pixel_spacing: PixelSpacing,
    *,
    area_z_threshold: float = 2.5,      # Z-score threshold for area
    dice_threshold: float = 0.7,        # min Dice overlap with neighbors
    displacement_threshold_px: float = 50,  # max centroid shift vs median
) -> OutlierVerdict:
Три независимые проверки:

Проверка	Формула	Фильтр
Area Z-score	`z =	area - median(neighbors)
Dice overlap	Dice(target_mask, neighbor_mean_mask)	Dice < 0.7
Centroid displacement	centroid_dist(target, median_centroid)	dist > 50px
Итоговый вердикт: is_outlier = True если ≥ 2 из 3 проверок провалены.

4. Что нужно для neighbors
Neighbors — контуры для того же sop_instance_uid на соседних frame_index.

Текущая проблема: контуры хранятся flat tuple (sop_instance_uid, chamber, view, phase_key) — только один на фазу. Для outlier rejection нужно больше.

Решение: хранить не только один контур на фазу, а все контуры за всё время (flat tuple, frame_index уже есть). При сохранении нового контура не удалять старые — просто добавлять.

Где менять:

StudyMeasurementSessionStore.merge_contours() (study_measurement_session.py:93) — убрать dedup/replace по phase_key, оставить dedup только если frame_index совпадает
Это единственное изменение в data model.

5. Интеграция в pipeline
A) После auto-segmentation (app_controller.py:2028 _on_auto_segment_finished)
После quality gate (explain_lv_auto_reject_reason) и до создания Contour:

if not reject_reason:
    neighbors = _collect_neighbor_contours(instance_uid, frame_index, window=5)
    if len(neighbors) >= 2:
        verdict = detect_outlier(new_contour, neighbors, pixel_spacing)
        if verdict.is_outlier:
            logger.warning(f"Outlier detected: {verdict.reason}")
            new_contour = dataclasses.replace(
                new_contour,
                review_pending=True,
                measurement_label=f"outlier_{verdict.reason}"
            )
Поведение: контур не блокируется, но помечается и требует ручного подтверждения.

B) После ручного контура (review accept / manual draw)
Аналогичная проверка — если ручной контур выбивается из соседних, показать warning в status bar:

# main_window.py, после accept_ai_contour_review
neighbors = controller._collect_neighbor_contours(...)
verdict = detect_outlier(contour, neighbors, spacing)
if verdict.is_outlier:
    self._show_status(tr("status.contour_outlier",
        reason=verdict.reason, value=verdict.metric_value))
6. Hints/Suggestions для встроенного temporal fusion
Temporal fusion уже делает ±20 neighbour frames voting. Outlier rejection должен подсказывать fusion, какие кадры исключить:

def compute_robust_volumes(
    multi_frame_contours: dict[int, Contour],
    pixel_spacing: PixelSpacing,
) -> dict[str, float]:
    """Отбрасывает outlier-контуры перед расчётом LVEF."""
    areas = {idx: polygon_area_mm2(c, ps) for idx, c in multi_frame_contours.items()}
    median_area = np.median(list(areas.values()))
    mad = np.median(np.abs(np.array(list(areas.values())) - median_area))
    valid = {idx: a for idx, a in areas.items() if abs(a - median_area) / max(mad, 1) < 2.5}
    # расчёт volumes только по valid
7. UI: Что видит пользователь
Сценарий	Что происходит
Auto ONNX контур — outlier	Контур создаётся с review_pending=True + в status bar: "Контур на кадре N выбивается из соседних (площадь X vs медиана Y). Проверьте вручную."
Ручной контур — outlier	Warning в status bar, контур не блокируется
В результатах (overlay)	Напротив LVEF: "LVEF: 55% (на базе 18/20 кадров, 2 outlier исключены)"
8. Порядок реализации
#	Что	Где	Сложность
1	ContourOutlierDetector с 3 проверками	Новый файл	🟢 легко
2	_collect_neighbor_contours() в AppController	app_controller.py	🟢 легко
3	Изменить merge_contours() — не удалять старые контуры разных frame_index	study_measurement_session.py	🟢 легко
4	Интеграция в _on_auto_segment_finished	app_controller.py:2028	🟡 средне
5	Интеграция после ручного контура	main_window.py	🟡 средне
6	compute_robust_volumes() для temporal fusion	Новый сервис или расширение существующего	🟡 средне
7	UI: status bar сообщения + i18n	i18n файлы	🟢 легко
8	Тесты	tests/	🟢 легко
9. Без чего можно обойтись (YAGNI)
Mask-level Dice — требует хранения бинарных масок, а не только контуров. Начать с area Z-score только — уже даёт 90% ценности. Dice добавить потом.
Shape-based (Hausdorff distance) — сложно, прирост marginal
Автоматическое удаление outlier — никогда. Только flag + review. Клинический софт не удаляет контуры автоматически.
10. Тесты
# tests/unit/test_contour_outlier_detector.py
def test_normal_contour_not_flagged():
    neighbors = [make_contour(area=100) for _ in range(5)]
    target = make_contour(area=105)
    verdict = detect_outlier(target, neighbors, spacing)
    assert not verdict.is_outlier

def test_outlier_flagged():
    neighbors = [make_contour(area=100) for _ in range(5)]
    target = make_contour(area=300)  # 3x median
    verdict = detect_outlier(target, neighbors, spacing)
    assert verdict.is_outlier
    assert "area" in verdict.reason

def test_insufficient_neighbors_skips():
    verdict = detect_outlier(target, neighbors=[], spacing)
    assert not verdict.is_outlier  # skip if < 2 neighbors

def test_integration_with_quality_gate():
    # auto-segment produces outlier → review_pending=True
    ...
Начинать?
