# Měsíční přehledy in TURTO CRM

Reporting calculations, imports, charts and exports originate from the user's
TURTO – Měsíční přehledy 1.1.2 source package, `releases/1.1.2/TURTO_source_1.1.2.zip`
on `mesicni-prehledy-stable` at `04814a104855043fc6fa815a455602c50eedfbb9` in this repository.

CRM owns navigation, user preferences, window lifecycle, themes and updates.
The standalone launcher/updater/Windows shortcut management are not embedded.
The report database is beside the currently selected CRM database in
`<database-stem>_prehledy/turto_dashboard.db`. TEST therefore has a separate store.
SQLite snapshots allow taking over existing reporting data without altering the
standalone database. Imports still preview changes and back up before commit.

There is deliberately no automatic joining or synchronization of accounting
documents with CRM offers, companies or projects. A future data-source adapter
can replace the reporting store without changing report calculations.
