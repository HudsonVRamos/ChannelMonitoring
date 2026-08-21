"""Verifica validade dos cookies no storageState."""
import json
import time

with open("temp_state.json") as f:
    data = json.load(f)

cookies = data.get("cookies", [])
print(f"Total cookies: {len(cookies)}")
print()

now = time.time()
expired = 0
valid = 0
session = 0

for c in cookies:
    name = c.get("name", "?")
    domain = c.get("domain", "")
    exp = c.get("expires", -1)

    if exp > 0:
        remaining = exp - now
        if remaining > 0:
            hours = remaining / 3600
            print(f"  VALIDO   {name:35s} ({hours:.1f}h restantes) {domain}")
            valid += 1
        else:
            hours = abs(remaining) / 3600
            print(f"  EXPIRADO {name:35s} (ha {hours:.1f}h) {domain}")
            expired += 1
    else:
        print(f"  SESSION  {name:35s} {domain}")
        session += 1

print()
print(f"Resumo: {valid} validos, {expired} expirados, {session} session-only")
if expired > 0:
    print("ATENCAO: Cookies expirados! Gere um novo storageState.")
