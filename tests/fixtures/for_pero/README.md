# STE fixtures: real study clips (compact derivative)

Компактная производная из 19 реальных STE-клипов. Исходники (`data/dicom/For_pero`)
хранятся в **закрытом** репозитории `areatu/Sonoforge_data` (кадры содержат впаянные
ФИО); здесь лежит только обезличенный экспорт, поэтому папка публичная и обычная
(не Git LFS — см. исключения в `.gitattributes`).

## Состав

| Файл | Описание |
|------|----------|
| `<clip>.npz` | Все кадры клипа в JPEG + метаданные анализа (число кадров, fps, pixel spacing) |
| `<clip>.json` | Выхолощенный дайджест DICOM-заголовка, включая приватные теги с вендорскими значениями strain |
| `ui_reference/*.png` | Скриншоты вендорских экранов STE (Samsung/Philips) для визуальной сверки |
| `index.json` | Инвентарь фикстур (источник, перечень клипов, геометрия) |
| `_diagnostics.md` | Диагностика последней CI-выгрузки (перегенерируется воркфлоу) |

## Клипы

- `gold1…gold6`, `gold7+ECG`, `gold8+ECG` — Samsung RS85 (золотые клипы, часть с ЭКГ);
- `gold_Ph_ECG1/2`, `strain_ph1…3` — Philips;
- `strain_sams1…6` — экраны «3 Point Contour» Samsung с вендорскими значениями.

## Регенерация

Воркфлоу [`ste-fixtures.yml`](../../../.github/workflows/ste-fixtures.yml) запускает
[`tools/ste_fixture_export.py`](../../../tools/ste_fixture_export.py) на раннере, где
доступен закрытый репозиторий данных (секрет `SONOFORGE_DATA_TOKEN`), и коммитит
результат обратно. Вручную (нужен клон закрытого репозитория):

```bash
python tools/ste_fixture_export.py \
    --source /path/to/Sonoforge_data/data/dicom/For_pero \
    --out tests/fixtures/for_pero
```

Тесты-контракт фикстур: [`tests/unit/test_ste_real_clips.py`](../../unit/test_ste_real_clips.py)
(пропускаются, если фикстур нет в чекауте).
