"""
CLI wrapper around select_expiration.select_expiration(), for the live
signal-monitor triggers to call directly instead of eyeballing "the
nearest expiration" (2026-09-06).

Usage (live pipeline):
  python3 resolve_expiration.py --expirations-json '["2026-09-11","2026-09-18","2026-10-16"]'
(or --expirations-file <path to the same JSON array>)

Prints one line of JSON:
  {"expiration": "YYYY-MM-DD" | null, "method": "...", "note": "..."}
Exit code is always 0 -- a rejection ("nothing far enough out") is a
valid, expected outcome, not a script error; the caller checks the
"expiration" field (null => log signal-only and stop).
"""
import argparse, json, sys
sys.path.insert(0, '/home/claude/smc_bot')
sys.path.insert(0, '/home/claude/smc_bot/diag/backtest')
from select_expiration import select_expiration

p = argparse.ArgumentParser()
p.add_argument('--expirations-json', help='JSON array of available "YYYY-MM-DD" expiration strings, inline')
p.add_argument('--expirations-file', help='path to a JSON file containing the same array')
args = p.parse_args()

if not args.expirations_json and not args.expirations_file:
    print(json.dumps({"expiration": None, "method": "ERROR",
                      "note": "must pass --expirations-json or --expirations-file"}))
    sys.exit(0)

if args.expirations_file:
    expirations = json.load(open(args.expirations_file))
else:
    expirations = json.loads(args.expirations_json)

exp, method, note = select_expiration(expirations)
print(json.dumps({"expiration": exp, "method": method, "note": note}))
