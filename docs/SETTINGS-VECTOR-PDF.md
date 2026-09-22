# Nastavení a vektorové PDF nabídek

Navazuje na vydanou verzi 8.0.45. Změna je připravená lokálně; číslo vydání ani
veřejný aktualizační kanál se touto úpravou nemění.

Nastavení je rozděleno na Obecné, Data a úložiště a Aktualizace a údržba. Každá část
má vlastní svislé posouvání, zalamování popisů a dostupné ovládání klávesnicí.
Přesun fokusu na tlačítko či pole jej automaticky odkryje. Kolečko funguje i nad
vnořenými prvky bez zásahu do jiných stránek aplikace. Zachované jsou všechny
dosavadní funkce včetně archivních cest a obnovení předchozí verze.

Standardní záhlaví PDF se vykresluje na přesnou šířku tabulky. Geometrie levého
loga, červeného titulku a pravého bloku TURTO se mění pouze jednotným měřítkem;
prázdná část šedého a modrého pruhu mezi nimi vyplňuje zbývající šířku. Kresba je
vektorová, titulek, číslo nabídky i všechny údaje v zápatí jsou viditelný text PDF
s vloženými písmy. Nejde o bitmapu s neviditelnou OCR vrstvou.

Stejné vykreslení používá pracovní náhled i export. Změna politiky vykreslení je
součástí otisku šablony, aby se před novým vydáním ověřil aktuální náhled. Již
uložené revize PDF zůstávají zachované. Vlastní obrázky nesouvisejících šablon se
nepřekreslují. Původní firemní JPEG soubory slouží jako reference a pro rozpoznání
jejich dříve exportovaných kopií.

Ověření: skutečné Tk okno 740×520, 900×620 a 1450×900, světlý/tmavý vzhled,
dosažitelnost všech polí a tlačítek, posouvání nad potomky a automatické odkrytí
fokusu. PDF kontroly ověřují různé okraje a výšky záhlaví, český text, opakování na
více stránkách, vlastní otevírací dobu, shodu náhledu/exportu a historii revizí.
Nové kontroly jsou zařazeny do instalačního workflow pro příští sestavení.
