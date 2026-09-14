from __future__ import annotations

from pathlib import Path


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: očekáván 1 výskyt, nalezeno {count}')
    return text.replace(old, new, 1)


def patch_charts(path: str | Path) -> None:
    path = Path(path)
    text = path.read_text(encoding='utf-8')

    text = _replace_once(
        text,
        "PALETTE=(COLORS['teal'],COLORS['amber'],COLORS['blue'],'#AB96DF','#D693B3','#96C5A4','#8193A9','#BF9780')\n",
        "PALETTE=(COLORS['teal'],COLORS['amber'],COLORS['blue'],'#AB96DF','#D693B3','#96C5A4','#8193A9','#BF9780')\n"
        "SPECIAL_COLORS={'Milan':COLORS['teal'],'Honza':COLORS['blue'],'Jirka':COLORS['amber'],'Nezařazené':'#8193A9'}\n"
        "MIN_DONUT_DEGREES=0.5\n\n"
        "def _metric_color(key):\n"
        "    return {'revenue':COLORS['teal'],'profit':COLORS['amber'],'margin':COLORS['blue'],'count':COLORS['blue']}.get(key,COLORS['text'])\n\n"
        "def _display_colors(items):\n"
        "    # Barvy se přidělují jen právě zobrazeným kategoriím. TOP položky tak\n"
        "    # nemohou dostat stejnou barvu kvůli cyklování palety přes skryté řádky.\n"
        "    result={};used=set();palette_index=0\n"
        "    for item in items:\n"
        "        label=str(item.get('label') or 'Bez názvu')\n"
        "        if label in SPECIAL_COLORS:\n"
        "            color=SPECIAL_COLORS[label]\n"
        "        elif label.startswith('Nezařazené') or label.startswith('Ostatní'):\n"
        "            color='#8193A9'\n"
        "        else:\n"
        "            color=None\n"
        "            for _ in range(len(PALETTE)):\n"
        "                candidate=PALETTE[palette_index%len(PALETTE)];palette_index+=1\n"
        "                if candidate not in used:\n"
        "                    color=candidate;break\n"
        "            if color is None:color=PALETTE[palette_index%len(PALETTE)]\n"
        "        result[label]=color;used.add(color)\n"
        "    return result\n",
        'chart palette helpers',
    )

    text = _replace_once(
        text,
        "        self._colors={str(r.get('label') or r.get('name') or r.get('customer') or r.get('code') or 'Bez názvu'):PALETTE[i%len(PALETTE)] for i,r in enumerate(self.rows)}\n        self._colors.update({'Milan':COLORS['teal'],'Jirka':COLORS['amber'],'Honza':COLORS['blue'],'Nezařazené':'#8193A9'})\n",
        "        self._colors={}\n",
        'ShareChart initial colors',
    )

    text = _replace_once(
        text,
        "        for key,b in self.metric_buttons.items():b.configure(bg=COLORS['panel_alt'] if key==self.metric else COLORS['panel_soft'],fg=COLORS['teal'] if key==self.metric else COLORS['muted'],disabledforeground=COLORS['muted'],activebackground=COLORS['border'])\n",
        "        for key,b in self.metric_buttons.items():b.configure(bg=COLORS['panel_alt'] if key==self.metric else COLORS['panel_soft'],fg=_metric_color(key) if key==self.metric else COLORS['muted'],disabledforeground=COLORS['muted'],activebackground=COLORS['border'])\n",
        'ShareChart metric button color',
    )

    text = _replace_once(
        text,
        "        if not items:\n            self._text(w/2,h/2,'Pro zvolený ukazatel nejsou data.',width=w-15,anchor='center',color=COLORS['muted']);return\n        note=self._note\n",
        "        if not items:\n            self._text(w/2,h/2,'Pro zvolený ukazatel nejsou data.',width=w-15,anchor='center',color=COLORS['muted']);return\n        self._colors=_display_colors(items)\n        note=self._note\n",
        'ShareChart visible color assignment',
    )

    text = _replace_once(
        text,
        "            for i,x in enumerate(items):\n                if x['value']<=0:continue\n                extent=-359.99*x['value']/total\n                c.create_arc(x0,y0,x0+size,y0+size,start=start,extent=extent,fill=self._colors.get(x['label'],'#8193A9'),outline=COLORS['panel'])\n                self._wedges.append((cx,cy,size/2,size*.30,start,extent,x,total));start+=extent\n",
        "            for i,x in enumerate(items):\n                if x['value']<=0:continue\n                degrees=359.99*x['value']/total\n                extent=-degrees\n                # Tk může extrémně malý extent zaokrouhlit na 0 a vykreslit ho\n                # jako celý kruh. Takový řez je pod rozlišovací schopností grafu,\n                # proto zůstane v legendě/procentech, ale nekreslí se do donutu.\n                if degrees>=MIN_DONUT_DEGREES:\n                    c.create_arc(x0,y0,x0+size,y0+size,start=start,extent=extent,fill=self._colors.get(x['label'],'#8193A9'),outline=COLORS['panel'],width=2)\n                    self._wedges.append((cx,cy,size/2,size*.30,start,extent,x,total))\n                start+=extent\n",
        'ShareChart tiny wedge guard',
    )

    text = _replace_once(
        text,
        "        avail=w-start_x-value_width-pw-28\n        label_width=max(35,avail*.50);bar_left=start_x+label_width+14;bar_right=w-value_width-pw-16\n        if bar_right-bar_left<35:\n            label_width=max(30,w-start_x-value_width-pw-26);bar_left=bar_right\n",
        "        avail=w-start_x-value_width-pw-28\n        # Sloupec názvů vychází z reálné délky textu, ne z poloviny šířky okna.\n        # Na širokém monitoru tak nevzniká velká prázdná plocha před sloupci.\n        label_need=max(self._font(9).measure(str(x['label'])) for x in items)+24\n        label_cap=max(100,min(360,w*.34))\n        label_width=max(70,min(label_cap,label_need));bar_left=start_x+label_width+14;bar_right=w-value_width-pw-16\n        if bar_right-bar_left<35:\n            label_width=max(30,bar_right-start_x-49);bar_left=start_x+label_width+14\n",
        'ShareChart responsive label width',
    )

    path.write_text(text, encoding='utf-8')


def patch_report_svg(path: str | Path) -> None:
    path = Path(path)
    text = path.read_text(encoding='utf-8')

    old = """def colors(rows,label_key):\n    result={str(x.get(label_key) or 'Bez názvu'):PALETTE[i%len(PALETTE)] for i,x in enumerate(rows)}\n    result.update({'Milan':TEAL,'Jirka':AMBER,'Honza':BLUE,'Nezařazené':'#8291A6'})\n    return result\n"""
    new = """SPECIAL_COLORS={'Milan':TEAL,'Honza':BLUE,'Jirka':AMBER,'Nezařazené':'#8291A6'}\n\ndef colors_for_labels(labels):\n    result={};used=set();palette_index=0\n    for raw in labels:\n        label=str(raw or 'Bez názvu')\n        if label in SPECIAL_COLORS:\n            color=SPECIAL_COLORS[label]\n        elif label.startswith('Nezařazené') or label.startswith('Ostatní'):\n            color='#8291A6'\n        else:\n            color=None\n            for _ in range(len(PALETTE)):\n                candidate=PALETTE[palette_index%len(PALETTE)];palette_index+=1\n                if candidate not in used:\n                    color=candidate;break\n            if color is None:color=PALETTE[palette_index%len(PALETTE)]\n        result[label]=color;used.add(color)\n    return result\n"""
    text = _replace_once(text, old, new, 'PDF display colors')
    text = _replace_once(text, "    color_map=colors(rows,label_key)\n", "    color_map=colors_for_labels([label for _,label in valid])\n", 'PDF bar colors')
    text = _replace_once(text, "    color_map=colors(rows,label_key)\n", "    color_map=colors_for_labels([x['label'] for x in items])\n", 'PDF share colors')
    path.write_text(text, encoding='utf-8')


def apply(stage: str | Path) -> None:
    stage = Path(stage)
    patch_charts(stage/'src/charts.py')
    patch_report_svg(stage/'src/report_svg.py')


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2:
        raise SystemExit('usage: patch_graphs.py <stage>')
    apply(sys.argv[1])
