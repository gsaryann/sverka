"""Build and evaluate code-derived ground truth for the boiler-room pair."""
import csv
import sys
from collections import defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import openpyxl
import match
import baseline_legacy
from parsers import parse_vor, parse_lsr
from evaluate import evaluate

VOR = ROOT / 'data/Приложение №2.3.1 Ведомость объемов работ №2.xlsx'
LSR = ROOT / 'data/Приложение №2.3 Локальный сметный расчет №2.xlsx'
OUT = ROOT / 'data/real_truth/pair_2_3_truth.csv'

def load_truth(path=OUT):
    """Read the emitted CSV into evaluate.evaluate() input records."""
    vor, lsr = parse_vor(str(VOR)), parse_lsr(str(LSR))
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        rows=list(csv.DictReader(f))
    return [dict(vor=(r['vor_num'].strip() or None), lsr=(r['lsr_num'].strip() or None), cls='Совпало') for r in rows]

def build():
    vor, lsr = parse_vor(str(VOR)), parse_lsr(str(LSR))
    wb = openpyxl.load_workbook(VOR, data_only=True); ws = wb[wb.sheetnames[0]]
    raw = {str(int(r[0])) if isinstance(r[0], (int,float)) else str(r[0]).strip(): str(r[4]).strip()
           for r in ws.iter_rows(min_row=8, values_only=True) if r[0] is not None and r[4]}
    wb.close()
    bycode = defaultdict(deque)
    for item in lsr: bycode[item.code.strip()].append(item)
    truth=[]; ambiguous=[]; pred_truth=[]
    for v in vor:
        code=raw.get(v.num,'').strip()
        candidates=bycode.get(code)
        if not candidates:
            ambiguous.append((v.num, code, 'код не найден')); continue
        l=candidates.popleft()
        # Repeated codes are paired in document order; record evidence for human audit.
        comment=f"код={code}; name_equal={v.name.strip().casefold()==l.name.strip().casefold()}; qty={v.qty} {v.unit} / {l.qty} {l.unit}"
        truth.append(dict(vor=v.num,lsr=l.num,cls='Совпало'))
        pred_truth.append((v.num,l.num,comment))
        if v.name.strip().casefold()!=l.name.strip().casefold(): ambiguous.append((v.num,code,'названия различаются'))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with OUT.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f); w.writerow(['vor_num','lsr_num','comment']); w.writerows(pred_truth)
    truth=load_truth()
    for l in lsr:
        if not any(t['lsr']==l.num for t in truth): truth.append(dict(vor=None,lsr=l.num,cls='Нет в ВОР'))
    for name,pred in [('SmartMatcher',match.match(vor,lsr)),('Legacy',baseline_legacy.match(vor,lsr,thr=.55,w_q=.3,w_o=.4))]:
        r=evaluate(pred,truth,lsr)
        print(name,*(f'{k}={r[k]:.4f}' for k in ('prec','rec','f1','cls_acc')))
        print('Ошибочные пары:',[(p['vor'],p['lsr']) for p in pred if p.get('lsr') and not any(t['vor']==p['vor'] and t['lsr']==p['lsr'] for t in truth)])
    print('Неоднозначные:',ambiguous)
if __name__=='__main__': build()
