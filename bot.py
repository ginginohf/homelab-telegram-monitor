#!/usr/bin/env python3
"""Owner-only server monitoring and resumable backup delivery through SOCKS5."""
import datetime as dt
import fcntl
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from alert_policy import AlertPolicy, merge_failed_units
from gpu_metrics import GpuSampler, format_gpu

CONFIG = Path(os.environ.get('MONITOR_CONFIG','config.json'))
ROOT = Path(os.environ.get('MONITOR_STATE','state'))
LIMIT = 45 * 1024 * 1024
DOCKER = set()
UNITS = set()
HELP = ('Команды:\n/status — состояние служб\n/metrics — CPU, видеоядро, память, диски, температура\n'
        '/report — полный отчёт\n/logs [служба] — последние записи журнала\n'
        '/backups — копии и очередь отправки\n/backup — информация о резервировании\n'
        '/help — эта справка\n\nДоступ разрешён только владельцу. Команд удаления, перезапуска и произвольной оболочки нет.')
KEYBOARD = {'keyboard': [['/status', '/metrics'], ['/report', '/backups'], ['/logs', '/backup']],
            'resize_keyboard': True}


def command(args, timeout=20):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {} if default is None else default


def atomic(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.chmod(0o600)
    tmp.replace(path)


def authorized(message, owner):
    return (message.get('from', {}).get('id') == owner and
            message.get('chat', {}).get('id') == owner and
            message.get('chat', {}).get('type') == 'private')


def cpu_counters():
    # guest times are already included in user/nice; don't count them twice.
    values = [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    return sum(values), values[3] + values[4]


def cpu_percent(before, after):
    total, idle = after[0] - before[0], after[1] - before[1]
    if total <= 0 or idle < 0:
        return None
    return max(0.0, min(100.0, 100.0 * (total - idle) / total))


def memory_percent():
    values = {line.split(':', 1)[0]: int(line.split()[1])
              for line in Path('/proc/meminfo').read_text().splitlines()}
    # Reclaimable cache counts as available memory, not memory pressure.
    return 100.0 * (1 - values['MemAvailable'] / values['MemTotal'])


class Bot:
    def __init__(self):
        global DOCKER, UNITS
        self.config = read_json(CONFIG)
        self.config['token'] = os.environ['TELEGRAM_BOT_TOKEN']
        self.config['proxy'] = os.environ.get('HTTPS_PROXY','')
        DOCKER=set(self.config.get('docker',[]));UNITS=set(self.config.get('units',[]))
        self.owner = int(self.config['owner_id'])
        self.guard = threading.RLock()
        self.state = read_json(ROOT / 'state.json')
        self.wake = threading.Event()
        self.resource_latest = {}

    def update(self, **values):
        with self.guard:
            self.state.update(values)
            atomic(ROOT / 'state.json', self.state)

    def api(self, method, data=None, file=None):
        # Keep the token and proxy password out of process arguments and journal output.
        lines = ['url = ' + json.dumps('https://api.telegram.org/bot' + self.config['token'] + '/' + method),
]
        if self.config.get('proxy'): lines.append('proxy = '+json.dumps(self.config['proxy']))
        if file:
            for key, value in (data or {}).items():
                lines.append('form-string = ' + json.dumps(key + '=' + str(value)))
            lines.append('form = ' + json.dumps('document=@' + str(file) + ';type=application/octet-stream'))
        else:
            lines += ['header = "Content-Type: application/json"',
                      'data = ' + json.dumps(json.dumps(data or {}, ensure_ascii=True))]
        timeout = 600 if file else 45
        p = subprocess.run(['curl', '--config', '-', '--silent', '--show-error', '--connect-timeout', '12',
                            '--max-time', str(timeout)], input='\n'.join(lines) + '\n',
                           capture_output=True, text=True, timeout=timeout + 5)
        if p.returncode:
            raise RuntimeError('Telegram network error ' + str(p.returncode))
        try:
            response = json.loads(p.stdout)
        except ValueError:
            raise RuntimeError('Telegram returned an invalid response') from None
        if not response.get('ok'):
            code = response.get('error_code', 'unknown')
            if code == 429:
                time.sleep(min(response.get('parameters', {}).get('retry_after', 10), 60))
            raise RuntimeError('Telegram API error ' + str(code))
        return response['result']

    def redact(self, text):
        for secret in [self.config['token'], self.config['proxy']]:
            if secret: text = text.replace(secret, '[скрыто]')
        text = re.sub(r'bot\d+:[A-Za-z0-9_-]+', 'bot[скрыто]', text)
        return re.sub(r'(?i)((?:password|token|secret|api[_-]?key|authorization)\s*[:=]\s*)\S+',
                      r'\1[скрыто]', text)

    def send(self, text, keyboard=False):
        data = {'chat_id': self.owner, 'text': self.redact(text)[:4000]}
        if keyboard:
            data['reply_markup'] = KEYBOARD
        return self.api('sendMessage', data)

    def health(self):
        data = read_json(self.config.get('health_status','state/health.json'))
        errors = list(data.get('errors', []))
        health_fresh = False
        try:
            age = time.time() - dt.datetime.fromisoformat(data['checked_at']).timestamp()
            health_fresh = 0 <= age <= 180
            if age > 180:
                errors.append('проверка состояния устарела')
        except (KeyError, ValueError):
            errors.append('нет результата проверки состояния')
        _, failed, _ = command(['systemctl', '--failed', '--plain', '--no-legend', '--no-pager'])
        errors = merge_failed_units(errors, failed, health_fresh)
        if self.state.get('backup_error_since') and time.time() - self.state['backup_error_since'] > 3600:
            errors.append('отправка резервных копий в Telegram не удаётся более часа')
        return data, sorted(set(errors))

    def status(self):
        data, errors = self.health()
        lines = ['Сервер: ' + ('есть замечания' if errors else 'всё исправно')]
        for name, state in data.get('services', {}).items():
            lines.append(('✅ ' if state.get('ok') else '⚠️ ') + name)
        if errors:
            lines.append('\nЗамечания: ' + '; '.join(errors))
        lines.append('Проверено: ' + data.get('checked_at', 'нет данных'))
        return '\n'.join(lines)

    def metrics(self):
        memory = {}
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, value = line.split(':', 1)
            memory[key] = int(value.strip().split()[0]) * 1024
        uptime = float(Path('/proc/uptime').read_text().split()[0])
        lines = [f'Работа без перезагрузки: {uptime / 86400:.1f} суток',
                 'Нагрузка CPU (1/5/15 мин): ' + ', '.join(f'{x:.2f}' for x in os.getloadavg()),
                 f"RAM доступно: {memory['MemAvailable'] / 1024**3:.1f} / {memory['MemTotal'] / 1024**3:.1f} ГиБ",
                 f"Swap занят: {(memory['SwapTotal']-memory['SwapFree']) / 1024**3:.2f} ГиБ"]
        if self.resource_latest.get('cpu') is not None:
            lines.insert(1, f"CPU занят: {self.resource_latest['cpu']:.1f}% суммарной мощности всех ядер")
        lines.append(f"ОЗУ занято: {100 * (1 - memory['MemAvailable'] / memory['MemTotal']):.1f}%")
        lines.append(format_gpu(self.resource_latest))
        for label, path in self.config.get('mounts',[['Системный диск','/']]):
            if not os.path.ismount(path):
                lines.append('медиадиск: не подключён')
                continue
            usage = shutil.disk_usage(path)
            lines.append(f'{label}: свободно {usage.free / 1024**3:.1f} / {usage.total / 1024**3:.1f} ГиБ')
        _, sensors, _ = command(['sensors', '-j'])
        try:
            temps = [value for name, chip in json.loads(sensors).items() if name.startswith('coretemp')
                     for row in chip.values() if isinstance(row, dict)
                     for key, value in row.items() if key.endswith('_input')]
            if temps:
                lines.append(f'CPU: {max(temps):.0f} °C')
        except (ValueError, TypeError):
            pass
        return '\n'.join(lines)

    def logs(self, name):
        if name in DOCKER:
            _, out, err = command(['docker', 'logs', '--since', '24h', '--tail', '60', name])
            text = out + err
        elif name in UNITS:
            _, text, _ = command(['journalctl', '-u', name, '--since', '24 hours ago', '-n', '60', '--no-pager'])
        elif not name:
            _, text, _ = command(['journalctl', '--since', '24 hours ago', '-p', 'err', '-n', '40', '--no-pager'])
        else:
            return 'Доступные журналы: ' + ', '.join(sorted(DOCKER | UNITS))
        return 'Журнал ' + (name or 'ошибок сервера') + ':\n' + self.redact(text)[-3600:]


    def report(self):
        return 'Отчёт домашнего сервера — ' + dt.datetime.now().strftime('%d.%m.%Y %H:%M') + '\n\n' + \
               self.status() + '\n\n' + self.metrics() + '\n\n' + 'Доставка архивов не включена в эту редакцию.'

    def handle(self, message):
        if not authorized(message, self.owner):
            return
        words = message.get('text', '').strip().split(maxsplit=1)
        if not words:
            return
        name = words[0].split('@')[0].lower()
        if name in ('/start', '/help'):
            self.send(HELP, keyboard=True)
        elif name == '/status':
            self.send(self.status())
        elif name == '/metrics':
            self.send(self.metrics())
        elif name == '/report':
            self.send(self.report())
        elif name == '/logs':
            self.send(self.logs(words[1].strip() if len(words) > 1 else ''))
        elif name == '/backups':
            self.send('Доставка архивов не включена в эту редакцию.')
        elif name == '/backup':
            self.send('Доставка архивов не включена в эту редакцию.')
        else:
            self.send(HELP, keyboard=True)

    def check_resource_alerts(self, values, now):
        alerts = dict(self.state.get('resource_alerts', {}))
        for key, label in [('cpu', 'CPU'), ('ram', 'ОЗУ'), ('gpu', 'Видеоядро Intel (самый занятый блок, среднее за 10 с)')]:
            value = values.get(key)
            if value is None:
                continue
            previous = alerts.get(key, {})
            active = previous.get('active', False)
            if value > 95 and (not active or now - previous.get('notified_at', 0) >= 21600):
                self.send(f'⚠️ {label}: использование {value:.1f}% — выше порога 95%.')
                alerts[key] = {'active': True, 'notified_at': now}
                self.update(resource_alerts=dict(alerts))
            elif active and value <= 90:
                self.send(f'✅ {label}: использование снизилось до {value:.1f}% (не выше 90%).')
                alerts[key] = {'active': False, 'notified_at': now}
                self.update(resource_alerts=dict(alerts))

    def resources(self):
        previous = cpu_counters()
        gpu = GpuSampler()
        gpu.sample()
        while True:
            time.sleep(10)
            try:
                current = cpu_counters()
                values = {'cpu': cpu_percent(previous, current), 'ram': memory_percent()}
                values.update(gpu.sample())
                previous = current
                self.resource_latest = values
                self.check_resource_alerts(values, time.time())
            except Exception as error:
                print('Resource monitoring: ' + type(error).__name__, flush=True)

    def monitor(self):
        policy = AlertPolicy()
        while True:
            try:
                _, errors = self.health()
                old = self.state.get('reported_errors', [])
                now = time.time()
                notification = policy.step(errors, old, now, self.state.get('error_reminder', 0))
                if notification is not None:
                    self.send(('⚠️ Ошибки сервера: ' + '; '.join(notification)) if notification else '✅ Все ранее отмеченные ошибки устранены.')
                    self.update(reported_errors=notification, error_reminder=now)
                day = dt.date.today().isoformat()
                if dt.datetime.now().hour >= self.config.get('daily_hour', 9) and self.state.get('report_day') != day:
                    self.send(self.report())
                    self.update(report_day=day)
                    self.wake.set()
                boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
                if self.state.get('reported_boot') != boot:
                    self.send('Сервер и Telegram-мониторинг работают. Ежедневный отчёт — в 09:00 МСК.\n' + self.metrics())
                    self.update(reported_boot=boot)
            except Exception as error:
                print('Monitor: ' + type(error).__name__, flush=True)
            time.sleep(60)




    def run(self):
        commands = [{'command': name, 'description': description} for name, description in
                    [('status', 'Состояние служб'), ('metrics', 'Метрики сервера'), ('report', 'Полный отчёт'),
                     ('logs', 'Последние ошибки или журнал службы'), ('backups', 'Копии и очередь отправки'),
                     ('backup', 'Отправить новые готовые копии'), ('help', 'Справка')]]
        try:
            self.api('setMyCommands', {'commands': commands})
        except Exception:
            pass
        threading.Thread(target=self.monitor, daemon=True).start()

        threading.Thread(target=self.resources, daemon=True).start()
        while True:
            try:
                updates = self.api('getUpdates', {'offset': self.state.get('offset', 0), 'timeout': 25,
                                                  'allowed_updates': ['message']})
                for update in updates:
                    try:
                        self.handle(update.get('message', {}))
                    finally:
                        self.update(offset=update['update_id'] + 1)
            except Exception as error:
                print('Polling: ' + type(error).__name__, flush=True)
                time.sleep(15)




if __name__ == '__main__':
    ROOT.mkdir(mode=0o700, exist_ok=True)
    with (ROOT / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        Bot().run()
