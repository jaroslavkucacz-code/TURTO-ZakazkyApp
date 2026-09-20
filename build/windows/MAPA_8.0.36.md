# Mapa v TURTO CRM 8.0.36

## Online adresy

Stažení ani aktualizace celého adresáře ČR již nejsou potřeba. Mapa používá
veřejné online vyhledávání ČÚZK nad RÚIAN. Jednotlivé nalezené GPS se ukládají
přímo k původnímu záznamu CRM, a proto se při dalším zobrazení znovu nehledají.
Uložené body, včetně bodů doplněných starým adresářem, zůstávají zachované.

- **Dohledat GPS online**: vyberte jeden záznam s adresou. Při více výsledcích
  zvolte správný. Nalezený bod je nejprve pouze náhled; použijte **Uložit bod
  k vybranému záznamu**. Nahrazení dosavadních GPS se výslovně potvrzuje.
- **Hromadné doplnění GPS**: označte řádky pomocí Ctrl/Shift a ponechte rozsah
  **Vybrané záznamy**, nebo zvolte **Všechny ve filtru**. Doplní se pouze chybějící
  GPS z úplných, jednoznačných adres včetně PSČ. Existující GPS se nepřepisují.
- Výsledky dávky zobrazují počet nalezených shod, adres ke kontrole a záznamů,
  které se nestihly zpracovat. Při výpadku lze uložit již dohledané shody. Zbytek
  lze spustit znovu. Hledání i ukládání lze zastavit.

Hledání vyžaduje internet. ČÚZK dostává pouze hledanou adresu, nikoli název
společnosti/akce, kontakty, poznámky, firemní ID nebo jiné údaje CRM. Požadavky
jsou postupné, časově a velikostně omezené; opakované adresy se v jedné dávce
dohledávají jednou. Neexistuje žádná automatická synchronizace všech GPS.

## Stavba bez adresy – hledání parcely

1. Vyberte Akci, ke které chcete polohu uložit.
2. V části **Najít parcelu v ČR** vyplňte název nebo šestimístný kód katastrálního
   území a klikněte na **Vyhledat katastrální území**. Vyberte konkrétní území
   s uvedeným kódem.
3. Zadejte celé parcelní číslo, například `123/4`. Pro stavební parcelu lze použít
   `st. 123/4` nebo výběr **Stavební**. Výběr **Automaticky** nabídne při shodném
   čísle stavební i pozemkovou parcelu k rozlišení.
4. Klikněte na **Najít parcelu a zobrazit bod**. Fialový špendlík je pouze náhled.
5. Použijte **Uložit bod k vybranému záznamu**. S GPS se uloží také označení parcely,
   katastrálního území a identifikátor parcely ČÚZK. Adresa Akce se tím nemění.
6. Jde o **definiční bod parcely**, nikoli automaticky o místo plánované budovy
   nebo vjezd na stavbu. Přesnou polohu lze následně upravit přes **Umístit kliknutím**.

Hledají se současné záznamy bez konce platnosti a bez příznaku nesprávnosti.
Rozdělená či přečíslovaná parcela podle starého projektu nemusí být nalezena.
Katastrální mapa a hranice parcel nejsou touto verzí přidány jako další mapová vrstva.

## Ověření a zdroje

- ČÚZK: https://ags.cuzk.gov.cz/arcgis/rest/services/RUIAN/MapServer
- Rozhraní: https://geoportal.cuzk.gov.cz/Dokumenty/Rozhrani_GeocodeSOE.pdf
- Služby zdarma, bez registrace, zdrojová data denně aktualizována:
  https://geoportal.cuzk.gov.cz/mGeoportal/Default.aspx?c=sit.vyhled.uvod_A.CZ&f=paticka.CZ
- `scripts/validate-836-online-map.py` ověřuje převod ID, současnost záznamů,
  jednoznačnost adres, rozlišení parcel, přerušení, výpadek služby, souběžné změny,
  oprávnění a skutečné ovládání Tk. Přepínač `--live` prověří veřejné ukázkové údaje
  na živé službě; běžné CI používá reprodukovatelné odpovědi.
- Kompletní Windows validace zahrnuje i předchozí testy Mapy, skutečný WebView2,
  instalaci a aktualizaci. Dojde pouze k přidání sloupce `map_label` v tabulkách
  společností a akcí; zachovává se původní databáze i vazby přes její ID.
