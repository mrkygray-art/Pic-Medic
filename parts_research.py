"""Opt-in, bounded public web research. Search results are candidates, never compatibility proof.

Live search uses the Brave Search API when BRAVE_SEARCH_API_KEY is set on the server.
Without a key PC Medic does NOT search; it returns direct manufacturer/retailer links the
user can open. (Bing's public RSS feed was removed in 1.16.15: it ignores the query and
returned generic homepages that looked like real results.)
"""
import json, os, re, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

OEM_DOMAINS={'lenovo':'lenovo.com','dell':'dell.com','hp':'hp.com','hewlett':'hp.com','asus':'asus.com','acer':'acer.com',
             'microsoft':'microsoft.com','msi':'msi.com','micro-star':'msi.com','apple':'apple.com','samsung':'samsung.com','razer':'razer.com'}
RETAILERS=('amazon.com','cdw.com','microcenter.com','bestbuy.com','newegg.com','crucial.com','walmart.com','bhphotovideo.com')
FIELD=re.compile(r'[\w .+\-/()]{0,90}')

def part_profile(kind):
    """Search phrase plus the words a result must mention to be about this part."""
    k=kind.lower()
    if 'charger' in k or 'adapter' in k:return 'AC adapter charger',r'charger|adapter|\b\d{2,3}\s?w\b|watt'
    if 'battery' in k:return 'battery',r'batter'
    if 'ram' in k or 'memory' in k:return 'RAM memory upgrade',r'\bram\b|memory|ddr[345]|so-?dimm'
    if 'ssd' in k or 'storage' in k:return 'SSD storage upgrade',r'\bssd\b|nvme|m\.2|solid state|storage'
    if 'graphics' in k or 'gpu' in k:return 'graphics',r'graphics|\bgpu\b|nvidia|geforce|radeon'
    return kind,re.escape(k)

def _clean(value,limit,name):
    text=' '.join(str(value or '').split())[:limit]
    if not FIELD.fullmatch(text):raise ValueError('Invalid '+name)
    return text

def plan(kind, manufacturer, model, product_name='', part_number=''):
    """Exactly what would be sent to the search provider; shown to the user before consent."""
    kind=_clean(kind,90,'part type');manufacturer=_clean(manufacturer,70,'manufacturer');model=_clean(model,80,'model')
    product_name=_clean(product_name,60,'product name');part_number=_clean(part_number,40,'part number')
    if not kind.strip():raise ValueError('Invalid part type')
    if not manufacturer.strip() or not model.strip():raise ValueError('Manufacturer and model are required')
    phrase,keywords=part_profile(kind)
    oem=next((domain for key,domain in OEM_DOMAINS.items() if key in manufacturer.lower()),'')
    identity=' '.join(x for x in (manufacturer,product_name,model) if x)
    base=' '.join(x for x in (identity,phrase,part_number) if x)
    queries=[]
    if oem:queries.append(('Manufacturer',f'{base} site:{oem}'))
    queries.append(('Retailers',base))
    if part_number:queries.append(('Part number',f'"{part_number}" {phrase}'))
    return {'kind':kind,'manufacturer':manufacturer,'model':model,'product_name':product_name,'part_number':part_number,
            'phrase':phrase,'keywords':keywords,'oem':oem,'identity':identity,'base':base,'queries':queries,
            'provider':'brave' if os.environ.get('BRAVE_SEARCH_API_KEY','').strip() else 'none'}

def preview(**fields):
    p=plan(**fields)
    return {'provider':p['provider'],'queries':[q for _,q in p['queries']],
            'shared_fields':{k:p[k] for k in ('manufacturer','model','product_name','part_number','kind') if p[k]}}

def direct_links(p):
    """Links the user opens in their own browser. Nothing is sent until they click."""
    g=lambda q:'https://www.google.com/search?'+urllib.parse.urlencode({'q':q})
    links=[]
    if p['oem']=='lenovo.com':
        links.append({'title':'Lenovo PSREF specifications for '+p['model'],'url':g(f'site:psref.lenovo.com {p["model"]} {p["product_name"]}'.strip()),'source_type':'manufacturer'})
    if p['oem']:
        links.append({'title':'Manufacturer pages: '+p['base'],'url':g(f'site:{p["oem"]} {p["base"]}'),'source_type':'manufacturer'})
    links+=[{'title':'Amazon search','url':'https://www.amazon.com/s?'+urllib.parse.urlencode({'k':p['base']}),'source_type':'retailer'},
            {'title':'CDW search','url':'https://www.cdw.com/search/?'+urllib.parse.urlencode({'key':p['base']}),'source_type':'retailer'},
            {'title':'Micro Center search','url':'https://www.microcenter.com/search/search_results.aspx?'+urllib.parse.urlencode({'Ntt':p['base']}),'source_type':'retailer'}]
    if 'RAM' in p['phrase'] or 'SSD' in p['phrase']:
        links.append({'title':'Crucial compatibility search','url':g(f'site:crucial.com {p["identity"]}'),'source_type':'retailer'})
    return links

def _brave(query,key):
    req=urllib.request.Request('https://api.search.brave.com/res/v1/web/search?'+urllib.parse.urlencode({'q':query,'count':10}),
                               headers={'Accept':'application/json','X-Subscription-Token':key,'User-Agent':'PCMedic/1.16.15'})
    with urllib.request.urlopen(req,timeout=10) as response:
        return json.loads(response.read(1_000_000)).get('web',{}).get('results',[])

def assess(entry, p):
    """Label a search hit, or return None when it is not about this part (e.g. a homepage)."""
    url=str(entry.get('url',''));parsed=urllib.parse.urlparse(url)
    if parsed.scheme!='https' or not parsed.netloc:return None
    # Homepages and locale roots (/, /us/en/, /us/en/pc/) are never about a specific part.
    segments=[x for x in parsed.path.lower().split('/') if x]
    if all(re.fullmatch(r'[a-z]{2}(-[a-z]{2})?|pc|home|index\.html?|selectproduct',x) for x in segments):return None
    title=re.sub('<[^>]*>','',str(entry.get('title','')))[:150]
    snippet=re.sub('<[^>]*>','',str(entry.get('description','')))[:320]
    text=' '.join((title,snippet,url)).lower()
    if not re.search(p['keywords'],text):return None
    ids=[x.lower() for x in (p['model'],p['product_name'],p['part_number']) if x]
    host=parsed.netloc.lower()
    source_type='manufacturer' if p['oem'] and (host==p['oem'] or host.endswith('.'+p['oem'])) else 'retailer' if any(host==r or host.endswith('.'+r) for r in RETAILERS) else 'other'
    if any(i in text for i in ids):match='possible'
    elif p['manufacturer'].lower() in text:match='unverified'
    else:return None
    # 'verified' is never assigned from search text; only OEM documentation the user checks can verify fit.
    return {'title':title,'url':url,'snippet':snippet,'source_type':source_type,'match':match}

def research(kind, manufacturer, model, product_name='', part_number=''):
    p=plan(kind,manufacturer,model,product_name,part_number)
    result={'provider':p['provider'],'searched':False,'queries':[q for _,q in p['queries']],'query':p['queries'][-1][1] if p['part_number'] else p['base'],
            'sources':[],'search_links':direct_links(p),'errors':[],'verified':False,
            'searched_at_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'note':'Search results are unverified candidates. Confirm the exact OEM machine type, connector, voltage and wattage (chargers), battery part number (batteries), or slot/form factor and supported capacity (memory/storage). Prices and availability change. Do not buy from a title match alone.'}
    key=os.environ.get('BRAVE_SEARCH_API_KEY','').strip()
    if not key:
        result['errors'].append('Live web search is not configured on this PC (no BRAVE_SEARCH_API_KEY), so PC Medic did not search. The links below open the manufacturer and retailer searches in your browser.')
        return result
    result['searched']=True
    seen=set()
    def run(item):
        label,query=item
        try:return label,_brave(query,key),None
        except urllib.error.HTTPError as exc:
            return label,[],'rejected the API key' if exc.code in (401,403) else 'rate limit reached' if exc.code==429 else f'HTTP {exc.code}'
        except Exception as exc:return label,[],'unavailable ('+type(exc).__name__+')'
    with ThreadPoolExecutor(max_workers=3) as pool:
        for label,hits,error in pool.map(run,p['queries']):
            if error:result['errors'].append(f'{label} search: Brave Search {error}.');continue
            for hit in hits:
                item=assess(hit,p)
                if item and item['url'] not in seen:seen.add(item['url']);result['sources'].append(item)
    rank={'manufacturer':0,'retailer':1,'other':2}
    result['sources'].sort(key=lambda s:(s['match']!='possible',rank[s['source_type']]))
    result['sources']=result['sources'][:10]
    return result
