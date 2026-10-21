"""Read-only 7-day signal format catalog for Trade folder groups."""
import argparse, asyncio, json, os, re, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from telethon import TelegramClient, utils
from telethon.tl.functions.messages import GetDialogFiltersRequest
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from config.config import load_config
from parser.normalizer import normalize_text
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from core.models import SourceMetadata

def session(config):
 p=os.environ.get('TELEGRAM_READONLY_SESSION')
 if p:return p[:-8] if p.endswith('.session') else p
 return str(Path(config.data_dir)/'telegram_user')
async def main():
 ap=argparse.ArgumentParser();ap.add_argument('--days',type=int,default=7);ap.add_argument('--output');a=ap.parse_args();cfg=load_config();stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');out=Path(a.output or ROOT/'audit_output'/f'trade_format_catalog_{stamp}');out.mkdir(parents=True,exist_ok=True);cut=datetime.now(timezone.utc)-timedelta(days=a.days);client=TelegramClient(session(cfg),cfg.telegram.api_id,cfg.telegram.api_hash);parser=SignalParser();up=ChannelUpdateParser();data=defaultdict(lambda:{'messages':0,'signals':0,'updates':0,'valid':0,'status':Counter(),'formats':Counter(),'samples':[]})
 await client.connect();
 try:
  if not await client.is_user_authorized():raise RuntimeError('Telegram session unauthorized')
  raw=await client(GetDialogFiltersRequest());fs=getattr(raw,'filters',raw if isinstance(raw,list) else []);ids={};
  for f in fs:
   title=str(getattr(getattr(f,'title',None),'text',getattr(f,'title','')) or '')
   if not re.search(r'trade|kèo',title,re.I):continue
   for p in list(getattr(f,'pinned_peers',[]) or [])+list(getattr(f,'include_peers',[]) or []):
    try:ids[utils.get_peer_id(p)]=title
    except:pass
  dialogs={d.id:d for d in await client.get_dialogs(limit=500)}
  for cid in ids:
   d=dialogs.get(cid)
   if not d:continue
   key=str(cid); title=d.title; rec=data[key]; rec['title']=title; rec['folder']=ids[cid]
   async for m in client.iter_messages(d.entity):
    if m.date and m.date<cut:break
    rec['messages']+=1; rawtxt=m.raw_text or ''; norm=normalize_text(rawtxt); typ,val,detail=up.parse_update(norm) if norm else (None,None,None)
    if typ and getattr(typ,'value','UNKNOWN')!='UNKNOWN':rec['updates']+=1;continue
    if not norm:continue
    try:
     parsed=parser.parse(rawtxt,SourceMetadata(chat_id=cid,message_id=m.id,telegram_timestamp=m.date or datetime.now(timezone.utc)));rec['signals']+=int(bool(parsed.symbol_candidate));rec['status'][parsed.validation_status.value]+=1
     if parsed.symbol_candidate:
      rec['valid']+=int(parsed.validation_status.value=='VALIDATED'); mode=parsed.entry_mode.value;fmt=f'{mode}|{parsed.side.value if parsed.side else "NONE"}|TP{len(parsed.take_profits)}|LEV{"Y" if parsed.leverage_requested else "N"}|SL{"Y" if parsed.stop_loss else "N"}';rec['formats'][fmt]+=1
      if len(rec['samples'])<5:rec['samples'].append({'message_id':m.id,'raw':rawtxt,'format':fmt,'status':parsed.validation_status.value})
    except Exception as e:rec['status']['ERROR']+=1
 finally:await client.disconnect()
 obj={'generated_utc':datetime.now(timezone.utc).isoformat(),'days':a.days,'scope':'trade_folders_only','groups':[]}
 for cid,r in data.items():obj['groups'].append({'chat_id':cid,**{k:(dict(v) if isinstance(v,Counter) else v) for k,v in r.items()}})
 (out/'FORMAT_CATALOG.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8');lines=['# Trade folder signal format catalog','',f'Window: {a.days} days','', '| Group | Messages | Signals | Updates | Validated | Formats |','|---|---:|---:|---:|---:|---|'];
 for r in obj['groups']:lines.append(f"| {r['title']} | {r['messages']} | {r['signals']} | {r['updates']} | {r['valid']} | {', '.join(f'{k}={v}' for k,v in r['formats'].items())} |")
 (out/'FORMAT_CATALOG.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(out)
if __name__=='__main__':asyncio.run(main())
