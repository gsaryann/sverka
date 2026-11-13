# Стенд сравнения LLM-API (СверкаСмет)

Положить папку `llmbench/` в корень проекта sverka (рядом с match.py).

1. Ключи в `.env` (нужные из списка):
   YANDEX_API_KEY, YANDEX_FOLDER_ID, GIGACHAT_AUTH_KEY (+ GIGACHAT_CA_BUNDLE — корневой сертификат НУЦ Минцифры), CLOUDRU_API_KEY
2. Проверка скоринга без ключей:
   python llmbench/bench.py --tasks llmbench/tasks_set1.json --providers selftest
3. Реальный замер (3 повтора — для устойчивости ответов):
   python llmbench/bench.py --tasks llmbench/tasks_set1.json --providers yandex_flash,gigachat_pro --repeat 3
   python llmbench/bench.py --tasks llmbench/tasks_set1_work.json --providers all --repeat 3
4. Результат: таблица в консоли, results_bench/summary.csv и bench_<провайдер>.json (по каждому запросу).

В providers.json проверить: ID моделей (особенно Cloud.ru и GigaChat), base_url и цены — они взяты из открытых источников/выписки, часть пересчитана и не подтверждена.
Наборы: tasks_set1.json — 27 запросов как в прототипе (верная строка есть среди 5 кандидатов во всех 27 запросах); tasks_set1_work.json — 22 запроса с полным пулом строк-работ (верный ответ есть во всех 22 запросах).
Пересоздать наборы: python llmbench/export_tasks.py data/ВОР.xlsx data/ЛСР.xlsx llmbench/tasks_set1.json [work]
