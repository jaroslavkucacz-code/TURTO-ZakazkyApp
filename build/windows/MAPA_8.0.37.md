# Mapa a ortofoto v TURTO CRM 8.0.37

V záložce **Mapa** je přepínač **Podklad: Mapa / Ortofoto ČR**.
Kliknutím přepnete mezi dosavadní mapou OpenFreeMap a leteckými snímky ČÚZK.
Zůstává zachováno místo, přiblížení, výběr záznamů, jejich špendlíky i náhled
nalezené parcely. Přepínat lze také během umísťování bodu kliknutím.
Tlačítko **Obnovit zobrazení** zachová zvolený podklad.

Odstraněno je výběrové pole **Všechny společnosti**. Textové hledání a ostatní
filtry zůstávají dostupné; přepínač podkladu nemění výběr záznamů v mapě.

Ortofoto pokrývá Českou republiku. Mimo jeho pokrytí zůstává původní mapa.
Načítají se jen dlaždice pro prohlíženou oblast a až po zapnutí ortofota.
Při nedostupnosti ortofota se zobrazí zpráva s možností přepnout na běžnou mapu.

## Zdroje

- Běžná mapa: [OpenFreeMap](https://openfreemap.org/), OpenMapTiles a OpenStreetMap.
- Ortofoto: [© ČÚZK](https://ags.cuzk.gov.cz/arcgis1/rest/services/ORTOFOTO_WM/MapServer),
  veřejná služba ve Web Mercatoru (dlaždice 256 px, úrovně 6–20).
- OpenFreeMap neposkytuje letecké snímky; doplnění zdroje ČÚZK nemění ovládání mapy.

## Ověření

`validate-837-map-renderer.js` kontroluje přepnutí před načtením mapy, opakované
přepínání, zachování vrstev, kamery, náhledu a rozpracovaného umístění a návrat
po výpadku ortofota. `validate-837-basemaps.py` ověřuje stejné operace v reálném
Windows WebView2 včetně živých snímků ČÚZK, původní mapy, obnovení zobrazení,
odstranění filtru a zachování GPS v databázi. Windows CI ukládá oba náhledy.
