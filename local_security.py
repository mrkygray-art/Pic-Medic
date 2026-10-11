"""Only the Windows account that started PC Medic may use it.

On a shared computer (several accounts signed in at once) any account can connect to 127.0.0.1.
For each request, Windows' TCP table tells us which process owns the browser's end of the connection;
that process's account must match ours. Anything we cannot verify is refused.
"""
import ctypes
import os
import socket
from ctypes import wintypes

AF_INET = 2
TCP_TABLE_OWNER_PID_ALL = 5
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_USER = 1


def _port(raw):
    return socket.ntohs(raw & 0xFFFF)


def connection_pid(client_port, server_port):
    """PID of the process that owns the client end of a loopback connection, or None."""
    iphlpapi = ctypes.WinDLL('iphlpapi')
    size = wintypes.DWORD(0)
    iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0)
    for _ in range(3):  # the table can grow between the size query and the read
        buf = ctypes.create_string_buffer(size.value + 4096)
        size = wintypes.DWORD(len(buf))
        if iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(size), False, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0) == 0:
            break
    else:
        return None
    # MIB_TCPTABLE_OWNER_PID: DWORD count, then rows of six DWORDs:
    # state, local addr, local port, remote addr, remote port, owning pid.
    words = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))
    for i in range(words[0]):
        row = 1 + i * 6
        if _port(words[row + 2]) == client_port and _port(words[row + 4]) == server_port:
            return words[row + 5]
    return None


def process_sid(pid):
    """String SID of the account running a process, or None if Windows will not tell us."""
    kernel32, advapi32 = ctypes.WinDLL('kernel32', use_last_error=True), ctypes.WinDLL('advapi32', use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return None  # another account's process: a standard user cannot open it, which is itself a "no"
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            needed = wintypes.DWORD(0)
            advapi32.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(needed))
            info = ctypes.create_string_buffer(needed.value)
            if not advapi32.GetTokenInformation(token, TOKEN_USER, info, needed, ctypes.byref(needed)):
                return None
            sid = ctypes.cast(info, ctypes.POINTER(ctypes.c_void_p))[0]  # TOKEN_USER.User.Sid
            text = wintypes.LPWSTR()
            if not advapi32.ConvertSidToStringSidW(ctypes.c_void_p(sid), ctypes.byref(text)):
                return None
            try:
                return text.value
            finally:
                kernel32.LocalFree(text)
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(process)


_OWN_SID = None


def same_user(client_address, server_port):
    """True when the connecting process runs as the same Windows account as this server."""
    if os.name != 'nt':
        return True
    global _OWN_SID
    try:
        if _OWN_SID is None:
            _OWN_SID = process_sid(os.getpid())
        pid = connection_pid(client_address[1], server_port)
        if pid is None or not _OWN_SID:
            return False
        if pid == os.getpid():
            return True
        return process_sid(pid) == _OWN_SID
    except (OSError, ValueError, AttributeError):
        return False
