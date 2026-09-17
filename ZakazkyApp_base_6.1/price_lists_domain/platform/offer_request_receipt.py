"""Assign a supplier offer and record receipt from its original source mail."""
from datetime import datetime
from email.utils import parsedate_to_datetime


def mail_date(value):
    """Keep the calendar date recorded by the mail, independent of the PC zone."""
    text = str(value or '').strip()
    if not text:
        return ''
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).date().isoformat()
    except ValueError:
        try:
            return parsedate_to_datetime(text).date().isoformat()
        except (ValueError, TypeError, OverflowError):
            return ''


def assign_to_request(con, offer_id, request_id, user_name=''):
    """Caller owns the transaction, including the link, receipt and history.

    The first dated mail among this request's offers is the first receipt.
    Never substitute the PDF's issue date, import date or today's date. An
    existing manually entered receipt is retained if no source mail is dated.
    Reassignment/unlinking does not erase the previous request's receipt.
    """
    if not con.in_transaction:
        con.execute('BEGIN IMMEDIATE')
    offer = con.execute('''SELECT request_id,project_id,action_id,offer_number
        FROM supplier_offers WHERE id=?''', (offer_id,)).fetchone()
    request = con.execute('''SELECT r.*,a.project_id FROM requests r
        LEFT JOIN actions a ON a.id=r.action_id WHERE r.id=?''', (request_id,)).fetchone()
    if not offer or not request:
        raise ValueError('Nabídka nebo poptávka již neexistuje. Obnovte přehled.')
    if request['archived']:
        raise ValueError('Archivovanou poptávku nejdříve obnovte.')

    project_id = request['project_id']
    link_changed = (offer['request_id'], offer['project_id'], offer['action_id']) != (
        request_id, project_id, None)
    if link_changed:
        con.execute('''UPDATE supplier_offers
            SET request_id=?,project_id=?,action_id=NULL WHERE id=?''',
            (request_id, project_id, offer_id))

    dates = [mail_date(row['sent_at']) for row in con.execute('''
        SELECT DISTINCT m.id,m.sent_at FROM supplier_offers o
        JOIN offer_source_attachments att ON att.offer_id=o.id
        JOIN offer_source_messages m ON m.id=att.message_id
        WHERE o.request_id=?''', (request_id,))]
    source_date = min((value for value in dates if value), default='')
    received = source_date or mail_date(request['received_date'])
    receipt_changed = bool(received) and (
        request['received_date'] != received or bool(request['no_response']))
    if receipt_changed:
        con.execute('''UPDATE requests SET received_date=?,no_response=0,updated_by=?
            WHERE id=?''', (received, user_name, request_id))

    if request['action_id'] and (link_changed or receipt_changed):
        details = f"Nabídka: {offer['offer_number'] or '#'+str(offer_id)}; Poptáváno: {request['item'] or ''}."
        if received:
            details += f" Obdrženo: {received}" + (' (datum původního e-mailu).' if source_date else ' (zachované datum).')
        else:
            details += ' Datum původního e-mailu není dostupné; datum obdržení nebylo změněno.'
        con.execute('''INSERT INTO action_history(action_id,user_name,event_type,summary,
            details,related_company_id,related_request_id)
            VALUES(?,?,?,?,?,?,?)''', (request['action_id'], user_name,
            'request_received' if receipt_changed else 'offer_assigned',
            'Přiřadil nabídku a označil poptávku jako obdrženou' if receipt_changed else 'Přiřadil přijatou nabídku k poptávce',
            details, request['company_id'], request_id))
    return received


def assign_from_ui(M, app, offer_id, request_id, parent):
    """Shared callback for the current editor and legacy assignment controls."""
    try:
        with M.db() as con:
            received = assign_to_request(con, offer_id, request_id, M.get_setting('active_user', ''))
    except Exception as exc:
        M.messagebox.showerror('Přiřazení nabídky', str(exc), parent=parent)
        return False
    if not received:
        M.messagebox.showinfo('Datum obdržení',
            'Nabídka byla přiřazena. U zdrojového e-mailu chybí platné datum '
            'nebo byla nabídka načtena samostatně z PDF. Datum Obdrženo '
            'doplňte v poptávce ručně.', parent=parent)
    return True
