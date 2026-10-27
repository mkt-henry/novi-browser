# Supervisor check for the LinkedIn rounds: read the saved drafts back from
# Campaign Manager's own API inside the logged-in No.VI browser page.
#
#   novi-browser exec <account> --site LinkedIn -c "$(cat verify_linkedin.py)"
#
# Edit ACCOUNT and CAMPAIGNS first (ids are in the Campaign Manager URL of each draft).
# Writes verify.json next to check.py, which prints the graded fields.
import json
ACCOUNT = 0  # ad account id
CAMPAIGNS = {'A7': 0, 'AE1': 0}  # round code -> campaign id
OUT = 'verify.json'

hd = {}
def _rq(r):
    if 'campaign-manager-api' in r.url and 'csrf-token' in r.headers and not hd:
        hd.update(r.headers)
page.on('request', _rq)
first = next(iter(CAMPAIGNS.values()))
page.goto(f'https://www.linkedin.com/campaignmanager/accounts/{ACCOUNT}/campaigns/{first}/review')
for _ in range(40):
    if hd: break
    page.evaluate('new Promise(r=>setTimeout(r,500))')
H = {k: v for k, v in hd.items() if k in ('csrf-token', 'x-restli-protocol-version', 'x-li-lang', 'x-li-er-key', 'accept-language', 'x-li-track')}
H['accept'] = 'application/json'
JS = '''async ([u,h])=>{const r=await fetch(u,{headers:h,credentials:'include'});return r.status+'|'+await r.text();}'''
B = 'https://www.linkedin.com/campaign-manager-api/'
def g(u):
    s = page.evaluate(JS, [B + u, H]); st, _, body = s.partition('|')
    try:
        return json.loads(body)
    except Exception:
        return {'_status': st, '_body': body[:300]}
out = {}
for k, i in CAMPAIGNS.items():
    out[k] = {'camp': g(f'campaignManagerCampaigns/{i}'),
              'cre': g(f'campaignManagerReportingCreatives?accountId={ACCOUNT}&q=cursorBasedCriteria&campaignIds=List({i})')}
out['all'] = g(f'campaignManagerCampaigns?q=accountAndStatuses&accountUrn=urn%3Ali%3AsponsoredAccount%3A{ACCOUNT}&statuses=List(ACTIVE,PAUSED,ARCHIVED,COMPLETED,DRAFT)&pagingContext=start=0&count=50')
open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, indent=1))
(len(hd), [(k, list(out[k]['camp'].keys())[:4]) for k in CAMPAIGNS])
