"""Conservative, offline Windows help. No scans, network requests or repairs."""
import re

TOPICS = [
 (r'\b(?:ram|memory)\b.*\b(?:difference|versus|vs|storage|disk)\b|\b(?:difference|versus|vs)\b.*\b(?:ram|memory)\b',
  'RAM is short-term working memory for running apps. Storage (SSD/HDD) holds files and Windows after power is off. VRAM is memory used by graphics hardware. If you want more apps open at once, ask about RAM; if C: is full, ask about storage.'),
 (r'\b(?:what is|what does|explain)\b.*\b(?:ram|random access memory)\b',
  'RAM is the computer’s short-term working space. More RAM can help when programs compete for memory, but it does not automatically speed up every computer. To check an upgrade, ask “Can I upgrade my RAM?”'),
 (r'\b(?:what is|what does|explain)\b.*\b(?:ssd|solid.state drive)\b',
  'An SSD stores Windows, apps and files. It is usually faster than a traditional hard drive. Available capacity is not the same as SSD health. For an upgrade, the exact laptop or motherboard model and drive interface must be verified.'),
 (r'\b(?:what is|what does|explain)\b.*\b(?:gpu|graphics card|vram)\b',
  'The GPU processes graphics; VRAM is memory used by graphics hardware. Most integrated graphics share system RAM, and most laptops cannot upgrade dedicated VRAM separately.'),
 (r'\b(?:how (?:do|can) i|how to|where (?:do|can) i)\b.*\b(?:check|find|see|view)\b.*\b(?:ram|memory)\b',
  'Open Task Manager (Ctrl+Shift+Esc) → Performance → Memory. You can view installed RAM, current use, speed and sometimes slot information. Slot counts are not proof that a physical upgrade is possible.'),
 (r'\b(?:how (?:do|can) i|how to|where (?:do|can) i)\b.*\b(?:check|find|see|view)\b.*\b(?:storage|disk space|free space|c: drive)\b',
  'Open Settings → System → Storage to see space used on C:. PC Medic Storage Explorer can help identify large files. Review before deleting anything; avoid manually removing Windows system files.'),
 (r'\b(?:how (?:do|can) i|how to)\b.*\b(?:update|install)\b.*\b(?:windows|drivers?)\b',
  'For Windows updates, open Settings → Windows Update → Check for updates. For drivers, prefer Windows Update optional updates or the PC manufacturer’s official support page. Do not use random driver-download sites.'),
 (r'\b(?:what is|what does|explain)\b.*\b(?:event viewer|event log|event id)\b',
  'Windows Event Viewer records system, application and security events. An error entry is not automatically a fault. PC Medic looks at source, timing, frequency and related symptoms before prioritizing an event.'),
 (r'\b(?:what is|what does|explain)\b.*\b(?:cpu|processor)\b',
  'The CPU runs instructions for Windows and applications. High CPU use during a brief task can be normal; sustained high use with slowdowns deserves investigation.'),
]

def lookup(question):
    q=' '.join(question.lower().split())
    for pattern, answer in TOPICS:
        if re.search(pattern, q, re.I):
            return answer + '\n\nNo diagnostic was needed. This answer is from PC Medic’s offline Windows knowledge base.'
    return None
