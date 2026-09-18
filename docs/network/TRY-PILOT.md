# TURTO CRM – síťový pilot 0.2.0 pro Windows

Tento balíček umožňuje vyzkoušet serverovou agendu Společnosti ve Windows bez instalace Pythonu. Jde o samostatný zkušební program. Běžné CRM spouštějte dál jeho stávající ikonou.

## První spuštění

1. Rozbalte celý ZIP do nové místní složky, například `C:\TURTO-pilot`. Ponechte u obou EXE i složku `_internal`. Program nespouštějte přímo z okna ZIP a nekopírujte pouze samotné EXE.
2. Správce připraví na firemním serveru PostgreSQL a zkušební databázi. Postup je ve složce `pro-spravce`, soubor `SERVER.md`. Balíček obsahuje umělá ukázková data, takže první pokus nevyžaduje převod vašich provozních dat.
3. Spusťte `TURTO-CRM-Sitovy-Pilot.exe`. V okně připojení vyplňte adresu serveru, port, testovací databázi, schéma, svůj osobní serverový účet a vyberte veřejný certifikát dodaný správcem.
4. Klikněte na **Uložit připojení**, zadejte heslo a stiskněte **Přihlásit**. Heslo se neukládá. Při dalším spuštění se načtou údaje připojení a znovu zadáte jen heslo.

V kanceláři používejte firemní Wi-Fi nebo kabelovou síť. Z domova nejprve připojte firemní VPN. Adresa serveru, databáze a přihlášení zůstávají stejné; samostatný domácí profil není potřeba. Při nedostupnosti sítě se zobrazí upozornění. Program neukládá obchodní data do místní náhradní kopie.

Pokud se při prvním startu objeví kontrola neznámého vydavatele, balíček nemá firemní podpis. Nechte správce posoudit schválení tohoto konkrétního balíčku podle interních pravidel. Neměňte kvůli němu plošné zabezpečení Windows.

## Co vyzkoušet na dvou počítačích

1. Přihlaste dva různé osobní účty s právem úprav do stejné testovací databáze a schématu. Založte firmu s názvem „TEST – síťový pilot“. Na druhém PC klikněte na **Vyhledat / obnovit**; firma se musí objevit.
2. Otevřete tuto firmu současně na obou PC. Na prvním změňte poznámku a uložte. Na druhém zkuste uložit vlastní změnu. Program musí oznámit, že záznam mezitím změnil jiný uživatel; první změna zůstane zachovaná.
3. Otevřete **Historii změn**. Musí ukázat autora a provedené úpravy. Pak přihlaste účet čtenáře: společnost lze otevřít, ale nelze založit novou ani uložit úpravu.
4. Z domova zapněte VPN a načtěte tutéž firmu. Bez VPN a mimo kancelář musí přihlášení selhat. Samotné připojení k běžné domácí Wi-Fi přístup nenahrazuje.
5. Pokud se spojení přeruší během ukládání a výsledek není jistý, po obnovení VPN použijte **Ověřit uložení**. Teprve podle výsledku pokračujte. Před zavřením takového okna pokud možno dokončete ověření.

Čtenář a druhý editor musí mít vlastní PostgreSQL účty; účet správce databáze není určený pro běžné testování. Ukázka obsahuje identity „Pilot – editor“ a „Pilot – čtenář“. Správce může pro druhého editora propojit další osobní serverový účet se zkušební identitou editora; historie navíc uchovává konkrétní serverový účet.

## Rozsah

Fungují Společnosti: vyhledání, založení, úprava základních údajů, aktivita, role odběratel/dodavatel a historie. Další agendy CRM zatím nejsou napojené. Změny testovací kopie se nepřenášejí do běžného CRM. Balíček nepoužívá jeho aktualizační kanál ani registraci instalace.

Počítače mají lokálně jen program a nastavení spojení. PostgreSQL musí běžet jako databázová služba na firemním serveru nebo na vyhrazeném stroji v jeho síti. Pouhá sdílená složka pro tuto variantu nestačí.
