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
   jsou stále rozsáhlé. Jejich převod na lifecycle hooky a registr migrací bude
   samostatná další etapa; tento první řez je záměrně nechává funkčně beze změny.

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

## Automatická pojistka

`scripts/audit-runtime-overrides.py --check` nyní blokuje:

- skrytý import nebo spuštění jiné verzované vrstvy mimo `runtime_bootstrap.py`;
- více než jednoho vlastníka `App.build_help`;
- více než jednoho vlastníka `enable_dialog_maximize`;
- syntakticky nečitelný Python soubor.

Záměrně zatím neblokuje všechny historické multi-owner symboly. Jejich počet slouží
jako metrika dalšího úklidu, nikoli jako důvod riskantně odstranit obchodní workflow.

## Další etapy

Po stabilizaci této etapy budou následovat dvě největší oblasti dluhu:

- nahrazení mnoha wrapperů `App.__init__` deklarativními lifecycle hooky;
- nahrazení řetězce wrapperů `ensure_schema` jedním registrem databázových migrací.

Každá z nich musí mít vlastní kompatibilitní testy nad kopií reálné 7.9.2 databáze.
