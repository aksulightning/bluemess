"""Parse the documented Linux memory metric without rounding before acceptance."""
from decimal import Decimal


MEMORY_LIMIT_MIB = 300


def parse_meminfo(text):
    values = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0].endswith(':'):
            try:
                values[fields[0][:-1]] = int(fields[1])
            except ValueError:
                pass
    required = ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree')
    if any(key not in values for key in required):
        raise ValueError('Incomplete /proc/meminfo reading')
    if not (0 <= values['MemAvailable'] <= values['MemTotal']):
        raise ValueError('Impossible available-memory value')
    if not (0 <= values['SwapFree'] <= values['SwapTotal']):
        raise ValueError('Impossible swap reading')
    used = Decimal(values['MemTotal'] - values['MemAvailable']) / Decimal(1024)
    swap_used = values['SwapTotal'] - values['SwapFree']
    return {'MemTotal_kib': values['MemTotal'],
            'MemAvailable_kib': values['MemAvailable'],
            'SwapUsed_kib': swap_used, 'used_MiB': str(used),
            'accepted': used <= Decimal(MEMORY_LIMIT_MIB) and swap_used == 0}


def summarize(readings):
    if len(readings) != 3:
        raise ValueError('Exactly three fresh-boot readings are required')
    used = [Decimal(item['used_MiB']) for item in readings]
    return {'boots': readings, 'minimum_MiB': str(min(used)),
            'maximum_MiB': str(max(used)),
            'accepted': all(item['accepted'] for item in readings)}
