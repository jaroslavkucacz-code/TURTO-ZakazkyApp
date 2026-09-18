# Stav první etapy přechodu na PostgreSQL

Datum kontroly 18. září 2026. Základ CRM 8.0.34, hlavní větev `d060d96`. Testovací větev `feature/postgresql-pilot` je dostupná jako [draft PR 108](https://github.com/jaroslavkucacz-code/TURTO-ZakazkyApp/pull/108). Nebyla začleněna do hlavní větve ani vydána jako aktualizace.

**První převod dat prošel na standardním PostgreSQL 16 i 18.** Výsledek potvrzuje [běh serverových testů](https://github.com/jaroslavkucacz-code/TURTO-ZakazkyApp/actions/runs/35349305873) pro commit `9cc4473b9c0a878febfd2b52d7ca6a8025ccbd05`. Následující změna tohoto protokolu upravuje pouze dokumentaci, nikoli ověřovaný kód.

## Provedené kontroly

| Oblast | Výsledek |
| --- | --- |
| Syntaxe nových modulů | Prošla |
| PostgreSQL 16 | 21 testů prošlo, žádný přeskočený |
| PostgreSQL 18 | 21 testů prošlo, žádný přeskočený |
| Bezpečnost SQLite zdroje a profilů připojení | 13 z uvedených 21 testů na každé verzi serveru |
| Serverové integrační scénáře | 8 z uvedených 21 testů na každé verzi serveru |
| Stávající správa souborů a záloh CRM | Dalších 14 testů prošlo na obou prostředích |
| Stávající oprávnění CRM 8.0.34 | Databázová regresní kontrola prošla na obou prostředích |
| Inventura schématu vytvořeného aktuálním CRM | 50 běžných tabulek, 38 triggerů, 89 explicitních indexů; běžné tabulky prošly kontrolou datových typů a obsahu |
| Napojení GUI na server a práce na dvou PC | Dosud neimplementováno; GUI stále používá SQLite |

Serverové testy ověřily převod celého schématu aktuálního CRM se zkušebními obchodními záznamy, české texty, binární přílohy, duplicity, číselné hodnoty a zachování čítačů po odstraněných ID. Dále ověřily opětovné porovnání dat, vynucení cizích a unikátních klíčů, odmítnutí přepsání existujícího cíle, vrácení celé transakce při chybě, souběh dvou převodů do stejného schématu a utajení hesla při chybě spojení.

Záloha přes `pg_dump` byla skutečně obnovena pomocí `pg_restore` do jiné testovací databáze. Následná kontrola všech převedených tabulek potvrdila shodné počty řádků a otisky obsahu.

Dřívější lokální pokus použít PGlite s TCP adaptérem selhal při přenosu `COPY FROM STDIN` na úrovni protokolu. Následné úspěšné testy proběhly na standardních PostgreSQL serverech; přenos nebyl upraven kvůli omezení náhradního prostředí.

## Rozsah následující etapy

Ověřený výsledek je datová kopie pro další vývoj a nadále má `application_ready=false`. Ještě není provozní databází pro připojení stávajícího CRM. Převod SQL dotazů, úplného schématu a triggerů, serverové přihlášení a oprávnění, souběžné editace agend, přílohy, Přehledy a napojení obrazovek zůstávají dalšími kroky popsanými v README. Vaše aktuální provozní databáze nebyla na server převáděna; testy použily izolovaný základ ze zdrojů CRM a zkušební záznamy.
