"""Management views based on observed documents; missing data stays missing."""
from .analytics import period_bounds, _next_month


def coverage_rows(analytics, year, month, mode='month'):
    start, end = period_bounds(year, month, mode)
    rows = {r['period']: dict(r) for r in analytics.db.query('''
        SELECT substr(d.doc_date,1,7) period, COUNT(*) documents,
          SUM(CASE WHEN src.import_type='ZISK_ZASOBY' THEN 1 ELSE 0 END) missing_delivery,
          COUNT(p.doc_no) profit_documents,
          SUM(CASE WHEN TRIM(COALESCE(d.customer,''))='' THEN 1 ELSE 0 END) no_customer,
          SUM(CASE WHEN COALESCE(d.center,'') NOT IN ('M','J','H') THEN 1 ELSE 0 END) unassigned,
          MAX(d.doc_date) latest_date
        FROM delivery_notes d LEFT JOIN profit_documents p ON p.doc_no=d.doc_no
        LEFT JOIN imports src ON src.id=d.source_import_id
        WHERE d.doc_date BETWEEN ? AND ? GROUP BY period
        ''', (start.isoformat(), end.isoformat()))}
    legacy = {r['period'] for r in analytics.db.query(
        'SELECT period FROM monthly_summary WHERE period BETWEEN ? AND ?',
        (start.isoformat()[:7], end.isoformat()[:7]))}
    items = {r['period']: dict(r) for r in analytics.db.query('''
        SELECT substr(d.doc_date,1,7) period, COUNT(*) items, COUNT(i.sales_total) priced
        FROM profit_items i JOIN delivery_notes d ON d.doc_no=i.doc_no
        WHERE d.doc_date BETWEEN ? AND ? GROUP BY period
        ''', (start.isoformat(), end.isoformat()))}
    out = []
    cursor = start
    while cursor <= end:
        key = cursor.strftime('%Y-%m')
        r = dict(period=key, documents=0, missing_delivery=0, profit_documents=0,
                 no_customer=0, unassigned=0, latest_date=None, items=0, priced=0)
        r.update(rows.get(key, {})); r.update(items.get(key, {}))
        r['delivery_documents'] = r['documents'] - r['missing_delivery']
        n, p = r['documents'], r['profit_documents']
        r['coverage'] = 100*p/n if n else None
        r['profit_source'] = ('Položkový zisk' if p == n else 'Částečný zisk') if p else (
            'Historický souhrn' if key in legacy else 'Chybí zisk')
        issues = []
        if not n and key not in legacy: issues.append('Bez podkladů')
        elif not r['delivery_documents']: issues.append('Chybí export DL')
        if r['missing_delivery']: issues.append(f"Doplnit {r['missing_delivery']} DL")
        if n and p < n and (p or key not in legacy): issues.append(f'Doplnit zisk k {n-p} DL')
        if r['unassigned']: issues.append(f"Středisko: {r['unassigned']}")
        if r['no_customer']: issues.append(f"Zákazník: {r['no_customer']}")
        r['status'] = '; '.join(issues) or 'Podklady navázány'
        out.append(r); cursor = _next_month(cursor)
    return out


def monthly_comparison(analytics, year, month, mode='month'):
    # The month view gives the year to date, just like the main trend graph.
    start, end = period_bounds(year, month, 'ytd' if mode == 'month' else mode)
    current = {}; previous = {}
    for y in range(start.year, end.year+1):
        current.update((x['period'], x) for x in analytics.monthly_trend(y))
        previous.update((x['period'], x) for x in analytics.monthly_trend(y-1))
    delivery_coverage = {}
    for y in range(start.year-1, end.year+1):
        delivery_coverage.update((r['period'],r) for r in coverage_rows(analytics,y,12,'year'))
    out = []; cursor = start
    while cursor <= end:
        key = cursor.strftime('%Y-%m'); x = dict(current[key])
        prev = previous.get(f'{cursor.year-1}-{cursor.month:02d}', {})
        old, new = prev.get('revenue'), x['revenue']
        old_quality=delivery_coverage[f'{cursor.year-1}-{cursor.month:02d}']
        if not old_quality['delivery_documents'] or old_quality['missing_delivery']: old=None
        if not delivery_coverage[key]['delivery_documents']: new=x['revenue']=None
        x['previous_revenue'] = old
        x['change'] = new-old if new is not None and old is not None else None
        x['change_percent'] = x['change']/old*100 if old is not None and old > 0 and x['change'] is not None else None
        x['average'] = new/x['count'] if x['count'] and new is not None else None
        x['data_note'] = {'raw':'Položkový zisk', 'partial':'Zisk je částečný',
                          'legacy':'Historický zisk', 'missing':'Chybí zisk', 'empty':'Bez dat'}[x['source']]
        quality=delivery_coverage[key]
        if quality['missing_delivery']:
            x['data_note']='Chybí export DL'
            x['change']=x['change_percent']=x['average']=x['margin']=None
            if not quality['delivery_documents']: x['revenue']=None
        out.append(x); cursor = _next_month(cursor)
    return out


def customer_changes(analytics, year, month, mode='month'):
    start, end = analytics._where(year, month, mode)
    old_start, old_end = analytics._where(year-1, month, mode)
    def totals(a, b):
        return {r['customer']: dict(r) for r in analytics.db.query('''
            SELECT customer, SUM(base_amount) revenue, COUNT(*) documents
            FROM delivery_notes WHERE doc_date BETWEEN ? AND ?
            AND (source_import_id IS NULL OR source_import_id NOT IN (SELECT id FROM imports WHERE import_type='ZISK_ZASOBY'))
            AND TRIM(COALESCE(customer,''))<>'' GROUP BY customer''', (a,b))}
    current, previous = totals(start,end), totals(old_start,old_end)
    # Empty comparison periods are unknown, not zero activity for every customer.
    current_available = bool(analytics.db.scalar("SELECT COUNT(*) FROM delivery_notes WHERE doc_date BETWEEN ? AND ? AND (source_import_id IS NULL OR source_import_id NOT IN (SELECT id FROM imports WHERE import_type='ZISK_ZASOBY'))", (start,end)))
    previous_available = bool(analytics.db.scalar("SELECT COUNT(*) FROM delivery_notes WHERE doc_date BETWEEN ? AND ? AND (source_import_id IS NULL OR source_import_id NOT IN (SELECT id FROM imports WHERE import_type='ZISK_ZASOBY'))", (old_start,old_end)))
    first = {r['customer']: r['first_date'] for r in analytics.db.query(
        'SELECT customer, MIN(doc_date) first_date FROM delivery_notes GROUP BY customer')}
    out = []
    for name in current.keys() | previous.keys():
        a, b = current.get(name), previous.get(name)
        value = float(a['revenue']) if a else (0.0 if current_available else None)
        old = float(b['revenue']) if b else (0.0 if previous_available else None)
        change = value-old if value is not None and old is not None else None
        if not current_available or not previous_available: state = 'Chybí srovnávací podklady'
        elif not a: state = 'Bez odběru v období'
        elif not b: state = 'První evidovaný odběr' if first[name] >= start else 'Obnovený odběr'
        elif change > 0.005: state = 'Růst'
        elif change < -0.005: state = 'Pokles'
        else: state = 'Beze změny'
        out.append(dict(customer=name, revenue=value, previous_revenue=old, change=change,
                        change_percent=change/old*100 if old is not None and old > 0 and change is not None else None,
                        count=a['documents'] if a else 0, state=state, first_date=first[name]))
    out.sort(key=lambda r: abs(r['change'] or 0), reverse=True)
    return out


def project_results(analytics, year, month, mode='month'):
    a,b = analytics._where(year,month,mode)
    out = [dict(r) for r in analytics.db.query('''
        SELECT COALESCE(NULLIF(TRIM(d.project),''),'Bez zakázky') project,
          COUNT(*) documents, SUM(d.base_amount) revenue, SUM(p.profit_total) profit,
          COUNT(p.doc_no) profit_documents,
          SUM(CASE WHEN d.source_import_id IN (SELECT id FROM imports WHERE import_type='ZISK_ZASOBY') THEN 1 ELSE 0 END) missing_delivery,
          SUM(CASE WHEN p.doc_no IS NOT NULL THEN d.base_amount ELSE 0 END) matched_revenue
        FROM delivery_notes d LEFT JOIN profit_documents p ON p.doc_no=d.doc_no
        WHERE d.doc_date BETWEEN ? AND ? GROUP BY 1 ORDER BY revenue DESC''', (a,b))]
    for r in out:
        r['margin'] = r['profit']/r['revenue']*100 if r['documents'] == r['profit_documents'] and not r['missing_delivery'] and r['revenue'] > 0 else None
        if r['missing_delivery']==r['documents']: r['revenue']=None
        r['coverage'] = f"{r['profit_documents']} / {r['documents']}"
    return out


def collect_management(analytics, year, month, mode='month'):
    return dict(months=monthly_comparison(analytics,year,month,mode),
                customers=customer_changes(analytics,year,month,mode),
                projects=project_results(analytics,year,month,mode),
                coverage=coverage_rows(analytics,year,month,mode))
