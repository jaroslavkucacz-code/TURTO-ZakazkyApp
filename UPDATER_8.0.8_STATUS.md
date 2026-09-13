# TURTO CRM 8.0.8 — vydáno

Stabilní vydání `v8.0.8` bylo zveřejněno 13. 9. 2026 v 20:07:54 UTC.

- Zdrojový commit sestavení: `e86fde121f30370b76cf1bfee5aae6b48d2557bf`.
- Úspěšná kompletní validace: https://github.com/jaroslavkucacz-code/TURTO-ZakazkyApp/actions/runs/34779446776
- Úspěšná publikace: https://github.com/jaroslavkucacz-code/TURTO-ZakazkyApp/actions/runs/34779780429
- Vydání: https://github.com/jaroslavkucacz-code/TURTO-ZakazkyApp/releases/tag/v8.0.8

## Ověřeno

Na Windows prošla původní kontrola instalace/datového umístění a všech 29 regresních testů updateru + 7 testů potvrzení připravenosti, zrušení a procesních zámků. Na Linuxu prošly odpovídající sady; dvě kontroly vyhrazené pro Windows byly přeskočeny.

Hotové EXE a instalátor prošly čistou instalací, inicializací runtime a databáze, kontrolou TkDnD a parserů nabídek, spuštěním adresářového updateru, potvrzením připravenosti při živém rodičovském procesu, skutečnou aktualizací a návratem verze, opravnou instalací a odinstalací. Bylo kontrolováno zachování testovací databáze včetně porovnání SHA-256. Úplný strojový protokol je součástí vydání jako `TURTO_CRM_8.0.8_validation.json`.

Publikovány byly přesně otestované soubory bez nového sestavení. Publikační workflow ověřilo shodu zdrojového commitu, výsledků všech povinných úloh, testovacího protokolu, hashů vstupních souborů i hashů souborů v GitHub Release.

| Soubor | SHA-256 |
| --- | --- |
| TURTO_CRM_Setup_8.0.8.exe | `4a567c4f8827f89eba4d70b854207917814dda47e09abd08c5f1bc5fc7a31c66` |
| TURTO_CRM_Update_8.0.8.zip | `99be947509722a8ba8a70f33fc30b3e34a43ef8b3371cc000e1aa45800aa96f0` |

## Přechod a aktualizační kanály

Z 8.0.7 a starších verzí je nutná jednorázová instalace plným `TURTO_CRM_Setup_8.0.8.exe` přes stávající instalaci, bez předchozí odinstalace. Databáze ani uživatelská data nejsou součástí balíčku.

Původní `latest-windows.json` zůstal beze změny na 8.0.7, aby známý chybný updater neinstaloval vlastní opravu. Nová aplikace používá `latest-windows-v2.json`, publikovaný na 8.0.8 se shodnými kontrolními součty. Oba manifesty a metadata skutečného vydání byly po publikaci znovu načteny a ověřeny.

## Bezpečnostní omezení

ESET není na hostovaném testovacím stroji instalován. Nebyl ověřen výsledek jeho detekce u tohoto sestavení a není slíbeno odstranění falešného poplachu. Program nemění nastavení ochrany, nevytváří výjimky a neobnovuje soubory z karantény. Historické záznamy karantény zůstávají správou ESETu.

Výměna používá připravený adresář, dva přejmenovací kroky a záznam transakce. Nejde o jednu atomickou operaci odolnou proti každému přerušení napájení. Při neúspěšné obnově se zachová původní adresář a informace pro zotavení; původní program se před přípravou nové verze postupně nemaže.
