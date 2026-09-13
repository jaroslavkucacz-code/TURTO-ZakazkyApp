TURTO – Měsíční přehledy
Verze 1.0.0 – nativní Windows vydání

SPUŠTĚNÍ
- Doporučeno: TURTO_Mesicni_Prehledy.exe
- Případně START_TURTO.bat, který spustí stejné EXE.
- Pro běžný provoz už není potřeba mít nainstalovaný Python.
- Program neotevírá konzolové okno.

HLAVNÍ FUNKCE
- tmavý manažerský dashboard v češtině
- období: měsíc / YTD / rok / posledních 12 měsíců
- obrat, hrubý zisk, vážená marže, počet DL, průměrná hodnota DL a režijní listy
- interaktivní graf obratu, zisku a marže
- výkon obchodníků M=Milan, J=Jirka, H=Honza včetně zisku
- zákazníci s historií a rozklikávacím detailem
- produkty a položky dodacích listů
- vyhledávání a řazení ve všech tabulkách
- export do Excelu a manažerského PDF reportu
- oddělená SQLite databáze s možností sdíleného umístění
- zálohování databáze
- online aktualizace se zachováním databáze, importů, exportů a config.json

NATIVNÍ WINDOWS VERZE 1.0
- hlavní proces je TURTO_Mesicni_Prehledy.exe, nikoli pythonw.exe
- ikona TURTO je vložena přímo do EXE
- zástupce na ploše/Start menu míří přímo na EXE
- aktualizace používají samostatný TURTO_Update_Helper.exe
- Python runtime je součástí aplikace v interní složce a uživatel jej nemusí instalovat ani spravovat

DATABÁZE
Výchozí: data\turto_dashboard.db
V Nastavení lze zvolit jiné umístění. Databáze a config.json nejsou součástí aktualizačních balíčků a při aktualizaci se nepřepisují.

EXPORT PDF
PDF se vytváří přes systémový Microsoft Edge/Chrome z interního HTML/SVG reportu.

EXPORT EXCEL
XlsxWriter je v nativním EXE již zabalený; není potřeba nic instalovat přes pip.

Vytvořil Ing. Jaroslav Kučera
