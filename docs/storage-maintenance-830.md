# Zálohy a úklid úložiště (8.0.30)

V **Nastavení → Zálohy a úklid úložiště…** se nejprve zobrazí náhled.
Načtení náhledu nic nemaže a automatická údržba je po aktualizaci vypnutá.

## První úklid

1. Zkontrolujte řádky označené **K úklidu** a vyberte konkrétní soubory
   (Ctrl/Shift nebo **Vybrat vše k úklidu**).
2. Preferujte **Přesunout do archivu…** na jiný disk. Kopie se ověří SHA-256;
   originál se odstraní až po úspěšné kontrole. Na stejném disku se místo neuvolní.
   Případně použijte **Smazat vybrané…**: vyžaduje potvrzení, je trvalé a nepoužívá koš.
3. Před úklidem vznikne ověřená bezpečnostní záloha aktuální databáze. Musí pro ni
   zbývat místo přibližně o velikosti databáze. Náhled uvádí hrubou velikost
   kandidátů, nikoli zaručený čistý přírůstek volného místa.
4. Výsledek a případná chyba se zobrazí v dialogu. Protokol je v
   `logs/storage_cleanup_*.json`, archiv navíc obsahuje `manifest.json`.

Živá databáze, přílohy nabídek, ceníky, konfigurace ani rozbalené programové
složky nejsou kandidáty. Neznámé názvy, ruční/importní/migrační zálohy, soubory
odkazované archivem nebo poslední aktualizací a zálohy s SQLite doprovodnými
soubory (`-wal`, `-shm`, `-journal`) zůstávají zachované. Ty poslední vyžadují
samostatnou kontrolu; nástroj je nerozděluje ani automaticky neopravuje.

## Uchování a volitelná automatika

Automatické zálohy před aktualizací/návratem verze, denní zálohy a bezpečnostní
zálohy před tímto úklidem zachovávají posledních 5 kusů plus nejnovější bod
každého z posledních 7 kalendářních dnů, 8 kalendářních týdnů a 12 měsíců.
Překryvy se počítají jednou; chybějící historické body nelze zpětně vytvořit.
Soubory mladší 24 hodin se nikdy nepromazávají. U rozpoznaných aktualizačních
ZIPů zůstávají dva nejnovější v každé sledované složce a explicitní odkazy
poslední aktualizace/návratu/chyby. Jinak pojmenované soubory zůstanou.

Zaškrtnutí **Denní záloha a automatické promazávání…** samo nic neukládá.
Použijte **Uložit pravidla** a potvrďte. Automatika je svázaná s konkrétní
databází, běží při spuštěném CRM (kontrola 15 sekund po startu a poté každou
hodinu), vytvoří nejvýše jednu úspěšnou denní zálohu a uvolní jen přebytečné
automatické soubory vzniklé **až po zapnutí**. Staré soubory zůstávají k ručnímu
posouzení. Při vypnutém CRM se nic neplánuje ani nezálohuje. V režimu TEST je
úklid i spuštění automatické údržby zakázané.

Denní výsledek je v `logs/storage_daily.json`, chyba v
`logs/storage_daily_error.json`. Vypnutí a uložení pravidel zastaví další běhy.
Probíhající údržba/aktualizace se navzájem blokují zámkem; selhání zálohy,
nečitelná metadata nebo změna vybraného souboru úklid zastaví. Již dokončené
přesuny/smazání jsou uvedené v protokolu. Ruční zálohy zůstávají bez omezení,
proto ani tato pravidla nepředstavují absolutní limit velikosti složky.

## Obnova

Zálohy vznikají SQLite backup API včetně potvrzených dat z WAL a před zveřejněním
se kontrolují. Jde o soubory SQLite `.db`, nikoli ZIP balíčky pro **Import kompletní
databáze…**. Pro obnovu použijte existující **Správu databáze → Připojit existující
databázi…** a doporučenou volbu zkopírování do standardní složky. Předem zavřete
ostatní okna CRM, ověřte požadované datum a počítejte s nahrazením aktuálního
obsahu; dialog před nahrazením nabízí bezpečnostní zálohu dosavadních dat.
Archivovaný soubor lze nejprve zkopírovat na bezpečné místo a ověřit jeho
SHA-256 podle manifestu. Návrat programu používá existující dialog pro návrat
verze; úklid chrání soubory, na které tento mechanismus odkazuje.

Záloha na témže disku nechrání před poruchou disku. Samostatný externí archiv
nebo jiné nezávislé zálohování zůstává potřeba. Tato změna nemění databázový
server ani připravovanou migraci pro více PC.
