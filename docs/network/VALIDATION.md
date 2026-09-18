# Stav první etapy přechodu na PostgreSQL

Datum kontroly 18. září 2026. Základ CRM 8.0.34, hlavní větev `d060d96`. Práce je v místní větvi `feature/postgresql-pilot`; nebyla začleněna do hlavní větve ani vydána jako aktualizace.

## Provedené kontroly

| Oblast | Výsledek |
| --- | --- |
| Syntaxe nových modulů | Prošla |
| Bezpečnost SQLite zdroje a profilů připojení | 13 testů prošlo |
| Stávající správa souborů a záloh CRM | 14 testů prošlo |
| Stávající oprávnění CRM 8.0.34 | Databázová část regresní kontroly prošla |
| Inventura schématu vytvořeného aktuálním CRM | 50 běžných tabulek, 38 triggerů, 89 explicitních indexů; všechny běžné tabulky prošly kontrolou datových typů a obsahu |
| PostgreSQL 16 a 18 | Workflow připraveno, zatím nespuštěno |
| Převod přes ovladač, rollback, souběh a skutečná obnova | 8 integračních testů připraveno, na standardním serveru zatím neověřeno |
| Windows GUI a souběžná práce na dvou PC | V této etapě netestováno; GUI ještě není připojeno k PostgreSQL |

Lokální pokus použít PGlite s TCP adaptérem selhal při přenosu `COPY FROM STDIN` na úrovni protokolu. Tento pokus se nepočítá jako úspěšný integrační test a není náhradou za testování na standardním PostgreSQL. Produkční přenos nebyl kvůli omezení tohoto náhradního prostředí měněn.

Uživatel 18. září 2026 výslovně schválil odeslání testovací větve na GitHub a spuštění ověřovacích testů. Odeslání a serverové testy právě probíhají; jejich výsledky budou doplněny po dokončení. Před úspěšným dokončením se tato etapa nesmí označit za ověřený převod na serveru.

## Rozsah následující revize

Připravený kód přidává samostatný modul pro kontrolu a převod kopie dat, profil spojení, zálohu, testy a návod. Neupravuje produkční továrnu spojení, verzi aplikace, její aktualizační manifesty ani databázi uživatele. První větev je určena pro revizi a doplnění integrace popsané v README. Serverové přihlášení, oprávnění, úplné schéma, přílohy, Přehledy a napojení obrazovek zůstávají dalšími kroky.
