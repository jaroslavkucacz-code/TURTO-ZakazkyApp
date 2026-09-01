#!/usr/bin/env bash
set -euo pipefail

# --- Prepare release ---
set -euo pipefail
VERSION="$(tr -d ' \r\n' < release_version.txt)"
STAGE="ZakazkyApp_v${VERSION}"
BASE_DIR="ZakazkyApp_base_6.1"
test -d "$BASE_DIR"
python scripts/validate-6339-catalog-price-ux.py "$BASE_DIR"
python scripts/validate-7100-commercial-cleanup.py "$BASE_DIR"
python scripts/validate-7200-visual-issued-offers.py "$BASE_DIR"
python scripts/validate-7300-polish.py "$BASE_DIR"
python scripts/validate-7400-issued-pricing-columns.py "$BASE_DIR"
rm -rf "$STAGE"
cp -a "$BASE_DIR" "$STAGE"
cp post_baseline.py "$STAGE/post_baseline.py"

RUNTIME="$STAGE/_runtime"
mkdir -p "$RUNTIME"
for f in \
  crm_features.py crm_runtime.py crm_v605.py crm_price_lists.py \
  v606_features.py v608_stability.py v611_audit.py v613_ui.py v614_next.py \
  v615_input.py v616_stability.py v617_offerhub.py v618_inputfix.py v619_fixes.py \
  v620_outlookdrop.py v621_prices.py v623_exports.py v624_legacy_exports.py \
  v625_stability.py v628_modernui_resize.py v631_diskdrop.py \
  v632_offerlinks.py v633_offerassign_deadlines.py \
  v636_action_offers_stabletable.py v637_project_offer_model.py \
  v638_table_updatefix.py v640_warning_cleanup.py \
  v644_default_date_sort.py v710_cleanup.py v720_visual_offer.py v730_polish.py v740_offer_defaults.py post_baseline.py
do
  [ -f "$STAGE/$f" ] && mv "$STAGE/$f" "$RUNTIME/$f"
done
[ -d "$STAGE/price_lists_domain" ] && mv "$STAGE/price_lists_domain" "$RUNTIME/price_lists_domain"

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
text,count=re.subn(
    r'APP_VERSION\s*=\s*["\'][^"\']+["\']',
    f'APP_VERSION="{version}"',text,count=1,
)
if count!=1:raise SystemExit('APP_VERSION replacement failed')
path.write_text(text,encoding='utf-8')
PY

cat > "$STAGE/ZakazkyCRM.pyw" <<'PYW'
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'_runtime'
if str(RUNTIME) not in sys.path:sys.path.insert(0,str(RUNTIME))
import app,crm_features,crm_runtime,crm_v605,crm_price_lists,v606_features,v608_stability,v611_audit,v613_ui,v614_next,v615_input,v616_stability,v617_offerhub,v618_inputfix,v619_fixes,v620_outlookdrop,v621_prices,v623_exports,v624_legacy_exports,v625_stability,v628_modernui_resize,v631_diskdrop,v632_offerlinks,v633_offerassign_deadlines,v636_action_offers_stabletable,v637_project_offer_model,v638_table_updatefix,v640_warning_cleanup,v644_default_date_sort,post_baseline,v710_cleanup,v720_visual_offer,v730_polish,v740_offer_defaults
crm_features.apply(app);crm_runtime.apply(app);crm_v605.apply(app);v606_features.apply(app);v608_stability.apply(app);v611_audit.apply(app);v613_ui.apply(app);v614_next.apply(app);v615_input.apply(app);v616_stability.apply(app);v617_offerhub.apply(app);v618_inputfix.apply(app);v619_fixes.apply(app);v620_outlookdrop.apply(app);v621_prices.apply(app);v623_exports.apply(app);v625_stability.apply(app);v628_modernui_resize.apply(app);v632_offerlinks.apply(app);v633_offerassign_deadlines.apply(app);v636_action_offers_stabletable.apply(app);v637_project_offer_model.apply(app);v638_table_updatefix.apply(app);v640_warning_cleanup.apply(app);post_baseline.apply(app);v631_diskdrop.apply(app);v644_default_date_sort.apply(app);crm_features.install_offer_ui(app);crm_price_lists.apply(app);v710_cleanup.apply(app);v720_visual_offer.apply(app);v730_polish.apply(app);v740_offer_defaults.apply(app)
app.cleanup_stale_test_session();app.ensure_schema();app.ensure_test_user();app.migrate_v41_visual_once();app.import_mail_contacts_v220_once();app.import_mail_contacts_v221_once();app.restore_people_from_v280_backup_once();app.post_import_cleanup_v222_once();app.App().mainloop()
PYW

cat > "$STAGE/Spustit_Zakazky.vbs" <<'VBS'
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.Run "py -m pip install -r requirements.txt --disable-pip-version-check --no-input", 0, True
sh.Run "pyw ZakazkyCRM.pyw", 0, False
VBS

# --- Validate Python ---
set -euo pipefail
python -m compileall -q "$STAGE"

# --- Validate clean runtime layout ---
set -euo pipefail
DIR="$STAGE"
test -d "$DIR/_runtime"
test -e "$DIR/_runtime/v644_default_date_sort.py"
test -e "$DIR/_runtime/v710_cleanup.py"
test -e "$DIR/_runtime/v720_visual_offer.py"
test -e "$DIR/_runtime/v730_polish.py"
test -e "$DIR/_runtime/v740_offer_defaults.py"
test -e "$DIR/_runtime/v631_diskdrop.py"
test -e "$DIR/_runtime/crm_price_lists.py"
test -d "$DIR/_runtime/price_lists_domain"
test ! -e "$DIR/crm_price_lists.py"
test ! -e "$DIR/price_lists_domain"
for obsolete in \
  v622_palette.py v626_smoothui.py v627_fastui_dropfix.py \
  v630_safeofferdrop.py v634_assignment_search.py v635_actions_sort.py \
  v641_fill_tables.py v642_exact_table_fill.py v642_fullwidth_all.py \
  v645_project_table_fill.py post_fix_613.py
do
  test ! -e "$DIR/_runtime/$obsolete"
  test ! -e "$DIR/$obsolete"
done
test -e "$DIR/ZakazkyCRM.pyw"
test -e "$DIR/Spustit_Zakazky.vbs"
test -e "$DIR/Spustit_Zakazky.bat"
grep -q "ZakazkyCRM.pyw" "$DIR/Spustit_Zakazky.bat"
! grep -q "pyw app.py" "$DIR/Spustit_Zakazky.bat"
! grep -q "pythonw app.py" "$DIR/Spustit_Zakazky.bat"
grep -q "post_baseline.apply(app);v631_diskdrop.apply(app);v644_default_date_sort.apply(app)" "$DIR/ZakazkyCRM.pyw"
grep -q "crm_features.install_offer_ui(app);crm_price_lists.apply(app);v710_cleanup.apply(app);v720_visual_offer.apply(app);v730_polish.apply(app);v740_offer_defaults.apply(app)" "$DIR/ZakazkyCRM.pyw"
grep -q "def group_offer_items" "$DIR/_runtime/v710_cleanup.py"
grep -q "class OfferPreview" "$DIR/_runtime/v720_visual_offer.py"
grep -q "pdf_renderer.render_offer_pdf" "$DIR/_runtime/v720_visual_offer.py"
grep -q "Poslední platný náhled zůstal zobrazen" "$DIR/_runtime/v730_polish.py"
grep -q "company_merge_history" "$DIR/_runtime/v730_polish.py"
grep -q "Zákl. marže" "$DIR/_runtime/v740_offer_defaults.py"
grep -q "pricing_rule_source_snapshot" "$DIR/_runtime/v740_offer_defaults.py"
grep -q "Všichni dodavatelé" "$DIR/_runtime/v740_offer_defaults.py"
grep -q "tree.bind(\"<Button-3>\", popup, add=False)" "$DIR/_runtime/v740_offer_defaults.py"
grep -q "Barvy jsou upozornění" "$DIR/_runtime/v730_polish.py"
grep -q "def install_offer_ui" "$DIR/_runtime/crm_features.py"
grep -q "Zpracovat nabídku" "$DIR/_runtime/crm_features.py"
grep -q "def ensure_price_list_schema" "$DIR/_runtime/price_lists_domain/schema.py"
grep -q "CREATE TABLE IF NOT EXISTS product_subgroups" "$DIR/_runtime/price_lists_domain/platform/database.py"
grep -q "def choose_taxonomy" "$DIR/_runtime/price_lists_domain/platform/categories.py"
grep -q "CREATE TABLE IF NOT EXISTS catalog_products" "$DIR/_runtime/price_lists_domain/platform/database.py"
grep -q "def sync_price_list" "$DIR/_runtime/price_lists_domain/platform/product_catalog.py"
grep -q "_turto_commercial_presentation_owner" "$DIR/_runtime/price_lists_domain/platform/commercial_workspace.py"
grep -q "_turto_commercial_workspace_v6339" "$DIR/_runtime/price_lists_domain/platform/commercial_workspace.py"
grep -q "Struktura cen" "$DIR/_runtime/price_lists_domain/platform/commercial_workspace.py"
grep -q "def reorder_category" "$DIR/_runtime/price_lists_domain/platform/categories.py"
grep -q "_turto_product_workspace_v639" "$DIR/_runtime/price_lists_domain/platform/product_workspace.py"
grep -q "Vrátit poslední přesun" "$DIR/_runtime/price_lists_domain/platform/product_workspace.py"
grep -q "Detail vybrané ceny" "$DIR/_runtime/price_lists_domain/platform/commercial_workspace.py"
grep -q "Doporučená cena" "$DIR/_runtime/price_lists_domain/platform/price_page.py"
grep -q "Produkty ve výběru" "$DIR/_runtime/price_lists_domain/platform/categories.py"
grep -q "Přiřadit skupinu / podskupinu" "$DIR/_runtime/price_lists_domain/platform/offers.py"
grep -q "if not mivo:" "$DIR/_runtime/price_lists_domain/platform/worksets.py"
grep -q "Windows.Media.Ocr" "$DIR/_runtime/price_lists_domain/ocr.py"
grep -q "price_list_archive_dir" "$DIR/_runtime/price_lists_domain/archive.py"
grep -q "+ Nová Akce" "$DIR/_runtime/price_lists_domain/opportunity.py"
grep -q "Označit jako Ceník" "$DIR/_runtime/price_lists_domain/offer_integration.py"
grep -qi "openpyxl" "$DIR/requirements.txt"
python - "$DIR/ZakazkyCRM.pyw" <<'PY'
import pathlib,sys
text=pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert text.index('v644_default_date_sort.apply(app)') < text.index('crm_features.install_offer_ui(app)')
assert text.index('crm_features.install_offer_ui(app)') < text.index('crm_price_lists.apply(app)')
assert text.index('crm_price_lists.apply(app)') < text.index('v710_cleanup.apply(app)')
assert text.index('v710_cleanup.apply(app)') < text.index('v720_visual_offer.apply(app)')
assert text.index('v720_visual_offer.apply(app)') < text.index('v730_polish.apply(app)')
assert text.index('v730_polish.apply(app)') < text.index('v740_offer_defaults.apply(app)')
PY
python - "$DIR" <<'PY'
import pathlib,sys
root=pathlib.Path(sys.argv[1])
sys.path.insert(0,str(root/'_runtime'))
from price_lists_domain.common import _number
from price_lists_domain.model import _base_item
assert _number('368,37') == 368.37
item=_base_item(source_price=368.37,price_basis_qty=100,unit='m')
assert abs(item['normalized_unit_price']-3.6837)<1e-9
PY
! grep -q "v624_legacy_exports.apply(app)" "$DIR/ZakazkyCRM.pyw"
! grep -Eq "v622_palette|v626_smoothui|v627_fastui_dropfix|v630_safeofferdrop|v634_assignment_search|v635_actions_sort" "$DIR/ZakazkyCRM.pyw"

# One native drop owner. Whole Outlook MSG never reads descriptor data.
! grep -q "tkdnd::drop_target" "$DIR/_runtime/v620_outlookdrop.py"
grep -q "class UnifiedDropTarget" "$DIR/_runtime/v631_diskdrop.py"
grep -q "def _enable_faulthandler" "$DIR/_runtime/v631_diskdrop.py"
grep -q "def _install_tk_exception_guard" "$DIR/_runtime/v631_diskdrop.py"
grep -q "def virtual_descriptors" "$DIR/_runtime/v631_diskdrop.py"
grep -q "def virtual_pdf_content" "$DIR/_runtime/v631_diskdrop.py"
grep -q "def materialize_pdf_attachments" "$DIR/_runtime/v631_diskdrop.py"
grep -q "RegisterClipboardFormat('FileContents')" "$DIR/_runtime/v631_diskdrop.py"
grep -q "RenPrivateMessages" "$DIR/_runtime/v631_diskdrop.py"
grep -q "RenPrivateLatestMessages" "$DIR/_runtime/v631_diskdrop.py"
grep -q "if Path(name).suffix.lower() == '.pdf'" "$DIR/_runtime/v631_diskdrop.py"
grep -q "M.App.import_selected_outlook_offer = import_selected_outlook_offer" "$DIR/_runtime/v631_diskdrop.py"
! grep -Fq "pythoncom.PumpWaitingMessages(" "$DIR/_runtime/v631_diskdrop.py"
python - "$DIR/_runtime/v631_diskdrop.py" <<'PY'
import pathlib,sys
text=pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert "def is_outlook_message_drop" in text
assert "RenPrivateMessages" in text
assert "RenPrivateLatestMessages" in text
assert "pythoncom.PumpWaitingMessages(" not in text
whole=text.index("if kind == 'outlook_messages'")
descriptor=text.index("descriptors = virtual_descriptors", whole)
assert whole < descriptor
PY

# One DB-first archive/export pipeline with strict attachment filtering.
grep -q "MAIN_ATTACHMENT_EXTS" "$DIR/_runtime/post_baseline.py"
grep -q "def is_main_attachment" "$DIR/_runtime/post_baseline.py"
grep -q "Inline images" "$DIR/_runtime/post_baseline.py"
grep -q "M.App._start_offer_batch = start_offer_batch" "$DIR/_runtime/post_baseline.py"
grep -q "M.App.delete_offer = delete_offer" "$DIR/_runtime/post_baseline.py"
grep -q "import v624_legacy_exports" "$DIR/_runtime/post_baseline.py"
test "$(grep -o "v624_legacy_exports.apply" "$DIR/_runtime/post_baseline.py" | wc -l)" -eq 1

# Rich GEROtop text, supplier-owned Leviat reference and archive naming.
grep -q "details_rich_json" "$DIR/_runtime/post_baseline.py"
grep -q "def ensure_offer_rich_details" "$DIR/_runtime/post_baseline.py"
grep -q "details_rich_json" "$DIR/_runtime/v624_legacy_exports.py"
grep -q "Reference zákazníka (Leviat)" "$DIR/_runtime/v624_legacy_exports.py"
grep -q "f'nabídka {supplier}_{date_token}_{label}'" "$DIR/_runtime/post_baseline.py"
python - "$DIR/_runtime/v624_legacy_exports.py" "$DIR/_runtime/post_baseline.py" <<'PY'
import pathlib,sys
export=pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
baseline=pathlib.Path(sys.argv[2]).read_text(encoding='utf-8')
lev=export.split('def _export_leviat',1)[1].split('def _estimate_height',1)[0]
assert "_v(offer, 'reference')" in lev
assert "_v(offer, 'action_name'" not in lev
folder=baseline.split('def folder_for',1)[1].split('def attachment_name',1)[0]
assert "action_name or offer_no" in folder
assert "nabídka {supplier}_{date_token}_{label}" in folder
assert 'sha256' not in folder
PY

grep -q "rmtree(target/'_runtime'" "$DIR/crm_updater.pyw"

# --- Build ZIP and manifest ---
set -euo pipefail
DIR="$STAGE"
VER="$VERSION"
ZIP="ZakazkyApp_v${VER}.zip"
rm -f "$ZIP"
zip -qr "$ZIP" "$DIR" -x '*/__pycache__/*' '*.pyc'
SHA="$(sha256sum "$ZIP"|awk '{print $1}')"
python - "$VER" "$ZIP" "$SHA" <<'PY'
import json,sys,pathlib
version,filename,sha=sys.argv[1:]
notes_path=pathlib.Path('release_notes.txt')
notes=notes_path.read_text(encoding='utf-8').strip() if notes_path.exists() else ''
pathlib.Path('latest.json').write_text(
    json.dumps({'version':version,'file':filename,'sha256':sha,'notes':notes},ensure_ascii=False,indent=2)+'\n',
    encoding='utf-8',
)
PY

# --- Publish package ---
set -euo pipefail
VER="$VERSION"
ZIP="ZakazkyApp_v${VER}.zip"
git config user.name "TURTO Update Bot"
git config user.email "actions@users.noreply.github.com"
git add -f "$ZIP" latest.json
git commit -m "Publish ZakazkyApp v${VER} update"
for try in 1 2 3; do
  git pull --rebase origin main && git push origin HEAD:main && exit 0
  sleep $((try*2))
done
exit 1
