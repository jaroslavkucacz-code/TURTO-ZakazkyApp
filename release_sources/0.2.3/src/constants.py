APP_NAME = 'TURTO – Měsíční přehledy'
APP_VERSION = '0.2.3'
DB_SCHEMA_VERSION = 2

CENTER_NAMES = {
    'J': 'Jirka',
    'H': 'Honza',
    'M': 'Milan',
}
PRIMARY_CENTERS = ('J', 'H', 'M')

COLORS = {
    'bg': '#111827',
    'panel': '#172033',
    'panel_alt': '#1D293D',
    'panel_soft': '#223047',
    'border': '#2A3A52',
    'text': '#F3F6FA',
    'muted': '#93A4B8',
    'teal': '#1CC8A0',
    'teal2': '#39D7B4',
    'amber': '#F2B84B',
    'red': '#EF6A6A',
    'blue': '#63A7FF',
    'grid': '#324257',
}


def center_display(code):
    code = (code or '').strip()
    if code in CENTER_NAMES:
        return CENTER_NAMES[code]
    if not code:
        return 'Nezařazené'
    return f'Nezařazené ({code})'
