# TURTO CRM 6.0.13 incremental features
# Process-oriented branched help kept current with actual CRM behavior.
import datetime

def apply(M):
    # Legacy warning wrappers stay in place; the final stability layer applies current thresholds.
    old_mivo=M.App.refresh_mivo_requests
    def mivo(self):
        return old_mivo(self)
    M.App.refresh_mivo_requests=mivo

    old_req=M.App.refresh_requests
    def requests(self):
        return old_req(self)
    M.App.refresh_requests=requests

    # Legacy help composition removed in 8.0; professional_workflow owns help.
