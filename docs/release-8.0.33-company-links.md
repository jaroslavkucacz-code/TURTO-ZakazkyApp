# TURTO CRM 8.0.33

- V okně nové i upravované poptávky je výběr **Řeší** přímo pod Akcí.
  Používá stejné uložené pole jako sloupec Řeší v tabulce. Nadále se předvyplní
  přihlášený uživatel, bez Admin a TEST; zůstávají zachované uživatelské texty mailů.
- Přehledy → Zákazníci zobrazují společnost z adresáře a stav párování.
  **Párování firem s adresářem…** je dostupné také v Nastavení přehledů.
- Jednoznačné shody názvů se propojí automaticky. Porovnání sjednocuje velikost
  písmen, mezery a zápis běžných právních forem; zachovává diakritiku, čísla a
  právní formu. Část názvu ani podobnost nejsou automatickou shodou.
- U více shod a rozdílného názvu lze vybrat konkrétní existující firmu (s IČO a ID
  pro rozlišení). Zápis vyžaduje **Uložit přiřazení**. Enter pouze vybírá
  z našeptávače. Import nevytváří nové společnosti.
- **Nepárovat** blokuje automatické přiřazení daného názvu. **Obnovit automatické
  párování** vrací název k posouzení podle aktuálního adresáře.
- Vazba je v databázi CRM přes ID společnosti a přežije přejmenování, sloučení,
  opakované importy i převzetí celé databáze přehledů. Společnost s vazbou lze
  archivovat; nezmizí omylem při mazání adresáře. Souběžně změněné ruční přiřazení
  nelze přepsat ze starého otevřeného formuláře.
- V historii zákazníka tlačítko **Nabídky a objednávky z CRM…** zobrazí navázané
  vydané nabídky a přijaté objednávky za všechna období, včetně stavů a měn.
  Dvojklik otevře původní doklad CRM.
- Původní názvy a částky importů, finanční výpočty i exporty zůstávají zachované.
  Nabídky a objednávky nejsou přičítány k obratu. Vazba připravuje společnou
  identitu firem pro další kombinované přehledy; finanční zákaznické řádky se
  v této verzi stále zobrazují podle původních názvů importu.

Ověření: testy názvů, nejednoznačnosti, ručního výběru, vyloučení a obnovení,
přejmenování a sloučení firem, opakovaného převzetí importů, zachování finančních
dat; skutečné formuláře Windows v obou motivech, práce s Enter, uložení Řeší,
procházení dokladů CRM a oddělení TEST. Dále dosavadní regresní a instalační brány.
