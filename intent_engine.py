"""Local, deterministic, safety-first question routing for PC Medic.
No cloud, no commands, no automatic diagnostics for informational questions.
"""
import re
from offline_knowledge import lookup

def classify(question):
    q=' '.join(question.lower().split())
    def has(pattern): return bool(re.search(pattern,q,re.I))
    # Questions about the computer's actual network configuration are inventory requests,
    # not generic how-to advice or reasons to run a broad health scan.
    network_terms=r'\b(ipconfig|ip address|ipv4|ipv6|subnet|default gateway|gateway|dns|dhcp|mac address|physical address|network adapter|ethernet adapter|wifi adapter|wi-fi adapter|dns suffix|lease|wins|host name|hostname)\b'
    if has(network_terms) and (has(r'\b(what|which|show|tell|list|check|find|my|this|current|installed|configured|configuration|settings|ipconfig)\b') or has(r'\b(dns|dhcp|gateway|ipv4|ipv6|subnet|mac address)\b')):
        return {'intent':'network_inventory','scan':'none','answer':'I will read the active Windows network adapter configuration without changing any settings.'}
    # Compound hardware questions require an inventory and a compatibility handoff,
    # not a generic definition of RAM or a performance scan.
    if has(r'\b(ram|memory|ssd|hard drive|storage|gpu|graphics card)\b') and has(r'\b(upgrade|upgrading|add|buy|purchase|compatible|where can i buy|where to buy)\b'):
        if has(r'\b(memory)\b') and not has(r'\b(ram|ssd|storage|gpu|graphics)\b'):
            return {'intent':'memory_clarify','scan':'none','answer':'Do you mean RAM, storage or graphics memory?'}
        return {'intent':'hardware_inventory','scan':'none','answer':'I will identify installed hardware, then offer manufacturer compatibility research with your approval.'}
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
