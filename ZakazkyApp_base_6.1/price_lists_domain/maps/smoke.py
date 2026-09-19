"""Exercise the installed map host and PROJ payload without touching CRM rows."""
import time
from .bridge import Bridge


def check(M):
    from pyproj import Transformer
    lon,lat=Transformer.from_crs('EPSG:5514','EPSG:4326',always_xy=True).transform(-742000,-1043000)
    if not (50<lat<50.2 and 14.3<lon<14.6):
        raise RuntimeError('Installed PROJ coordinate database is unavailable.')
    root=M.tk.Tk(); root.geometry('700x450+0+0')
    frame=M.tk.Frame(root); frame.pack(fill='both',expand=True)
    events=[]; bridge=None
    try:
        root.update()
        bridge=Bridge(frame,events.append)
        sent=False; deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            root.update(); time.sleep(.025)
            if any(e.get('type')=='ready' for e in events) and not sent:
                bridge.send({'type':'data','data':{'type':'FeatureCollection','features':[]}}); sent=True
            if any(e.get('type')=='data-applied' for e in events): break
        if not any(e.get('type')=='embedded' for e in events):
            raise RuntimeError('Installed map host was not embedded in Tk: '+str(events))
        if not any(e.get('type')=='data-applied' for e in events):
            raise RuntimeError('Installed map JavaScript bridge failed: '+str(events))
        return ['WebView2 embedded in Tk','bundled MapLibre JSON bridge','bundled PROJ S-JTSK conversion']
    finally:
        if bridge: bridge.close()
        root.destroy()
