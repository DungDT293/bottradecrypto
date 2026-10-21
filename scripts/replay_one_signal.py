"""Replay one real collected Telegram signal against Binance Futures.
Read-only public klines/mark-price klines. No account/order endpoints.
"""
import json, sys, time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'audit_output'/'telegram_understanding_20261020T171249Z'/'MESSAGES_CLASSIFIED.jsonl'
OUT=ROOT/'audit_output'/'telegram_understanding_20261020T171249Z'/'ONE_SIGNAL_REPLAY.md'
K='https://fapi.binance.com/fapi/v1/klines'; M='https://fapi.binance.com/fapi/v1/markPriceKlines'

def get(url,params):
 r=Request(url+'?'+urlencode(params),headers={'User-Agent':'read-only-replay/1.0'})
 with urlopen(r,timeout=30) as x:return json.loads(x.read())

def candles(url,symbol,start,end):
 out=[]; cur=start
 while cur<end:
  b=get(url,{'symbol':symbol,'interval':'1m','startTime':cur,'endTime':end,'limit':1500})
  if not b:break
  out+=b; nxt=int(b[-1][0])+60000
  if nxt<=cur or len(b)<1500:break
  cur=nxt; time.sleep(.02)
 return out

def main():
 chosen=None
 for line in open(SRC,encoding='utf-8'):
  x=json.loads(line); c=x.get('classification',{})
  if c.get('category')=='SIGNAL' and c.get('symbol') and c.get('side') in ('LONG','SHORT') and c.get('entries') and c.get('stop_loss') and c.get('take_profits') and x['telegram_timestamp'].startswith('2026-10-19'):
   chosen=x;break
 if not chosen:raise SystemExit('No qualifying 2026-10-19 signal found')
 c=chosen['classification']; symbol=c['symbol']; side=c['side']; entry=Decimal(c['entries'][0]); sl=Decimal(c['stop_loss']); tps=[Decimal(x) for x in c['take_profits']]
 ts=datetime.fromisoformat(chosen['telegram_timestamp'].replace('Z','+00:00')); start=int(ts.timestamp()*1000); end=start+72*3600*1000
 price=candles(K,symbol,start,end); mark=candles(M,symbol,start,end); marks={int(x[0]):(Decimal(str(x[2])),Decimal(str(x[3]))) for x in mark}
 log=[]; entered=False; status='UNKNOWN'; be=False; be_sl=None; finish='No terminal event'
 for k in price:
  t=int(k[0]); hi=Decimal(str(k[2]));lo=Decimal(str(k[3])); mh,ml=marks.get(t,(hi,lo)); dt=datetime.fromtimestamp(t/1000,timezone.utc).isoformat()
  if not entered:
   if lo<=entry<=hi:entered=True;log.append((dt,'ENTRY_FILLED',f'Contract range {lo}..{hi} quét Entry {entry}'))
   continue
  hit_sl=(ml<=sl) if side=='LONG' else (mh>=sl); hit_tp=(hi>=min(tps)) if side=='LONG' else (lo<=max(tps))
  if hit_sl and hit_tp:status='UNKNOWN';finish='Cùng nến chạm TP và SL';log.append((dt,'UNKNOWN',f'contract {lo}..{hi}; mark {ml}..{mh}'));break
  if hit_tp:
   tp1=min(tps) if side=='LONG' else max(tps);be_sl=entry*(Decimal('1.0005') if side=='LONG' else Decimal('0.9995'));be=True;log.append((dt,'TP1_BE',f'TP1 {tp1}; dời SL giả lập về {be_sl}'));continue
  if be and ((ml<=be_sl) if side=='LONG' else (mh>=be_sl)):
   status='WIN';finish='TP1 đã chạm, phần còn lại dời BE và bị đóng';log.append((dt,'BE_EXIT',f'Mark chạm BE {be_sl}'));break
  if hit_sl:status='LOSS';finish='Mark price chạm SL trước TP';log.append((dt,'SL_EXIT',f'Mark {ml}..{mh} chạm SL {sl}'));break
 if not entered:status='ENTRY_MISSED';finish='Không quét vùng Entry trong 72 giờ'
 if status=='UNKNOWN' and finish=='No terminal event':finish='Không có TP/SL trong 72 giờ'
 lines=['# Replay một tín hiệu Binance Futures','',f"- Telegram: {chosen['telegram_timestamp']}",f"- Group: {chosen['chat_title']} ({chosen['chat_id']})",f"- Message: {chosen['message_id']}",f"- Symbol: {symbol}",f"- Side: {side}",f"- Entry: {entry}",f"- SL: {sl}",f"- TP: {', '.join(map(str,tps))}",'- Dữ liệu: Binance contract klines + mark-price klines, 1m, horizon 72h','',f'## Kết quả: **{status}**',f'- {finish}','', '## Nhật ký']
 lines += [f'- `{x[0]}` — **{x[1]}** — {x[2]}' for x in log]
 OUT.write_text('\n'.join(lines)+'\n',encoding='utf-8'); print(OUT)
if __name__=='__main__':main()
