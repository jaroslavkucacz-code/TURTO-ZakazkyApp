# TURTO CRM 8.0 – velký úklid runtime architektury

## Výchozí stav

Refaktor vychází přesně z publikované verze 7.9.2. Funkční chování, pracovní databáze,
historické nabídky, PDF revize, vlastní šablony a vratné aktualizace jsou pro tuto
etapu považovány za kompatibilitní kontrakt.

Předchozí audit 7.7 správně zavedl `runtime_bootstrap.py` jako čitelné místo pořadí
vrstev, ale v aktivním kódu zůstaly některé skryté vazby mezi verzovanými moduly a
řada plně překrytých vlastníků UI funkcí. Velký úklid proto není hromadné mazání
historických souborů; je to postupné převádění aktivní funkčnosti na jednoznačné
vlastníky s regresními testy.

## Pravidla architektury 8.0

1. **Jediná kompozice runtime:** pořadí verzovaných vrstev definuje pouze
   `runtime_bootstrap.py`. Verzovaný modul nesmí uvnitř `apply()` spouštět další
   verzovanou vrstvu ani ji importovat jen proto, aby měnil její globální stav.
2. **Jeden finální vlastník průřezových funkcí:** nápověda a maximalizace dialogů
   mají právě jednoho aktivního vlastníka. Staré implementace, které byly před
   vznikem `App` vždy přepsány, se již neinstalují.
3. **Sdílené doménové utility patří do domény:** dekódování rich-text metadat
   nabídek je v `offers_engine.rich_text`, nikoli ve vrstvě konkrétní verze Nevoga.
4. **Žádné skryté patchování sousední vrstvy:** starší seskupování položek čte
   současný kanonický grouper dynamicky z runtime místo přepisování globálu v
   `v710_cleanup` z `v740_offer_defaults`.
5. **Kompatibilitu nemažeme naslepo:** řetězce `App.__init__` a `ensure_schema`
   se převádějí po samostatných etapách s regresními testy, ne hromadným mazáním.

## Konkrétní konsolidace v první etapě

- `v624_legacy_exports` je aplikován explicitně v bootstrapu; `post_baseline.py`
  už jej skrytě nespouští.
- `v767_offer_reprocess_images` už skrytě nespouští `v768_clean_table_markers`;
  pořadí je pouze v bootstrapu.
- `v740_offer_defaults` už nepřepisuje modulový globál v `v710_cleanup`.
- Rich-text segmenty Nevoga/PLEXUS používají společný modul `offers_engine.rich_text`.
- Historické `build_help` wrappery před 7.8 se neinstalují; jediným vlastníkem je
  `price_lists_domain.issued_offers.professional_workflow`.
- Staré implementace `enable_dialog_maximize` v raných stabilizačních vrstvách se
  neinstalují; finální vlastník zůstává `v770_runtime_policy` / `dialog_chrome`.

## Druhá etapa – lifecycle aplikace

Řetězec startovacích wrapperů se převádí na jediný vlastník `App.__init__` v
`app_lifecycle.py`. Jednotlivé moduly už nerebalí celý konstruktor, ale registrují
pojmenované `before` / `after` hooky. To zachovává jejich pořadí a vedlejší efekty,
ale odstraňuje closure surgery, rekurzivní startovací normalizaci a několik
opakovaných časovačů.

Převedeny jsou mimo jiné startovací části `post_baseline`, `v710_cleanup`,
`v760_table_activity_performance`, automatické aktualizace a dříve migrované
runtime/UI moduly. `v644_default_date_sort` už konstruktor nerozebírá a znovu
neskládá; zůstává pouze stabilizačním mostem pro skutečně potřebné Tk operace.

`scripts/validate-800-app-lifecycle.py` navíc kontroluje, že jediným statickým
přiřazením `App.__init__` je kanonický lifecycle modul a že registry jsou
idempotentní a deterministické.

## Třetí etapa – lifecycle databázového schématu

Řetězec 14 wrapperů `ensure_schema` je nahrazen jediným vlastníkem v
`schema_lifecycle.py`. Základní schéma z `app.py` se spouští vždy jako první a
jednotlivé doménové/verzované vrstvy pouze registrují pojmenované aditivní migrace.
Pořadí registrací odpovídá původnímu pořadí wrapperů: Ceníky, platforma, finalizace,
Vydané nabídky, zákaznické ceny a následně vrstvy v710 až v770.

Migrace zůstávají idempotentní a zachovávají své dosavadní pomocné vstupy. Speciální
okamžitá kontrola Nevoga v `v769` dál volá celé `M.ensure_schema()`, takže se nemění
ani historické pořadí při instalaci této vrstvy. PLEXUS migrace v `v7616` si také
ponechává svůj bezpečný okamžitý pokus vedle registrace pro každý další start.

`scripts/validate-800-schema-lifecycle.py` hlídá jediného statického vlastníka,
idempotentní registraci a deterministické pořadí. Plný runtime test navíc ověřuje
přesný seznam všech 14 migrací v reálné kompozici.

## Automatická pojistka

`scripts/audit-runtime-overrides.py --check` nyní blokuje:

- skrytý import nebo spuštění jiné verzované vrstvy mimo `runtime_bootstrap.py`;
- více než jednoho vlastníka `App.__init__`;
- více než jednoho vlastníka `ensure_schema`;
- více než jednoho vlastníka `App.build_help`;
- více než jednoho vlastníka `enable_dialog_maximize`;
- syntakticky nečitelný Python soubor.

Záměrně zatím neblokuje všechny historické multi-owner symboly. Jejich počet slouží
jako metrika dalšího úklidu, nikoli jako důvod riskantně odstranit obchodní workflow.

## Další etapa

Po lifecycle konsolidaci zbývá největší dluh v přepisovaných UI metodách (`build`,
`show_page`, `refresh_*`) a v několika exportních/importních řetězcích. Další řezy
budou pokračovat po jedné funkční oblasti a vždy s konkrétním regresním testem;
pracovní databáze a historické dokumenty zůstávají kompatibilitním kontraktem.
