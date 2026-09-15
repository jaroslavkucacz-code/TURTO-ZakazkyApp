"""Release checks exercise Tk button events, rendered series and page integration."""
import json
import os
import tempfile
import tkinter as tk
from pathlib import Path

from .charts import BusinessChart, ShareChart


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _click(root,button):
    """Dispatch the real Tk mouse binding, not the command implementation."""
    assert str(button.cget('state')) != 'disabled',button.cget('text')
    root.update_idletasks();root.update()
    x=max(1,button.winfo_width()//2);y=max(1,button.winfo_height()//2)
    button.event_generate('<Enter>',x=x,y=y)
    button.event_generate('<Motion>',x=x,y=y)
    button.event_generate('<ButtonPress-1>',x=x,y=y)
    button.event_generate('<ButtonRelease-1>',x=x,y=y)
    root.update_idletasks();root.update()


def _signature(chart):
    c=chart.canvas
    return [(c.type(i),c.coords(i),c.itemcget(i,'fill')) for i in c.find_withtag('series') or c.find_withtag('segment')]


def run_chart_check(capture=None,output=None):
    output=Path(output) if output else None
    if output:output.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[]
    root=tk.Tk();root.title('TURTO – kontrola grafů');root.geometry('960x740+0+0');root.configure(bg='#172033')
    root.report_callback_exception=lambda *args:errors.append(str(args))
    def snap(name):
        if capture and output:capture(root,output/(name+'.png'))
    try:
        data=[{'label':'Led','period':'2026-01','revenue':1200,'profit':200,'margin':200/12,'profit_complete':True},
              {'label':'Úno','period':'2026-02','revenue':2500,'profit':-400,'margin':-16,'profit_complete':True},
              {'label':'Bře','period':'2026-03','revenue':1800,'profit':600,'margin':600/18,'profit_complete':True},
              {'label':'Dub','period':'2026-04','revenue':None,'profit':None,'margin':None,'profit_complete':False}]
        selected=[];periods=[]
        chart=BusinessChart(root,data,on_state_change=selected.append,on_period_click=periods.append)
        chart.pack(fill='both',expand=True,padx=15,pady=15);root.update()
        signatures=[]
        for key,_ in chart.VIEWS:
            _click(root,chart.view_buttons[key]);assert chart.view==key
            signatures.append(_signature(chart));snap('monthly-'+key)
        assert len({repr(x) for x in signatures})==3,'Chart types render identically'
        for key in chart._buttons:
            before=chart._enabled[key];_click(root,chart._buttons[key])
            assert chart._enabled[key] is not before
            assert not chart.canvas.find_withtag(key)
        assert not any(chart._enabled.values())
        assert 'Vyberte' in chart.status.cget('text')
        _click(root,chart._buttons['margin']);assert chart._enabled['margin']
        assert chart.canvas.find_withtag('margin');assert not chart.canvas.find_withtag('revenue')
        _click(root,chart.view_buttons['bars'])
        assert all(chart.canvas.type(i)=='rectangle' for i in chart.canvas.find_withtag('margin'))
        l,t,r,b=chart._plot_bounds
        chart.canvas.event_generate('<Button-1>',x=int(chart._centers[1]),y=int((t+b)/2));root.update()
        assert periods[-1]['period']=='2026-02'
        saved=chart.state();chart.destroy()
        chart=BusinessChart(root,data,preferences=saved);chart.pack(fill='both',expand=True);root.update()
        assert chart.state()==saved
        chart.destroy();checks.append('Monthly types, every series toggle including last, signed axes, period click and saved state')

        chart=BusinessChart(root,[{'label':'Srpen','revenue':0,'profit':50,'profit_available':False,'margin':20,'profit_complete':False}])
        chart.pack(fill='both',expand=True);root.update()
        assert chart._available=={'revenue':True,'profit':False,'margin':False}
        assert str(chart._buttons['profit'].cget('state'))=='disabled'
        assert str(chart._buttons['margin'].cget('state'))=='disabled'
        assert 'Bez podkladů' in chart.status.cget('text');snap('monthly-missing-data');chart.destroy()
        checks.append('Zero is valid; missing profit and incomplete margin are disabled and explained')

        rows=[{'label':label,'profit':profit,'revenue':rev,'count':count}
              for label,profit,rev,count in [('Milan',200,1300,3),('Jirka',450,1600,4),('Honza',100,1400,7),('Nezařazené',0,0,0)]]
        metrics=(('profit','Zisk','money'),('revenue','Obrat','money'),('count','Počet DL','count'))
        clicked=[];chart=ShareChart(root,rows,metrics=metrics,initial_metric='profit',on_item_click=clicked.append)
        chart.pack(fill='both',expand=True,padx=15,pady=15);root.update()
        signatures=[]
        for key,_ in chart.VIEWS:
            _click(root,chart.view_buttons[key]);assert chart.view==key
            signatures.append(_signature(chart));snap('share-'+key)
            for metric,_,_ in metrics:
                _click(root,chart.metric_buttons[metric]);assert chart.metric==metric
                assert chart.canvas.find_withtag('segment')
            _click(root,chart.metric_buttons['profit'])
        assert len({repr(x) for x in signatures})==3,'Share views render identically'
        x0,y0,x1,y1,item,total=chart._hit_regions[0]
        chart.canvas.event_generate('<Button-1>',x=int((x0+x1)/2),y=int((y0+y1)/2));root.update()
        assert clicked[-1]['label']==item['label']
        _click(root,chart.view_buttons['shares']);root.geometry('490x740+0+0');root.update()
        assert chart.view=='shares' and chart.canvas.find_withtag('donut'),'Ring disappeared at narrow width'
        for b in [*chart.metric_buttons.values(),*chart.view_buttons.values()]:
            assert b.winfo_x()+b.winfo_width()<=b.master.winfo_width()+2,('clipped button',b.cget('text'))
        snap('share-narrow');chart.destroy();root.geometry('960x740+0+0');root.update()
        checks.append('All three metrics and views, legend click and ring on a narrow panel')

        for kind,modified in [('negative',[dict(rows[0],profit=-20),rows[1]]),
                              ('zero',[dict(rows[0],profit=0),dict(rows[1],profit=0)]),
                              ('missing',[dict(rows[0],profit=None,revenue=None),dict(rows[1],profit=None,revenue=None)])]:
            chart=ShareChart(root,modified,metrics=metrics,initial_metric='profit')
            chart.pack(fill='both',expand=True,padx=15,pady=15);root.update()
            if kind=='missing':
                assert chart.metric=='count';assert str(chart.metric_buttons['profit'].cget('state'))=='disabled'
                assert 'Bez podkladů' in chart.status.cget('text')
            else:
                assert chart.view=='compare';assert str(chart.view_buttons['shares'].cget('state'))=='disabled'
                assert str(chart.view_buttons['stacked'].cget('state'))=='disabled'
                before=chart.state();chart.view_buttons['shares'].invoke();assert chart.state()==before
                _click(root,chart.metric_buttons['revenue']);assert str(chart.view_buttons['shares'].cget('state'))=='normal'
                _click(root,chart.view_buttons['shares']);assert chart.canvas.find_withtag('donut')
                _click(root,chart.metric_buttons['profit']);assert chart.view=='compare'
            snap('share-'+kind);chart.destroy()
        chart=ShareChart(root,[],metrics=metrics,initial_metric='profit');chart.pack(fill='both',expand=True);root.update()
        assert all(str(b.cget('state'))=='disabled' for b in [*chart.metric_buttons.values(),*chart.view_buttons.values()]);chart.destroy()
        checks.append('Negative totals, zero totals, missing metrics, automatic fallback and completely empty data')
        assert not errors,errors
    finally:root.destroy()

    from .runtime_check import seed
    from .ui import App
    from .config import load_config
    with tempfile.TemporaryDirectory(prefix='turto_charts_') as tmp:
        rootpath=Path(tmp);seed(rootpath)
        previous=os.environ.get('TURTO_REPORTING_DATA_ROOT');os.environ['TURTO_REPORTING_DATA_ROOT']=str(rootpath)
        original=App._auto_check_updates;App._auto_check_updates=lambda self:None
        app=None
        try:
            app=App();app.state('normal');app.geometry('1000x740+0+0');app.period_var.set('2026-08')
            app.report_callback_exception=lambda *args:errors.append(str(args))
            for page in ['Přehled','Obrat & marže','Obchodníci','Zákazníci','Produkty']:
                app.show_page(page);app.update()
                charts=[x for x in _descendants(app.container) if isinstance(x,(BusinessChart,ShareChart))]
                assert charts,('No charts on page',page)
                for chart in charts:
                    metric_buttons=chart._buttons if isinstance(chart,BusinessChart) else chart.metric_buttons
                    for key,button in metric_buttons.items():
                        if str(button.cget('state'))=='disabled':continue
                        before=chart._enabled[key] if isinstance(chart,BusinessChart) else None
                        _click(app,button)
                        if isinstance(chart,BusinessChart):
                            assert chart._enabled[key] is not before;_click(app,button)
                        else:assert chart.metric==key
                    for key,button in chart.view_buttons.items():
                        if str(button.cget('state'))=='disabled':continue
                        _click(app,button);assert chart.view==key
                assert not errors,(page,errors)
                checks.append('Every available button on page '+page)
                if capture and output:capture(app,output/('page-'+str(len(checks))+'.png'))
            app.open_customer_detail('Testovací zákazník 01 – modelová stavební společnost');app.update()
            dialogs=[x for x in app.winfo_children() if isinstance(x,tk.Toplevel)];assert dialogs
            history=next(x for x in _descendants(dialogs[-1]) if isinstance(x,BusinessChart))
            for key,button in history.view_buttons.items():
                _click(app,button);assert history.view==key
            for key,button in history._buttons.items():
                if str(button.cget('state'))!='disabled':
                    before=history._enabled[key];_click(app,button);assert history._enabled[key] is not before
            dialogs[-1].destroy()
            chartprefs=load_config()['chart_preferences'];assert chartprefs['products']['view']=='stacked'
            app.destroy();app=None
            app=App();app.state('normal');app.geometry('1000x740+0+0');app.period_var.set('2026-08');app.show_page('Produkty');app.update()
            product=next(x for x in _descendants(app.container) if isinstance(x,ShareChart))
            assert product.state()==chartprefs['products'],'Preferences not restored after app restart'
            assert app.db.scalar('SELECT count(*) FROM delivery_notes')==60
            checks.append('Customer detail buttons, restored chart preferences after app restart, data unchanged')
            assert not errors,errors
        finally:
            if app is not None:app.destroy()
            App._auto_check_updates=original
            if previous is None:os.environ.pop('TURTO_REPORTING_DATA_ROOT',None)
            else:os.environ['TURTO_REPORTING_DATA_ROOT']=previous
    if output:(output/'chart-checks.json').write_text(json.dumps({'result':'PASS','checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
    print('TURTO_CHART_CHECKS_OK',len(checks))
    return 0
