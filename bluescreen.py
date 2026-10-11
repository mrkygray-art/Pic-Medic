"""Blue screens: what a stop code means, and which driver a crash dump points to.

parse_event() reads the "rebooted from a bugcheck" event (no admin needed). parse_dump() reads a kernel
minidump (C:\\Windows\\Minidump, readable only as administrator, so the deep scan calls it) and finds the
likely driver the way BlueScreenView does: a bug check parameter that points into a driver, otherwise the
first non-kernel driver on the crash stack. It is a heuristic, so answers say "likely", and anything that
doesn't validate is dropped rather than guessed.
"""
import re
import struct

# code: (name, what happened in plain words, what usually causes it)
STOP_CODES = {
    0x0A: ('IRQL_NOT_LESS_OR_EQUAL', 'A driver touched memory it wasn’t allowed to.', 'driver'),
    0x19: ('BAD_POOL_HEADER', 'Windows found its memory bookkeeping damaged.', 'driver_or_ram'),
    0x1A: ('MEMORY_MANAGEMENT', 'Windows’ memory manager found a serious error.', 'ram'),
    0x1E: ('KMODE_EXCEPTION_NOT_HANDLED', 'A driver hit an error it didn’t handle.', 'driver'),
    0x24: ('NTFS_FILE_SYSTEM', 'The file system ran into a problem reading or writing the drive.', 'disk'),
    0x3B: ('SYSTEM_SERVICE_EXCEPTION', 'A driver failed while Windows was running a system call.', 'driver'),
    0x50: ('PAGE_FAULT_IN_NONPAGED_AREA', 'Something referenced memory that doesn’t exist.', 'driver_or_ram'),
    0x7A: ('KERNEL_DATA_INPAGE_ERROR', 'Windows couldn’t read data back from the drive into memory.', 'disk'),
    0x7B: ('INACCESSIBLE_BOOT_DEVICE', 'Windows lost access to the drive it starts from.', 'boot'),
    0x7E: ('SYSTEM_THREAD_EXCEPTION_NOT_HANDLED', 'A driver hit an error it didn’t handle.', 'driver'),
    0x7F: ('UNEXPECTED_KERNEL_MODE_TRAP', 'The processor raised an error Windows couldn’t recover from.', 'hardware'),
    0x9C: ('MACHINE_CHECK_EXCEPTION', 'The processor reported a hardware error.', 'hardware'),
    0x9F: ('DRIVER_POWER_STATE_FAILURE', 'A driver didn’t respond while the PC was going to sleep, waking up or shutting down.', 'driver_power'),
    0xA0: ('INTERNAL_POWER_ERROR', 'Windows’ power management hit a fatal error.', 'power'),
    0xA5: ('ACPI_BIOS_ERROR', 'The firmware (BIOS/UEFI) gave Windows power information it couldn’t use.', 'bios'),
    0xBE: ('ATTEMPTED_WRITE_TO_READONLY_MEMORY', 'A driver tried to write to protected memory.', 'driver'),
    0xC2: ('BAD_POOL_CALLER', 'A driver misused Windows’ memory pool.', 'driver'),
    0xC4: ('DRIVER_VERIFIER_DETECTED_VIOLATION', 'Driver Verifier caught a driver breaking the rules.', 'verifier'),
    0xC5: ('DRIVER_CORRUPTED_EXPOOL', 'A driver damaged Windows’ memory pool.', 'driver'),
    0xD1: ('DRIVER_IRQL_NOT_LESS_OR_EQUAL', 'A driver touched memory it wasn’t allowed to.', 'driver'),
    0xE2: ('MANUALLY_INITIATED_CRASH', 'Someone triggered this crash on purpose (a keyboard shortcut or debugger).', 'manual'),
    0xEA: ('THREAD_STUCK_IN_DEVICE_DRIVER', 'The graphics driver got stuck waiting for the graphics card.', 'graphics'),
    0xEF: ('CRITICAL_PROCESS_DIED', 'A process Windows can’t run without stopped.', 'system'),
    0xF4: ('CRITICAL_OBJECT_TERMINATION', 'A process Windows can’t run without ended, often because the drive stopped responding.', 'disk'),
    0xFC: ('ATTEMPTED_EXECUTE_OF_NOEXECUTE_MEMORY', 'A driver tried to run code from memory marked as data.', 'driver'),
    0x101: ('CLOCK_WATCHDOG_TIMEOUT', 'One processor core stopped responding.', 'hardware'),
    0x109: ('CRITICAL_STRUCTURE_CORRUPTION', 'Windows found its own code or data modified.', 'driver_or_ram'),
    0x116: ('VIDEO_TDR_FAILURE', 'The graphics driver stopped responding and couldn’t be restarted.', 'graphics'),
    0x117: ('VIDEO_TDR_TIMEOUT_DETECTED', 'The graphics driver stopped responding.', 'graphics'),
    0x119: ('VIDEO_SCHEDULER_INTERNAL_ERROR', 'The graphics scheduler found a fatal error.', 'graphics'),
    0x124: ('WHEA_UNCORRECTABLE_ERROR', 'The hardware reported an error it couldn’t correct.', 'hardware'),
    0x12B: ('FAULTY_HARDWARE_CORRUPTED_PAGE', 'Windows found memory that hardware had corrupted.', 'ram'),
    0x133: ('DPC_WATCHDOG_VIOLATION', 'A driver took too long to finish its work.', 'driver_storage'),
    0x139: ('KERNEL_SECURITY_CHECK_FAILURE', 'Windows detected damaged data in its own core.', 'driver_or_ram'),
    0x13A: ('KERNEL_MODE_HEAP_CORRUPTION', 'A driver damaged Windows’ memory heap.', 'driver'),
    0x144: ('BUGCODE_USB3_DRIVER', 'The USB 3 driver hit a fatal error.', 'usb'),
    0x154: ('UNEXPECTED_STORE_EXCEPTION', 'Windows’ memory compression store hit an error, often from the drive.', 'disk'),
}
ADVICE = {
    'driver': 'Usually a driver. Update or roll back drivers installed or updated just before the crashes started (graphics, Wi-Fi, antivirus and VPN drivers are common).',
    'driver_or_ram': 'Usually a driver, sometimes faulty memory. Update recent drivers; if it keeps happening, run Windows Memory Diagnostic.',
    'ram': 'Often faulty or loose memory. Run Windows Memory Diagnostic, and reseat or test the RAM modules.',
    'disk': 'Often the drive or its connection. Check drive health, back up your files, and update the storage driver and SSD firmware.',
    'boot': 'Often a storage driver or BIOS setting change (such as RAID/AHCI mode), or a failing drive. Use Startup Repair from Advanced startup.',
    'hardware': 'Usually hardware: overheating, overclocking, power, or a failing processor or memory. Check temperatures, remove overclocks, and update the BIOS.',
    'driver_power': 'Usually a graphics, Wi-Fi, Bluetooth or USB driver that doesn’t handle sleep well. Update it from the PC or device maker.',
    'power': 'Often a power-management driver or the BIOS. Update the chipset driver and BIOS from the PC maker.',
    'bios': 'Update the BIOS/UEFI firmware from the PC maker’s support site.',
    'verifier': 'Driver Verifier is turned on. Turn it off (verifier /reset, then restart) unless you’re testing drivers on purpose.',
    'manual': 'No fault to fix unless nobody did this on purpose.',
    'graphics': 'Usually the graphics driver, sometimes an overheating or overclocked graphics card. Install the latest driver from the graphics card maker.',
    'system': 'Often damaged Windows system files or a failing drive. Run a deep scan (file check) and check drive health.',
    'driver_storage': 'Often a storage driver or SSD firmware, sometimes graphics. Update the SSD firmware, chipset/storage driver and graphics driver.',
    'usb': 'Usually a USB device or the USB controller driver. Unplug USB devices one at a time and update the chipset driver.',
}
# Kernel and HAL appear on almost every crash stack; the likely cause is the first driver after them.
CORE = {'ntoskrnl.exe', 'ntkrnlmp.exe', 'ntkrnlpa.exe', 'ntkrpamp.exe', 'hal.dll', 'halmacpi.dll', 'halacpi.dll', 'kdcom.dll', 'kd.dll'}
EVENT_RE = re.compile(r'bugcheck was:\s*(0x[0-9a-fA-F]+)\s*\(([^)]*)\)', re.I)
DUMP_RE = re.compile(r'dump was saved in:\s*(\S+?\.dmp)', re.I)


def code_hex(code):
    return f'0x{code:08X}'


def explain(code):
    """{'code','name','meaning','advice'} for a stop code; unknown codes keep the number."""
    name, meaning, kind = STOP_CODES.get(code, (None, None, None))
    return {'code': code_hex(code), 'name': name or 'Unknown stop code', 'meaning': meaning or 'PC Medic doesn’t have this stop code in its list.',
            'advice': ADVICE.get(kind, 'Search the stop code on Microsoft Learn, or ask Claude to interpret it.')}


def parse_event(message):
    """The bugcheck event text -> {'code': int, 'params': [hex], 'dump': file name or None}, or None."""
    m = EVENT_RE.search(message or '')
    if not m:
        return None
    params = [p.strip() for p in m.group(2).split(',') if p.strip()][:4]
    d = DUMP_RE.search(message or '')
    return {'code': int(m.group(1), 16), 'params': params, 'dump': d.group(1).replace('\\', '/').rsplit('/', 1)[-1] if d else None}


# ---------------- minidump reading ----------------
NAME_RE = re.compile(r'^[\w.\-]{1,64}\.(sys|exe|dll)$', re.I)
KERNEL_SPACE = 0xFFFF800000000000


def _u32(b, o):
    return struct.unpack_from('<I', b, o)[0] if 0 <= o <= len(b) - 4 else None


def _u64(b, o):
    return struct.unpack_from('<Q', b, o)[0] if 0 <= o <= len(b) - 8 else None


def _dump_string(b, o):
    """DUMP_STRING: a ULONG length in characters, then UTF-16 text."""
    n = _u32(b, o)
    if n is None or not 0 < n < 260 or o + 4 + 2 * n > len(b):
        return None
    try:
        return b[o + 4:o + 4 + 2 * n].decode('utf-16-le')
    except UnicodeDecodeError:
        return None


def _driver_list(b, triage, rel):
    """[(name, base, size)] from the triage driver list, trying the entry sizes Windows versions use."""
    off, count = _u32(b, triage + 48), _u32(b, triage + 52)
    if off is None or not count or count > 3000:
        return []
    off += rel
    for entry in (0x90, 0x98, 0xA0, 0xA8, 0xB0, 0xB8, 0xC0, 0xC8, 0xD0, 0xE0, 0xF0, 0x100, 0x110, 0x120):
        drivers, bad = [], 0
        for i in range(count):
            e = off + i * entry
            name_off, base, size = _u32(b, e), _u64(b, e + 8 + 0x30), _u32(b, e + 8 + 0x40)
            name = _dump_string(b, name_off + rel) if name_off is not None else None
            if name and NAME_RE.match(name) and base and base >= KERNEL_SPACE and size and 0 < size < 0x20000000:
                drivers.append((name, base, size))
            else:
                bad += 1
                if bad > max(2, count // 10):
                    break
        if drivers and bad <= max(2, count // 10):
            return drivers
    return []


def _stack(b, triage, rel):
    off, size = _u32(b, triage + 40), _u32(b, triage + 44)
    if off is None or not size or size > 0x100000:
        return []
    off += rel
    return [v for v in (_u64(b, off + i) for i in range(0, size - 7, 8)) if v]


def _owner(drivers, address):
    for name, base, size in drivers:
        if base <= address < base + size:
            return name
    return None


def parse_dump(data):
    """Read a 64-bit kernel minidump. Returns {'code','params','build','driver','reason'} or None if it isn't one.
    'driver' is None when PC Medic can't tell; it never guesses from data that doesn't validate."""
    if len(data) < 0x2100 or data[:8] != b'PAGEDU64':
        return None
    code = _u32(data, 0x38)
    params = [_u64(data, 0x40 + 8 * i) for i in range(4)]
    out = {'code': code, 'params': [f'0x{p:016X}' for p in params], 'build': _u32(data, 0x0C), 'driver': None, 'reason': None}
    if _u32(data, 0xF98) != 4:  # 4 = triage (small memory) dump; other kinds don't carry a driver list here
        return out
    triage = 0x2000
    for rel in (0, triage):  # driver and stack offsets are from the file start on current Windows; older dumps used the triage block
        drivers = _driver_list(data, triage, rel)
        if not drivers:
            continue
        for p in params:
            name = _owner(drivers, p) if p and p >= KERNEL_SPACE else None
            if name and name.lower() not in CORE:
                out.update(driver=name, reason='a bug check parameter points into this driver')
                return out
        for value in _stack(data, triage, rel):
            name = _owner(drivers, value) if value >= KERNEL_SPACE else None
            if name and name.lower() not in CORE:
                out.update(driver=name, reason='it is the first driver on the crash stack after the Windows kernel')
                return out
        out['reason'] = 'only Windows kernel code was on the crash stack'
        return out
    return out


def parse_dump_file(path, limit=16 * 1024 * 1024):
    try:
        with open(path, 'rb') as f:
            return parse_dump(f.read(limit))
    except OSError:
        return None
