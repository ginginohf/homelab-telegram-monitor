"""Debounce each incident independently; keep critical storage alerts immediate."""
class AlertPolicy:
    def __init__(self):
        self.present_since = {}
        self.absent_since = {}

    def step(self, errors, reported, now, last_sent):
        current, old = set(errors), set(reported)
        for name in list(self.present_since):
            if name not in current: del self.present_since[name]
        for name in current:
            self.present_since.setdefault(name, now)
            self.absent_since.pop(name, None)
        critical = lambda name: name in ('media-usb-unavailable','media-disk-unavailable') or 'free-below-' in name
        stable = {name for name in current if name in old or critical(name) or now-self.present_since[name] >= 120}
        for name in old-current:
            self.absent_since.setdefault(name, now)
            if now-self.absent_since[name] < 120: stable.add(name)
        if stable == old:
            return sorted(stable) if stable and now-last_sent >= 21600 else None
        urgent = any(critical(name) for name in stable-old)
        if not stable or not old or urgent or now-last_sent >= 600:
            return sorted(stable)
        return None

def merge_failed_units(errors, failed_output, health_fresh):
    result=set(errors)
    for line in failed_output.splitlines():
        if not line.strip(): continue
        unit=line.split()[0]
        if unit=='server-health.service' and health_fresh and errors: continue
        name=unit.removesuffix('.service')
        if name in ('vps-backup','casino-backup','server-state-backup') or name in result:
            result.add(name)
        else: result.add('служба '+unit)
    return sorted(result)
