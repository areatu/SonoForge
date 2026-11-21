- `perf(ci)`: длинные logic-jobs разделены на три файловых shard на каждой из прежних
  пяти OS/Python-комбинаций (Linux 3.11/3.12/3.13, Windows/macOS 3.11).
  - Балансировка largest-first по числу реально собранных pytest items, включая параметризацию;
    файл целиком остаётся в одном shard, xdist `loadfile` и порядок внутри файла сохранены.
    Тайминги пока не используются как веса: для этого сначала нужны измерения CI.
  - `pytest_ci_metrics` сохраняет полный eligible inventory до разбиения, выбранные nodeids,
    результаты и setup/call/teardown timings каждого теста. CLI-параметры sharding не наследуются
    вложенными pytest-процессами тестов, в отличие от переменных окружения.
  - Новый обязательный `logic_evidence` проверяет все три shard каждой платформы: завершение,
    отсутствие collection errors, дублей и пропусков nodeids, совпадение выбранных и выполненных
    тестов. Обязательные формулы проверяются на объединённых Linux/3.11 outcomes, не по частям.
  - Coverage объединяет все три logic data-файла и прежние шесть GUI data-файлов. Пороговые
    значения и проверки потерь после worker crash не ослаблены. Финальные required checks
    `test (ubuntu-latest, 3.11)` / macOS / Windows сохранены и требуют `logic_evidence`.
  - Inventory передаёт точные nodeids; Linux partition gate проверяет их полное непересекающееся
    объединение с учётом отдельно выполняемого timing-budget теста.
  - В GitHub Step Summary добавлен top файлов по времени setup/call/teardown; полные timings
    остаются в JSON artifacts. Windows path suite выполняется один раз, на shard 0.
  - Qt-cleanup, маркеры тестов, платформенное покрытие, concurrency и dependency lock не изменены.
    Ускорение ожидается за счёт дополнительных runners; целевые минуты требуют замера в Actions,
    а очереди и неравномерная стоимость файлов могут уменьшить выигрыш.
  - Регрессии включают реальные маленькие pytest-прогоны без xdist и с двумя workers,
    объединение результатов, required-formulas CLI и отрицательные сценарии пропусков/дублей.
