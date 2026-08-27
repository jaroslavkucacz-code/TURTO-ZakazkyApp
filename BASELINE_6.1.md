# TURTO CRM – konsolidovaný základ 6.1

Od verze 6.1.0 se release buildy nevytvářejí z původního základu 5.7.2 a dlouhého seznamu historických patchů při každém vydání.

## Princip

- Verze 6.1.0 vytvoří a uloží adresář `ZakazkyApp_base_6.1` jako nový zmrazený výchozí bod.
- Tento baseline obsahuje kompletní funkční stav aplikace k 6.0.45/6.1.0 včetně dosavadních runtime modulů a launcheru.
- Následující verze 6.1.x kopírují přímo tento baseline a přidávají pouze nové změny vzniklé po konsolidaci.
- Databáze uživatele zůstává mimo instalační balíček v `Documents/TURTO Zakazky/data/zakazky.db` a konsolidace ji nemění ani nenahrazuje.

## Proč

Cílem je zjednodušit release workflow, zkrátit seznam historických kroků při buildu a snížit riziko, že se při další úpravě omylem vynechá starší modul nebo se změní pořadí historických vrstev.

## Další vývoj

Nové změny po 6.1.0 se mají přidávat jako malé, jasně pojmenované moduly nad baseline. Po větším množství změn lze vytvořit další konsolidační milestone (např. 6.2.0) stejným způsobem.
