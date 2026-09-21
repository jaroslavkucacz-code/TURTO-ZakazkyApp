"""Resolve imported center codes using ownership effective on each document date."""
from calendar import monthrange
from datetime import date
from .constants import CENTER_NAMES


class Mapping:
    def __init__(self, rows=None):
        self.rows=list(rows) if rows is not None else [dict(center=c,salesperson_id=c,name=n,valid_from='0001-01-01',valid_to=None) for c,n in CENTER_NAMES.items()]

    def owner(self, code, day):
        code=str(code or '').strip().upper();day=str(day or '')
        return next((r for r in self.rows if r['center']==code and r['valid_from']<=day
                     and (not r['valid_to'] or day<r['valid_to']) and r['salesperson_id'] is not None),None)

    def display(self,code,day):
        row=self.owner(code,day)
        return f"{row['name']} · {row['center']}" if row else ('Nezařazené'+(f' ({code})' if code else ''))

    def other_sql(self, alias=''):
        p=alias+'.' if alias else ''
        quote=lambda x:"'"+str(x).replace("'","''")+"'"
        terms=[f"(upper(trim(coalesce({p}center,'')))={quote(r['center'])} AND {p}doc_date>={quote(r['valid_from'])}"
               +(f" AND {p}doc_date<{quote(r['valid_to'])}" if r['valid_to'] else '')+')'
               for r in self.rows if r['salesperson_id'] is not None]
        return 'NOT ('+(' OR '.join(terms) if terms else '0')+')'

    def legacy_owner(self,code,year,month):
        start=f'{year:04d}-{month:02d}-01';end=f'{year:04d}-{month:02d}-{monthrange(year,month)[1]:02d}'
        points={start,end}
        for r in self.rows:
            if r['center']!=code:continue
            points.update(x for x in (r['valid_from'],r['valid_to']) if x and start<=x<=end)
        owners=[self.owner(code,day) for day in points]
        ids={r['salesperson_id'] if r else None for r in owners}
        return owners[0] if len(ids)==1 else None


def legacy_allocation(analytics,mapping,year,month):
    rows=analytics.db.query('SELECT * FROM monthly_summary WHERE period=?',(f'{year:04d}-{month:02d}',))
    if not rows:return []
    r=dict(rows[0]);total=float(r['profit_total'] or 0)
    by_code={c:float(r['profit_'+c.lower()] or 0) for c in ('J','H','M')}
    explicit=float(r['profit_other'] or 0)
    result=[(mapping.legacy_owner(c,year,month),value) for c,value in by_code.items()]
    result.append((None,explicit if abs(explicit)>1e-9 else total-sum(by_code.values())))
    return result


def salespeople(analytics,year,month,mode):
    start,end=analytics._where(year,month,mode);mapping=analytics.center_mapping()
    groups={}
    def bucket(owner):
        sid=owner['salesperson_id'] if owner else 'OTHER'
        if sid not in groups:
            groups[sid]=dict(code=sid if isinstance(sid,str) else f'S{sid}',name=owner['name'] if owner else 'Nezařazené',
                            revenue=0.,profit=0.,count=0,centers=set())
        if owner:groups[sid]['centers'].add(owner['center'])
        return groups[sid]
    for r in mapping.rows:
        if r['salesperson_id'] is not None and r['valid_from']<=end and (not r['valid_to'] or r['valid_to']>start):bucket(r)
    bucket(None)
    raw_months=set()
    for r in analytics.db.query('''SELECT d.center,d.doc_date,SUM(d.base_amount) revenue,COUNT(*) count,
          SUM(coalesce(p.profit_total,0)) profit,COUNT(p.doc_no) profit_docs
          FROM delivery_notes d LEFT JOIN profit_documents p ON p.doc_no=d.doc_no
          WHERE d.doc_date BETWEEN ? AND ? GROUP BY d.center,d.doc_date''',(start,end)):
        group=bucket(mapping.owner(r['center'],r['doc_date']))
        group['revenue']+=float(r['revenue'] or 0);group['count']+=r['count'];group['profit']+=float(r['profit'] or 0)
        if r['profit_docs']:raw_months.add(r['doc_date'][:7])
    cursor=date.fromisoformat(start).replace(day=1);last=date.fromisoformat(end)
    while cursor<=last:
        if cursor.strftime('%Y-%m') not in raw_months:
            for owner,profit in legacy_allocation(analytics,mapping,cursor.year,cursor.month):bucket(owner)['profit']+=profit
        cursor=date(cursor.year+int(cursor.month==12),1 if cursor.month==12 else cursor.month+1,1)
    rows=list(groups.values());revenue=sum(r['revenue'] for r in rows);profit=sum(r['profit'] for r in rows)
    for r in rows:
        r.update(margin=r['profit']/r['revenue']*100 if r['revenue'] else 0,
                 avg_order=r['revenue']/r['count'] if r['count'] else 0,
                 share=r['revenue']/revenue*100 if revenue else 0,
                 profit_share=r['profit']/profit*100 if profit else 0,centers=', '.join(sorted(r['centers'])))
    return sorted(rows,key=lambda r:r['revenue'],reverse=True)
