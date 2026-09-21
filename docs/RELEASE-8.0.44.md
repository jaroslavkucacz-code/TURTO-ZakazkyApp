# TURTO CRM 8.0.44

Portfolio používá společné hledání v tabulce: živé filtrování, podmínky přidávané Enterem, jejich odebrání a Zrušit filtrování. Hledají se také kontaktní osoby ve sbalených společnostech. Nalezený kontakt se zobrazí pod svou společností.

Produktové skupiny a podskupiny se při přiřazení vybírají v rozbalovacím stromu s hledáním. Zůstává i možnost přiřadit samotnou skupinu nebo položku nezařadit.

Interní cenotvorba řadí položky stejně jako PDF náhled. Svislé posouvání obou částí se propojuje podle konkrétních položek, včetně změny přiblížení a stránkování. Na řádku podskupiny lze společně nastavit marži a slevu. Jednotlivé položky mohou mít vlastní hodnoty označené hvězdičkou; další změna podskupiny tyto výjimky zachová. Přes pravé tlačítko lze položku vrátit k marži nebo slevě podskupiny. Nastavení a výjimky se ukládají s nabídkou.

Nabídka opakuje název podskupiny na každé stránce, na které pokračují její položky, také při rozdělení dlouhé položky. Náhled a výsledné PDF používají stejný postup.

Ve formuláři nabídky je Obchodní zástupce propojen s databází. Výběr se omezuje na aktivní zástupce přiřazené odběrateli v Portfoliu. Přímo z nabídky lze přidat či upravit kontaktní osobu v adresáři a upravit přiřazení zástupců společnosti. Pole Příležitost je skryto a při tvorbě nabídky se používá TURTO – Standard. Historické PDF a existující šablony se nemažou.

Aktualizace zachovává databázi, přílohy a uživatelská nastavení. Nové vazby a údaje cenotvorby doplní při spuštění aplikace.

## Ověření

Samostatná regrese 8.0.44 ověřuje ukládání a opětovné načtení individuálních marží/slev, návrat k podskupině, neplatné číselné vstupy, aktuální i historická přiřazení zástupců, hledání kontaktů, stromový výběr, skutečné editace adresáře a rolování oběma směry i po změně přiblížení. Rozšířená regrese PDF kontroluje název podskupiny na každém fragmentu položky, součty, geometrii a shodu náhledu s finálním PDF. Před vydáním musí projít kontrola sestavené aplikace, instalace a aktualizace.
