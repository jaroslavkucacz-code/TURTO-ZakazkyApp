# Úklid starých záloh s doprovodnými soubory (8.0.31)

V Nastavení → Zálohy a úklid úložiště zaškrtněte **Zahrnout staré zálohy
s doprovodnými soubory**. Náhled se obnoví. Databáze a její `-wal`, `-shm`
a `-journal` jsou jeden řádek se součtem velikostí. Samostatné doprovodné
soubory se nevybírají. Použijte Vybrat vše k úklidu a potvrďte přesun do
archivu na jiný disk nebo trvalé smazání. Před akcí vznikne ověřená záloha.

Volba platí pouze pro tento ruční úklid. Denní automatika staré skupiny
nezahrnuje. Ruční, importní a migrační zálohy zůstávají chráněné, stejně
jako používaná databáze, odkazy obnovy, hardlinky a soubory mladší 24 hodin.
Pravidla posledních 5 + 7 denních + 8 týdenních + 12 měsíčních bodů se počítají
i nad rozpoznanými automatickými zálohami s doprovodnými soubory.

Samotná přítomnost SHM nedokazuje, že je záloha používaná. Před zásahem se
na Windows otevřou všechny členy skupiny výhradně (CreateFileW bez sdílení).
Pokud některý používá jiný proces nebo přístup není povolen, operace se
zastaví a celá tato skupina zůstane. Zámky zůstávají po celou dobu kopírování,
ověření a označování ke smazání. Viz [Microsoft CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).

Při archivaci se každý člen nejprve zkopíruje a ověří SHA-256. Před odstraněním
prvního originálu musí být ověřené všechny kopie. Žádné SQLite přepínání režimu,
checkpoint nebo oprava staré zálohy se neprovádí. Archivovaný WAL může obsahovat
potvrzená data a patří ke své databázi; při obnově kopírujte celou skupinu.

Protokol obsahuje jednotlivé členy, skutečně zpracované bajty a případnou chybu.
Před zásahem je zapsán seznam `pending_group`. Vícesouborové smazání není
jediná atomická operace. Databáze se označuje ke smazání jako první a její
výhradní handle zavírá poslední, aby při přerušení nezůstala použitelná
databáze s chybějící částí žurnálu. Přerušený seznam vyžaduje kontrolu podle
protokolu; nástroj jej automaticky nedokončuje.

Náhled zobrazuje objem chráněných položek. Odhad úklidu nezohledňuje novou
bezpečnostní zálohu a další data vznikající při práci v CRM.
