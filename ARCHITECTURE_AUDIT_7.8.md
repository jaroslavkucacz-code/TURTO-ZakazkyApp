# TURTO CRM 7.8 – audit vydávání nabídek a nápovědy

## Cíl

Verze 7.8 převádí vydání nabídky z několika samostatných tlačítek na řízený obchodní proces. Změna je aditivní: používá stávající tabulky obchodních dokumentů, stávající číslování a jediný kanonický PDF renderer.

## Zjištěné slabiny předchozího procesu

1. PDF bylo možné vytvořit přímo bez souhrnné kontroly obchodních údajů.
2. Outlook koncept automaticky nastavoval stav `Odesláno`, i když uživatel zprávu pouze otevřel.
3. Poslední PDF se mohlo znovu připojit bez ověření, zda se od poslední revize nezměnily položky, ceny nebo podmínky.
4. Stav aktuálnosti PDF nebyl v editoru ani detailu nabídky viditelný.
5. Zavření editoru používalo dvojici potvrzovacích dialogů a nerozlišovalo skutečné změny.
6. Nápověda byla statická, bez vyhledávání a bez podrobného postupu pro Vydané nabídky.

## Vlastnictví funkcí

`price_lists_domain.issued_offers.professional_workflow` je finální vlastník:

- obchodního preflightu;
- řízeného vydání PDF;
- otisku zákaznického obsahu a šablony;
- rozlišení aktuální / zastaralé / chybějící PDF revize;
- Outlook konceptu bez automatického stavu Odesláno;
- výslovného potvrzení skutečného odeslání;
- vyhledávatelného centra nápovědy.

Renderer zůstává `price_lists_domain.issued_offers.pdf_renderer` a jeho vizuální integrace `v720_visual_offer`. Nová vrstva renderer nekopíruje ani nenahrazuje.

## Stavový model

- `Rozpracováno`: editovatelný koncept.
- `Připraveno`: kontrola proběhla a PDF je vydané nebo připravené k předání.
- `Odesláno`: pouze po výslovném potvrzení uživatele; dokument se uzamkne.
- `Přijato`, `Zamítnuto`, `Zrušeno`: terminální stavy.

Outlook koncept je evidován v historii jako `email_draft`, nikoli jako odeslání.

## Revize a aktuálnost

Otisk revize zahrnuje zákaznické snapshoty, předmět, vazby na Akci a Příležitost, podmínky, pořadí a zákaznický obsah položek, prodejní ceny, DPH, celkovou slevu a PDF šablonu včetně hashů souborů záhlaví a zápatí. Interní změna marže bez změny zákaznické ceny nevytváří falešně zastaralé PDF.

Terminální dokument považuje své archivované PDF za autoritativní historický výstup, i když se později změní globální šablona.

## Kompatibilita

Vrstva je načtena po všech dosavadních úpravách Vydaných nabídek a před finální globální runtime politikou `v770_runtime_policy`. Nezavádí databázovou migraci. Vydání je ověřováno na Pythonu 3.12 a 3.14, existujícími regresními testy nabídek a skutečným Tk/Xvfb testem.
