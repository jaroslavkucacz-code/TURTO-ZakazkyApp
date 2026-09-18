# Přechod TURTO CRM na PostgreSQL

Testovací větev připravuje a ověřuje kopii dat pro síťový provoz. Vychází z hlavní větve CRM 8.0.34 (commit `d060d96`). První serverová agenda **Společnosti** má vlastní okno v Nastavení → Síťový pilot společností. Jeho přípravu, osobní přihlášení a rozsah popisuje [DIRECTORY.md](DIRECTORY.md). Běžné agendy CRM nadále používají SQLite; nastavení instalace ani aktualizační kanál se nepřepínají.

## Co je připravené

- Konzistentní kopie SQLite včetně potvrzených změn ve WAL; zdroj se otevírá pouze pro čtení.
- Kontrola integrity, cizích klíčů a skutečných datových typů ještě před zápisem na server.
- Převod všech běžných tabulek z vybrané CRM databáze do **nového** schématu `turto_pilot_*` v PostgreSQL. Zachovává ID, texty, čísla, historii, nastavení, oprávnění uložená v datech a binární přílohy. Kontrola porovnává počet řádků i SHA-256 celého obsahu každé tabulky, včetně duplicit.
- Primární klíče, jednoduché neselektivní unikátní indexy a deklarované cizí klíče se na serveru znovu ověřují. Čítače automatických ID pokračují i po dříve odstraněných nejvyšších ID.
- Celý převod je jedna transakce. Chyba vrátí zpět i vytvoření schématu; již existující schéma se nikdy nepoužije znovu. Dva současné převody do stejného schématu nemohou vzájemně přepsat data.
- Samostatná opakovaná kontrola po potvrzení převodu, export zálohy přes `pg_dump` a integrační zkouška obnovy do jiné databáze.
- Připojení má samostatný profil bez uloženého hesla. Vzdálené spojení vyžaduje ověření TLS certifikátu. Při chybě není automatický přechod na místní databázi.

**Výsledek je ověřená datová kopie pro vývoj, nikoli provozní databáze CRM.** Manifest na serveru obsahuje `application_ready: false`, úplné původní DDL a zbývající překážky. Není bezpečné s tímto schématem zahájit běžnou práci.

## Co zbývá před provozem více počítačů

1. Převést dotazy a migrace schématu jednotlivých agend. Současný klient používá `PRAGMA`, `sqlite_master`, `INSERT OR REPLACE`, `lastrowid`, `BEGIN IMMEDIATE` a další rozhraní SQLite. Pouhá záměna ovladače by nefungovala.
2. Převést výchozí výrazy sloupců, CHECK pravidla, indexy, triggery poslední aktivity a fulltext. Původní definice jsou uchované v manifestu, ale v první etapě se automaticky nespouštějí. Odvozený fulltext `price_list_items_fts` a jeho pomocné tabulky se nekopírují, neboť vycházejí z přenesených položek ceníků. CZECH/NOCASE zatím nejsou na serveru emulované; textová unikátnost používá výchozí kolaci PostgreSQL.
3. Rozšířit osobní serverové přihlášení a oprávnění z pilotních Společností na další agendy a správu uživatelů. Zároveň oddělit nastavení počítače a přihlášené relace od společných firemních dat. Stávající klientské kontroly a SQLite TEMP triggery nejsou serverovým zabezpečením.
4. Zkontrolovat všechny souběžné změny: nabídky, položky, číslování dokladů, poptávky, více řešitelů a oprávnění. Doplnit kontroly verze záznamu a transakce; při výpadku nesmí vzniknout nezávislé lokální zápisy.
5. Převést Přehledy z jejich samostatného úložiště a externí dokumenty/přílohy v adresářích. První převod zahrnuje jen jeden výslovně vybraný soubor CRM. Cesty k dokumentům zachová, jejich soubory tím nekopíruje. Binární hodnoty přímo v SQLite se přenášejí.
6. Doplnit společné nastavení serveru pro celé CRM, Windows balíček a testy skutečné práce na dvou PC, obnovu kompletního provozu a denní/týdenní zálohování na firemní infrastruktuře. Automatické plánování záloh zatím není zapnuté.

## Postup zkušebního převodu

Příkazy spouštějte ve složce `ZakazkyApp_base_6.1` této testovací větve, nikoli ve složce nainstalovaného CRM. Potřebujete Python 3.12+, samostatnou prázdnou testovací databázi PostgreSQL 16+ a účet s právem `CREATE` v této databázi. Pro zálohu také nástroje `pg_dump` a `pg_restore` stejné hlavní verze jako server nebo kompatibilní novější klient. Nepoužívejte ostrý databázový účet ani ostrou cílovou databázi.

```powershell
python -m pip install -r requirements-network.txt
python -m network_db snapshot --source "C:\TURTO\data\zakazky.db" --target "C:\TURTO-pilot\kopie.db"
python -m network_db inspect --source "C:\TURTO-pilot\kopie.db" --report "C:\TURTO-pilot\kontrola.json"
```

Cesty jsou příklady; zdroj musí být skutečná aktuální databáze vašeho CRM. Existující cílový soubor ani zpráva se nepřepisují. JSON protokol může obsahovat názvy tabulek a původní schéma, nikoli obsah obchodních řádků. Kopie databáze obsahuje firemní data a musí být uložena se stejnými přístupovými právy jako původní data.

Zkopírujte `docs/network/profile.example.json` mimo repozitář a upravte adresu serveru, název testovací databáze, účet a cestu k důvěryhodnému certifikátu. Heslo patří do proměnné `TURTO_PG_PASSWORD`, případně do standardního lokálního úložiště hesel libpq; ne do JSON, příkazových argumentů či GitHubu. Pro test na `127.0.0.1` lze výslovně nastavit `sslmode` na `disable`.

```powershell
python -m network_db check --profile "C:\TURTO-pilot\profile.json"
python -m network_db migrate --source "C:\TURTO-pilot\kopie.db" --profile "C:\TURTO-pilot\profile.json" --schema turto_pilot_prvni --report "C:\TURTO-pilot\prevod.json"
python -m network_db verify --profile "C:\TURTO-pilot\profile.json" --schema turto_pilot_prvni
python -m network_db backup --profile "C:\TURTO-pilot\profile.json" --schema turto_pilot_prvni --target "C:\TURTO-pilot\pilot.dump"
```

Po úspěchu musí `verify` vrátit `ok: true` a všechny tabulky musí mít shodný kontrolní otisk. `application_ready` má v této etapě zůstat `false`. Při porušených vazbách nebo nekompatibilních hodnotách se postup zastaví; opravy dat se nedělají automaticky. Po ztrátě spojení v okamžiku potvrzení je stav transakce nejistý: použijte `verify`, nikoli automatické opakování nebo mazání schématu. Pokud selže zápis místního protokolu po úspěšném potvrzení, manifest zůstává na serveru a stejná kontrola funguje.

Obnovu zálohy zkoušejte výhradně v jiné prázdné databázi. `pg_restore --list` kontroluje čitelnost souboru, nikoli úplnou obnovitelnost. Integrační test provádí skutečné obnovení a následné porovnání obsahu. Záloha pilotního schématu neobsahuje ostatní databáze, externí přílohy, serverové role ani serverové nastavení.

## Ověřování při vývoji

Skutečný stav provedených a neprovedených kontrol je v [VALIDATION.md](VALIDATION.md).

```bash
python tests/network/test_migration.py
TURTO_TEST_POSTGRES=1 TURTO_PG_PASSWORD=... python tests/network/test_migration.py
```

První příkaz kontroluje bezpečnost zdroje bez serveru; integrační testy označí jako přeskočené. Druhý vyžaduje skutečný PostgreSQL na `127.0.0.1`, databázi `turto_pilot_test` a testovací účet `postgres` s právem vytvořit databázi pro zkoušku obnovy. Port, uživatele a databázi lze upravit proměnnými `TURTO_TEST_PG_PORT`, `TURTO_TEST_PG_USER` a `TURTO_TEST_PG_DATABASE`. Jde pouze o automatizované testovací prostředí, nikoli doporučená oprávnění provozního uživatele.

GitHub workflow `Validate PostgreSQL migration pilot` spouští kontrolu na skutečném PostgreSQL 16 a 18. Obsahuje převod celého schématu aktuálního CRM se zkušebními obchodními záznamy, přílohami a kontrolou obnovy. Výsledky běhu jsou rozhodující; samotná existence workflow neznamená úspěšné ověření.

Technické podklady: [transakce Psycopg](https://www.psycopg.org/psycopg3/docs/basic/transactions.html), [pg_dump](https://www.postgresql.org/docs/current/app-pgdump.html), [datové typy PostgreSQL](https://www.postgresql.org/docs/current/datatype.html).
