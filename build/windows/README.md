# TURTO CRM 8.x – Windows EXE distribution

This directory owns the production Windows EXE line introduced with TURTO CRM 8.0.1.
The legacy Python-distributed 7.9.x channel remains separate through `latest.json`.

## Produced packages

- `TURTO_CRM_Setup_<version>.exe` – first installation on a new Windows PC.
- `TURTO_CRM_Update_<version>.zip` – hash-verified payload for an already installed 8.x application.

The setup package installs program files per-user under `%LOCALAPPDATA%\Programs\TURTO CRM`.
Business data are deliberately not embedded in the installer and are never removed by uninstall.

## First run / existing data

Before the main application initializes its schema, `data_onboarding.py` checks the configured database.
If no valid TURTO CRM database is available, the user can:

1. create/use a new standard database under `%USERPROFILE%\Documents\TURTO Zakazky\data\zakazky.db`, or
2. select an existing SQLite database and either:
   - safely copy it into the standard TURTO data folder using SQLite backup, or
   - keep using the selected file in-place.

When an existing standard 7.x database is found during the first 8.x start, TURTO CRM adopts it only
after a validated read-only SQLite safety backup is created. The first 8.x adoption is recorded in
the per-user installation metadata so this special backup is not repeated on every start.

The database choice is not limited to first start. The installer creates a Start-menu entry
`TURTO CRM - Připojit nebo změnit databázi`, which starts the frozen application with
`--data-setup` and reopens the data wizard without requiring Python or reinstalling TURTO CRM.

When an already existing standard database is replaced through this management mode, the current
standard database is first copied to the TURTO backup directory with SQLite's backup API. Only
after that backup validates successfully is the selected database copied into the standard location.
The selected source file is not deleted or modified.

In-place SQLite files should be local and single-writer. A network share or cloud-synchronized folder
is not a replacement for a multi-user database server. The database-management wizard explicitly
warns the user to close any other running TURTO CRM window before switching databases.

The selected location is stored per Windows user in `%LOCALAPPDATA%\TURTO CRM\installation.json`.

## Frozen runtime

- Main application: PyInstaller `onedir`; no system Python installation is required on the target PC.
- Updater: PyInstaller `onefile`, copied to a temporary directory before replacing the installed program.
- Windows 8.x update channel: `latest-windows.json`, separate from legacy `latest.json`.
- Production binaries live as GitHub Release assets; the manifest contains their expected SHA-256 hashes.

## CI installation contract

The Windows validation deliberately uses two separate hosted Windows runners:

1. the build runner creates and validates the Setup EXE and update ZIP and uploads them as an artifact;
2. a fresh runner downloads only that artifact, performs a silent installation, starts the installed
   frozen `TURTO CRM.exe` against an external temporary data root, performs an updater transaction,
   starts the updated frozen runtime again, uninstalls the application and verifies that the business
   database remains available and protected.

The production publisher repeats a final installer smoke test before creating the GitHub Release and
publishing `latest-windows.json`.

## Safety contract

Before every 8.x update/rollback the updater must:

- create a consistent SQLite database backup from a read-only source connection,
- snapshot the currently installed program,
- preserve Inno Setup uninstaller metadata,
- replace program files only,
- validate the new EXE payload,
- restart `TURTO CRM.exe`,
- restore the previous program automatically if program replacement fails.

## Release gate

Production Windows publishing is intentionally explicit. `windows_release_request.json` is the release
request and the dedicated Windows publisher reacts only to that file. Ordinary development commits do
not publish a new 8.x build.

## Installer compiler

The Windows installer uses Inno Setup for a polished per-user installer and Czech UI. Confirm the
applicable Inno Setup license for the intended TURTO deployment model when changing distribution scope.
