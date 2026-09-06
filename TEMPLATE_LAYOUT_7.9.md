# TURTO CRM 7.9 – firemní nabídky a vlastní šablony

## Jediný měřený výstup pro nový vzhled

`corporate_renderer.Layout` sází A4 přímo pomocí PyMuPDF. Vstupem je snapshot nabídky,
položek a validované JSON nastavení šablony. Náhled i vydání používají stejnou
funkci `pdf_renderer.render_offer_snapshot`; výstup obsahuje skutečné klikací
oblasti s původními indexy položek i po zařazení do skupin a stránkování.

Původní šablony mají `layout_json = '{}'` a zachovávají dosavadní renderer. Nový
renderer jejich uložené nastavení nemění. Wrapper v710 u nové šablony neprovádí
staré globální přepisování loaderu kvůli seskupení; seskupení řeší nová sazba.
Nevzniká další runtime patch ani změna pořadí bootstrapu.

## Uložení a zpětná kompatibilita

Migrace pouze přidává výchozí JSON/builtin klíč k šablonám a dva odkazy na obrázek
k položkám. Existující přiřazení šablon, dokumenty a PDF revize se nepřepisují.
Firemní předloha se vloží jednou. Jako výchozí nahradí pouze nepersonalizovaný
původní preset bez nahrané grafiky. Vlastní výchozí šablona zůstává výchozí.

Firemní předlohu nelze uložením ani deaktivací odstranit. Uživatel vytváří vlastní
kopie. Reset je pouze rozpracovaná změna do výslovného uložení. Uživatelská grafika
leží mimo instalaci, proto ji aktualizace programu nepřepisují. Vratný aktualizátor
se v této změně nemění. Při návratu na starší program zůstanou nové údaje v DB;
starší program ovšem nezná nový layout a pro jeho sazbu je třeba starší šablona.

## Obrázky a PDF revize

PLEXUS odkazuje na společný `offer_image_assets.asset_key`; neukládá se BLOB ke
každému řádku. Ostatní zdrojové obrázky dostanou trvalý, obsahově adresovaný soubor.
Náhled nic neukládá do číslování ani revizí. Finální PDF se nejprve dokončí do
pomocného souboru a následně atomicky přesune. Historická PDF se nepřekreslují.
Otisk aktuálnosti zahrnuje vzhled šablony, původní artwork, případný podpis i obsah
obrázků položek. Komerční výpočty používají existující service.calculate_totals.

## Ruční úpravy

Vydané nabídky → Šablony PDF; přímo v editoru také Upravit šablony.
Stránka / Písmo / Sloupce / Dolní bloky: okraje, rozteče, výška obrázků, barvy těla,
pořadí a šířky sloupců, popisky, vlastní kontakty a poznámka, původní nebo nahrané
záhlaví/zápatí, vlastní podpis, volitelný rozpis DPH. Nejde o volný vektorový editor.
Logo se při změně barvy těla dokumentu nepřebarvuje ani nepřekresluje.

Export/import ZIP obsahuje pouze validované JSON a obrázky s SHA-256. Import
nepoužívá extractall, odmítá traversal/duplicitní cesty a neprovádí žádný kód.
F1 obsahuje samostatný návod. Náhled používá zřetelně označené ukázkové údaje.

## Regresní kontrola

validate-7900-corporate-templates: migrace staré DB, ochrana předlohy, vlastní
výchozí kopie, export/import včetně shodných bytů artworku, chybná geometrie,
shared PLEXUS, PDF pixelová shoda náhledu a vydání, revizní otisk, dlouhé texty,
100+ řádků a přesná geometrie kliknutí.

validate-7900-runtime-integration: skutečný runtime_bootstrap, živý editor nabídky,
přechod do modalního editoru šablony, uložení, návrat focus/grab a nový náhled.
CI matice zahrnuje Python 3.12/3.14 Linux a Python 3.14 Windows.
