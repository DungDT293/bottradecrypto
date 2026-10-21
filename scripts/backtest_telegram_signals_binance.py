"""Backtest Telegram text signals against Binance Futures price and mark-price klines.
Read-only: no credentials, no order endpoints, no writes to runtime DB.
"""
from __future__ import annotations
import json, time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'audit_output'/'telegram_understanding_20261020T171249Z'/'MESSAGES_CLASSIFIED.jsonl'
OUT=ROOT/'audit_output'/'telegram_understanding_20261020T171249Z'/'BINANCE_CHART_BACKTEST.json'
KLINE='https://fapi.binance.com/fapi/v1/klines'
MARK='https://fapi.binance.com/fapi/v1/markPriceKlines'


def get(url, params):
    req=Request(url+'?'+urlencode(params),headers={'User-Agent':'read-only-audit/1.0'})
    with urlopen(req,timeout=30) as r:return json.loads(r.read())

def klines(url,symbol,start,end):
    rows=[]; cursor=start
    while cursor<end:
        batch=get(url,{'symbol':symbol,'interval':'1m','startTime':cursor,'endTime':end,'limit':1500})
        if not batch:break
        rows.extend(batch); nxt=int(batch[-1][0])+60000
        if nxt<=cursor:break
        cursor=nxt
        if len(batch)<1500:break
        time.sleep(.02)
    return rows

def run(row):
    c=row.get('classification') or {}
    if c.get('category')!='SIGNAL' or c.get('side') not in ('LONG','SHORT') or not c.get('entries') or not c.get('stop_loss') or not c.get('take_profits'):
        return None
    try:
        symbol=c['symbol']; side=c['side']; entry=Decimal(c['entries'][0]); sl=Decimal(c['stop_loss']); tps=[Decimal(x) for x in c['take_profits']]
        ts=datetime.fromisoformat(row['telegram_timestamp'].replace('Z','+00:00')); start=int(ts.timestamp()*1000); end=start+72*3600*1000
        contract=klines(KLINE,symbol,start,end); mark=klines(MARK,symbol,start,end)
        marks={int(x[0]):(Decimal(str(x[2])),Decimal(str(x[3]))) for x in mark}
        entered=False; status='UNKNOWN'; reason='NO_TERMINAL_HIT'; ambiguous=0
        for k in contract:
            t=int(k[0]); hi=Decimal(str(k[2])); lo=Decimal(str(k[3])); mh,ml=marks.get(t,(hi,lo))
            if not entered:
                if lo<=entry<=hi: entered=True
                else:continue
            if side=='LONG':
                hit_sl=ml<=sl; hit_tp=hi>=min(tps)
            else:
                hit_sl=mh>=sl; hit_tp=lo<=max(tps)
            if hit_sl and hit_tp: status='UNKNOWN'; reason='SAME_MINUTE_TP_SL'; ambiguous=1; break
            if hit_tp: status='WIN'; reason='TP_BEFORE_SL'; break
            if hit_sl: status='LOSS'; reason='MARK_SL_BEFORE_TP'; break
        if not entered: reason='ENTRY_NOT_REACHED'
        return {'status':status,'reason':reason,'ambiguous':ambiguous,'entry_reached':entered,'chat_id':row['chat_id'],'chat_title':row['chat_title'],'message_id':row['message_id'],'telegram_timestamp':row['telegram_timestamp'],'symbol':symbol,'side':side,'entry':str(entry),'sl':str(sl),'tps':[str(x) for x in tps]}
    except Exception as e:
        return {'status':'UNKNOWN','reason':f'{type(e).__name__}:{e}','chat_id':row.get('chat_id'),'chat_title':row.get('chat_title'),'message_id':row.get('message_id'),'symbol':c.get('symbol')}

def main():
    rows=[json.loads(x) for x in SRC.open(encoding='utf-8')]; results=[]; seen=set()
    for i,row in enumerate(rows,1):
        key=(row.get('chat_id'),row.get('message_id'))
        if key in seen:continue
        seen.add(key); result=run(row)
        if result:results.append(result)
        if i%100==0:print(f'{i}/{len(rows)} processed; results={len(results)}',flush=True)
    summary=defaultdict(lambda:{'chat_title':'','valid_signals':0,'WIN':0,'LOSS':0,'UNKNOWN':0,'MISSED_ENTRY':0,'ambiguous':0})
    for r in results:
        d=summary[str(r['chat_id'])];d['chat_title']=r.get('chat_title','');d['valid_signals']+=1
        if r['reason']=='ENTRY_NOT_REACHED':d['MISSED_ENTRY']+=1
        else:d[r['status']]+=1
        d['ambiguous']+=r.get('ambiguous',0)
    table=[]
    for cid,d in summary.items():
        denom=d['WIN']+d['LOSS'];rate=round(d['WIN']/denom*100,2) if denom else None
        table.append({'chat_id':cid,**d,'win_rate_estimate_pct':rate,'rating':'Nên theo dõi' if denom>=10 and rate is not None and rate>=55 else 'Cần đánh giá thêm'})
    OUT.write_text(json.dumps({'generated_utc':datetime.now(timezone.utc).isoformat(),'window_days':30,'method':'Binance contract 1m + mark-price 1m; entry gate; 72h; same-minute TP/SL UNKNOWN','summary':table,'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    md=OUT.with_suffix('.md'); lines=['# Xếp hạng tín hiệu Telegram/Kèo trade','', '| Nhóm | Signal hợp lệ | Win | Loss | Unknown/Miss Entry | Win Rate | Đánh giá |','|---|---:|---:|---:|---:|---:|---|']
    for d in sorted(table,key=lambda x:(x['win_rate_estimate_pct'] is not None,x['win_rate_estimate_pct'] or -1),reverse=True):lines.append(f"| {d['chat_title']} | {d['valid_signals']} | {d['WIN']} | {d['LOSS']} | {d['UNKNOWN']+d['MISSED_ENTRY']} | {d['win_rate_estimate_pct'] if d['win_rate_estimate_pct'] is not None else 'UNKNOWN'} | {d['rating']} |")
    md.write_text('\n'.join(lines)+'\n',encoding='utf-8');print(md)
if __name__=='__main__':main()
