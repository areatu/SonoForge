# Models

> [English version](README.md)

ONNX модели для автоматической сегментации.

## Модели

| Файл | Описание | Статус |
|------|----------|--------|
| `echonet_seg_resnet50.onnx` | LV сегментация A4C (EchoNet-Dynamic) | Exported |
| `echonet_seg_resnet50_int8.onnx` | INT8 квантизованная версия | Exported |
| `echonet_la_resnet50_224.onnx` | LA сегментация (fine-tuned) | Exported |
| `ma_landmark_224.onnx` | Mitral annulus landmark detection | Exported |
| `deeplabv3_resnet50_random.pt` | PyTorch исходные веса | Source |
| `model_manifest.json` | Конфигурация моделей | — |

## Размеры

- LV segmentation: ~400 KB (+ 158 MB external data)
- LA segmentation: ~152 MB
- INT8 версия: ~39 MB
- Landmark: ~1.3 MB

## Использование

Модели автоматически загружаются из `_MEIPASS/models/`, если эта папка есть в сборке, затем из пользовательского каталога данных ОС или папки `models/` в исходниках.

Пользовательский каталог моделей — папка `models/` внутри `%LOCALAPPDATA%\SonoForge` в Windows, `$XDG_DATA_HOME/sonoforge` в Linux (по умолчанию `~/.local/share/sonoforge`) или `~/Library/Application Support/SonoForge` в macOS. Портативный режим хранит модели рядом с исполняемым файлом. Старый путь `~/.local/share/sonoforge/models/` пока остаётся резервным для чтения на релиз миграции.

SHA-256 архива `models-v1.tar.gz` опубликован в [`SHA256SUMS`](SHA256SUMS) и закреплён в runtime setup. Все облегчённые лаунчеры проверяют хеш до распаковки; при несовпадении архив отклоняется.

Проверка скачанного вручную архива: сверьте его дайджест со строкой в `SHA256SUMS` (`sha256sum models-v1.tar.gz`). Asset `SHA256SUMS` релиза models-v1 сейчас содержит переводы строк CRLF; в Linux сначала уберите их (`tr -d '\r' < SHA256SUMS | sha256sum -c`) либо используйте копию из этого репозитория — она авторитетная, в LF. Установка от asset не зависит: лаунчеры берут дайджест из этого дерева.

См. `model_manifest.json` для конфигурации.
