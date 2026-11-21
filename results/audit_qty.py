import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from parsers import parse_vor, parse_lsr
import match

vor = parse_vor('data/ВОР.xlsx')
lsr = parse_lsr('data/ЛСР.xlsx')
res = match.match(vor, lsr, thr=0.50, min_text_threshold=0.20)

count = 0
for i, item in enumerate(res):
    cand = item.get('candidate')
    if cand and not cand.qty_matched:
        count += 1
        v = item.get('vor_item')
        l = cand.lsr_item
        cls = item.get('cls')
        exp = item.get('explanation')
        print(f"#{i+1}: VOR '{v.name[:35]}' ({v.qty} {v.unit}) vs LSR '{l.name[:35]}' ({l.qty} {l.unit})")
        print(f"   cls: {cls} | exp: {exp}\n")

print(f"Total volume discrepancies: {count}")
