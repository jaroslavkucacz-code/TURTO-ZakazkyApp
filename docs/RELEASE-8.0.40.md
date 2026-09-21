# TURTO CRM 8.0.40

## Portfolio

První podzáložka sekce Obchod obsahuje portfolio odběratelů. Přihlášenému
obchodníkovi se předvybere jeho vlastní portfolio, ale může zobrazit i ostatní
obchodníky, všechny odběratele nebo firmy bez přiřazení. Tlačítko **Přiřadit
obchodníky…** dovoluje vybrat více zástupců u jedné společnosti. Při sloučení
společností se jejich přiřazení spojí.

Obchodníci a měsíční přehledy používají společná jména a střediska Pohody:
J – Jiří Cír, H – Jan Mayer, M – Milan Soukup. Dosavadní zkratky a přezdívky
se sjednotí při migraci bez ztráty vazeb. Existující uživatelé se shodným jménem
nebo přezdívkou se propojí automaticky. Ostatní účty může ADMIN propojit ve
správě uživatelů, v okně **Funkce a oprávnění**, pole **Obchodník / středisko
Pohody**. Funkce uživatele zůstává oddělená od oprávnění k záložkám.

## Úkoly a připomínky

Úkol vidí jeho zadavatel a aktuální řešitel. Platí to také pro připomínky,
počty na přehledu, archiv a historii úkolů. Úkol zadaný sobě se neopakuje.
Při přejmenování uživatele zůstává vlastnictví zachováno. Nového řešitele
je nutné vybrat mezi aktivními uživateli. Přímé a hromadné změny cizích úkolů
jsou chráněné také při zápisu do databáze.

## Ověření odeslání poptávky

Nový koncept z Poptávek i MIVO dostane vlastní skrytý identifikátor a uloží
se v klasickém Outlooku. CRM e-mail nikdy samo neodešle. Sloupec **E-mail**
rozlišuje **Koncept vytvořen**, **Odesláno** s časem a **Odeslání neověřeno**.
Změna předmětu neporuší propojení. Každý další koncept se eviduje samostatně;
již ověřené odeslání zůstává zachováno.

Kontrola probíhá na pozadí po spuštění CRM a přibližně každé tři minuty,
případně tlačítkem **Ověřit odeslání v Outlooku**. Používá již otevřený klasický
Outlook, dostupné koncepty a složky Odeslaná pošta jednotlivých úložišť.
Nedostupný Outlook, zpráva přesunutá pravidlem mimo tyto složky, odstraněná
kopie nebo neúplná synchronizace znamená neověřený stav. Starší koncepty bez
identifikátoru nelze automaticky přiřadit. Jde o odeslání, nikoli o potvrzení
doručení nebo přečtení.

Implementace se opírá o oficiální vlastnosti Outlooku
[Sent](https://learn.microsoft.com/en-us/office/vba/api/outlook.mailitem.sent),
[SentOn](https://learn.microsoft.com/en-us/office/vba/api/outlook.mailitem.senton)
a [PropertyAccessor](https://learn.microsoft.com/en-us/office/vba/api/outlook.propertyaccessor.setproperty).

## Ověření

Nové testy používají oddělené databáze a syntetické zprávy. Ověřují migraci
aliasů, více obchodníků u firmy, souběžné změny, role a přepínání uživatelů,
přidělení a přeřazení úkolů, soukromé historie, skutečné ovládání Windows
a chování produkčního kódu pro Outlook bez odeslání skutečného e-mailu.
Součástí vydání je úplná stávající regresní sada, sestavení instalátoru
a čistá instalace se zkouškou aktualizátoru. Živá uživatelská databáze ani
Outlook profil nejsou při těchto testech měněny.
