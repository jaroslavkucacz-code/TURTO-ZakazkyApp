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

In-place SQLite files should be local and single-writer. A network share or cloud-synchronized folder is not a replacement for a multi-user database server.

The selected location is stored per Windows user in `%LOCALAPPDATA%\TURTO CRM\installation.json`.

## Frozen runtime

- Main application: PyInstaller `onedir`, no Python installation required on the target PC.
- Updater: PyInstaller `onefile`, copied to a temporary directory before replacing the installed program.
- Windows 8.x update channel: `latest-windows.json` (separate from legacy `latest.json`).

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
