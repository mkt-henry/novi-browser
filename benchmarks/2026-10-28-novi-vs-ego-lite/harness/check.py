import json, datetime, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open('verify.json', encoding='utf-8'))

def seg(c, facet):
    out = []
    for a in c['targetingCriteria']['include']['and']:
        for o in a['or']:
            if o['facet']['urn'].endswith(facet):
                out += [s['name'] for s in o['segments']]
    return out

def facets(c):
    return [o['facet']['urn'].split(':')[-1] for a in c['targetingCriteria']['include']['and'] for o in a['or']]

f = lambda t: datetime.datetime.fromtimestamp(t / 1000, datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M KST')
for k in [k for k in d if k != 'all']:
    c = d[k]['camp']
    rs = c['runSchedule']
    keys = [x for x in c.keys() if 'udget' in x.lower()]
    print(k, c.get('name'), '| status', c.get('status'), '| obj', c['objectiveType'], '| format', c.get('format'), c['adFormats'])
    print('  facets', facets(c), '| loc', seg(c, 'locations'), '| lang', seg(c, 'interfaceLocales'), '| ind', seg(c, 'industries'), '| sen', seg(c, 'seniorities'))
    print('  exclude', json.dumps(c['targetingCriteria'].get('exclude'), ensure_ascii=False)[:100])
    print('  expansion', c['audienceExpansionEnabled'], '| offsite', c['offsiteDeliveryEnabled'], '| sched', f(rs['start']), '~', f(rs['end']))
    print('  budget', {x: c[x] for x in keys}, '| group', c['campaignGroupId'])
    for cr in d[k]['cre'].get('elements', []):
        s = json.dumps(cr, ensure_ascii=False)
        print('  cre', cr.get('name') or cr.get('creativeName'), cr.get('status') or cr.get('intendedStatus'),
              '| intro' , 'Backing a startup that wants to grow in Korea & Asia? Best Partner M&C runs performance marketing, content and influencer campaigns for portfolio companies.' in s,
              '| headline', 'Scale your portfolio into Korea & Asia' in s,
              '| url', ('utm_campaign=bench_' + k.lower()) in s,
              '| image', ('image' in s.lower() and 'digitalmediaAsset' in s) or 'urn:li:image' in s)
for e in d['all'].get('elements', []):
    if 'BENCH' in e['name']:
        print(e['id'], e['name'], e['status'])
