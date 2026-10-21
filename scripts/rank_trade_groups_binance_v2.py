"""Rate-limited, cached Binance chart replay for 30-day Telegram signals.
Public read-only endpoints only. Never uses account/order endpoints.
"""
from __future__ import annotations
import json, time, hashlib
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]
AUD=ROOT/'audit_output'/'telegram_understanding_20261020T171249Z'
SRC=AUD/'MESSAGES_CLASSIFIED.jsonl'; REPORT=AUD/'COLLECTION_REPORT.json'
OUT=AUD/'BINANCE_RANKING_FINAL.md'; JSON_OUT=AUD/'BINANCE_RANKING_FINAL.json'
CACHE=AUD/'binance_replay_cache'; CACHE.mkdir(exist_ok=True)
BASE='https://fapi.binance.com/fapi/v1'; THROTTLE=0.35


def request(path, params):
    time.sleep(THROTTLE)
    req=Request(BASE+path+'?'+urlencode(params),headers={'User-Agent':'trade-audit-readonly/2.0'})
    with urlopen(req,timeout=40) as r:return json.loads(r.read())

def cached(symbol, kind, day, start, end):
    name=f'{symbol}_{kind}_{day}.json'; path=CACHE/name
    if path.exists(): return json.loads(path.read_text())
    url='/markPriceKlines' if kind=='mark' else '/klines'; interval='1m' if kind=='mark' else '15m'
    out=[]; cur=start
    try:
        while cur<end:
            rows=request(url,{'symbol':symbol,'interval':interval,'startTime':cur,'endTime':end,'limit':1500})
            if not rows: break
            out.extend(rows); step=60000 if interval=='1m' else 900000; nxt=int(rows[-1][0])+step
            if nxt<=cur or len(rows)<1500: break
            cur=nxt
        path.write_text(json.dumps(out),encoding='utf-8'); return out
    except HTTPError as e:
        raise RuntimeError(f'HTTP_{e.code}') from e

def signal_rows():
    out=[]; seen=set()
    for line in SRC.open(encoding='utf-8'):
        x=json.loads(line); c=x.get('classification') or {}; k=(x.get('chat_id'),x.get('message_id'))
        if k in seen or c.get('category')!='SIGNAL' or c.get('side') not in ('LONG','SHORT') or not c.get('symbol') or not c.get('entries') or not c.get('stop_loss') or not c.get('take_profits'):continue
        seen.add(k); out.append(x)
    return out

def tms(x): return int(datetime.fromisoformat(x['telegram_timestamp'].replace('Z','+00:00')).timestamp()*1000)

def main():
    rows=signal_rows(); valid=set()
    for line in json.loads(REPORT.read_text())['chats']: valid.add(line['chat_id'])
    groups=defaultdict(list)
    for x in rows: groups[x['classification']['symbol']].append(x)
    symbols=set(x['symbol'] for x in json.loads(request('/exchangeInfo',{}).get('symbols',[])) if x.get('status')=='TRADING' and x.get('quoteAsset')=='USDT')
    # Screen all symbols with cached 15m chunks, no per-signal repeated requests.
    screen={}; candidates=[]
    for symbol, items in groups.items():
        if symbol not in symbols: continue
        lo=min(tms(x) for x in items); hi=min(max(tms(x) for x in items)+72*3600*1000,int(datetime.now(timezone.utc).timestamp()*1000))
        rows15=[]; cur=datetime.fromtimestamp(lo/1000,timezone.utc).date()
        last=datetime.fromtimestamp(hi/1000,timezone.utc).date()
        while cur<=last:
            s=int(datetime(cur.year,cur.month,cur.day,tzinfo=timezone.utc).timestamp()*1000); e=s+24*3600*1000
            rows15 += cached(symbol,'screen',cur.isoformat(),s,e); cur+=timedelta(days=1)
        screen[symbol]=rows15
        for x in items:
            c=x['classification']; vals=[Decimal(str(v)) for v in c['entries']]; a=min(vals); b=max(vals); ts=tms(x)
            if any(int(k[0])>=ts and Decimal(str(k[2]))>=a and Decimal(str(k[3]))<=b for k in rows15): candidates.append(x)
    results=[]
    for x in rows:
        c=x['classification']; symbol=c['symbol']
        if symbol not in symbols: results.append({'status':'UNKNOWN','reason':'SYMBOL_NOT_TRADING_USDT','chat_id':x['chat_id'],'chat_title':x['chat_title'],'message_id':x['message_id'],'symbol':symbol})
        elif x not in candidates: results.append({'status':'UNKNOWN','reason':'ENTRY_MISSED','chat_id':x['chat_id'],'chat_title':x['chat_title'],'message_id':x['message_id'],'symbol':symbol})
    for ix,x in enumerate(candidates,1):
        c=x['classification']; symbol=c['symbol']; ts=tms(x); end=min(ts+72*3600*1000,int(datetime.now(timezone.utc).timestamp()*1000)); day=datetime.fromtimestamp(ts/1000,timezone.utc).date(); last=datetime.fromtimestamp(end/1000,timezone.utc).date(); contract=[];mark=[]
        try:
            cur=day
            while cur<=last:
                s=int(datetime(cur.year,cur.month,cur.day,tzinfo=timezone.utc).timestamp()*1000);e=s+24*3600*1000;contract+=cached(symbol,'exact',cur.isoformat(),s,e);mark+=cached(symbol,'mark',cur.isoformat(),s,e);cur+=timedelta(days=1)
            mc={int(k[0]):(Decimal(str(k[2])),Decimal(str(k[3]))) for k in mark}; vals=[Decimal(str(v)) for v in c['entries']];entry_min=min(vals);entry_max=max(vals);sl=Decimal(str(c['stop_loss']));tp=Decimal(str(c['take_profits'][0]));entered=False; status='UNKNOWN';reason='NO_TERMINAL_HIT'
            for k in sorted(contract,key=lambda z:int(z[0])):
                t=int(k[0]);hi=Decimal(str(k[2]));lo=Decimal(str(k[3]));mh,ml=mc.get(t,(hi,lo))
                if not entered:
                    if lo<=entry_max and hi>=entry_min: entered=True
                    else:continue
                hsl=ml<=sl if c['side']=='LONG' else mh>=sl; htp=hi>=tp if c['side']=='LONG' else lo<=tp
                if hsl and htp:status='UNKNOWN';reason='SAME_MINUTE_TP_SL';break
                if htp:status='WIN';reason='TP1_BEFORE_SL';break
                if hsl:status='LOSS';reason='MARK_SL_BEFORE_TP';break
            results.append({'status':status,'reason':reason,'chat_id':x['chat_id'],'chat_title':x['chat_title'],'message_id':x['message_id'],'symbol':symbol})
        except Exception as e: results.append({'status':'UNKNOWN','reason':f'FETCH_{e}','chat_id':x['chat_id'],'chat_title':x['chat_title'],'message_id':x['message_id'],'symbol':symbol})
        if ix%25==0:print(f'exact {ix}/{len(candidates)}',flush=True)
    agg=defaultdict(lambda:{'chat_title':'','valid_signals':0,'WIN':0,'LOSS':0,'UNKNOWN':0,'ENTRY_MISSED':0})
    for r in results:d=agg[str(r['chat_id'])];d['chat_title']=r.get('chat_title','');d['valid_signals']+=1;d[r['status']]+=1
    table=[]
    for cid,d in agg.items():den=d['WIN']+d['LOSS'];rate=round(d['WIN']/den*100,2) if den else None;table.append({'chat_id':cid,**d,'win_rate_estimate_pct':rate,'rating':'Nên theo dõi' if den>=10 and rate is not None and rate>=55 else 'Cần đánh giá thêm'})
    table.sort(key=lambda z:(z['win_rate_estimate_pct'] is not None,z['win_rate_estimate_pct'] or -1),reverse=True)
    payload={'generated_utc':datetime.now(timezone.utc).isoformat(),'method':'cached 15m screen + cached 1m contract/mark; 72h; same-minute UNKNOWN','input_signals':len(rows),'results':len(results),'ranking':table,'details':results};JSON_OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Xếp hạng Trade-folder — Binance Futures','', '| Tên nhóm | Signal | Win | Loss | Unknown/Miss | Win Rate | Đánh giá |','|---|---:|---:|---:|---:|---:|---|']
    for d in table:lines.append(f"| {d['chat_title']} | {d['valid_signals']} | {d['WIN']} | {d['LOSS']} | {d['UNKNOWN']+d['ENTRY_MISSED']} | {d['win_rate_estimate_pct'] if d['win_rate_estimate_pct'] is not None else 'UNKNOWN'} | {d['rating']} |")
    OUT.write_text('\n'.join(lines)+'\n',encoding='utf-8');print(OUT)
if __name__=='__main__':main()
