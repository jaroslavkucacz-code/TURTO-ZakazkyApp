# TURTO CRM 7.7 – cíle architektonické revize

Tato větev nahrazuje skryté řetězení verzovaných vrstev explicitním pořadím
modulů a jedním finálním vlastníkem společných UI pravidel.

Kontrolované oblasti:

- jednotné vlastnictví zvýraznění termínů a dlouho čekajících poptávek;
- jednoznačné zarovnání a pružná geometrie tabulek Poptávky a Akce;
- sdílené a deduplikované obrázky PLEXUS s viditelným náhledem v CRM;
- jednotné umísťování dialogů, kalendářů, našeptávačů a nabídek na monitor
  rodičovského okna;
- jednotná identita `TURTO CRM` a transparentní ikona;
- odstranění skrytých `import ...; apply(M)` mostů mezi verzovanými moduly;
- automatická statická kontrola duplicitních runtime vlastníků.
