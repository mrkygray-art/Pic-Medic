"""Local, deterministic, safety-first question routing for PC Medic.
No cloud, no commands, no automatic diagnostics for informational questions.
"""
import re
from offline_knowledge import lookup

AFFIRM_TRIGGERS={'yes','yeah','yep','sure','ok','okay','research','search','go','find','buy','proceed','continue'}
AFFIRM_WORDS=AFFIRM_TRIGGERS|{'please','ahead','it','them','that','this','up','look','online','parts','part','for','me','do','where','can','i','the','one','options','a','and'}
DECLINE_TRIGGERS={'no','nope','nah','cancel','skip','offline','not'}
DECLINE_WORDS=DECLINE_TRIGGERS|{'thanks','thank','you','now','stay','dont','do','it','that','please','search','research','online','right'}

def _reply_kind(q):
    """Classify a short reply as an approval or a refusal of the pending offer."""
    words=re.sub(r"[^a-z ]",' ',q.replace("'",'')).split()
    if not words or len(words)>8:return None
    if set(words)<=DECLINE_WORDS and set(words)&DECLINE_TRIGGERS:return 'decline'
    if set(words)<=AFFIRM_WORDS and set(words)&AFFIRM_TRIGGERS:return 'affirm'
    return None

def classify(question, context=None):
    q=' '.join(question.lower().split())
    context=context if isinstance(context,dict) else {}
    def has(pattern): return bool(re.search(pattern,q,re.I))
    # Short follow-ups ("Yes, research it", "no thanks") refer to the pending research offer.
    if context.get('pending_research'):
        reply=_reply_kind(q)
        if reply=='affirm':return {'intent':'research_confirm','scan':'none'}
        if reply=='decline':return {'intent':'research_decline','scan':'none'}
    elif _reply_kind(q)=='affirm':
        return {'intent':'no_pending_offer','scan':'none','answer':'There is no search waiting for approval right now. Tell me which part you want researched, for example "I need a new charger" or "Can I upgrade my RAM?".'}
    # Replacement parts are shopping/research requests, not battery-health or charging advice.
    if has(r'\b(charger|power adapter|ac adapter|charging brick|power brick|power supply)\b') and not has(r'\b(not charging|won.t charge|isn.t charging|stopped charging|charging slow\w*)\b'):
        return {'intent':'replacement_part','part':'replacement laptop charger','scan':'none'}
    if has(r'\b(batter(y|ies))\b') and has(r'\b(replace\w*|new|buy|purchase|order|need|find|where can i|swap)\b') and not has(r'\b(drain\w*|health|life|report|lasting|dies fast)\b'):
        return {'intent':'replacement_part','part':'replacement laptop battery','scan':'none'}
    # An error code ("what does 0x80070643 mean?") is looked up offline (error_codes.py).
    if has(r'\b0x[0-9a-f]{1,8}\b') or (has(r'\b8[0-9a-f]{7}\b') and has(r'\b(error|code|update|fail\w*)\b')):
        import error_codes
        code=error_codes.find_code(q)
        if code is not None:return {'intent':'error_code','code':f'0x{code:08X}','scan':'none'}
    # Slowness starts a guided troubleshooting case (troubleshooter.py). When the wording says when it happens,
    # the case skips the "when is it slow?" question. Slow internet is a network problem, not a slow PC.
    if has(r'\b(slow\w*|sluggish|lag|lags|lagging|laggy|stutter\w*|takes (forever|ages|a long time)|unresponsive|hangs|hanging|bogged down)\b') \
            and not has(r'\b(internet|wi-?fi|download\w*|upload\w*|network|connection|printer|print\w*)\b'):
        when = ('gaming' if has(r'\b(games?|gaming|fps|steam|fortnite|minecraft|roblox|valorant)\b') else
                'startup' if has(r'\b(boot\w*|start ?up|starting up|turn(s|ing)? on|sign(ing)? in|log(ging)? ?in|restart\w*)\b') else
                'browsing' if has(r'\b(browser|browsing|web ?pages?|websites?|chrome|edge|firefox|tabs?|youtube)\b') else None)
        return {'intent':'slow','context':when,'scan':'none'}
    # "Can it run games?" is answered from the graphics card, processor and RAM.
    if has(r'\b(games?|gaming|gamer|fps|frame ?rate|steam|fortnite|minecraft|roblox|valorant|call of duty|gta|cyberpunk|elden ring)\b') and not has(r'\b(crash\w*|freez\w*|lag\w*|stutter\w*|won.t (start|launch|open))\b'):
        return {'intent':'gaming','scan':'none'}
    # Questions a read-only Windows check can answer directly (system_checks.py).
    checks=[
        ('battery',r'\bbatter(y|ies)\b.*\b(health|life|wear\w*|capacity|drain\w*|cycles?|condition|report|dies|lasting|lasts|hold\w*|good|ok)\b|\bhow (is|good is) my battery\b'),
        ('crashes',r'\b(blue ?screens?|bsod|crash\w*|stop code|bug ?check)\b|\b(restart\w*|reboot\w*|shut\w* (down|off))\b.*\b(by itself|on its own|randomly|unexpectedly|for no reason)\b'),
        ('updates',r'\b(windows )?updates?\b.*\b(fail\w*|error\w*|stuck|won.t install|not installing|history)\b'),
        ('startup_apps',r'\b(startup apps?|start ?up programs?|launch at startup)\b|\b(slow|long|forever)\b.*\b(boot\w*|start ?up|to start)\b|\bstarts slowly\b'),
        ('pending_reboot',r'\b(need|have|should i) to (restart|reboot)\b|\b(restart|reboot) (pending|required|needed)\b|\bpending (restart|reboot)\b|\buptime\b|\blast (restart|reboot)\b'),
        ('disk_health',r'\b(disk|drive|ssd|hard drive|hdd)\b.*\b(health\w*|failing|dying|smart|bad sectors?|errors?|wear|full|free space|space left|running out)\b'),
        ('security',r'\b(antivirus|anti-virus|virus protection|defender|firewall|bitlocker|device encryption|tpm|secure boot|security (check|posture|status|settings|scan))\b|\b(is|are|am)\b.*\b(computer|pc|laptop|desktop|it|i)\b.*\b(secure|protected|safe from|hackable)\b|\bhow (secure|safe|protected) is\b'),
    ]
    for name,pattern in checks:
        if has(pattern):return {'intent':'system_check','check':name,'scan':'none'}
    # Opening a Windows tool is an allowlisted, user-approved launch, never command execution.
    if has(r'\b(open|launch|start|run|bring up)\b') and has(r'\b(powershell|power shell|command prompt|cmd(\.exe)?|dos|terminal)\b'):
        return {'intent':'open_tool','tool':'powershell' if has(r'\b(powershell|power shell|terminal)\b') else 'command-prompt','scan':'none'}
    if has(r'\b(ports?|sockets?)\b') and has(r'\b(how many|what|which|show|list|have|installed)\b'):
        return {'intent':'ports_clarify','scan':'none'}
    # Questions about the computer's actual network configuration are inventory requests,
    # not generic how-to advice or reasons to run a broad health scan.
    network_terms=r'\b(ipconfig|ip address|my ip|ip|ipv4|ipv6|subnet|default gateway|gateway|dns|dhcp|mac address|physical address|network adapter|ethernet adapter|wifi adapter|wi-fi adapter|dns suffix|lease|wins|host name|hostname)\b'
    if has(network_terms) and (has(r'\b(what|which|show|tell|list|check|find|my|this|current|installed|configured|configuration|settings|ipconfig)\b') or has(r'\b(dns|dhcp|gateway|ipv4|ipv6|subnet|mac address)\b')):
        return {'intent':'network_inventory','scan':'none','answer':'I will read the active Windows network adapter configuration without changing any settings.'}
    # Compound hardware questions require an inventory and a compatibility handoff,
    # not a generic definition of RAM or a performance scan.
    if has(r'\b(ram|memory|ssd|hard drive|storage|gpu|graphics card)\b') and has(r'\b(upgrade|upgrading|add|buy|purchase|compatible|where can i buy|where to buy)\b'):
        if has(r'\b(memory)\b') and not has(r'\b(ram|ssd|storage|gpu|graphics)\b'):
            return {'intent':'memory_clarify','scan':'none','answer':'Do you mean RAM, storage or graphics memory?'}
        if has(r'\b(ssd|hard drive|storage)\b') and not has(r'\b(ram)\b'):return {'intent':'storage_upgrade','scan':'none'}
        if has(r'\b(gpu|graphics card)\b') and not has(r'\b(ram)\b'):return {'intent':'graphics_upgrade','scan':'none'}
        return {'intent':'ram_upgrade','scan':'none','answer':'I will identify installed RAM, then offer manufacturer compatibility research with your approval.'}
    # Hardware inventory requests take priority over generic dictionary answers.
    # Everyday questions: local guidance first; never mistake them for a reason to launch a generic scan.
    topics = [
      (r'\b(fan|jet engine|loud fan|overheat|getting hot|running hot|temperature)\b', 'Heat or fan noise can come from blocked vents, background CPU load or cooling problems. First check airflow and whether the fan is constantly loud. If it is safe, inspect Task Manager for high CPU usage. If the computer is extremely hot, shut it down and allow it to cool. Would you like a short performance check?'),
      (r'\b(battery|charging|charger|plugged in|power adapter|won.t turn on|doesn.t turn on)\b', 'For battery questions, Windows can generate a battery report with powercfg /batteryreport (when supported). Rapid drain may involve screen brightness, workload or battery wear. If the PC will not power on, check the outlet, cable and charging indicator first. Would you like help with battery health, charging or power-on troubleshooting?'),
      (r'\b(wi-?fi|wireless|internet|router|network|ethernet|bluetooth)\b', 'Let us narrow down the connection problem. Does the issue affect only this computer or other devices too? For Wi-Fi, check Airplane mode and the connected network, then review the network adapter in Device Manager. PC Medic will not reset your network automatically.'),
      (r'\b(virus|malware|infected|antivirus|defender|suspicious pop.?up|browser redirect)\b', 'Windows Security includes Microsoft Defender protection. For suspected malware, check Windows Security > Virus & threat protection, review recent detections and consider a scan. Do not click suspicious pop-ups. PC Medic will not declare a system clean without evidence.'),
      (r'\b(backup|back up|restore files|recover files|factory reset|sell my|recycl)\b', 'Before resetting, selling or repairing a computer, back up important files and verify that the backup can be opened. A Windows reset may erase installed programs or personal files depending on options. Would you like help backing up files or preparing for a reset?'),
      (r'\b(keyboard|touchpad|mouse|external monitor|connect.*tv|hdmi|displayport|usb.?c)\b', 'First check the physical connection and whether Windows detects the device. For an external display, try Win+P to choose Duplicate or Extend. For input devices, check Device Manager and restart only after saving work. Which device is affected?'),
      (r'\b(startup|boot time|starts slowly|slow boot|startup apps)\b', 'Slow startup often relates to startup apps, updates or disk activity. Open Task Manager > Startup apps to review impact; disable only programs you recognize. Would you like a performance watch or help reviewing startup items?'),
      (r'\b(clear disk|free up space|disk space|storage full|c:.*full|clean up)\b', 'To free space safely, open Settings > System > Storage and review Temporary files and Storage Sense. Check Downloads before deleting anything. PC Medic can inspect capacity without removing files. Would you like to review storage usage?'),
    ]
    for pattern, answer in topics:
        if has(pattern) and not has(r'\b(what (?:type|model)|which|how much|installed|specs|specifications|upgrade|add more|replace)\b'):
            return {'intent':'guided_knowledge','scan':'none','answer':answer}
    if has(r'\b(what|which|tell|show|identify|know|find)\b') and has(r'\b(my computer|my pc|this computer|computer model|pc model|my system|manufacturer|system information|system specs|make and model)\b') and not has(r'\b(freez\w*|crash\w*|slow|fail\w*)\b'):
        return {'intent':'hardware_inventory','scan':'none','answer':'I will identify your computer using local Windows system information.'}
    if has(r'\b(what|which|show|tell|check|list|do i have|installed|my|can i|upgrade|add)\b') and has(r'\b(display|monitor|screen|video card|graphics card|gpu|graphics adapter|processor|cpu|motherboard|mainboard|memory|ram|ssd|storage|hard drive|disk|system specs|computer model)\b') and not has(r'\b(freez\w*|crash\w*|slow|fail\w*|disconnect\w*|not working)\b'):
        if has(r'\b(memory)\b') and has(r'\b(add|upgrade|more|expand)\b') and not has(r'\b(ram|vram|video|graphics|ssd|storage)\b'):
            return {'intent':'memory_clarify','scan':'none'}
        return {'intent':'hardware_inventory','scan':'none','answer':'I will inspect the relevant Windows hardware inventory and explain what is installed. An upgrade requires separate manufacturer compatibility verification.'}
    if has(r'\b(froze|frozen|freezes|freezing|freeze|crashed|crashes|locked up|locking up)\b'):
        return {'intent':'performance','scan':'watch','answer':'I will check recent performance activity. A short watch may not capture a past freeze; related event logs may require a full health check.'}
    knowledge=lookup(q)
    if knowledge: return {'intent':'offline_knowledge','scan':'none','answer':knowledge}
    if not q: return {'intent':'clarify','answer':'Tell me what you would like to know or what is happening. I will explain my plan before running any test.','scan':'none'}
    if has(r'\b(memory|ram)\b') and has(r'\b(add|upgrade|install|replace|buy|purchase|expand|more|capacity|slots?|compatible)\b'):
        if has(r'\b(vram|video memory|graphics memory)\b'): return {'intent':'graphics_upgrade','scan':'none'}
        if has(r'\b(ssd|storage|disk space|hard drive)\b'): return {'intent':'storage_upgrade','scan':'none'}
        if has(r'\b(ram|ddr\d?|sodimm|dimm)\b'): return {'intent':'ram_upgrade','scan':'none'}
        return {'intent':'memory_clarify','scan':'none'}
    if has(r'\b(ssd|storage|hard drive|disk|drive)\b') and has(r'\b(upgrade|replace|buy|install|add|capacity|more space)\b'): return {'intent':'storage_upgrade','scan':'none'}
    if has(r'\b(vram|graphics card|gpu|video card)\b') and has(r'\b(upgrade|replace|buy|install|add|memory)\b'): return {'intent':'graphics_upgrade','scan':'none'}
    if has(r'\b(how much|what|which|show|tell|list|check|do i have|is my)\b') and has(r'\b(ram|memory|processor|cpu|windows version|model|manufacturer|specs|specifications|disk space|storage|graphics card|gpu)\b') and not has(r'\b(crash|freeze|freezing|slow|error|fail|broken|disconnect)\b'):
        return {'intent':'system_info','scan':'none','answer':'This is a system-information question, not a performance problem. I can inspect the available Windows hardware inventory without running a health check. For an upgrade, we must still verify compatibility against the exact manufacturer model.'}
    if has(r'\b(what is|what does|explain|difference between|how do i|how to|should i|can i)\b') and not has(r'\b(crash|freez|fail|error|slow|disconnect|overheat|not working|won.t start)\b'):
        return {'intent':'howto','scan':'none','answer':'This sounds like a question rather than a symptom. I will not run a diagnostic automatically. Tell me the specific Windows feature or task, and I can explain the safe next steps. If hardware compatibility or current prices are involved, local information alone cannot verify them.'}
    if has(r'\b(wifi|wi-fi|wireless|internet|network|ethernet|bluetooth)\b'):
        return {'intent':'network','scan':'none','answer':'This sounds like a connectivity issue. Before a broad health check, note whether the problem affects Wi-Fi only or also wired connections, whether other devices disconnect, and when it happens. A targeted network diagnostic is recommended; this build does not yet automate the WLAN report. No scan has started.'}
    if has(r'\b(windows update|update fail|failed update|install error|blue screen|bsod|unexpected shutdown|reboot|disk error|driver error)\b'):
        return {'intent':'health','scan':'health','answer':'I recommend a read-only Health Check to examine Windows events, storage and device findings. It may help identify a related error but cannot guarantee a root cause.'}
    if has(r'\b(freez\w*|slow\w*|lag\w*|stutter\w*|spike\w*|overheat\w*|hot|fan loud|high cpu|high memory|sluggish|hang\w*|unresponsive)\b'):
        return {'intent':'performance','scan':'watch','answer':'I recommend a short Performance Watch to sample CPU, memory and disk activity. Brief samples may miss intermittent issues.'}
    return {'intent':'clarify','scan':'none','answer':'I want to understand your request before choosing a test. Are you asking a question about your computer, planning an upgrade, or troubleshooting something that is not working? No scan has started.'}
