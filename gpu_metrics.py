"""Intel i915 PMU engine busy time; no external tools or software estimates."""
import ctypes
import os
from pathlib import Path
import platform
import struct

class GpuSampler:
    def __init__(self):
        self.fds = {}
        self.previous = {}
        self.error = None

    def close(self):
        for fd in self.fds.values():
            os.close(fd)
        self.fds.clear()
        self.previous.clear()

    def _open(self):
        if platform.machine() != 'x86_64':
            raise OSError('unsupported perf syscall architecture')
        base = Path('/sys/bus/event_source/devices/i915')
        kind = int((base / 'type').read_text())
        cpu = int((base / 'cpumask').read_text().strip().split(',')[0].split('-')[0])
        libc = ctypes.CDLL(None, use_errno=True)
        libc.syscall.restype = ctypes.c_long
        try:
            for path in sorted((base / 'events').glob('*-busy')):
                if path.with_suffix('.unit').read_text().strip() != 'ns':
                    continue
                config = int(path.read_text().strip().split('=')[1], 0)
                attr = ctypes.create_string_buffer(128)
                # perf_event_attr: read_format includes total_time_enabled/running.
                struct.pack_into('IIQQQQ', attr, 0, kind, 128, config, 0, 0, 3)
                fd = libc.syscall(298, ctypes.byref(attr), -1, cpu, -1, 8)
                if fd < 0:
                    raise OSError(ctypes.get_errno(), 'i915 perf_event_open')
                self.fds[path.name.removesuffix('-busy')] = fd
            if not self.fds:
                raise OSError('no i915 busy counters')
        except Exception:
            self.close()
            raise

    @staticmethod
    def percent(before, after):
        busy, enabled, running = [a-b for a,b in zip(after, before)]
        if busy < 0 or enabled <= 0 or running <= 0:
            return None
        # Scale multiplexed PMU counts; nanoseconds cancel to percentage.
        return max(0.0, min(100.0, busy / running * 100.0))

    def sample(self):
        try:
            if not self.fds:
                self._open()
            values = {}
            for name, fd in self.fds.items():
                now = struct.unpack('QQQ', os.read(fd, 24))
                old = self.previous.get(name)
                self.previous[name] = now
                if old is not None:
                    value = self.percent(old, now)
                    if value is not None:
                        values[name] = value
            self.error = None
            return {'gpu': max(values.values()) if values else None,
                    'gpu_engines': values, 'gpu_error': None}
        except (OSError, ValueError, struct.error) as error:
            self.close()
            self.error = str(error)
            return {'gpu': None, 'gpu_engines': {}, 'gpu_error': self.error}

def format_gpu(values):
    if values.get('gpu') is None:
        return 'Видеоядро Intel: замер недоступен' if values.get('gpu_error') else 'Видеоядро Intel: ожидается первый замер'
    labels = {'rcs0': '3D/вычисления', 'vcs0': 'видеокодеки', 'bcs0': 'копирование'}
    details = ', '.join(f'{labels.get(k,k)} {v:.1f}%' for k,v in sorted(values.get('gpu_engines', {}).items()))
    return f"Видеоядро Intel: {values['gpu']:.1f}% (самый занятый блок, среднее за 10 с)\nGPU: {details}"
