import json

with open('results/demo_86_rows.json', 'r', encoding='utf-8') as f:
    rows = json.load(f)

print(f"Total rows: {len(rows)}")

status_counts = {}
for r in rows:
    st = r['statusText']
    status_counts[st] = status_counts.get(st, 0) + 1

print("\n=== STATUS DISTRIBUTION ===")
for st, cnt in status_counts.items():
    print(f"  {st}: {cnt}")

print("\n=== ITEMS WITH FINANCIAL RISK OR DIFFERENCES ===")
diff_items = [r for r in rows if r['status'] == 'diff' or r['risk'] != '0 ₽']
for d in diff_items:
    print(f"#{d['id']} | VOR: {d['vor'][:40]} | LSR: {d['lsr'][:40]} | Qty: {d['vv']} -> {d['lv']} | Sim: {d['sim']}% | Status: {d['statusText']} | Risk: {d['risk']}")

print("\n=== SAMPLE ITEMS REQUIRING VERIFICATION (status: part) ===")
part_items = [r for r in rows if r['status'] == 'part']
for p in part_items[:8]:
    print(f"#{p['id']} | VOR: {p['vor'][:40]} | LSR: {p['lsr'][:40]} | Qty: {p['vv']} -> {p['lv']} | Sim: {p['sim']}% | Reason: {p['reason'][:60]}")

print("\n=== CHECKING REASONING TEXTS ===")
for r in rows[:5]:
    print(f"Row #{r['id']}:")
    print(f"  VOR: {r['vor']}")
    print(f"  LSR: {r['lsr']} (Code: {r['code']})")
    print(f"  Reason: {r['reason']}")
