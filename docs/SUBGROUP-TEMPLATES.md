# Vzhled nabídky podle podskupin

Lokální pokračování po 8.0.45, společně s úpravou Nastavení a vektorového PDF.

Modré záhlaví sloupců se vykresluje pod každým šedým názvem podskupiny. Při
pokračování na další stránce se opakuje název podskupiny a její vlastní sloupce.
Samostatné služby a doprava mají společné sloupce. Výpočty cen a závěrečné součty
se nastavením viditelnosti nemění; historické revize PDF zůstávají zachované.

Editor šablony obsahuje záložku Podskupiny s hledáním, vícenásobným výběrem,
výběrem celé skupiny a návratem ke společnému nastavení. Pro každou podskupinu
lze zvolit veřejné sloupce i popis, kód u názvu a poznámku. Název výrobku je vždy
viditelný. Smíšený hromadný výběr mění pouze přepnutou volbu. Popisky, poměrné
šířky a pořadí vycházejí ze společného nastavení; doplňkové sloupce se vkládají
k souvisejícím údajům. Pravidla jsou uložena v layout_json šablony, navázána na
identitu podskupiny. Přenosný ZIP používá názvy místo lokálních databázových ID.

Náhled používá plné PDF s posouváním, přiblížením a kliknutím pro výběr podskupiny.
Zobrazuje aktuální neuloženou nabídku nebo výslovně označenou ukázku vybraných
podskupin (nejvýše prvních osm; úpravy platí pro celý výběr). Přepočet probíhá
v pomocném procesu, starší výsledek nepřepíše novější volby. Stránky se převádějí
na náhledové obrázky pouze v právě viditelné oblasti. Přiblížení nepřepočítává PDF.
Názvy a pořadí z katalogu se zachytí před předáním procesu, takže výstup odpovídá
finálnímu exportu i po změně katalogového řazení nebo názvu.

Kontroly v scripts/validate-subgroup-templates.py ověřují rozdílná i smíšená
nastavení, obnovení společných voleb, vazbu na ID, uložení a přenos šablony,
samostatné služby, nabídku pouze s názvy, dlouhé položky a pokračování podskupin,
nezměněné součty a obrazovou shodu náhledu/exportu. Přepínač --ui ověřuje skutečné
ovládací prvky, kliknutí v PDF, asynchronní změny, hromadný výběr, ukázkový režim,
vícestránkové posouvání a uložení. Testy jsou zařazeny do instalačního workflow.
