"""Shared, dependency-free chart data rules and signed axis geometry."""
from __future__ import annotations
import math
from dataclasses import dataclass


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def series_value(row, key):
    if key == 'profit' and not row.get('profit_available', True):
        return None
    return number(row.get(key))


def nice_step(value):
    if not value or not math.isfinite(value) or value <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(value))
    frac = value / exp
    return next((n * exp for n in (1, 2, 2.5, 5, 10) if frac <= n), 10 * exp)


@dataclass(frozen=True)
class Axis:
    minimum: float
    maximum: float
    step: float
    divisor: float = 1
    unit: str = ''
    decimals: int = 0

    def position(self, value, top, bottom):
        return bottom - (value - self.minimum) / (self.maximum - self.minimum) * (bottom - top)

    def ticks(self):
        count = round((self.maximum-self.minimum)/self.step)
        return [self.minimum + i*self.step for i in range(count+1)]

    def label(self, value):
        return f'{value/self.divisor:.{self.decimals}f}'.replace('.', ',')


def axis(values, percent=False):
    vals = [v for x in values if (v := number(x)) is not None]
    lo, hi = min([0.0] + vals), max([0.0] + vals)
    if hi == lo:
        hi = 5.0 if percent else 1.0
    span = hi-lo
    step = nice_step(span/4)
    low = math.floor(lo/step)*step
    high = math.ceil(hi/step)*step
    if high <= low:
        high = low+step
    # Exact endpoints remain visible; captions occupy a separate strip.
    if percent:
        divisor, unit = 1.0, '%'
    elif max(abs(low), abs(high)) >= 1_000_000:
        divisor, unit = 1_000_000.0, 'mil. Kč'
    elif max(abs(low), abs(high)) >= 10_000:
        divisor, unit = 1_000.0, 'tis. Kč'
    else:
        divisor, unit = 1.0, 'Kč'
    scaled = step/divisor
    decimals = next((n for n in range(7) if abs(round(scaled,n)-scaled) < 1e-9), 6)
    return Axis(low, high, step, divisor, unit, decimals)


def grouped(rows, metric, maximum=6):
    """Positive shares or signed comparison. Never sum heterogeneous ratios."""
    valid = []
    missing = 0
    for row in rows:
        value = series_value(row, metric)
        if value is None:
            missing += 1
            continue
        valid.append({'label':str(row.get('label') or row.get('name') or row.get('customer') or row.get('code') or 'Bez názvu'),
                      'value':value, 'source':row})
    valid.sort(key=lambda x:abs(x['value']), reverse=True)
    out = valid[:maximum]
    rest = valid[maximum:]
    # Keep positive and negative residuals separate, so cancellation is visible.
    for label, items in (('Ostatní', [x for x in rest if x['value']>=0]),
                         ('Ostatní záporné', [x for x in rest if x['value']<0])):
        if items:
            out.append({'label':f'{label} ({len(items)})', 'value':sum(x['value'] for x in items), 'source':None})
    return out, missing, any(x['value']<0 for x in valid)


def money(value, decimals=0):
    v=number(value)
    return '—' if v is None else f'{v:,.{decimals}f} Kč'.replace(',', ' ').replace('.', ',')


def percent(value):
    v=number(value)
    return '—' if v is None else f'{v:.1f} %'.replace('.', ',')


def count(value):
    v=number(value)
    return '—' if v is None else f'{v:,.0f}'.replace(',', ' ')
