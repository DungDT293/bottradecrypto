"""Rank 30-day Trade-folder signals using Binance public historical archives.
No authenticated calls, no account/order endpoints, no runtime DB writes.
"""
from __future__ import annotations
import csv, io, json, time, zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]; AUD=ROOT/'audit_output'/'telegram_understanding_20261020T171249Z'
SRC=AUD/'MESSAGES_CLASSIFIED.jsonl'; CACHE=AUD/'binance_archive_cache'; CACHE.mkdir(exist_ok=True)
OUT=AUD/'BINANCE_RANKING_FINAL.md'; JSON_OUT=AUD/'BINANCE_RANKING_FINAL.json'
ARCH='https://data.binance.vision/data/futures/um/daily'


def rows_archive(symbol,kind,interval,day):
    name=f'{symbol}_{kind}_{interval}_{day}.json'; path=CACHE/name
    if path.exists(): return json.loads(path.read_text())
    folder='klines' if kind=='contract' else 'markPriceKlines'; fn=f'{symbol}-{interval}-{day}.zip'; url=f'{ARCH}/{folder}/{symbol}/{interval}/{fn}'
    req=Request(url,method='GET',headers={'User-Agent':'trade-audit-archive/1.0'})
    try:
        with urlopen(req,timeout=60) as r:data=r.read()
        z=zipfile.ZipFile(io.BytesIO(data)); raw=z.read(z.namelist()[0]); out=[]
        for row in csv.DictReader(io.StringIO(raw.decode('utf-8'))):
            out.append([int(row['open_time']),row['open'],row['high'],row['low'],row['close']])
        path.write_text(json.dumps(out),encoding='utf-8'); return out
    except HTTPError:
        path.write_text('[]',encoding='utf-8'); return []

def parse_signals():
    out=[];seen=set()
    for line in SRC.open(encoding='utf-8'):
        x=json.loads(line);c=x.get('classification') or {};k=(x.get('chat_id'),x.get('message_id'))
        if k in seen or c.get('category')!='SIGNAL' or c.get('side') not in ('LONG','SHORT') or not c.get('symbol') or not c.get('entries') or not c.get('stop_loss') or not c.get('take_profits'):continue
        seen.add(k);out.append(x)
    return out

def ts(x):return int(datetime.fromisoformat(x['telegram_timestamp'].replace('Z','+00:00')).timestamp()*1000)
def day_ms(d):return int(datetime(d.year,d.month,d.day,tzinfo=timezone.utc).timestamp()*1000)
def days_between(a,b):
 d=datetime.fromtimestamp(a/1000,timezone.utc).date();e=datetime.fromtimestamp(b/1000,timezone.utc).date()
 while d<=e:yield d;d+=timedelta(days=1)
def flatten(symbol,kind,interval,start,end):
 out=[]
 for d in days_between(start,end):out+=rows_archive(symbol,kind,interval,d.isoformat())
 return sorted(out,key=lambda x:x[0])

def replay(x, contract, mark):
 c=x['classification'];side=c['side'];vals=[Decimal(str(v)) for v in c['entries']];a=min(vals);b=max(vals);sl=Decimal(str(c['stop_loss']));tp=Decimal(str(c['take_profits'][0]));m={int(k[0]):(Decimal(str(k[2])),Decimal(str(k[3]))) for k in mark};entered=False
 for k in contract:
  t=int(k[0]);hi=Decimal(str(k[2]));lo=Decimal(str(k[3]));mh,ml=m.get(t,(hi,lo))
  if not entered:
   if lo<=b and hi>=a:entered=True
   else:continue
  hsl=ml<=sl if side=='LONG' else mh>=sl;htp=hi>=tp if side=='LONG' else lo<=tp
  if hsl and htp:return 'UNKNOWN','SAME_MINUTE_TP_SL'
  if htp:return 'WIN','TP1_BEFORE_SL'
  if hsl:return 'LOSS','MARK_SL_BEFORE_TP'
 return ('UNKNOWN','ENTRY_MISSED' if not entered else 'NO_TERMINAL_HIT')

def main():
 signals=parse_signals(); symbols=defaultdict(list)
 for x in signals:symbols[x['classification']['symbol']].append(x)
 candidates=[];results=[]
 # 15m screen per symbol/day, fetched from static Binance archive.
 for symbol,items in symbols.items():
  start=min(ts(x) for x in items);end=min(max(ts(x) for x in items)+72*3600*1000,int(datetime.now(timezone.utc).timestamp()*1000))
  screen=flatten(symbol,'contract','15m',start,end)
  for x in items:
   c=x['classification'];vals=[Decimal(str(v)) for v in c['entries']];a=min(vals);b=max(vals);t=ts(x)
   if any(int(k[0])>=t and Decimal(str(k[3]))<=b and Decimal(str(k[2]))>=a for k in screen):candidates.append(x)
   else:results.append({'status':'UNKNOWN','reason':'ENTRY_MISSED','chat_id':x['chat_id'],'chat_title':x['chat_title'],'message_id':x['message_id'],'symbol':symbol})
 print('signals',len(signals),'entry_candidates',len(candidates),'missed',len(results),flush=True)
 def one(x):
  start=ts(x);end=min(start+72*3600*1000,int(datetime.now(timezone.utc).timestamp()*1000));symbol=x['classification']['symbol']
  try:return x,replay(x,flatten(symbol,'contract','1m',start,end),flatten(symbol,'mark','1m',start,end))
  except Exception as e:return x,('UNKNOWN',f'FETCH_{type(e).__name__}')
 with ThreadPoolExecutor(max_workers=8) as ex:
  for i,f in enumerate(as_completed([ex.submit(one,x) for x in candidates]),1):
   x,(st,reason)=f.result();results.append({'status':st,'reason':reason,'chat_id':x['chat_id'],'chat_title':x['chat_title'],'message_id':x['message_id'],'symbol':x['classification']['symbol']})
   if i%25==0:print('exact',i,'/',len(candidates),flush=True)
 agg=defaultdict(lambda:{'chat_title':'','valid_signals':0,'WIN':0,'LOSS':0,'UNKNOWN':0,'ENTRY_MISSED':0})
 for r in results:d=agg[str(r['chat_id'])];d['chat_title']=r.get('chat_title','');d['valid_signals']+=1;d[r['status']]+=1
 table=[]
 for cid,d in agg.items():den=d['WIN']+d['LOSS'];rate=round(d['WIN']/den*100,2) if den else None;table.append({'chat_id':cid,**d,'win_rate_estimate_pct':rate,'rating':'Nên theo dõi' if den>=10 and rate is not None and rate>=55 else 'Cần đánh giá thêm'})
 table.sort(key=lambda z:(z['win_rate_estimate_pct'] is not None,z['win_rate_estimate_pct'] or -1),reverse=True)
 payload={'generated_utc':datetime.now(timezone.utc).isoformat(),'method':'Binance data.binance.vision: 15m contract screen + 1m contract + 1m mark; 72h; same-minute UNKNOWN','input_signals':len(signals),'results':len(results),'ranking':table,'details':results};JSON_OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
 lines=['# Xếp hạng Trade-folder — Binance Futures','', '| Tên nhóm | Signal | Win | Loss | Unknown/Miss | Win Rate | Đánh giá |','|---|---:|---:|---:|---:|---:|---|']
 for d in table:lines.append(f"| {d['chat_title']} | {d['valid_signals']} | {d['WIN']} | {d['LOSS']} | {d['UNKNOWN']+d['ENTRY_MISSED']} | {d['win_rate_estimate_pct'] if d['win_rate_estimate_pct'] is not None else 'UNKNOWN'} | {d['rating']} |")
 OUT.write_text('\n'.join(lines)+'\n',encoding='utf-8');print(OUT)
if __name__=='__main__':main()
