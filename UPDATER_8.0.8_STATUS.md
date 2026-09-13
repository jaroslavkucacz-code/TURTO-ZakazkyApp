# TURTO CRM 8.0.8 updater hotfix (work in progress)

Based on main b614872eb09c03bb06eefc0999a01ca6da711bee (8.0.7).
Core code is committed on hotfix-808-updater-safety, NOT released yet.

Architecture: onedir updater without UPX; reuse verified working bundle; receipt stops recreation of missing/quarantined files; OS-owned lock; readiness handshake; non-destructive Windows process wait; stage and validate a complete installation before directory rename; keep old directory if rollback fails; do not change database location or ESET policy.

Migration: first install 8.0.8 using official Setup. Do not move the old latest-windows.json channel off 8.0.7. New versions read latest-windows-v2.json. This prevents using the known-bad 8.0.7 updater to install its own fix.

Still required: cancellation checks after handshake; behavioral source tests including Windows file locks; build/smoke workflow adaptation for onedir; successful frozen install/update/rollback/uninstall tests; publish release and safe manifest only after tests.
