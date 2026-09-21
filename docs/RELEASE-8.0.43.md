# CRM 8.0.43 – ověření odeslaných poptávek a jednodušší Portfolio

CRM rozpozná odeslané poptávky i tehdy, když Outlook při hledání podle interního identifikátoru vrátí prázdný výsledek. Kontrola v takovém případě projde odpovídající časové období Odeslané pošty a ověří přesný identifikátor zprávy a čas odeslání. Opravena je také kontrola více e-mailů současně ve Windows PowerShellu. Zachované identifikátory umožní doplnit stav i u již odeslaných poptávek; není nutné je odesílat znovu.

V Poptávkách i MIVO je **Ověřit odeslání v Outlooku** v nabídce po kliknutí pravým tlačítkem na řádek. Funguje pro jeden i více vybraných řádků. Pravé kliknutí na označený řádek zachová celý výběr; kliknutí mimo výběr zvolí daný řádek. Kontrola pracuje pouze s vybranými poptávkami, respektuje přihlášeného uživatele a jeho oprávnění a větší výběr ověřuje postupně na pozadí. Automatické ověřování zůstává zapnuté. Původní horní tlačítko a doprovodný text jsou odstraněny.

V Portfoliu jsou odstraněna samostatná tlačítka **Přiřadit obchodníky…**, **Otevřít detail** a **+ Kontakt**. Jejich funkce zůstávají dostupné v tabulce. **Obchodníci a střediska…** je nyní červené hlavní tlačítko v pravém horním rohu, stejně jako Nová poptávka. Obnovit přehled je u filtrů a původní pruh tlačítek je odstraněn.

Ověření pokrývá skutečné Windows nabídky a více než sto vybraných pokusů o odeslání, oddělení Poptávek a MIVO, zachování výběru, již ověřené zprávy, změnu uživatele během kontroly, oprávnění a oba vzhledy Portfolia. Outlook testy spouštějí celý ověřovací skript bez přístupu ke skutečné poště; před vydáním byla připravená oprava ověřena také pouze čtením dvou uživatelem uvedených zpráv, bez zápisu do živé databáze. Databáze, přílohy a uživatelská nastavení zůstávají při aktualizaci zachované.
