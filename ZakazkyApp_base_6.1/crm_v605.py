# TURTO CRM v6.0.5 compatibility marker
#
# TURTO CRM 8.0.4 retired the runtime work historically installed here:
# - action status auditing is owned by v611_audit,
# - temporary sort reset/navigation is owned by v628 + lazy_refresh,
# - recipient_usage schema/contact ranking is owned by v608_stability,
# - MIVO warning/tag rules are owned by v608_stability,
# - status_late colors + Calibri bold font are owned together by
#   v628_modernui_resize.
#
# Keep the module/apply entry point so the explicit historical bootstrap remains
# stable, but do not install another wrapper/callback/database pass.


def apply(module):
    module._turto_v605_retired_804 = True
