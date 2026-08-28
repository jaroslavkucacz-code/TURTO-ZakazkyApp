from pathlib import Path

app_path = Path('ZakazkyApp_base_6.1/app.py')
text = app_path.read_text(encoding='utf-8')
old = 'self.notes_button=ttk.Button(top,text="📝",style="TopAction.TButton",width=6,command=self.open_user_notes)'
new = 'self.notes_button=ttk.Button(top,text="📝 Poznámky",style="TopAction.TButton",width=15,command=self.open_user_notes)'
if old not in text:
    raise SystemExit('notes button build marker not found')
text = text.replace(old, new, 1)
old2 = "self.notes_button.configure(text=f'📝 {count}' if count else '📝')"
new2 = "self.notes_button.configure(text=f'📝 Poznámky ({count})' if count else '📝 Poznámky')"
if old2 not in text:
    raise SystemExit('notes button refresh marker not found')
text = text.replace(old2, new2, 1)
app_path.write_text(text, encoding='utf-8')

Path('release_version.txt').write_text('6.3.16\n', encoding='utf-8')
Path('release_notes.txt').write_text(
    '• Tlačítko osobních Poznámek v horní liště je nově výraznější a obsahuje text „Poznámky“.\n'
    '• Pokud má aktivní uživatel nearchivované poznámky, tlačítko ukazuje jejich počet ve formátu „Poznámky (N)“.\n'
    '• Umístění zůstává přímo vedle aktivního uživatele; funkce Poznámek, archivace, vyhledávání i oddělení podle uživatele se nemění.\n',
    encoding='utf-8',
)
