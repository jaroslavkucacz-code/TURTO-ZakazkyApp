from __future__ import annotations

from calendar import monthrange
from datetime import date

from .constants import CENTER_NAMES, PRIMARY_CENTERS

MONTH_NAMES = ['Leden','Únor','Březen','Duben','Květen','Červen','Červenec','Srpen','Září','Říjen','Listopad','Prosinec']
MONTH_SHORT_NAMES = ['Led','Úno','Bře','Dub','Kvě','Čvn','Čvc','Srp','Zář','Říj','Lis','Pro']


def period_bounds(year: int, month: int, mode='month'):
    if mode == 'year':
        return date(year, 1, 1), date(year, 12, 31)
    if mode == 'ytd':
        return date(year, 1, 1), date(year, month, monthrange(year, month)[1])
    if mode == 'rolling12':
        end = date(year, month, monthrange(year, month)[1])
        y, m = year, month
        for _ in range(11):
            m -= 1
            if m == 0:
                m, y = 12, y - 1
        return date(y, m, 1), end
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _next_month(d: date) -> date:
    return date(d.year + (1 if d.month == 12 else 0), 1 if d.month == 12 else d.month + 1, 1)


class Analytics:
    def __init__(self, db, center_provider=None):
        self.db = db
        self.center_provider = center_provider

    def center_mapping(self):
        from .center_reporting import Mapping
        return Mapping(self.center_provider() if self.center_provider else None)

    def center_display(self,code,day):
        return self.center_mapping().display(code,day)

    def _where(self, year, month, mode='month'):
        start, end = period_bounds(year, month, mode)
        return start.isoformat(), end.isoformat()

    def _other_sql(self,alias=''):
        return self.center_mapping().other_sql(alias)

    def _raw_profit_exists(self, year: int, month: int) -> bool:
        start, end = period_bounds(year, month, 'month')
        n = self.db.scalar(
            '''SELECT COUNT(*) FROM profit_documents p
               JOIN delivery_notes d ON d.doc_no=p.doc_no
               WHERE d.doc_date BETWEEN ? AND ?''',
            (start.isoformat(), end.isoformat())
        ) or 0
        return int(n) > 0

    def _raw_profit_month(self, year: int, month: int, center: str | None = None) -> float:
        start, end = period_bounds(year, month, 'month')
        params = [start.isoformat(), end.isoformat()]
        extra = ''
        if center and center != 'OTHER':
            extra = ' AND d.center=?'
            params.append(center)
        elif center == 'OTHER':
            extra = f' AND {self._other_sql("d")}'
        return float(self.db.scalar(
            f'''SELECT COALESCE(SUM(p.profit_total),0) FROM profit_documents p
                JOIN delivery_notes d ON d.doc_no=p.doc_no
                WHERE d.doc_date BETWEEN ? AND ? {extra}''', params
        ) or 0)

    def _legacy_profit_month(self, year: int, month: int, center: str | None = None) -> float:
        if center == 'OTHER':
            from .center_reporting import legacy_allocation
            return sum(value for owner,value in legacy_allocation(self,self.center_mapping(),year,month) if owner is None)
        period = f'{year:04d}-{month:02d}'
        row = self.db.query(
            '''SELECT profit_total,profit_m,profit_j,profit_h,profit_other
               FROM monthly_summary WHERE period=?''', (period,)
        )
        if not row:
            return 0.0
        r = row[0]
        if center == 'M': return float(r['profit_m'] or 0)
        if center == 'J': return float(r['profit_j'] or 0)
        if center == 'H': return float(r['profit_h'] or 0)
        total = float(r['profit_total'] or 0)
        if center == 'OTHER':
            explicit = float(r['profit_other'] or 0)
            residual = total - float(r['profit_m'] or 0) - float(r['profit_j'] or 0) - float(r['profit_h'] or 0)
            # Older sheets often left profit_other blank/zero although the total
            # contains a small unassigned remainder. Preserve that remainder.
            return explicit if abs(explicit) > 1e-9 else residual
        return total

    def _profit_for_period(self, year, month, mode='month', center: str | None = None):
        start, end = period_bounds(year, month, mode)
        cursor = start.replace(day=1)
        total = 0.0
        while cursor <= end:
            if self._raw_profit_exists(cursor.year, cursor.month):
                total += self._raw_profit_month(cursor.year, cursor.month, center)
            else:
                total += self._legacy_profit_month(cursor.year, cursor.month, center)
            cursor = _next_month(cursor)
        return total

    def kpis(self, year, month, mode='month'):
        start, end = self._where(year, month, mode)
        row = self.db.query(
            '''SELECT COALESCE(SUM(base_amount),0) revenue, COUNT(*) cnt
               FROM delivery_notes WHERE doc_date BETWEEN ? AND ?''', (start, end)
        )[0]
        revenue, count = float(row['revenue'] or 0), int(row['cnt'] or 0)
        profit = self._profit_for_period(year, month, mode)
        margin = profit / revenue * 100 if revenue else 0
        avg = revenue / count if count else 0
        overhead = float(self.db.scalar(
            '''SELECT COALESCE(SUM(total_amount),0) FROM overhead_docs
               WHERE doc_date BETWEEN ? AND ?''', (start, end)
        ) or 0)
        unassigned = self.db.query(
            f'''SELECT COALESCE(SUM(base_amount),0) revenue, COUNT(*) cnt
                FROM delivery_notes WHERE doc_date BETWEEN ? AND ? AND {self._other_sql()}''', (start, end)
        )[0]
        yoy = self._yoy_revenue(year, month, mode, revenue)
        return {
            'revenue': revenue, 'profit': profit, 'margin': margin, 'count': count,
            'avg_order': avg, 'overhead': overhead, 'yoy': yoy,
            'unassigned_count': int(unassigned['cnt'] or 0),
            'unassigned_revenue': float(unassigned['revenue'] or 0),
            'unassigned_profit': self._profit_for_period(year, month, mode, 'OTHER'),
        }

    def _yoy_revenue(self, year, month, mode, current):
        if year <= 1900:
            return 0
        start, end = self._where(year - 1, month, mode)
        prev = float(self.db.scalar(
            '''SELECT COALESCE(SUM(base_amount),0) FROM delivery_notes
               WHERE doc_date BETWEEN ? AND ?''', (start, end)
        ) or 0)
        return ((current / prev) - 1) * 100 if prev else 0

    def monthly_trend(self, year):
        out = []
        for m in range(1, 13):
            start, end = self._where(year, m, 'month')
            row = self.db.query(
                '''SELECT COALESCE(SUM(base_amount),0) revenue, COUNT(*) cnt
                   FROM delivery_notes WHERE doc_date BETWEEN ? AND ?''', (start, end)
            )[0]
            rev = float(row['revenue'] or 0)
            count = int(row['cnt'] or 0)
            profit = float(self._profit_for_period(year, m, 'month'))
            margin = profit / rev * 100 if rev else 0.0
            out.append({
                'month': m,
                'label': MONTH_SHORT_NAMES[m-1],
                'full_label': f'{MONTH_NAMES[m-1]} {year}',
                'revenue': rev,
                'profit': profit,
                'margin': margin,
                'count': count,
                'has_data': count > 0 or abs(rev) > 1e-9 or abs(profit) > 1e-9,
            })
        return out

    def salespeople(self, year, month, mode='month'):
        from .center_reporting import salespeople
        return salespeople(self,year,month,mode)

    def top_customers(self, year, month, mode='month', limit=10):
        start, end = self._where(year, month, mode)
        rows = [dict(r) for r in self.db.query(
            '''SELECT d.customer,
                      SUM(d.base_amount) revenue,
                      COALESCE(SUM(p.profit_total),0) profit,
                      COUNT(DISTINCT d.doc_no) count,
                      COUNT(DISTINCT p.doc_no) profit_docs,
                      COALESCE(SUM(CASE WHEN p.doc_no IS NOT NULL THEN d.base_amount ELSE 0 END),0) profit_revenue
               FROM delivery_notes d LEFT JOIN profit_documents p ON p.doc_no=d.doc_no
               WHERE d.doc_date BETWEEN ? AND ? AND TRIM(d.customer)<>''
               GROUP BY d.customer ORDER BY revenue DESC LIMIT ?''',
            (start, end, limit)
        )]
        for x in rows:
            x['revenue']=float(x.get('revenue') or 0)
            x['profit']=float(x.get('profit') or 0)
            x['count']=int(x.get('count') or 0)
            x['profit_docs']=int(x.get('profit_docs') or 0)
            x['profit_revenue']=float(x.get('profit_revenue') or 0)
            x['profit_available']=x['profit_docs']>0
            x['profit_complete']=x['count']>0 and x['profit_docs']>=x['count']
            x['margin']=(x['profit']/x['profit_revenue']*100) if x['profit_available'] and x['profit_revenue'] else None
        return rows

    def customer_history(self, customer):
        """Monthly history for one customer.

        Revenue and delivery-note counts come from DATA POHODA for all available
        months. Profit is deliberately exposed only for months where a raw
        Zisk (zásoby) report is actually linked to that customer's documents;
        older monthly summary profit cannot be safely allocated to customers.
        """
        rows = self.db.query(
            '''SELECT substr(d.doc_date,1,7) period,
                      COALESCE(SUM(d.base_amount),0) revenue,
                      COUNT(DISTINCT d.doc_no) count,
                      COALESCE(SUM(p.profit_total),0) profit,
                      COUNT(DISTINCT p.doc_no) profit_docs,
                      COALESCE(SUM(CASE WHEN p.doc_no IS NOT NULL THEN d.base_amount ELSE 0 END),0) profit_revenue,
                      MAX(d.doc_date) last_date
               FROM delivery_notes d
               LEFT JOIN profit_documents p ON p.doc_no=d.doc_no
               WHERE d.customer=? AND d.doc_date>='2000-01-01'
               GROUP BY substr(d.doc_date,1,7)
               ORDER BY period''',
            (customer,)
        )
        out=[]
        for r in rows:
            item=dict(r)
            item['revenue']=float(item.get('revenue') or 0)
            item['profit']=float(item.get('profit') or 0)
            item['count']=int(item.get('count') or 0)
            item['profit_docs']=int(item.get('profit_docs') or 0)
            item['profit_revenue']=float(item.get('profit_revenue') or 0)
            item['profit_available']=item['profit_docs']>0
            item['profit_complete']=item['count']>0 and item['profit_docs']>=item['count']
            item['margin']=(item['profit']/item['profit_revenue']*100) if item['profit_available'] and item['profit_revenue'] else None
            out.append(item)
        return out

    def top_documents(self, year, month, mode='month', center=None, limit=20):
        start, end = self._where(year, month, mode)
        params = [start, end]
        extra = ''
        if center and center != 'OTHER':
            extra = ' AND d.center=?'
            params.append(center)
        elif center == 'OTHER':
            extra = f' AND {self._other_sql("d")}'
        params.append(limit)
        return [dict(r) for r in self.db.query(
            f'''SELECT d.doc_no,d.doc_date,d.customer,d.project,d.center,d.base_amount,
                       COALESCE(p.profit_total,0) profit,
                       CASE WHEN d.base_amount<>0 THEN COALESCE(p.profit_total,0)/d.base_amount*100 ELSE 0 END margin
                FROM delivery_notes d LEFT JOIN profit_documents p ON p.doc_no=d.doc_no
                WHERE d.doc_date BETWEEN ? AND ? {extra}
                ORDER BY d.base_amount DESC LIMIT ?''', params
        )]

    def document_detail(self, doc_no):
        """Detail dodacího listu včetně dostupných položkových dat.

        Cenové a maržové sloupce jsou nullable; budoucí bohatší export z POHODY je
        může naplnit bez změny rozhraní nebo databázového modelu.
        """
        rows = self.db.query(
            '''SELECT d.doc_no,d.doc_date,d.customer,d.description,d.center,d.project,d.note,
                      d.base_amount,d.total_amount,COALESCE(p.profit_total,0) profit_total,
                      CASE WHEN d.base_amount<>0 AND p.doc_no IS NOT NULL
                           THEN p.profit_total/d.base_amount*100 ELSE NULL END margin_percent,
                      CASE WHEN p.doc_no IS NOT NULL THEN 1 ELSE 0 END profit_available
               FROM delivery_notes d LEFT JOIN profit_documents p ON p.doc_no=d.doc_no
               WHERE d.doc_no=?''', (doc_no,)
        )
        if not rows:
            return None
        items=[dict(r) for r in self.db.query(
            '''SELECT id,doc_no,code,name,item_text,quantity,profit_unit,profit_total,
                      sales_unit,sales_total,cost_unit,cost_total,margin_amount,margin_percent
               FROM profit_items WHERE doc_no=? ORDER BY id''', (doc_no,)
        )]
        out=dict(rows[0]); out['items']=items
        return out

    def products(self, year, month, limit=100, mode='month'):
        start, end = self._where(year, month, mode)
        rows = [dict(r) for r in self.db.query(
            '''SELECT i.code, i.name,
                      COALESCE(SUM(i.quantity),0) quantity,
                      COALESCE(SUM(i.profit_total),0) profit,
                      COUNT(DISTINCT i.doc_no) documents,
                      SUM(CASE WHEN i.sales_total IS NOT NULL THEN i.sales_total ELSE 0 END) sales,
                      SUM(CASE WHEN i.cost_total IS NOT NULL THEN i.cost_total ELSE 0 END) cost,
                      SUM(CASE WHEN i.sales_total IS NOT NULL THEN 1 ELSE 0 END) sales_rows
               FROM profit_items i JOIN delivery_notes d ON d.doc_no=i.doc_no
               WHERE d.doc_date BETWEEN ? AND ?
               GROUP BY i.code,i.name ORDER BY profit DESC LIMIT ?''', (start, end, limit)
        )]
        for x in rows:
            x['quantity']=float(x.get('quantity') or 0)
            x['profit']=float(x.get('profit') or 0)
            x['documents']=int(x.get('documents') or 0)
            x['sales_rows']=int(x.get('sales_rows') or 0)
            x['sales']=float(x.get('sales') or 0) if x['sales_rows'] else None
            x['cost']=float(x.get('cost') or 0) if x['sales_rows'] else None
            x['margin']=(x['profit']/x['sales']*100) if x['sales'] not in (None,0) else None
        return rows

    def item_data_coverage(self, year, month, mode='month'):
        start, end = self._where(year, month, mode)
        doc_count=int(self.db.scalar('''SELECT COUNT(DISTINCT d.doc_no) FROM delivery_notes d
             JOIN profit_items i ON i.doc_no=d.doc_no WHERE d.doc_date BETWEEN ? AND ?''',(start,end)) or 0)
        total_docs=int(self.db.scalar('''SELECT COUNT(*) FROM delivery_notes WHERE doc_date BETWEEN ? AND ?''',(start,end)) or 0)
        sales_rows=int(self.db.scalar('''SELECT COUNT(*) FROM profit_items i JOIN delivery_notes d ON d.doc_no=i.doc_no
             WHERE d.doc_date BETWEEN ? AND ? AND i.sales_total IS NOT NULL''',(start,end)) or 0)
        return {'item_docs':doc_count,'total_docs':total_docs,'sales_available':sales_rows>0}

    def overheads(self, year, month, mode='month'):
        start, end = self._where(year, month, mode)
        mapping=self.center_mapping();groups={}
        for row in self.db.query('''SELECT center,doc_date,SUM(total_amount) amount,COUNT(*) count FROM overhead_docs
                WHERE doc_date BETWEEN ? AND ? GROUP BY center,doc_date''',(start,end)):
            name=mapping.display(row['center'],row['doc_date']);key=(row['center'],name)
            item=groups.setdefault(key,dict(center=row['center'],name=name,amount=0.,count=0))
            item['amount']+=float(row['amount'] or 0);item['count']+=row['count']
        return sorted(groups.values(),key=lambda r:r['amount'],reverse=True)

    def available_periods(self):
        rows = self.db.query("SELECT DISTINCT substr(doc_date,1,7) period FROM delivery_notes WHERE doc_date>='2000-01-01' ORDER BY period DESC")
        return [r['period'] for r in rows]
