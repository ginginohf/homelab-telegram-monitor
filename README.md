# Homelab Telegram Monitor

**English** | [Русский](README.ru.md)

[![Tests](https://github.com/ginginohf/homelab-telegram-monitor/actions/workflows/tests.yml/badge.svg)](https://github.com/ginginohf/homelab-telegram-monitor/actions/workflows/tests.yml) [MIT](LICENSE)

Ask a Telegram bot for Linux service status, CPU/RAM/disk/temperature metrics and Intel GPU engine utilization, and receive threshold alerts.

## What it does

- `/status` combines the configured health report with failed systemd units; stale health reports are flagged.
- `/metrics` shows uptime, CPU load/utilization, RAM, swap, mounted disks, temperature and Intel i915 GPU activity when available.
- `/report` combines status and metrics; `/logs` exposes only configured service/container logs (or recent system errors).
- Background monitoring provides threshold alerts, recovery notifications and a daily report.
- GPU alerts use the busiest engine: above 95% triggers an alert, at or below 90% recovers, with a six-hour reminder interval.
- Commands are accepted only from the configured owner in a private chat. There is no arbitrary shell, restart or delete command.

## Examples and screenshots

See [worked examples](docs/EXAMPLES.md) for reproducible demonstrations and output. Examples use synthetic data; no private server configuration is included.

```text
Сервер: есть замечания
✅ web-demo
⚠️ backup-demo

Замечания: backup-demo
Проверено: <current UTC time>

Видеоядро Intel: 96.2% (самый занятый блок, среднее за 10 с)
GPU: копирование 0.4%, 3D/вычисления 8.1%, видеокодеки 96.2%
```

This excerpt is captured from the synthetic example; see the linked example for mocked operations and reproduction steps. Application output may remain Russian.

## Requirements

Linux, Python 3.11+, curl; systemctl/journalctl for service checks, optional sensors and Docker.

## Quick start

```sh
git clone https://github.com/ginginohf/homelab-telegram-monitor.git
cd homelab-telegram-monitor
cp config.example.json config.json
# Set owner_id and allowed service/container names in config.json.
export TELEGRAM_BOT_TOKEN="$(python3 -c 'import getpass; print(getpass.getpass("Telegram token: "))')"
python3 bot.py
```

## Configuration and limits

Intel GPU counters require compatible i915 PMU access on x86_64; unavailable telemetry is not 0% usage. Ordinary metrics do not justify granting unrestricted root. Docker, journal and PMU permissions need deliberate setup. Backup delivery is not included: `/backup` explains the limitation. Command text currently remains Russian even though this documentation is bilingual.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Install dependencies first when `requirements.txt` is present. See [TESTING.md](TESTING.md) for scope and limitations.

## Documentation

- [Examples](docs/EXAMPLES.md)
- [Recovery and upgrades](RESTORE.md)
- [Security](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Third-party components](THIRD_PARTY.md)

## License

Original project code is available under the [MIT License](LICENSE). Third-party components retain their own licenses.
