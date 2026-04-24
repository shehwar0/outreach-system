from main import read_leads, import_leads_to_db
from database import Database

leads = read_leads('leads.sample.csv')
print(f'Parsed {len(leads)} leads')
for l in leads:
    print(f'  {l.name} | niche={l.niche} | score={l.lead_score} | {l.segment}')

db = Database()
n = import_leads_to_db(leads, db)
print(f'Imported {n} to DB')
print(f'DB total: {db.get_lead_count()}')

# Test analytics
from analytics import Analytics
a = Analytics(db)
kpis = a.get_kpis()
print(f'KPIs: {kpis}')

# Test follow-up engine
from follow_up_engine import FollowUpEngine
fe = FollowUpEngine(db)
due = fe.get_all_due_followups()
print(f'Due follow-ups: f1={len(due["followup1"])}, f2={len(due["followup2"])}')

print('\n=== ALL TESTS PASSED ===')
