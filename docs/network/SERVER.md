# Firemní server, kancelářská síť a VPN

Požadovaný provoz: kancelářská firemní Wi-Fi/kabel a domácí počítač po připojení firemní VPN používají stejný interní server PostgreSQL. Databáze se nesdílí jako SQLite soubor po SMB. Přesnou instalaci databázové služby je nutné zvolit podle systému serveru (Windows Server, Linux nebo NAS s podporovanou službou/virtuálním strojem).

## Údaje, které správce předá pro první zkoušku

| Údaj | Požadavek |
| --- | --- |
| Server | PostgreSQL 16 nebo novější; klientské sestavení se navíc zkouší proti PostgreSQL 17 ve Windows |
| Adresa | Jeden interní DNS název dosažitelný v kanceláři i přes VPN, například `crm-db.firma.internal`; skutečnou adresu určí správce |
| Port | Typicky TCP 5432; přístup z povolené kancelářské a VPN sítě |
| Testovací databáze | Nová samostatná databáze, například `turto_crm_pilot` |
| Testovací schéma | Například `turto_pilot_prvni`, připraví níže uvedený nástroj |
| TLS | Certifikát serveru s odpovídajícím DNS jménem v SAN a veřejný PEM certifikát důvěryhodné CA pro klienty |
| Osobní účty | Samostatné přihlášení pro každého testera; alespoň dva editoři a jeden čtenář pro celý scénář |

VPN musí zpřístupnit databázový port a překlad interního jména, nikoli jen diskovou sdílenou složku. Není potřeba publikovat PostgreSQL na veřejné internetové adrese. Serverový privátní klíč zůstává pouze na serveru; klienti dostanou veřejný certifikát CA. Ověření jména a certifikátu se používá i přes VPN.

Správce nastaví `listen_addresses` na potřebné interní rozhraní, `ssl=on`, serverový certifikát a privátní klíč. V `pg_hba.conf` povolí `hostssl` se SCRAM autentizací pro konkrétní databázi, účty a skutečné kancelářské/VPN rozsahy. Pravidla se vyhodnocují od prvního odpovídajícího záznamu; je třeba prověřit i dřívější obecná pravidla. Nepřidávat univerzální přístup ze všech sítí. Firewall musí odpovídat stejným povoleným rozsahům.

Podklady správce: [ověření TLS v libpq](https://www.postgresql.org/docs/current/libpq-ssl.html), [pravidla pg_hba.conf](https://www.postgresql.org/docs/current/auth-pg-hba-conf.html).

## Příprava umělé ukázky bez Pythonu

Z připraveného balíčku používejte konzolový soubor `TURTO-CRM-Pilot-Admin.exe`. Následující příkazy PowerShellu se spouštějí ze složky s oběma EXE. PostgreSQL už musí být nainstalovaný a dostupný; tento nástroj neinstaluje server, nenastavuje VPN ani firewall.

1. Správce vytvoří novou prázdnou databázi pro pilot. Účet přípravy musí mít právo CREATE v této databázi a být následně vlastníkem vytvářeného schématu. Samostatná omezená uživatelská přihlášení vytvoří správce PostgreSQL.
2. Zkopíruje přiložený `profile.example.json` na `admin-profile.json` mimo běžné sdílení testerům a vyplní skutečnou adresu, databázi, účet přípravy a cestu k certifikátu. Nevyplňuje heslo do JSON. Profil neobsahuje data CRM.
3. Spustí ověření a přípravu. Přepínač `--ask-password` patří před název příkazu a otevře skrytou výzvu k heslu:

```powershell
.\TURTO-CRM-Pilot-Admin.exe --ask-password check --profile .\admin-profile.json
.\TURTO-CRM-Pilot-Admin.exe --ask-password prepare-demo --profile .\admin-profile.json --schema turto_pilot_prvni
```

Příprava založí nové schéma, převede ukázkové tabulky skutečného CRM a zapne serverové Společnosti. Vypíše ID a názvy zkušebních osob. Existující schéma nikdy nepřepisuje. Po chybě neodstraňujte schéma automaticky; zkontrolujte stav příkazy `verify` a `directory-install` popsanými v README/DIRECTORY. Příprava ukázky neotevírá žádnou databázi vašeho nainstalovaného CRM.

4. Správce PostgreSQL vytvoří osobní role. Příklad v psql; jména jsou vzory, použijte skutečné účty:

```sql
CREATE ROLE turto_tester1 LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
\password turto_tester1
CREATE ROLE turto_tester2 LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
\password turto_tester2
CREATE ROLE turto_ctenar LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
\password turto_ctenar
```

5. Účet přípravy propojí role s ID osob z výstupu přípravy. `ID_EDITORA` a `ID_CTENARE` nahraďte skutečnými celými čísly. Druhý tester může pro první zkoušku sdílet zkušební identitu editora; jeho přihlášení a heslo zůstávají osobní a historie uchovává serverový účet.

```powershell
.\TURTO-CRM-Pilot-Admin.exe --ask-password directory-authorize --profile .\admin-profile.json --schema turto_pilot_prvni --login turto_tester1 --user-id ID_EDITORA
.\TURTO-CRM-Pilot-Admin.exe --ask-password directory-authorize --profile .\admin-profile.json --schema turto_pilot_prvni --login turto_tester2 --user-id ID_EDITORA
.\TURTO-CRM-Pilot-Admin.exe --ask-password directory-authorize --profile .\admin-profile.json --schema turto_pilot_prvni --login turto_ctenar --user-id ID_CTENARE
```

Přehled osob lze znovu vypsat přes `directory-users --profile ... --schema ...`. Omezené role nesmějí mít přímá práva k tabulkám, právo CREATE na schéma, členství v jiných rolích ani vlastnictví databáze.

6. Testerům předá adresu, port, databázi, schéma, vlastní účet a veřejný certifikát CA. Hesla předá samostatně běžným firemním postupem. Tester zadá tyto údaje ve formuláři programu. Nejprve se provede kontrola v kanceláři, poté přes VPN.

## Vlastní kopie dat a zálohy

Pokud je potřeba místo umělé ukázky zkusit provozní kopii, použijte příkazy `snapshot`, `inspect`, `migrate`, `verify` a `directory-install` podle přiloženého README/DIRECTORY. Místo `python -m network_db` lze vždy použít `.\TURTO-CRM-Pilot-Admin.exe`; pro zadání hesla přidejte globální `--ask-password`. Ukázková a skutečná kopie musí mít odlišné schéma.

Příkaz `backup` potřebuje `pg_dump` a `pg_restore` kompatibilní se serverem v PATH. Balíček od verze 0.3.0 přikládá PostgreSQL pro místní ukázku ve složce `postgresql`; neinstaluje tím databázovou službu na firemní server a nepřidává nástroje do systémového PATH. Pro firemní zálohy musí správce ověřit kompatibilitu verze klientských nástrojů. Zálohy upraveného pilotu vyžadují `--allow-pilot-changes`. Zálohu ověřujte obnovou do jiné testovací databáze; role a hesla je nutné spravovat samostatně. Denní/týdenní zálohování a jeho cílové úložiště nastaví správce na firemní infrastruktuře.
