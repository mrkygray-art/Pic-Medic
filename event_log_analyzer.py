"""Bounded, read-only Windows event triage. No event messages leave this module."""
from collections import Counter

# Treat event IDs as leads, never proof of cause. DCOM 10010 alone is noise.
PRIORITY = {
    17: ("WHEA corrected hardware error", "System"),
    18: ("WHEA fatal hardware error", "System"),
    19: ("WHEA corrected hardware error", "System"),
    11: ("Disk controller error", "System"),
    41: ("Unexpected restart or power loss", "System"),
    6008: ("Unexpected shutdown", "System"),
    7: ("Disk I/O error", "System"),
    51: ("Disk paging I/O issue", "System"),
    55: ("Filesystem corruption warning", "System"),
    129: ("Storage controller timeout", "System"),
    153: ("Disk I/O retry", "System"),
    1000: ("Application crash", "Application"),
    1001: ("Application or Windows error report", "Application"),
    1002: ("Application hang", "Application"),
    20: ("Windows Update installation failure", "System"),
}
# Narrow known providers to avoid treating unrelated event IDs as identical.
PROVIDERS = {
    17: ("WHEA corrected hardware error", "System"),
    18: ("WHEA fatal hardware error", "System"),
    19: ("WHEA corrected hardware error", "System"),
    11: ("Disk controller error", "System"),
    17: ("whea-logger",), 18: ("whea-logger",), 19: ("whea-logger",), 11: ("disk",),
    41: ("kernel-power",), 6008: ("eventlog",),
    7: ("disk",), 51: ("disk",), 55: ("ntfs",),
    129: ("storahci", "stornvme", "iaStor", "storport"),
    153: ("disk",),
    1000: ("application error",), 1001: ("windows error reporting",),
    1002: ("application hang",), 20: ("windowsupdateclient",),
}

def summarize_events(check):
    if not isinstance(check, dict) or check.get('status') != 'ok':
        return {'status':'unavailable','groups':[], 'reason': (check or {}).get('reason','Event logs could not be read') if isinstance(check,dict) else 'Event logs could not be read'}
    data=check.get('data')
    if not isinstance(data,dict):
        return {'status':'unavailable','groups':[], 'reason':'Invalid event log response'}
    groups=[]
    for item in data.get('channels',[]):
        if item.get('status')!='ok': continue
        name=item.get('name','')
        events=item.get('events',[])
        if isinstance(events,dict):events=[events]
        if not isinstance(events,list):continue
        counts=Counter()
        times={}
        for e in events:
            if not isinstance(e,dict):continue
            try: eid=int(e.get('Id'))
            except (TypeError,ValueError):continue
            spec=PRIORITY.get(eid)
            if not spec or spec[1]!=name:continue
            provider=str(e.get('ProviderName','')).lower()
            if not any(p.lower() in provider for p in PROVIDERS[eid]):continue
            key=(eid,provider[:90]);counts[key]+=1
            t=str(e.get('TimeCreated',''))[:32]
            if t:times.setdefault(key,[]).append(t)
        for (eid,provider),n in counts.most_common(8):
            groups.append({'channel':name,'event_id':eid,'provider':provider,'count_sampled':n,
                           'description':PRIORITY[eid][0], 'latest':max(times.get((eid,provider),['']))})
    return {'status':'ok' if any(c.get('status')=='ok' for c in data.get('channels',[])) else 'unavailable',
            'groups':sorted(groups,key=lambda x:({18:100,7:95,11:90,51:90,17:85,19:80,41:75,6008:75,129:75,153:75,55:75,20:35}.get(x['event_id'],45),x['count_sampled'],x['latest']),reverse=True)[:12],
            'channels_checked':[c.get('name') for c in data.get('channels',[]) if c.get('status')=='ok'],
            'channels_unavailable':[c.get('name') for c in data.get('channels',[]) if c.get('status')!='ok'],
            'window_hours':data.get('window_hours',24), 'sample_limit_per_channel':data.get('limit_per_channel',80)}
