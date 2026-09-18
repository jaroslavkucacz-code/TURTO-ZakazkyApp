# Síťový pilot agendy Společnosti

První agenda pracuje přímo s testovací kopií na PostgreSQL: osobní přihlášení, vyhledávání a stránkování, založení společnosti, úprava názvu, IČ, DIČ, adresy, webu, poznámky a příznaků odběratel/dodavatel/aktivní. Přehled zobrazuje oficiální název, u starých nevyplněných názvů použije krátký název. Historie ukazuje posledních 100 serverových změn. Mazání ani další agendy zde nejsou zpřístupněny.

Okno otevřete v **Nastavení → Síťový pilot společností…** při spuštění zdrojů testovací větve. Samostatně jej lze spustit příkazem `python -m network_db.ui` ze složky `ZakazkyApp_base_6.1`. Potřebuje `requirements-network.txt` a Tk. Samostatný Windows balíček sestavuje a ověřuje workflow; obsahuje stejné okno, formulář nastavení připojení a konzolový nástroj správce. Návod je v [TRY-PILOT.md](TRY-PILOT.md), příprava firemního serveru pro kancelář a VPN v [SERVER.md](SERVER.md).

## Příprava správcem

Nejprve proveďte převod a kontrolu podle [README](README.md). Příkazy níže mají záměrně oddělený profil správce. Instalace agendy vyžaduje vlastníka schématu nebo správce PostgreSQL a čistou, ověřenou kopii; opakování již nainstalovanou agendu ani provedené změny nepřepíše.

```powershell
python -m network_db directory-install --profile "C:\TURTO-pilot\admin-profile.json" --schema turto_pilot_prvni
```

Správce vytvoří pro každou osobu samostatnou databázovou roli `LOGIN` bez práv superuživatele, CREATE DATABASE, CREATE ROLE, REPLICATION, BYPASSRLS, členství v jiných rolích, vlastnictví databáze, práva CREATE na pilotní schéma a přímých práv k jeho tabulkám. Například v psql připojeném jako správce:

```sql
CREATE ROLE turto_jana LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
\password turto_jana
SELECT id, name, active, tab_permissions FROM turto_pilot_prvni.users ORDER BY id;
```

Heslo se zadá do výzvy psql; nevkládá se do souboru SQL ani do příkazové řádky. Následně správce propojí roli se správnou existující aktivní osobou CRM. ID `7` je pouze příklad a musí být nahrazeno skutečným ID z testovací kopie:

```powershell
python -m network_db directory-authorize --profile "C:\TURTO-pilot\admin-profile.json" --schema turto_pilot_prvni --login turto_jana --user-id 7
```

Práva ke Společnostem se čtou z `users.tab_permissions`: `companies: 0` skryto, `1` pouze čtení, `2` úpravy. Chybějící hodnota má stejné výchozí oprávnění `2` jako stávající CRM; nesprávný formát nastavení přístup zamítne. Profil s názvem ADMIN odpovídá správci CRM, stále však musí mít vlastní omezené serverové přihlášení. Správu oprávnění v této etapě provádí správce nad serverovou kopií; změny uživatelů v místním SQLite se na server nesynchronizují.

Odebrání přístupu platí i pro již přihlášené relace při jejich další operaci:

```powershell
python -m network_db directory-revoke --profile "C:\TURTO-pilot\admin-profile.json" --schema turto_pilot_prvni --login turto_jana
```

## Práce v okně

Uživatel vybere JSON profil bez hesla, zadá své serverové jméno a heslo a přihlásí se. Profil musí odkazovat na správný testovací server a databázi; vzdálené připojení ověřuje TLS podle profilu. Heslo je pouze v paměti přihlášeného klienta, z formuláře po pokusu o přihlášení zmizí. Do logů a profilů se nezapisuje. Běžná práce nesmí používat profil správce.

Oprávnění kontroluje server při každém čtení i zápisu podle autentizovaného `session_user`, nikoli podle aktivního uživatele místního CRM. Osobní role dostává jen přístup k vyjmenovaným funkcím; přímý SELECT/UPDATE tabulek, změna mapování osob a manipulace s historií jsou zakázané. Funkce mají pevnou cestu hledání objektů a přístupy PUBLIC jsou odebrané.

Při uložení se porovnává verze otevřeného záznamu. Pokud ho mezitím změní jiná osoba, uložení se odmítne a rozepsané údaje zůstanou v okně. Tlačítko **Načíst aktuální údaje** po potvrzení načte novou verzi; potom lze změnu znovu provést. Firma, historie se skutečným autorem a záznam požadavku se ukládají v jedné transakci.

Po přerušení spojení během ukládání se formulář zamkne a nabídne **Ověřit uložení**. Server vyhledá výsledek podle jedinečného ID požadavku. Pokud požadavek neeviduje, lze stejný požadavek ručně zopakovat; opakované doručení se provede pouze jednou. Požadavek se automaticky neopakuje a neukládá se do místní databáze. Identifikátor rozepsaného požadavku žije v aktuálním okně; po jeho zavření nebo restartu je nutné zkontrolovat firmu a historii, než ji založíte znovu.

## Záloha upraveného pilotu

Příkaz `verify` stále porovnává převod s původní kopií SQLite. Po úpravě společnosti tedy správně hlásí rozdíl, nepřepisuje původní otisky. Pro zálohu již upravené serverové agendy je nutný výslovný parametr:

```powershell
python -m network_db backup --profile "C:\TURTO-pilot\admin-profile.json" --schema turto_pilot_prvni --allow-pilot-changes --target "C:\TURTO-pilot\po-upravach.dump"
```

Záloha zahrnuje data, historii, verze a evidenci dokončených požadavků. Obnovuje se do jiné prázdné testovací databáze pomocí `pg_restore --no-owner --no-privileges --single-transaction --exit-on-error`. Databázové role a hesla nejsou součástí zálohy. Správce je musí připravit samostatně a před zpřístupněním obnovené databáze znovu provést `directory-authorize` pro každou osobu; tím se obnoví omezené přístupy k funkcím. Automatický test ověřuje skutečnou obnovu upravené firmy i historie.

## Rozsah testu

Manifest obsahuje `directory_api_version: 1` a nadále `application_ready: false`. Nové serverové společnosti nejsou synchronizované do místních agend zakázek, poptávek ani dalších tabulek CRM. Původní historie z SQLite zůstává v převedených tabulkách zachovaná; nové okno zobrazuje historii této serverové agendy. Další výchozí hodnoty, triggery a procesy celého CRM ještě nejsou převedené. Proto tato etapa slouží pro testování na kopii dat, nikoli pro plný provoz.

Workflow ověřuje osobní účty, zákaz přímého přístupu, čtenáře a skrytou agendu, změnu a odebrání práv, dva souběžné editory, opakované doručení požadavku, ztracenou odpověď, atomické vrácení změny při chybě historie, zálohu a obnovu. Samostatný test řídí skutečné Tk okno přes virtuální obrazovku: přihlášení, editaci, konflikt a čtenáře. Konkrétní výsledky jsou v [VALIDATION.md](VALIDATION.md); tato zkouška nenahrazuje ověření Windows a firemní sítě na dvou skutečných PC.
