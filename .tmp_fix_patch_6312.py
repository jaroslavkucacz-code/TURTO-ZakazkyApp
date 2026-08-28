from pathlib import Path

p = Path('.tmp_tableownership_6312.py')
src = p.read_text(encoding='utf-8')
marker = '# v637: data model/detail only, no main-table refresh wrappers.'
base = src.index(marker)
start = src.index("section_start = s.index(", base)
end_token = "p.write_text(s, encoding='utf-8')"
end = src.index(end_token, start) + len(end_token)
replacement = '''pattern = (
    r"\\n    # ------------------------------------------------------------------\\n"
    r"    # ACTIONS\\(projects\\) MAIN TABLE: show offers here, remove from Opportunities\\.\\n"
    r"    # ------------------------------------------------------------------\\n"
    r".*?"
    r"(?=\\n    # ------------------------------------------------------------------\\n"
    r"    # REAL ACTION DETAIL \\(ProjectDialog\\): related offers\\.\\n)"
)
main_table_note = '''\\n    # ------------------------------------------------------------------
    # MAIN TABLE OWNERSHIP
    # Columns and offer counts are finalized by post_baseline via v638 contract.
    # This module owns only the offer-link data model and related detail UI.
    # ------------------------------------------------------------------
'''
s, count = re.subn(pattern, main_table_note, s, count=1, flags=re.S)
if count != 1:
    raise SystemExit('v637 main-table wrapper section not found')
p.write_text(s, encoding='utf-8')'''
src = src[:start] + replacement + src[end:]
p.write_text(src, encoding='utf-8')
