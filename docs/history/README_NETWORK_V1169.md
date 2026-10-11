# PC Medic V1.16.9 — Offline network questions

This build adds a read-only Windows network configuration collector (`network_advisor.py`) and a local `/api/network-info` endpoint. Ask PC Medic can now answer questions about the local IP address, DNS servers, DHCP, gateway, subnet mask, IPv6, MAC address, and `ipconfig /all`-style configuration without a performance scan. It uses CIM data analogous to the configuration displayed by `ipconfig /all`, not the raw command output. No `ipconfig /release`, `/renew`, `/flushdns`, or other mutating operations are executed.

Local adapter addresses and MAC addresses are sensitive; do not share screenshots or reports publicly without redaction. Public IP lookup requires an external service and is not implemented.

Test on Windows: ask `What is my IP address?`, `Show ipconfig /all`, `What DNS servers am I using?`, `What is my default gateway?`, and `Is DHCP enabled?`. If the computer has multiple active adapters, the answer lists them separately.
