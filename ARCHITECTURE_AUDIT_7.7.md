# TURTO CRM 7.7 – audit aktivní runtime kompozice

Audit prošel 111 Python souborů a zaznamenal 590 přiřazení metod nebo runtime symbolů. Historické vrstvení obsahovalo 115 cílů s více než jedním vlastníkem, 69 skrytých importů/aplikací a 15 tříd dialogových oken. Ne každé opakované přiřazení je chyba, ale bez explicitního pořadí bylo obtížné určit, která implementace je při spuštění skutečně poslední.

## Kritické konflikty zjištěné před 7.7

- `App.__init__`, `enable_dialog_maximize`, `show_page` a několik refresh metod byly opakovaně baleny staršími stabilizačními vrstvami.
- `save_offer_import`, `process_offer_msg`, `process_offer_pdf` a `export_offer_excel` měly více vlastníků, což vysvětluje dřívější rozdíl mezi ruční a automatickou Nevoga extrakcí.
- `v767` spouštěl `v768`, zatímco `v768` skrytě spouštěl čtyři další Nevoga vrstvy; launcher tedy nepopisoval skutečný runtime pořádek.
- Dialogová geometrie měla minimálně dva samostatné vlastníky a část starého kódu stále používala rozměry primárního monitoru.
- Poptávky i Akce používaly několik různých zvýrazňovacích callbacků, které se mohly navzájem přepsat.

## Politika 7.7

`runtime_bootstrap.py` je jediné místo, které definuje pořadí aktivních modulů. `v768_clean_table_markers.py` je opět pouze malý kompatibilní modul a nespouští další vrstvy. `v770_runtime_policy.py` se aplikuje poslední a je jediným finálním vlastníkem:

1. názvu a ikony aplikace,
2. umístění dialogů a našeptávačů na monitoru rodiče,
3. tučného zvýraznění deadline a dlouho čekajících poptávek,
4. roztažení tabulky Akce,
5. vyhledání, doplnění a zobrazení obrázků PLEXUS,
6. uživatelského vstupu pro návrat předchozí verze.

Starší moduly zůstaly kvůli kompatibilitě databází a obchodních workflow. Jejich plošné odstranění by v jednom releasu zbytečně zvýšilo regresní riziko. Další konsolidace se má dělat po doménách, vždy s regresním testem a se zachováním jednoho finálního vlastníka.

## Vratnost

TURTO CRM 7.7.0 nese lokální, SHA-256 ověřený instalační balíček 7.6.16. Nový updater před každou výměnou programu vytvoří databázovou zálohu a ZIP snapshot současné instalace mimo instalační adresář. Návrat verze neobnovuje ani nemaže pracovní databázi; mění pouze programové soubory.

## Konsolidace náhledu PLEXUS v 7.7.3

Starší vrstva `v619` nadále vytváří pouze jeden pevný náhledový obal v detailu
přijaté nabídky. Finální politika `v770` už nevytváří druhý panel; dodává
společný resolver obrázků, obnovu vazby podle typu PLEXUS a konečné pořadí prvků
dialogu. Výsledkem je jeden panel, jeden zdroj obrazových dat a zavírací lišta až
na konci okna.


## Stabilizace filtrovacích lišt ve verzi 7.7.4

Synchronizace filtrovacích buněk nad tabulkami již nevstupuje z událostí
`Configure` ani `xscrollcommand` do vnořeného Tcl/Tk idle loopu. Požadavky na
překreslení se slučují do jednoho `after_idle` callbacku a jednoho volitelného
závěrečného časovače; souběžný redraw je blokovaný a zaniklé widgety se
ignorují. Tím je odstraněn nativní pád Windows/Python 3.14 zachycený po startu
verze 7.7.3 v `update_idletasks()`.
