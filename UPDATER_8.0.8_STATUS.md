# TURTO CRM 8.0.8 updater hotfix — validation stage

Core and cancellation handling are committed on hotfix-808-updater-safety. Not released yet.

New behavioral tests cover stage reuse/quarantine simulation, preflight/rename/rollback failures, real Windows file locks, live process waiting, cross-process locks, handshake cancellation, payload/hash validation and safe-channel separation. Windows CI builds the onedir application/updater and tests the exact installer, actual frozen update, rollback, repair install and uninstall with byte-level business-database checks. ESET itself is not available on the hosted runner; no ESET compatibility guarantee is made.

Migration: install 8.0.8 once with official Setup. The unsafe legacy latest-windows.json must remain on 8.0.7. New applications read latest-windows-v2.json.

Pending: successful CI results; publication workflow promoting the exact validated artifacts; release 8.0.8 and safe-channel manifest. Do not change main/update channels before successful verification.
