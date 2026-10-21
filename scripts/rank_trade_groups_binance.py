"""Rank Trade-folder Telegram signals against Binance Futures price history.

Public read-only endpoints only. No account/order endpoints and no runtime DB writes.
"""
from __future__ import annotations
import json, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'audit_output'/'telegram_understanding_20261020T171249Z'/'MESSAGES_CLASSIFIED.jsonl'
OUT=ROOT/'audit_output'/'telegram_understanding_20261020T171249Z'/'BINANCE_RANKING.md'
JSON_OUT=ROOT/'audit_output'/'telegram_understanding_20261020T171249Z'/'BINANCE_RANKING.json'
BASE='https://fapi.binance.com/fapi/v1'

def get(path, params):
    req=Request(BASE+path+'?'+urlencode(params), headers={'User-Agent':'trade-audit-readonly/1.0'})
    with urlopen(req, timeout=30) as r: return json.loads(r.read())

def valid_symbols():
    return {x['symbol'] for x in get('/exchangeInfo',{})['symbols'] if x.get('status')=='TRADING' and x.get('quoteAsset')=='USDT'}

def fetch(symbol, interval, start, end):
    out=[]; cur=start
    while cur<end:
        rows=get('/markPriceKlines' if interval=='mark' else '/klines', {'symbol':symbol,'interval':'1m' if interval=='mark' else '15m','startTime':cur,'endTime':end,'limit':1500})
        if not rows: break
        out.extend(rows); nxt=int(rows[-1][0])+60000*(1 if interval=='mark' else 15)
        if nxt<=cur or len(rows)<1500: break
        cur=nxt; time.sleep(.02)
    return out

def parse_rows():
    rows=[]
    for line in SRC.open(encoding='utf-8'):
        x=json.loads(line); c=x.get('classification') or {}
        if c.get('category')!='SIGNAL' or c.get('side') not in ('LONG','SHORT') or not c.get('symbol') or not c.get('entries') or not c.get('stop_loss') or not c.get('take_profits'): continue
        rows.append(x)
    seen=set(); out=[]
    for x in rows:
        k=(x['chat_id'],x['message_id'])
        if k not in seen: seen.add(k); out.append(x)
    return out

def replay(signal, contract, mark):
    c=signal['classification']; side=c['side']; entry_vals=[Decimal(str(v)) for v in c['entries']]; lo_entry=min(entry_vals); hi_entry=max(entry_vals); sl=Decimal(str(c['stop_loss'])); tp=Decimal(str(c['take_profits'][0])); entered=False
    marks={int(k[0]):(Decimal(str(k[2])),Decimal(str(k[3]))) for k in mark}
    for k in contract:
        t=int(k[0]); hi=Decimal(str(k[2])); lo=Decimal(str(k[3])); mh,ml=marks.get(t,(hi,lo))
        if not entered:
            if hi>=lo_entry and lo<=hi_entry: entered=True
            else: continue
        hit_sl=(ml<=sl) if side=='LONG' else (mh>=sl); hit_tp=(hi>=tp) if side=='LONG' else (lo<=tp)
        if hit_sl and hit_tp:return 'UNKNOWN','SAME_MINUTE_TP_SL'
        if hit_tp:return 'WIN','TP1_BEFORE_SL'
        if hit_sl:return 'LOSS','MARK_SL_BEFORE_TP'
    return ('UNKNOWN','ENTRY_MISSED' if not entered else 'NO_TERMINAL_HIT')

def main():
    symbols=valid_symbols(); signals=parse_rows(); now=int(datetime.now(timezone.utc).timestamp()*1000); groups=defaultdict(list)
    for s in signals: groups[s['classification']['symbol']].append(s)
    # Fetch one 15m screen per symbol over its signal span, then exact 1m/mark only for entry-reached candidates.
    screen={}; invalid=[]
    for symbol,items in groups.items():
        if symbol not in symbols: invalid.extend(items); continue
        times=[int(datetime.fromisoformat(x['telegram_timestamp'].replace('Z','+00:00')).timestamp()*1000) for x in items]
        start=min(times); end=min(max(times)+72*3600*1000,now)
        try: screen[symbol]=fetch(symbol,'15m',start,end)
        except Exception: screen[symbol]=[]
    results=[]
    for s in invalid: results.append({'status':'UNKNOWN','reason':'SYMBOL_NOT_TRADING_USDT','chat_id':s['chat_id'],'chat_title':s['chat_title'],'message_id':s['message_id'],'symbol':s['classification']['symbol']})
    candidates=[]
    for symbol,items in groups.items():
        if symbol not in symbols: continue
        candles=screen.get(symbol,[])
        for s in items:
            c=s['classification']; vals=[Decimal(str(v)) for v in c['entries']]; loe=min(vals); hie=max(vals); ts=int(datetime.fromisoformat(s['telegram_timestamp'].replace('Z','+00:00')).timestamp()*1000); entered=any(int(k[0])>=ts and Decimal(str(k[2]))>=loe and Decimal(str(k[3]))<=hie for k in candles)
            if not entered: results.append({'status':'UNKNOWN','reason':'ENTRY_MISSED','chat_id':s['chat_id'],'chat_title':s['chat_title'],'message_id':s['message_id'],'symbol':symbol}); continue
            candidates.append(s)
    def exact(s):
        c=s['classification']; ts=int(datetime.fromisoformat(s['telegram_timestamp'].replace('Z','+00:00')).timestamp()*1000); end=min(ts+72*3600*1000,now); symbol=c['symbol']
        try:return s,replay(s,fetch(symbol,'1m',ts,end),fetch(symbol,'mark',ts,end))
        except Exception as e:return s,('UNKNOWN',f'FETCH_ERROR:{type(e).__name__}')
    with ThreadPoolExecutor(max_workers=4) as ex:
        fs=[ex.submit(exact,s) for s in candidates]
        for i,f in enumerate(as_completed(fs),1):
            s,(status,reason)=f.result(); results.append({'status':status,'reason':reason,'chat_id':s['chat_id'],'chat_title':s['chat_title'],'message_id':s['message_id'],'symbol':s['classification']['symbol']});
            if i%25==0: print(f'exact {i}/{len(candidates)}',flush=True)
    agg=defaultdict(lambda: {'chat_title':'','valid_signals':0,'WIN':0,'LOSS':0,'UNKNOWN':0,'ENTRY_MISSED':0})
    for r in results:
        d=agg[str(r['chat_id'])];d['chat_title']=r.get('chat_title','');d['valid_signals']+=1;d[r['status']]=d.get(r['status'],0)+1
    table=[]
    for cid,d in agg.items():
        den=d['WIN']+d['LOSS'];rate=round(d['WIN']/den*100,2) if den else None; d['win_rate_estimate_pct']=rate;d['rating']='Nên theo dõi' if den>=10 and rate is not None and rate>=55 else 'Cần đánh giá thêm';table.append({'chat_id':cid,**d})
    table.sort(key=lambda x:(x['win_rate_estimate_pct'] is not None,x['win_rate_estimate_pct'] or -1),reverse=True)
    payload={'generated_utc':datetime.now(timezone.utc).isoformat(),'window_days':30,'method':'15m entry screen + 1m contract + 1m mark; 72h; same-minute TP/SL UNKNOWN','valid_input_signals':len(signals),'results':len(results),'ranking':table,'results_detail':results};JSON_OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Xếp hạng 18 nhóm — Binance Futures','', '| Tên Nhóm | Signal hợp lệ | Win | Loss | Unknown / Miss Entry | Win Rate (%) | Đánh giá |','|---|---:|---:|---:|---:|---:|---|']
    for d in table:lines.append(f"| {d['chat_title']} | {d['valid_signals']} | {d['WIN']} | {d['LOSS']} | {d['UNKNOWN']+d['ENTRY_MISSED']} | {d['win_rate_estimate_pct'] if d['win_rate_estimate_pct'] is not None else 'UNKNOWN'} | {d['rating']} |")
    OUT.write_text('\n'.join(lines)+'\n',encoding='utf-8');print(OUT)
if __name__=='__main__':main()
