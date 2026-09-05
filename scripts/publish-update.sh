#!/usr/bin/env bash
set -euo pipefail

# Historical regression manifest (documentation only; execution is owned by runtime_bootstrap).
# import app,crm_features,crm_runtime,crm_v605,crm_price_lists,v606_features,v608_stability,v611_audit,v613_ui,v614_next,v615_input,v616_stability,v617_offerhub,v618_inputfix,v619_fixes,v620_outlookdrop,v621_prices,v623_exports,v624_legacy_exports,v625_stability,v628_modernui_resize,v631_diskdrop,v632_offerlinks,v633_offerassign_deadlines,v636_action_offers_stabletable,v637_project_offer_model,v638_table_updatefix,v640_warning_cleanup,v644_default_date_sort,post_baseline,v710_cleanup,v720_visual_offer,v730_polish,v740_offer_defaults,v750_context_filters_offer_format,v760_table_activity_performance,v767_offer_reprocess_images,v768_clean_table_markers,v769_nevoga_offer
# crm_features.apply(app);crm_runtime.apply(app);crm_v605.apply(app);v606_features.apply(app);v608_stability.apply(app);v611_audit.apply(app);v613_ui.apply(app);v614_next.apply(app);v615_input.apply(app);v616_stability.apply(app);v617_offerhub.apply(app);v618_inputfix.apply(app);v619_fixes.apply(app);v620_outlookdrop.apply(app);v621_prices.apply(app);v623_exports.apply(app);v625_stability.apply(app);v628_modernui_resize.apply(app);v632_offerlinks.apply(app);v633_offerassign_deadlines.apply(app);v636_action_offers_stabletable.apply(app);v637_project_offer_model.apply(app);v638_table_updatefix.apply(app);v640_warning_cleanup.apply(app);post_baseline.apply(app);v631_diskdrop.apply(app);v644_default_date_sort.apply(app);crm_features.install_offer_ui(app);crm_price_lists.apply(app);v710_cleanup.apply(app);v720_visual_offer.apply(app);v730_polish.apply(app);v740_offer_defaults.apply(app);v750_context_filters_offer_format.apply(app);v760_table_activity_performance.apply(app);v767_offer_reprocess_images.apply(app);v768_clean_table_markers.apply(app);v769_nevoga_offer.apply(app)

VERSION="$(tr -d ' \r\n' < release_version.txt)"
STAGE="ZakazkyApp_v${VERSION}"
BASE_DIR="ZakazkyApp_base_6.1"
test -d "$BASE_DIR"

# Full regression suite retained from 7.6, plus the explicit 7.7 runtime policy.
python scripts/validate-6339-catalog-price-ux.py "$BASE_DIR"
python scripts/validate-7100-commercial-cleanup.py "$BASE_DIR"
python scripts/validate-7200-visual-issued-offers.py "$BASE_DIR"
python scripts/validate-7300-polish.py "$BASE_DIR"
python scripts/validate-7400-issued-pricing-columns.py "$BASE_DIR"
python scripts/validate-7500-context-filters-offer-format.py "$BASE_DIR"
python scripts/validate-7600-table-activity-performance.py "$BASE_DIR"
python scripts/validate-764-gerotop-geometry.py "$BASE_DIR"
python scripts/validate-767-offer-reprocess-images.py "$BASE_DIR"
python scripts/validate-768-clean-table-markers.py "$BASE_DIR"
python scripts/validate-769-nevoga-rich-description.py "$BASE_DIR"
python scripts/validate-7610-nevoga-exact-red-excel.py "$BASE_DIR"
python scripts/validate-7800-professional-offer-workflow.py "$BASE_DIR"
python scripts/validate-770-runtime-policy.py "$BASE_DIR"

rm -rf "$STAGE"
cp -a "$BASE_DIR" "$STAGE"
cp post_baseline.py "$STAGE/post_baseline.py"

# The first reversible release carries the proven 7.6.16 package locally.  From
# 7.7 onward the new updater snapshots the currently installed program before
# every change, so future releases do not need a recursively nested package.
if [[ "$VERSION" == "7.7.0" && -f latest.json ]]; then
  python - "$STAGE" <<'PY'
import hashlib,json,pathlib,shutil,sys
stage=pathlib.Path(sys.argv[1])
manifest=pathlib.Path('latest.json')
try:
    data=json.loads(manifest.read_text(encoding='utf-8'))
    package=pathlib.Path(str(data.get('file') or ''))
    if data.get('version')=='7.6.16' and package.is_file():
        target_dir=stage/'_rollback'
        target_dir.mkdir(parents=True,exist_ok=True)
        target=target_dir/package.name
        shutil.copy2(package,target)
        digest=hashlib.sha256(target.read_bytes()).hexdigest()
        expected=str(data.get('sha256') or '')
        if expected and digest.casefold()!=expected.casefold():
            raise SystemExit('Embedded rollback package SHA-256 mismatch')
        (target_dir/'rollback_manifest.json').write_text(
            json.dumps({'version':'7.6.16','file':target.name,'sha256':digest},ensure_ascii=False,indent=2)+'\n',
            encoding='utf-8',
        )
except Exception as exc:
    raise SystemExit(f'Unable to embed 7.6.16 rollback package: {exc}')
PY
fi

RUNTIME="$STAGE/_runtime"
mkdir -p "$RUNTIME"
for f in \
  runtime_bootstrap.py \
  crm_features.py crm_runtime.py crm_v605.py crm_price_lists.py \
  v606_features.py v608_stability.py v611_audit.py v613_ui.py v614_next.py \
  v615_input.py v616_stability.py v617_offerhub.py v618_inputfix.py v619_fixes.py \
  v620_outlookdrop.py v621_prices.py v623_exports.py v624_legacy_exports.py \
  v625_stability.py v628_modernui_resize.py v631_diskdrop.py \
  v632_offerlinks.py v633_offerassign_deadlines.py \
  v636_action_offers_stabletable.py v637_project_offer_model.py \
  v638_table_updatefix.py v640_warning_cleanup.py \
  v644_default_date_sort.py v710_cleanup.py v720_visual_offer.py v730_polish.py \
  v740_offer_defaults.py v750_context_filters_offer_format.py \
  v760_table_activity_performance.py v767_offer_reprocess_images.py \
  v768_clean_table_markers.py v769_nevoga_offer.py \
  v7614_nevoga_canonical_export.py v7615_nevoga_meter_units.py \
  v7616_requests_plexus_assets.py v770_runtime_policy.py post_baseline.py
do
  [[ -f "$STAGE/$f" ]] && mv "$STAGE/$f" "$RUNTIME/$f"
done
[[ -d "$STAGE/price_lists_domain" ]] && mv "$STAGE/price_lists_domain" "$RUNTIME/price_lists_domain"

rm -rf "$STAGE/__pycache__" "$STAGE/ZakazkyApp_v5.7" "$STAGE/original_source"
rm -f "$STAGE/post_fix_613.py" "$STAGE/v622_palette.py" \
      "$STAGE/v626_smoothui.py" "$STAGE/v627_fastui_dropfix.py" \
      "$STAGE/v630_safeofferdrop.py" "$STAGE/v634_assignment_search.py" \
      "$STAGE/v635_actions_sort.py" "$STAGE/v641_fill_tables.py" \
      "$STAGE/v642_exact_table_fill.py" "$STAGE/v642_fullwidth_all.py" \
      "$STAGE/v645_project_table_fill.py" \
      "$STAGE/Spustit_DIAGNOSTIKA.bat" "$STAGE/Spustit_Qt_PREVIEW.bat" \
      "$STAGE/Spustit_Zakazky_v5.bat" "$STAGE/Spustit_Zakazky_v5.vbs" \
      "$STAGE/Vytvorit_EXE.bat" "$STAGE/Vytvorit_manifest_aktualizace.py" "$STAGE/latest.example.json"

python - "$STAGE/app.py" "$VERSION" <<'PY'
import pathlib,re,sys
path=pathlib.Path(sys.argv[1])
text=path.read_text(encoding='utf-8')
version=sys.argv[2]
text,count=re.subn(r'APP_VERSION\s*=\s*["\'][^"\']+["\']',f'APP_VERSION="{version}"',text,count=1)
if count!=1:
    raise SystemExit('APP_VERSION replacement failed')
path.write_text(text,encoding='utf-8')
PY

cat > "$STAGE/ZakazkyCRM.pyw" <<'PYW'
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'_runtime'
if str(RUNTIME) not in sys.path:sys.path.insert(0,str(RUNTIME))
import app,runtime_bootstrap
runtime_bootstrap.apply_all(app)
app.cleanup_stale_test_session();app.ensure_schema();app.ensure_test_user();app.migrate_v41_visual_once();app.import_mail_contacts_v220_once();app.import_mail_contacts_v221_once();app.restore_people_from_v280_backup_once();app.post_import_cleanup_v222_once();app.App().mainloop()
PYW

cat > "$STAGE/Spustit_Zakazky.vbs" <<'VBS'
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.Run "py -m pip install -r requirements.txt --disable-pip-version-check --no-input", 0, True
sh.Run "pyw ZakazkyCRM.pyw", 0, False
VBS

python -m compileall -q "$STAGE"

# Clean runtime layout and one explicit composition owner.
test -d "$RUNTIME"
test -e "$RUNTIME/runtime_bootstrap.py"
test -e "$RUNTIME/v770_runtime_policy.py"
test -e "$RUNTIME/v7616_requests_plexus_assets.py"
test -e "$RUNTIME/v7614_nevoga_canonical_export.py"
test -e "$RUNTIME/v7615_nevoga_meter_units.py"
test -e "$RUNTIME/v769_nevoga_offer.py"
test -e "$RUNTIME/v768_clean_table_markers.py"
test -e "$RUNTIME/v767_offer_reprocess_images.py"
test -e "$RUNTIME/v760_table_activity_performance.py"
test -e "$RUNTIME/v631_diskdrop.py"
test -e "$RUNTIME/crm_price_lists.py"
test -d "$RUNTIME/price_lists_domain"
test -e "$RUNTIME/price_lists_domain/issued_offers/professional_workflow.py"
test -e "$STAGE/offers_engine/Gerotop_Parser_767.py"
test ! -e "$STAGE/runtime_bootstrap.py"
test ! -e "$STAGE/v770_runtime_policy.py"
test ! -e "$STAGE/crm_price_lists.py"
test ! -e "$STAGE/price_lists_domain"
grep -q "runtime_bootstrap.apply_all(app)" "$STAGE/ZakazkyCRM.pyw"
! grep -q "v624_legacy_exports.apply(app)" "$STAGE/ZakazkyCRM.pyw"
! grep -Eq "v622_palette|v626_smoothui|v627_fastui_dropfix|v630_safeofferdrop|v634_assignment_search|v635_actions_sort" "$STAGE/ZakazkyCRM.pyw"

grep -q "def group_offer_items" "$RUNTIME/v710_cleanup.py"
grep -q "class OfferPreview" "$RUNTIME/v720_visual_offer.py"
grep -q "pdf_renderer.render_offer_pdf" "$RUNTIME/v720_visual_offer.py"
grep -q "Poslední platný náhled zůstal zobrazen" "$RUNTIME/v730_polish.py"
grep -q "company_merge_history" "$RUNTIME/v730_polish.py"
grep -q "Zákl. marže" "$RUNTIME/v740_offer_defaults.py"
grep -q "pricing_rule_source_snapshot" "$RUNTIME/v740_offer_defaults.py"
grep -q "Všichni dodavatelé" "$RUNTIME/v740_offer_defaults.py"
grep -q "Formát výstupu: A4" "$RUNTIME/v750_context_filters_offer_format.py"
grep -q "supplier_presentation_snapshot" "$RUNTIME/v750_context_filters_offer_format.py"
grep -q "displayed_columns(tree)" "$RUNTIME/v750_context_filters_offer_format.py"
grep -q "Přidat připomínku" "$RUNTIME/v750_context_filters_offer_format.py"
grep -q "Poslední pohyb" "$RUNTIME/v760_table_activity_performance.py"
grep -q "sync_heading_anchors" "$RUNTIME/v760_table_activity_performance.py"
grep -q "single_union_query" "$RUNTIME/v760_table_activity_performance.py"
grep -q "reprocessed_existing" "$RUNTIME/v767_offer_reprocess_images.py"
grep -q "DELETE FROM supplier_offer_items WHERE offer_id" "$RUNTIME/v767_offer_reprocess_images.py"
grep -q "Gerotop_Parser_767 as gerotop" "$STAGE/offers_engine/Nabidky_Router.py"
grep -q "def _extract_row_image" "$STAGE/offers_engine/Gerotop_Parser_767.py"
grep -q "insert_image" "$STAGE/offers_engine/Gerotop_Parser_767.py"
grep -q "def install_offer_ui" "$RUNTIME/crm_features.py"
grep -q "Zpracovat nabídku" "$RUNTIME/crm_features.py"
grep -q "CREATE TABLE IF NOT EXISTS product_subgroups" "$RUNTIME/price_lists_domain/platform/database.py"
grep -q "CREATE TABLE IF NOT EXISTS catalog_products" "$RUNTIME/price_lists_domain/platform/database.py"
grep -q "_turto_commercial_workspace_v6339" "$RUNTIME/price_lists_domain/platform/commercial_workspace.py"
grep -q "Windows.Media.Ocr" "$RUNTIME/price_lists_domain/ocr.py"
grep -q "Kontrola a řízené vydání" "$RUNTIME/price_lists_domain/issued_offers/professional_workflow.py"
grep -qi "openpyxl" "$STAGE/requirements.txt"

# One native drop owner and one DB-first archive pipeline.
! grep -q "tkdnd::drop_target" "$RUNTIME/v620_outlookdrop.py"
grep -q "class UnifiedDropTarget" "$RUNTIME/v631_diskdrop.py"
grep -q "RenPrivateMessages" "$RUNTIME/v631_diskdrop.py"
! grep -Fq "pythoncom.PumpWaitingMessages(" "$RUNTIME/v631_diskdrop.py"
grep -q "MAIN_ATTACHMENT_EXTS" "$RUNTIME/post_baseline.py"
grep -q "def is_main_attachment" "$RUNTIME/post_baseline.py"
grep -q "M.App._start_offer_batch = start_offer_batch" "$RUNTIME/post_baseline.py"
grep -q "M.App.delete_offer = delete_offer" "$RUNTIME/post_baseline.py"
test "$(grep -o "v624_legacy_exports.apply" "$RUNTIME/post_baseline.py" | wc -l)" -eq 1

# Reversible update contract.
grep -q "_snapshot_program" "$STAGE/crm_updater.pyw"
grep -q "_database_backup" "$STAGE/crm_updater.pyw"
grep -q -- "--install" "$STAGE/crm_updater.pyw"
grep -q "rollback_preserves_database" "$RUNTIME/v770_runtime_policy.py"
if [[ "$VERSION" == "7.7.0" ]]; then
  test -e "$STAGE/_rollback/rollback_manifest.json"
  test -e "$STAGE/_rollback/ZakazkyApp_v7.6.16.zip"
fi

ZIP="ZakazkyApp_v${VERSION}.zip"
rm -f "$ZIP"
zip -qr "$ZIP" "$STAGE" -x '*/__pycache__/*' '*.pyc'
SHA="$(sha256sum "$ZIP" | awk '{print $1}')"
python - "$VERSION" "$ZIP" "$SHA" <<'PY'
import json,pathlib,sys
version,filename,sha=sys.argv[1:]
notes=pathlib.Path('release_notes.txt').read_text(encoding='utf-8').strip()
pathlib.Path('latest.json').write_text(
    json.dumps({'version':version,'file':filename,'sha256':sha,'notes':notes},ensure_ascii=False,indent=2)+'\n',
    encoding='utf-8',
)
PY

git config user.name "TURTO Update Bot"
git config user.email "actions@users.noreply.github.com"
git add -f "$ZIP" latest.json
git commit -m "Publish ZakazkyApp v${VERSION} update"
for try in 1 2 3; do
  git pull --rebase origin main && git push origin HEAD:main && exit 0
  sleep $((try*2))
done
exit 1
