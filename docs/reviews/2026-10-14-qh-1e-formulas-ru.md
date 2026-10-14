# QH-1e: обязательные синтетические formulas / units / rounding

**База:** `3d23a8f` (после #159). **Scope:** QH §5.6 «сразу, без внешних данных»,
A-15, численная часть S-11 и доказательство S-12. Первый из двух коммитов этой сессии.
Нет новых STE-алгоритмов, внешних/клинических данных, новых display precision или disk schema.

## Эталоны и frozen tolerances

`tests/unit/test_qh1e_formulas.py` — 111 cases. Скалярные сравнения:
`rel=1e-10, abs=1e-10`; display rounding проверяется отдельно. Simpson:
`rel=0.002` к аналитическому объёму (20 midpoint disks + полигон из 1001 точки).
Допуски заданы в тесте до проверки, не получены из измеренных результатов.

| Сценарий | Независимый oracle / доказательство |
|---|---|
| Bernoulli | ±280 cm/s → 31.36 mmHg, 400 → 64, ноль → 0; raw cm/s преобразуется в m/s |
| Simpson mono / bi | Полуэллипсоид `V=π D² L/6`, для двух разных диаметров `V=π D4 D2 L/6`, mm³→mL `/1000`; ED/ES → EF 71.2%; spacing (1,1), (0.5,0.5), (0.4,0.8) |
| Incomplete / QC | Нет spacing, zero/negative spacing → нет результата; только ED → partial без EF; pending contour не становится измерением |
| Doppler normalization | Треугольник 0→±400→0 cm/s за 200 ms, разные размеры/начала pixel axes: VTI 40 cm, Vmean 200 cm/s, PGmean 64/3, PGmax 64; `mean(v²)` не заменён `mean(v)²` |
| Repeats | 0/1/2/3/4/10 markers; число использованных = min(n,3); PG от средней последних трёх magnitudes, а не средней PG; пустой site отсутствует |
| BSA | Du Bois 170 cm/70 kg → 1.809707801753247 m²; patient source qualifiers, derived «Du Bois», manual override с auto provenance; без weight нет придуманного BSA |
| Calculator coverage ratchet | Есть независимый численный и rounding oracle для каждого из 10 `CALCULATORS`; новый calculator без case ломает тест |
| Calculator negative inputs | Для каждого calculator обязательный input отсутствует / 0 / -1 / NaN / ±Inf → нет указанного output, display «—»; прочие выходы проверяются существующими formula tests |
| Persistence / text / PDF | Настоящие repository+codec: save/close/new reader/restore signed Doppler и антропометрии; пересчёт совпадает; RU/EN. Panel `OutputValue.formatted()` → 31, flat text → 31.4, measurement table → 31.4, calculator table → 31; настоящий ReportLab PDF читается PyMuPDF, проверяются label/value/unit pairs |

**Parity не означает одинаковое число десятичных знаков:** сохранены существующие
precision каждого представления. Проверяется согласованное округление из одного raw значения,
а не перевод display-text обратно в клинические входы. Тест не выдаётся за GUI pixel/native test.
Ручной RAP=8 в parity case применяется заново после restore: его persistence — отдельный QH-1d,
этот срез не притворяется, что manual inputs уже сохраняются.

## Найденные и исправленные ошибки

1. `body_surface.bsa_du_bois_m2()` пропускал NaN/+Inf в BSA и indexed outputs.
   Воспроизведены 4 FAIL; добавлен `math.isfinite` для обоих входов.
2. `teichholz.volume_from_cm_ml(+Inf)` давал NaN. Добавлены finite guards в volume/EF/FS
   и caliper boundary; `volume_ml` сохраняет ValueError-контракт для недопустимого диаметра,
   wrappers возвращают None. Для допустимых входов арифметика не меняется.
3. `resources/bundled_fonts.py` импортировал QtGui даже для простого доступа к TTF для PDF.
   QtGui теперь лениво импортируется только UI-функциями. Реальный PDF не требует GL runtime.

## CI gate и локальное evidence

- `.github/required-tests/formulas.txt`: **29 обязательных записей** — новый набор, уже существующие
  numerical tests supported measurements, multi-output cases всех calculator families и существующие
  STE phantom ground-truth/strain-metric contracts. Никаких safety skips/xfail.
- `test-logic (ubuntu-latest, 3.11)` проверяет manifest по `pytest_ci_metrics` после полного
  unit run. Missing/skip/xfail/collection error → FAIL. Exit status gate не маскируется.
- Локально locked Python 3.11.2 / `uv.lock`, Qt 6.11.1: **276 passed**, 0 skipped/xfail,
  required gate **29/29**, count gate **276/276**. Набор содержит 111 новых случаев.
- Песочница не имеет native GL/EGL/dbus/xkb libraries. Для pytest использован **существующий**
  `tools/qtstub/mkstub.py` + offscreen. Это numerical/application evidence, **не native GUI acceptance**.
  Дополнительно базовые 37 cases (до расширения matrix) прошли из изолированной копии без
  pytest-qt и без stubs, включая настоящие RU/EN PDF. CI выполняет штатные repository tests
  с настоящими system libraries; его результаты — в PR checks.
- Controlled mutations (не входят в patch): Bernoulli coefficient 4→3 → FAIL;
  удаление BSA finite guard → FAIL; удаление QH-1e outcomes из metrics → required gate FAIL.
- JUnit/metrics/mutation logs локально в ignored `.cache/qh-evidence/`; в CI — bounded
  `pytest-logic-diagnostics`. Генерируемые PDF/fixtures/diagnostics в Git не входят.

## Статус и остаток

**QH-1e formulas: выполнен synthetic slice; CI подтверждается PR checks.**
Это не закрывает весь G1 data-safety, provenance/invalidation или vendor-equivalence.
**G1-STE: BLOCKED** — нет gold ED/landmarks, same-frame vendor values и согласованных
определений/manifest. Existing phantom truth не подменяет production tracking validation.
Tracking QC/low-SNR/rigid-motion tests остаются в отдельном GUI suite с прежними порогами.
Data protocol, расширенные bias/LoA/coverage и clinical review остаются по §5.6 плана.
