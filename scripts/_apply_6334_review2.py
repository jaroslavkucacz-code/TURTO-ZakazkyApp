from pathlib import Path

source = Path(__file__).with_name("_apply_6334_review.py")
text = source.read_text(encoding="utf-8")
old = r'f"Synchronizaci se nepodařilo dokončit:\n{exc}"'
new = r'f"Synchronizaci se nepodařilo dokončit:\\n{exc}"'
if old not in text:
    raise SystemExit("Expected escaped error message was not found")
text = text.replace(old, new, 1)
namespace = {"__name__": "__main__", "__file__": str(source)}
exec(compile(text, str(source), "exec"), namespace)
