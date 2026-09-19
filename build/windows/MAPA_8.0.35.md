# Mapa v TURTO CRM 8.0.35

Mapa používá online podklad OpenFreeMap bez API klíče a kreditů. MapLibre GL JS
je součástí instalace. Podklad vyžaduje internet; dostupnost veřejné služby není
garantovaná. Záznamy CRM se na mapový server neodesílají. Server dostává běžné
požadavky na mapové dlaždice pro prohlíženou oblast.

## Použití

1. Otevřete **Mapa**, vyberte **Společnosti**, **Akce** nebo **Obojí**.
2. Existující GPS akcí se zobrazí automaticky. Souřadnice mají pořadí šířka, délka.
3. Pro adresy společností stáhněte **Adresář ČR**. Jde o oficiální měsíční ZIP
   adresních míst RÚIAN (ČÚZK, CC BY 4.0). Index se uloží do místní cache tohoto
   počítače; není součástí CRM databáze ani jejích záloh. Podle připojení a výkonu
   může první stažení a příprava několik minut trvat. Lze také importovat ZIP ČÚZK.
4. **Doplnit polohy podle adres** nabídne pouze jednoznačné úplné shody včetně PSČ.
   Existující GPS se nepřepisují. Nejednoznačné, neúplné a zahraniční adresy lze
   umístit kliknutím do mapy nebo vložením GPS. Uložení bodu z mapy se potvrzuje.
5. **Otevřít záznam** otevírá původní formulář společnosti nebo Akce. Přejmenování
   nezaloží nový bod, protože identitou je stejné databázové ID.
6. V detailu Akce nastavte **Stav Akce** a **Na tuto Akci nyní dodáváme**.
   Ukončeno a Zrušeno jsou samostatné stavy. Starým akcím se stav automaticky
   neodhaduje z termínu, archivu ani objednávek. Filtr **Zahájení od/do** používá
   původní datum zahájení včetně obou krajních dnů; akce bez data vynechá.

Změna adresy ponechá původní GPS uložené, ale bod označí k ověření a do ověření
jej nezobrazí. Upravte souřadnice nebo potvrďte polohu znovu. Formulář otevřený
před změnou GPS jiným uživatelem nemůže jeho změnu přepsat. Archivované záznamy
se na mapě nezobrazují. Filtr společnosti používá ID vazeb z Techniky a dokumentů,
nikoli shodu názvů. Sloučení Akcí přesune i přímé vazby nabídek a objednávek;
historické texty a revize dokumentů zůstávají zachované.

## Oprávnění a Windows

ADMIN může nastavit samostatné oprávnění záložky Mapa. Současně platí oprávnění
Akcí a Společností: skryté záznamy se do mapového okna vůbec neposílají a změna
GPS vyžaduje právo úpravy mapy i příslušného původního záznamu. Změna uživatele
zavře předchozí mapový proces a načte jeho povolená data znovu.

Vestavěná mapa používá Microsoft Edge WebView2 Runtime. Pokud na počítači chybí,
CRM zobrazí chybu a tlačítko na oficiální instalační stránku. Zbytek CRM zůstane
dostupný. Cache WebView2 a RÚIAN je v `%LOCALAPPDATA%\TURTO\CRM-Maps`.

## Zdroje a sestavení

- OpenFreeMap: https://openfreemap.org/ a https://openfreemap.org/quick_start/
- Mapová data: OpenStreetMap contributors, https://www.openstreetmap.org/copyright
- OpenMapTiles: https://openmaptiles.org/
- RÚIAN: https://nahlizenidokn.cuzk.gov.cz/StahniAdresniMistaRUIAN.aspx
- Formát adres: https://vdp.cuzk.gov.cz/vymenny_format/csv/ad-csv-struktura.pdf
- WebView2: https://developer.microsoft.com/microsoft-edge/webview2/

Skript `scripts/build-map-host.py` ověřuje pevně zadané kontrolní součty MapLibre
5.6.2 a WebView2 SDK 1.0.4191.47, sestaví samostatný x64 WinForms host a přibalí
licence. Žádný JavaScript se nenačítá z CDN. Host přijímá pouze JSON, neposkytuje
JavaScriptu databázi ani libovolné spouštění příkazů a blokuje cizí navigaci.
Test `scripts/validate-835-map.py` ověřuje migraci, vazby, filtry, změny adres,
souběžné úpravy, oprávnění, RÚIAN a na Windows skutečný Tk/WebView2 most.
Vydání musí navíc projít stávajícími regresními testy a testem instalace/updateru.
