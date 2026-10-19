# Спайк UI-4.0 — предпросмотр отчёта (dev-only)

Проверка пути (а) из спеки редизайна §4.6: лист A4 в режиме «Отчёт» — это те же
байты PDF, что уходят на экспорт (`render_report` из
`infrastructure/measurement_report_pdf.py`), показанные в `QPdfView`, с
наведением «откуда значение» по координатам ячеек значений. В приложение ничего
из этого каталога не входит. Выводы — в
`docs/spikes/2026-10-19-ui-4-0-report-preview-spike-ru.md`.

## Скрипты

| Файл | Что делает |
|---|---|
| `probe_env.py` | доступность `PySide6.QtPdf`/`QtPdfWidgets` на версии из `uv.lock`, кто поставляет бинарники (essentials/addons), нужные API, `logicalDPI` |
| `render_bench.py` | бюджет пересборки: `render_report` + `QPdfDocument.load` + растер первой страницы; p50/p95 против 500 мс из спеки |
| `hover_probe.py` | геометрия `QPdfView` против пикселей: маркеры с известными координатами, сравнение с моделью `view_map.py`, хиттест-раундтрип |
| `view_map.py` | модель раскладки `QPdfView` (страница в координатах вьюпорта, «точка → пункт страницы») — воспроизводит `QPdfViewPrivate::calculateDocumentLayout` из Qt 6.11 |
| `demo_preview.py` | живое окно: предпросмотр отчёта + подсветка ячейки под курсором (`--smoke` — оффскрин-проверка) |

## Запуск

```bash
python tools/report_preview_spike/probe_env.py
python tools/report_preview_spike/render_bench.py --iterations 25
python tools/report_preview_spike/hover_probe.py --save-shots /tmp/shots
python tools/report_preview_spike/demo_preview.py
```

В контейнере без системного `libGL.so.1` Qt вообще не загружается — сначала
соберите заглушки (в репо есть инструмент, см. `tools/qtstub/mkstub.py`):

```bash
MKSTUB_CI_ONLY=1 python tools/qtstub/mkstub.py
export LD_LIBRARY_PATH=tools/qtstub/lib
export QT_QPA_PLATFORM=offscreen   # без окна; для demo_preview без --smoke уберите
```
