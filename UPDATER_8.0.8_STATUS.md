# TURTO CRM 8.0.8 updater hotfix — validation stage

Changes are committed on hotfix-808-updater-safety. Not released yet.

Initial Linux CI passed. Initial Windows run passed the installation/data-location foundation and all 29 updater regressions; one of seven handshake test cases used the Windows default encoding to read a UTF-8 Czech diagnostic. That test now explicitly reads UTF-8; the entire Windows build and integration run must pass before release.

New architecture: non-destructive process wait, real OS-owned locks, verified reusable onedir updater without UPX, readiness/cancellation handshake, complete staged replacement and retained rollback directory on recovery failure. No ESET settings or quarantine entries are changed.

The publication workflow promotes the exact installer and update ZIP from a successful complete CI run. It validates source commit, all required jobs, smoke report, input SHA-256 and published asset digests. It does not rebuild or overwrite release assets.

Migration: install 8.0.8 once with official Setup. The unsafe legacy latest-windows.json remains at 8.0.7. New applications use latest-windows-v2.json.

Pending: successful complete Windows CI, explicit release request with validated run/commit, release 8.0.8 publication and safe-channel readback. ESET itself is not installed on hosted runners and has not validated these binaries.
