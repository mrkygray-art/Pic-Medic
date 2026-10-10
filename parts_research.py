"""Opt-in, bounded public web research. Search results are candidates, never compatibility proof."""
import json, os, re, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from html import unescape

SITES={'manufacturer':'support.lenovo.com','cdw':'cdw.com','amazon':'amazon.com','microcenter':'microcenter.com'}

def research(kind, manufacturer, model, details=''):
    kind=str(kind)[:90]; manufacturer=str(manufacturer)[:70]; model=str(model)[:80]
    if not manufacturer.strip() or not model.strip():raise ValueError('Manufacturer and model are required')
    if not re.fullmatch(r'[\w .+\-/()]{1,90}',kind):raise ValueError('Invalid part type')
    terms=f'{manufacturer} {model} {kind} OEM compatible part number specifications'
    queries=[('Manufacturer',f'{manufacturer} {model} {kind} site:{SITES["manufacturer"]}'),('CDW',f'{manufacturer} {model} {kind} site:cdw.com'),('Amazon',f'{manufacturer} {model} {kind} site:amazon.com'),('Micro Center',f'{manufacturer} {model} {kind} site:microcenter.com')]
    sources=[]; errors=[]
    key=os.environ.get('BRAVE_SEARCH_API_KEY','').strip()
    if key:
        try:
            req=urllib.request.Request('https://api.search.brave.com/res/v1/web/search?'+urllib.parse.urlencode({'q':terms,'count':8}),headers={'Accept':'application/json','X-Subscription-Token':key,'User-Agent':'PCMedic/1.16.13'})
            with urllib.request.urlopen(req,timeout=12) as response:data=json.load(response)
            for entry in data.get('web',{}).get('results',[])[:8]:
                url=entry.get('url','')
                if url.startswith('https://'):sources.append({'title':entry.get('title','')[:150],'url':url,'snippet':re.sub('<[^>]*>','',entry.get('description',''))[:320],'status':'candidate'})
        except Exception:errors.append('Search provider was unavailable')
    else:
        # Public RSS may be blocked or incomplete; never present it as authoritative verification.
        try:
            url='https://www.bing.com/search?'+urllib.parse.urlencode({'q':terms,'format':'rss'})
            req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; PCMedic/1.16.13)'})
            with urllib.request.urlopen(req,timeout=10) as response:raw=response.read(300000)
            root=ET.fromstring(raw)
            for item in root.findall('.//item')[:8]:
                link=item.findtext('link','')
                if link.startswith('https://'):
                    sources.append({'title':unescape(item.findtext('title',''))[:150],'url':link,'snippet':unescape(re.sub('<[^>]*>','',item.findtext('description','')))[:320],'status':'candidate'})
        except Exception:errors.append('Public search was unavailable; use retailer search links')
    links=[{'title':label+' search','url':'https://www.google.com/search?'+urllib.parse.urlencode({'q':q})} for label,q in queries]
    return {'query':terms,'sources':sources,'search_links':links,'errors':errors,'verified':False,'note':'Search results are unverified candidates. Confirm exact OEM machine configuration, connector, voltage and required wattage (for chargers), or slot/form factor and supported capacity (for memory/storage). Prices and availability can change. Do not buy solely from a title match.'}
