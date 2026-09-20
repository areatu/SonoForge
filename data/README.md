# Data

Клинические данные (исходные DICOM-клипы) в этом публичном репозитории **не
хранятся** — они содержат идентифицирующую информацию и вынесены в закрытый
репозиторий.

## Где лежат исходные клипы

| Репозиторий | Содержимое | Доступ |
|-------------|------------|--------|
| [`areatu/Sonoforge_data`](https://github.com/areatu/Sonoforge_data) | `data/dicom/For_pero` — 19 STE-клипов (Samsung RS85, Philips; часть с ЭКГ), Git LFS | закрытый |

Исторически клипы жили здесь, в `data/dicom/For_pero` (Git LFS). 2026-09-17
папка перенесена в закрытый репозиторий из-за ФИО, впаянных в кадры; в публичной
истории остались только LFS-указатели.

## Производные данные (публичные, в этом репозитории)

| Путь | Что это |
|------|---------|
| `tests/fixtures/for_pero/` | Компактные фикстуры, выгруженные из клипов: кадры в JPEG + выхолощенные заголовки (`index.json`, `_diagnostics.md`). Обычные файлы, не LFS. |
| `gold/` | Эталонные аннотации сегментации LV/LA |

## Как фикстуры попадают в публичный репозиторий

Воркфлоу [`ste-fixtures.yml`](../.github/workflows/ste-fixtures.yml):
1. клонирует закрытый `areatu/Sonoforge_data` (секрет `SONOFORGE_DATA_TOKEN`),
2. запускает `tools/ste_fixture_export.py`,
3. коммитит компактный результат в `tests/fixtures/for_pero/` ветки, которая его запустила.

Локальная перегенерация (нужен доступ к закрытому репозиторию):

```bash
git clone https://github.com/areatu/Sonoforge_data.git /tmp/sonoforge_data
python tools/ste_fixture_export.py \
    --source /tmp/sonoforge_data/data/dicom/For_pero \
    --out tests/fixtures/for_pero
```

## Служебные скрипты

| Скрипт | Назначение |
|--------|------------|
| `../tools/migrate_for_pero.sh` | Одноразовая миграция клипов из публичного репозитория в закрытый (коммит с клипами зафиксирован в скрипте — работает и после слияния) |
