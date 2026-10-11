"""ChatGPT fallback and the sanitized evidence summaries shared with AI. Claude runs through assistant.py."""
from event_log_analyzer import summarize_events
import json, os, urllib.request, urllib.error

import settings
from analyze import analyze

# ChatGPT fallback for any question (Smart mode). The scan summary is background, never the subject:
# the old diagnostic template answered a charger question with disk-space findings.
CHAT_SYSTEM = ("You are PC Medic, a friendly Windows technician helping a non-technical person with their own computer. "
               "Answer the user's question directly and practically. A sanitized summary of their latest PC Medic scan is "
               "attached as background: mention it only when it is clearly relevant to the question, and never steer the "
               "answer toward unrelated findings. You cannot run checks or browse the web; say so when the answer depends on "
               "facts you do not have, such as the exact computer model. Never invent part numbers, prices or links. "
               "Plain text, no markdown headings or tables, usually under 180 words.")

def safe_summary(report):
    checks=report.get('checks',{})
    def data(k):
        x=checks.get(k,{})
        return x.get('data') if x.get('status')=='ok' else None
    m=data('memory'); ds=data('disks'); cpu=data('cpu'); events=data('recent_system_events')
    if isinstance(cpu,list):cpu=cpu[0] if cpu else None
    disks=[]
    for d in (ds if isinstance(ds,list) else [ds] if isinstance(ds,dict) else []):
        if isinstance(d,dict):disks.append({'drive':str(d.get('DeviceID')) if str(d.get('DeviceID','')) in ('C:','D:','E:','F:','G:') else None, 'size_gb':d.get('SizeGB'),'free_gb':d.get('FreeGB')})
    ev=[]
    for e in (events if isinstance(events,list) else [events] if isinstance(events,dict) else []):
        if isinstance(e,dict):ev.append({'event_id':e.get('Id'),'provider':str(e.get('ProviderName',''))[:90]})
    findings=[]
    for f in analyze(report)['findings']:
        title=str(f.get('title') or '')
        # Drive titles end with the drive's model name ('Storage health status: Samsung SSD 980'); keep only the kind of finding.
        if title.startswith(('Storage health status:','Drive reliability requires review:')):title=title.split(':')[0]
        findings.append({'severity':f.get('severity'),'title':title,'next_step':f.get('recommended_next_step')})
    return {'os_family':'Windows','cpu_load_percent':cpu.get('LoadPercentage') if isinstance(cpu,dict) else None,
            'memory':{k:m.get(k) for k in ('TotalGB','FreeGB')} if isinstance(m,dict) else None,
            'disks':disks[:12], 'event_counts':{'sampled':len(ev),'ids':[e['event_id'] for e in ev[:25]]},
            'findings':findings[:15], 'event_analysis':summarize_events(checks.get('event_log_analysis'))}


PERF_FIELDS = ('cpu_percent', 'memory_used_percent', 'memory_available_mb', 'disk_busy_percent', 'disk_queue_length')
def sanitize_investigation(data):
    """Allow only bounded numeric performance evidence; never accept process identity fields."""
    if data is None: return None
    if not isinstance(data, dict): raise ValueError('Invalid investigation evidence')
    samples=data.get('performance_samples', [])
    if not isinstance(samples,list) or len(samples)>20: raise ValueError('Invalid performance sample count')
    clean=[]
    for sample in samples:
        if not isinstance(sample,dict):raise ValueError('Invalid performance sample')
        row={}
        for k in PERF_FIELDS:
            v=sample.get(k)
            if type(v) in (int,float) and v==v and abs(v)<1000000:
                if k in ('cpu_percent','memory_used_percent','disk_busy_percent') and not 0<=v<=100:continue
                row[k]=round(v,2)
        clean.append(row)
    summary=data.get('watch_summary')
    safe_watch=None
    if isinstance(summary,dict):
        safe_watch={}
        for k in ('sample_count','duration_seconds','spike_count'):
            v=summary.get(k)
            if type(v) is int and 0<=v<=100000:safe_watch[k]=v
        metrics=summary.get('metrics')
        if isinstance(metrics,dict):
            safe_watch['metrics']={}
            for k in ('CPU','Memory','Disk'):
                m=metrics.get(k)
                if isinstance(m,dict):
                    safe_watch['metrics'][k]={}
                    for field in ('peak','average'):
                        v=m.get(field)
                        if type(v) in (int,float) and 0<=v<=100:safe_watch['metrics'][k][field]=round(v,2)
    return {'performance_samples':clean,'sample_count':len(clean),'watch_summary':safe_watch,
            'note':'Read-only sampled measurements; no process identities or raw logs. Missing counters are unknown. Short samples do not establish root cause.'}

def post(url, headers, payload):
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers=headers,method='POST')
    try:
        with urllib.request.urlopen(req,timeout=35) as r:return json.load(r)
    except urllib.error.HTTPError as e:
        # Never expose provider responses verbatim (could contain secrets).
        raise RuntimeError(f'Provider HTTP {e.code}; check model, key and account access') from None
    except (urllib.error.URLError,TimeoutError):raise RuntimeError('Provider connection failed or timed out') from None

def ask(provider, question, report, demo=False, tool_approved=False, investigation=None):
    """ChatGPT fallback: one request with the question and minimized scan/performance context. Claude uses assistant.py."""
    if provider!='openai':raise ValueError('Only the OpenAI fallback is served here')
    key,source=settings.key_for_use('openai');model=os.environ.get('PCMEDIC_OPENAI_MODEL','gpt-5.4')
    if not key:raise RuntimeError('ChatGPT is not set up on this PC. Add an OpenAI key in Settings.')
    evidence=safe_summary(report)
    # Only sanitized evidence + question are sent. No raw scan, user identity or process names.
    prompt='Question: '+question+'\n\nBackground (latest PC Medic scan, sanitized; use only if relevant): '+json.dumps(evidence)
    if investigation is not None:prompt+='\nSanitized performance investigation: '+json.dumps(sanitize_investigation(investigation))
    # One request, no tools: replaying reasoning items with store disabled fails in a tool loop on current models.
    url='https://api.openai.com/v1/responses'
    headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'}
    result=post(url,headers,{'model':model,'instructions':CHAT_SYSTEM,'input':[{'role':'user','content':prompt}],'max_output_tokens':2500,'store':False})
    texts=[c.get('text','') for x in result.get('output',[]) if x.get('type')=='message' for c in x.get('content',[]) if c.get('type')=='output_text']
    answer='\n'.join(texts).strip()
    if not answer:
        if result.get('status')=='incomplete':raise RuntimeError('ChatGPT ran out of space before answering. Try a shorter or more specific question.')
        raise RuntimeError('ChatGPT returned no answer.')
    settings.record_use(source)
    return {'answer':answer,'tools_used':[],'provider':provider}
