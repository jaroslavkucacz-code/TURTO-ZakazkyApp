# TURTO CRM 8.0.34

## Změny

- Okno **Ke zpracování** obsahuje zaškrtávací výběr více řešitelů. Nový záznam předvybere přihlášeného uživatele. ADMIN a TEST se nenabízejí. Existující seznamy, včetně historických osob, zůstávají zachované; zrušení okna nic neukládá. Souběžná změna řešitelů se nepřepíše starým formulářem.
- Prázdná hlavní záložka **Obchod** je mezi Přehled a Technika.
- **ADMIN → Administrace → Uživatelé → Správa uživatelů → Funkce a oprávnění…** umožňuje zadat funkci (včetně vlastního textu) a pro každou hlavní či podřízenou záložku vybrat **Skrýt / Jen číst / Číst i upravovat**. Funkce nemění přístup automaticky.
- Všem stávajícím i novým uživatelům zůstává výchozí plný přístup. ADMIN si ponechává správu aplikace. Oprávnění se ukládají k ID uživatele, takže vydrží jeho přejmenování.
- Skryté podzáložky se nenabízejí v navigaci; skupina bez viditelných podzáložek se skryje také. Přímé otevření skryté části je zablokované.
- Režim pro čtení chrání ukládání, stavové změny, mazání i importy. Související okna kontrolují oprávnění své cílové záložky. Hledání, filtrování a čtení zůstávají dostupné.
- Poptávky MIVO a běžné poptávky se při ukládání rozlišují podle dodavatele. Vydané nabídky a přijaté objednávky mají vlastní přístup i přes společné databázové tabulky. Importy přehledů a párování firem mají samostatné kontroly.

## Technické ověření

`scripts/validate-834-user-access.py` ověřuje aditivní migraci bez přepisu existujících dat, výchozí přístup, správu profilů jen administrátorem, odmítnutí souběžného přepisu, izolaci uživatelů, ochranu zápisů a rollback, oddělení MIVO a typů dokladů i importy přehledů. Ve Windows navíc ověřuje skutečné formuláře, více řešitelů, zrušení, skrytou navigaci, související okna pro čtení a změnu uživatele; pořizuje náhledy světlého i tmavého prostředí.

Databázový model zůstává lokální SQLite. Tato aktualizace nepřevádí aplikaci na serverový provoz a nemění dosavadní způsob přihlášení.
