"""Эталонная копия исходного baseline-алгоритма сопоставления.
Используется для воспроизводимого сравнительного анализа версий.
"""
import re
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from units import to_base

def norm(s):
    s = s.lower().replace('ё', 'е')
    return re.sub(r'[^\w\s\.\-,×x*/]', ' ', s)

def nums(s):
    return sorted(re.findall(r'\d+(?:[.,]\d+)?', s.replace(',', '.')))

def similarity(vor, lsr):
    vec = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), sublinear_tf=True)
    X = vec.fit_transform([norm(x.name) for x in vor + lsr])
    A, B = X[:len(vor)], X[len(vor):]
    return (A @ B.T).toarray()

def classify_pair(v, l, tol=1e-3):
    dv, qv = to_base(v.qty, v.unit)
    dl, ql = to_base(l.qty, l.unit)
    if dv is None or dl is None or dv != dl:
        return 'Расхождение единиц'
    if abs(qv - ql) > tol * max(abs(ql), 1e-9):
        return 'Расхождение объёма'
    if nums(v.name) != nums(l.name):
        return 'Расхождение по сути'
    return 'Совпало'

def qty_matrix(vor, lsr, tol=1e-3):
    M = np.zeros((len(vor), len(lsr)))
    bv = [to_base(x.qty, x.unit) for x in vor]
    bl = [to_base(x.qty, x.unit) for x in lsr]
    for i, (dv, qv) in enumerate(bv):
        for j, (dl, ql) in enumerate(bl):
            if dv is not None and dv == dl and abs(qv - ql) <= tol * max(abs(ql), 1e-9):
                M[i, j] = 1.0
    return M

def order_matrix(nv, nl):
    i = np.arange(nv)[:, None] / max(nv, 1)
    j = np.arange(nl)[None, :] / max(nl, 1)
    return 1 - np.abs(i - j)

def match(vor, lsr, thr=0.55, w_q=0.0, w_o=0.0):
    S = similarity(vor, lsr)
    if w_q:
        S = S + w_q * qty_matrix(vor, lsr)
    if w_o:
        S = S + w_o * order_matrix(len(vor), len(lsr))
    pairs = sorted(((S[i, j], i, j) for i in range(len(vor)) for j in range(len(lsr))), reverse=True)
    vi, lj = {}, {}
    for s, i, j in pairs:
        if s < thr:
            break
        if i in vi or j in lj:
            continue
        vi[i] = j
        lj[j] = i
    res = []
    for i, v in enumerate(vor):
        if i in vi:
            res.append(dict(vor=v.num, lsr=lsr[vi[i]].num, cls=classify_pair(v, lsr[vi[i]]), score=float(S[i, vi[i]])))
            continue
        j = int(S[i].argmax()) if len(lsr) > 0 else -1
        if j >= 0:
            k = lj.get(j)
            if S[i, j] >= thr and k is not None and vor[k].name == v.name and vor[k].unit == v.unit and abs(vor[k].qty - v.qty) < 1e-9:
                res.append(dict(vor=v.num, lsr=lsr[j].num, cls='Дубль', score=float(S[i, j])))
            else:
                res.append(dict(vor=v.num, lsr=None, cls='Нет в рассматриваемой смете', score=float(S[i, j])))
        else:
            res.append(dict(vor=v.num, lsr=None, cls='Нет в рассматриваемой смете', score=0.0))
    for j, l in enumerate(lsr):
        if j not in lj:
            res.append(dict(vor=None, lsr=l.num, cls='Нет в ВОР', score=0.0))
    return res
