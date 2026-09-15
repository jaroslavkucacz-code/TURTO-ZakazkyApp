import sys,time
from pathlib import Path
from PIL import ImageGrab
stage=Path(sys.argv[1]);output=Path(sys.argv[2])
sys.path.insert(0,str(stage))
from src.chart_check import run_chart_check
def capture(app,path):
    app.update_idletasks();app.update();time.sleep(0.12)
    ImageGrab.grab().save(path)
raise SystemExit(run_chart_check(capture,output))
