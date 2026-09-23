# Issue tracker: Local Markdown

Задачи и спецификации хранятся в `.scratch/`.

- Одна функциональность: `.scratch/<feature-slug>/`.
- Спецификация: `spec.md` внутри этой директории.
- Каждая задача: `issues/<NN>-<slug>.md`, нумерация с 01.
- Статус triage: строка `Status:` в начале задачи; значения определены в `triage-labels.md`.
- Обсуждение дописывается в конец под `## Comments`.

«Опубликовать в трекере» означает создать локальный Markdown-файл.
«Получить задачу» означает прочитать файл по указанному пути.

## Wayfinder

- Карта: `.scratch/<effort>/map.md`, разделы Notes, Decisions-so-far и Fog.
- Дочерние задачи: `issues/NN-<slug>.md`.
- `Type:`: research / prototype / grilling / task.
- В workflow wayfinder `Status:` отражает claimed / resolved; это состояния выполнения, отдельные от triage.
- `Blocked by: NN, NN` перечисляет зависимости. Задача доступна, когда все зависимости resolved.
- Следующая задача: первая по номеру незавершённая, свободная задача без открытых зависимостей.
- Перед работой сохранить `Status: claimed`.
- По завершении добавить `## Answer`, установить resolved, дописать краткий результат и ссылку в Decisions-so-far карты.
