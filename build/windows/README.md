# TURTO CRM 8.0 – Windows EXE distribution (preview)

This directory prepares the successor to the Python-distributed 7.9.x line.
Nothing here is published to the production update channel yet.

## Produced packages

- `TURTO_CRM_Setup_<version>.exe` – first installation on a new Windows PC.
- `TURTO_CRM_Update_<version>.zip` – hashable payload for an already installed 8.x application.

The setup package installs program files per-user under `%LOCALAPPDATA%\Programs\TURTO CRM`.
Business data are deliberately not embedded in the installer and are never removed by uninstall.

## First run / existing data

Before the main application initializes its schema, `data_onboarding.py` checks the configured database.
If no valid TURTO CRM database is available, the user can:

1. create/use a new standard database under `%USERPROFILE%\Documents\TURTO Zakazky\data\zakazky.db`, or
2. select an existing SQLite database and either:
   - safely copy it into the standard TURTO data folder using SQLite backup, or
   - keep using the selected file in-place.

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

- Main application: PyInstaller `onedir`, no Python installation required on the target PC.
- Updater: PyInstaller `onefile`, copied to a temporary directory before replacing the installed program.
- Windows 8.x update channel: `latest-windows.json` (separate from legacy `latest.json`).

## CI installation contract

The Windows workflow deliberately uses two separate hosted Windows runners:

1. the build runner creates and validates the Setup EXE and update ZIP and uploads them as an artifact;
2. a fresh runner downloads only that artifact, performs a silent installation, starts the installed
   frozen `TURTO CRM.exe` against an external temporary data root, validates SQLite, uninstalls the
   application and verifies that the business database still exists with the same SHA-256 hash.

This avoids hiding first-start issues through a warmed PyInstaller/Defender/runtime cache on the build machine.

## Safety contract

Before every 8.x update/rollback the updater must:

- create a consistent SQLite database backup,
- snapshot the currently installed program,
- preserve Inno Setup uninstaller metadata,
- replace program files only,
- validate the new EXE payload,
- restart `TURTO CRM.exe`.

## Installer compiler

The current preview uses Inno Setup because it supports a polished per-user installer and Czech UI.
Before production use, confirm the applicable commercial Inno Setup license for TURTO or replace this stage with another approved installer technology.
