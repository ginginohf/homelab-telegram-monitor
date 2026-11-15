# Worked example

[Русский](EXAMPLES.ru.md) | [Project overview](../README.md)

Captured from the actual message-formatting functions with synthetic status/GPU data. No Telegram account or live message is used. Russian output is the current application behavior.

From the repository root (install requirements first if present):

```sh
python3 examples/demo.py
```

Captured output:

```text
Сервер: есть замечания
✅ web-demo
⚠️ backup-demo

Замечания: backup-demo
Проверено: <current UTC time>

Видеоядро Intel: 96.2% (самый занятый блок, среднее за 10 с)
GPU: копирование 0.4%, 3D/вычисления 8.1%, видеокодеки 96.2%
```
