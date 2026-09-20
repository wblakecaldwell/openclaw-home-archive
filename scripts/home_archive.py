#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, mimetypes, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT=Path(os.path.expanduser(os.environ.get('HOME_ARCHIVE_ROOT','~/Documents/OpenClaw/HomeArchive')))
RECORDS,TRASH,STATE=ROOT/'records',ROOT/'trash',ROOT/'state'; SEQ=STATE/'sequence.json'; ALBUM='Home Archive'
IMAGE_EXTS={'.jpg','.jpeg','.png','.heic','.heif','.tif','.tiff','.gif','.webp','.bmp','.dng'}
def now(): return dt.datetime.now().astimezone().isoformat(timespec='seconds')
def today(): return dt.date.today().isoformat()
def emit(x,code=0): print(json.dumps(x,indent=2,ensure_ascii=False)); raise SystemExit(code)
def atomic_json(p,x):
 p.parent.mkdir(parents=True,exist_ok=True); fd,t=tempfile.mkstemp(prefix='.'+p.name+'.',dir=str(p.parent))
 try:
  with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(x,f,indent=2,ensure_ascii=False); f.write('\n'); f.flush(); os.fsync(f.fileno())
  os.replace(t,p)
 finally:
  try: os.unlink(t)
  except FileNotFoundError: pass
def append_jsonl(p,x):
 p.parent.mkdir(parents=True,exist_ok=True)
 with open(p,'a',encoding='utf-8') as f: f.write(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n'); f.flush(); os.fsync(f.fileno())
def init():
 for p in (RECORDS,TRASH,STATE): p.mkdir(parents=True,exist_ok=True)
 if not SEQ.exists(): atomic_json(SEQ,{'date':today(),'entity':0,'attachment':0})
 if not (ROOT/'README.md').exists(): (ROOT/'README.md').write_text('# Home Archive\n\nManaged by the OpenClaw Home Archive skill.\n')
 return {'ok':True,'root':str(ROOT)}
def next_id(kind):
 init(); st=json.loads(SEQ.read_text()); d=today().replace('-','')
 if st.get('date')!=today(): st={'date':today(),'entity':0,'attachment':0}
 st[kind]=int(st.get(kind,0))+1; atomic_json(SEQ,st); return f"{'HA' if kind=='entity' else 'HAA'}-{d}-{st[kind]:04d}"
def rdir(e): return RECORDS/e
def load(e):
 p=rdir(e)/'metadata.json'
 if not p.exists(): raise FileNotFoundError(f'record not found: {e}')
 return json.loads(p.read_text())
def facts(m): return {f['key']:f for f in m.get('facts',[]) if f.get('active',True)}
def render(m):
 fs=facts(m); L=[f"# {m.get('title') or m['id']}",'',f"- Archive ID: `{m['id']}`",f"- Created: {m.get('created_at','')}",f"- Updated: {m.get('updated_at','')}"]
 if m.get('event_date'): L.append(f"- Event date: {m['event_date']}")
 L += ['','## Summary','',m.get('summary') or '_No summary._','']
 if fs:
  L += ['## Current facts','']; L += [f"- **{k}**: {v.get('value','')} _(source: {v.get('source','unknown')})_" for k,v in sorted(fs.items())]; L.append('')
 if m.get('keywords'): L += ['## Keywords','',', '.join(sorted(set(m['keywords']),key=str.lower)),'']
 aa=[a for a in m.get('attachments',[]) if a.get('active',True)]
 if aa:
  L += ['## Attachments','']; L += [f"- `{a['id']}` — {a.get('role') or a.get('filename')} — {a.get('description','')} (`{a.get('stored_relpath')}`)" for a in aa]; L.append('')
 if m.get('notes'):
  L += ['## Notes / source messages','']; L += [f"- {n.get('at','')}: {n.get('text','')}" for n in m['notes']]; L.append('')
 (rdir(m['id'])/'record.md').write_text('\n'.join(L),encoding='utf-8')
def save(m): atomic_json(rdir(m['id'])/'metadata.json',m); render(m)
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()
def slug(s): return (re.sub(r'[^A-Za-z0-9._-]+','-',s).strip('-') or 'attachment')[:100]
def add_fact(m,f):
 nf={'key':str(f['key']).strip(),'value':str(f.get('value','')).strip(),'source':str(f.get('source','user')),'confidence':str(f.get('confidence','high')),'recorded_at':now(),'active':True}
 for old in m.get('facts',[]):
  if old.get('active',True) and old.get('key')==nf['key']: old['active']=False; old['superseded_at']=nf['recorded_at']; old['superseded_by_value']=nf['value']
 m.setdefault('facts',[]).append(nf)
def known_hashes():
 o={}
 for p in RECORDS.glob('HA-*/metadata.json'):
  try:
   m=json.loads(p.read_text());
   for a in m.get('attachments',[]): o[a.get('sha256')]=(m['id'],a)
  except Exception: pass
 return o
def add_atts(m,specs):
 known=known_hashes(); added=[]; dup=[]; ad=rdir(m['id'])/'attachments'; ad.mkdir(parents=True,exist_ok=True)
 for s in specs or []:
  src=Path(os.path.expanduser(s['path'])).resolve()
  if not src.is_file(): raise FileNotFoundError(str(src))
  h=sha(src)
  if h in known: e,a=known[h]; dup.append({'path':str(src),'existing_entity':e,'existing_attachment':a['id']}); continue
  aid=next_id('attachment'); dst=ad/f'{aid}--{slug(src.name)}'; shutil.copy2(src,dst)
  mime=mimetypes.guess_type(src.name)[0] or 'application/octet-stream'; img=src.suffix.lower() in IMAGE_EXTS or mime.startswith('image/')
  a={'id':aid,'filename':src.name,'stored_relpath':str(dst.relative_to(rdir(m['id']))),'sha256':h,'size':dst.stat().st_size,'mime':mime,'role':s.get('role',''),'description':s.get('description',''),'source_path':str(src),'added_at':now(),'active':True,'publish_to_photos':bool(s.get('publish_to_photos',img)) if img else False}
  m.setdefault('attachments',[]).append(a); known[h]=(m['id'],a); added.append(a)
 return added,dup
def spec(path): return json.loads(Path(path).read_text())
def create(s):
 e=next_id('entity'); rdir(e).mkdir(parents=True); t=now(); m={'schema_version':1,'id':e,'title':s.get('title') or e,'summary':s.get('summary',''),'event_date':s.get('event_date'),'created_at':t,'updated_at':t,'deleted':False,'keywords':list(dict.fromkeys(s.get('keywords',[]))),'facts':[],'attachments':[],'notes':[]}
 if s.get('user_text'): m['notes'].append({'at':t,'text':s['user_text'],'source':'user'})
 for f in s.get('facts',[]): add_fact(m,f)
 aa,dd=add_atts(m,s.get('attachments',[])); save(m); append_jsonl(rdir(e)/'events.jsonl',{'at':t,'type':'create','spec':s,'attachment_ids':[a['id'] for a in aa],'duplicates':dd}); return {'ok':True,'record':m,'attachments_added':aa,'duplicates':dd}
def add(e,s):
 m=load(e); t=now()
 for k in ('title','summary','event_date'):
  if s.get(k): m[k]=s[k]
 if s.get('user_text'): m.setdefault('notes',[]).append({'at':t,'text':s['user_text'],'source':'user'})
 m['keywords']=list(dict.fromkeys(m.get('keywords',[])+s.get('keywords',[])))
 for f in s.get('facts',[]): add_fact(m,f)
 aa,dd=add_atts(m,s.get('attachments',[])); m['updated_at']=t; save(m); append_jsonl(rdir(e)/'events.jsonl',{'at':t,'type':'add','spec':s,'attachment_ids':[a['id'] for a in aa],'duplicates':dd}); return {'ok':True,'record':m,'attachments_added':aa,'duplicates':dd}
def text(m):
 p=[m.get('title',''),m.get('summary',''),' '.join(m.get('keywords',[]))]
 for f in facts(m).values(): p += [f.get('key',''),f.get('value','')]
 for a in m.get('attachments',[]):
  if a.get('active',True): p += [a.get('filename',''),a.get('role',''),a.get('description','')]
 p += [n.get('text','') for n in m.get('notes',[])]; return ' '.join(p).lower()
def search(q,limit):
 terms=re.findall(r'[a-z0-9][a-z0-9._@+-]*',q.lower()); out=[]
 for p in RECORDS.glob('HA-*/metadata.json'):
  try: m=json.loads(p.read_text())
  except: continue
  if m.get('deleted'): continue
  hay=text(m); title=m.get('title','').lower(); score=sum(8*title.count(t)+3*hay.count(t) for t in terms)+(15 if q.lower() in hay else 0)
  if score: out.append({'id':m['id'],'title':m.get('title'),'summary':m.get('summary'),'event_date':m.get('event_date'),'score':score,'facts':{k:v['value'] for k,v in facts(m).items()},'attachments':[{'id':a['id'],'role':a.get('role'),'description':a.get('description'),'filename':a.get('filename')} for a in m.get('attachments',[]) if a.get('active',True)]})
 return sorted(out,key=lambda x:(-x['score'],x['title'] or ''))[:limit]
def find_att(aid):
 for p in RECORDS.glob('HA-*/metadata.json'):
  m=json.loads(p.read_text())
  for a in m.get('attachments',[]):
   if a['id']==aid: return m,a
 raise FileNotFoundError(aid)
def setfact(e,k,v,source,conf):
 m=load(e); old=facts(m).get(k); add_fact(m,{'key':k,'value':v,'source':source,'confidence':conf}); m['updated_at']=now(); save(m); append_jsonl(rdir(e)/'events.jsonl',{'at':m['updated_at'],'type':'set_fact','key':k,'value':v,'source':source,'before':old}); return {'ok':True,'id':e,'key':k,'old':old.get('value') if old else None,'new':v}
def rmfact(e,k):
 m=load(e); t=now(); old=None
 for f in m.get('facts',[]):
  if f.get('active',True) and f.get('key')==k: old=f.get('value'); f['active']=False; f['removed_at']=t
 if old is None: return {'ok':False,'error':'active fact not found','id':e,'key':k}
 m['updated_at']=t; save(m); append_jsonl(rdir(e)/'events.jsonl',{'at':t,'type':'remove_fact','key':k,'old':old}); return {'ok':True,'id':e,'key':k,'old':old}
def rmatt(aid):
 m,a=find_att(aid); t=now(); a['active']=False; a['removed_at']=t; m['updated_at']=t; save(m); append_jsonl(rdir(m['id'])/'events.jsonl',{'at':t,'type':'remove_attachment','attachment_id':aid}); return {'ok':True,'record':m['id'],'attachment':aid}
def delete(e):
 m=load(e); t=now(); m['deleted']=True; m['deleted_at']=t; m['updated_at']=t; save(m); append_jsonl(rdir(e)/'events.jsonl',{'at':t,'type':'delete'}); return {'ok':True,'id':e,'soft_deleted':True}
def merge(c,d):
 a,b=load(c),load(d); t=now(); existing=set(facts(a))
 for f in b.get('facts',[]):
  if f.get('active',True) and f['key'] not in existing: a.setdefault('facts',[]).append(f); existing.add(f['key'])
 a['keywords']=list(dict.fromkeys(a.get('keywords',[])+b.get('keywords',[]))); a.setdefault('notes',[]).extend(b.get('notes',[])); dest=rdir(c)/'attachments'; dest.mkdir(exist_ok=True); hs={x['sha256'] for x in a.get('attachments',[])}; moved=[]
 for x in b.get('attachments',[]):
  if x.get('sha256') in hs: continue
  src=rdir(d)/x['stored_relpath']; dst=dest/src.name
  if src.exists(): shutil.copy2(src,dst)
  x['stored_relpath']=str(dst.relative_to(rdir(c))); a.setdefault('attachments',[]).append(x); hs.add(x.get('sha256')); moved.append(x['id'])
 a['updated_at']=t; save(a); b['deleted']=True; b['merged_into']=c; b['updated_at']=t; save(b); append_jsonl(rdir(c)/'events.jsonl',{'at':t,'type':'merge_in','from':d,'attachments':moved}); append_jsonl(rdir(d)/'events.jsonl',{'at':t,'type':'merged_into','to':c}); return {'ok':True,'canonical':c,'merged':d,'attachments_moved':moved}

def osa(script,args=()):
 cp=subprocess.run(['osascript','-']+list(args),input=script,text=True,capture_output=True)
 if cp.returncode: raise RuntimeError(cp.stderr.strip() or cp.stdout.strip())
 return cp.stdout.strip()
def photos_ok():
 if sys.platform!='darwin': return False,'not macOS'
 try: return True,osa('tell application "Photos" to return name\n')
 except Exception as e: return False,str(e)
def ensure_album(): return osa('tell application "Photos"\nif not (exists album "Home Archive") then make new album named "Home Archive"\nreturn id of album "Home Archive"\nend tell\n')
def photo_meta(m,a):
 fs=facts(m); vals=[str(fs[k]['value']) for k in ('brand','model','serial','company','builder','contractor','part_number','paint','color') if k in fs]; title=(a.get('role') or m.get('title') or a.get('filename'))[:200]; desc=(m.get('title','')+'. '+(' · '.join(vals)+'. ' if vals else '')+a.get('description','')+f" Home Archive {m['id']} / {a['id']}.").strip(); kws=list(dict.fromkeys(['Home Archive',m['id'],a['id']]+m.get('keywords',[])+vals)); return title,desc,kws
def qlist(xs): return '{'+','.join(json.dumps(str(x)) for x in xs)+'}'
def find_photo(aid):
 sc='''on run argv\nset target to item 1 of argv\ntell application "Photos"\nset hits to search for target\nrepeat with p in hits\ntry\nif (keywords of p) contains target then return id of p\nend try\nend repeat\nend tell\nreturn ""\nend run\n'''; return osa(sc,[aid])
def set_meta(pid,title,desc,kws):
 sc=f'''on run argv\nset pid to item 1 of argv\ntell application "Photos"\nset p to media item id pid\nset name of p to {json.dumps(title)}\nset description of p to {json.dumps(desc)}\nset keywords of p to {qlist(kws)}\nend tell\nreturn pid\nend run\n'''; return osa(sc,[pid])
def import_photo(path,title,desc,kws):
 ensure_album(); sc=f'''on run argv\nset f to POSIX file (item 1 of argv)\ntell application "Photos"\nset imported to import {{f}} into album "Home Archive" skip check duplicates yes\nif (count of imported) is 0 then error "Photos import returned no media item"\nset p to item 1 of imported\nset name of p to {json.dumps(title)}\nset description of p to {json.dumps(desc)}\nset keywords of p to {qlist(kws)}\nreturn id of p\nend tell\nend run\n'''; return osa(sc,[str(path)])
def photo_items():
 for p in RECORDS.glob('HA-*/metadata.json'):
  try: m=json.loads(p.read_text())
  except: continue
  if m.get('deleted'): continue
  for a in m.get('attachments',[]):
   if a.get('active',True) and a.get('publish_to_photos'): yield m,a,rdir(m['id'])/a['stored_relpath']
def psync(dry):
 ok,why=photos_ok()
 if not ok: return {'ok':False,'error':'Photos unavailable','detail':why}
 ensure_album(); actions=[]
 for m,a,p in photo_items():
  title,desc,kws=photo_meta(m,a); pid=find_photo(a['id'])
  if pid: actions.append({'action':'update','attachment':a['id'],'photos_id':pid}); (None if dry else set_meta(pid,title,desc,kws))
  else: actions.append({'action':'import','attachment':a['id'],'path':str(p)}); (None if dry else import_photo(p,title,desc,kws))
 return {'ok':True,'dry_run':dry,'actions':actions,'count':len(actions)}
def managed_ids():
 sc='''tell application "Photos"\nset hits to search for "Home Archive"\nset out to ""\nrepeat with p in hits\ntry\nrepeat with k in (keywords of p)\nif (k as text) starts with "HAA-" then\nset out to out & (id of p) & linefeed\nexit repeat\nend if\nend repeat\nend try\nend repeat\nreturn out\nend tell\n'''; return [x for x in osa(sc).splitlines() if x.strip()]
def del_photos(ids):
 if not ids:return
 sc='''on run argv\ntell application "Photos"\nset doomed to {}\nrepeat with pid in argv\ntry\nset end of doomed to media item id (pid as text)\nend try\nend repeat\nif (count of doomed) > 0 then delete doomed\nend tell\nend run\n'''; osa(sc,ids)
def prebuild(dry,confirm):
 ok,why=photos_ok()
 if not ok:return {'ok':False,'error':'Photos unavailable','detail':why}
 ids=managed_ids(); count=sum(1 for _ in photo_items())
 if dry:return {'ok':True,'dry_run':True,'managed_assets_to_delete':len(ids),'then_reimport':count}
 if not confirm:return {'ok':False,'error':'confirmation required','hint':'rerun with --confirm after explicit user confirmation'}
 del_photos(ids); return {'ok':True,'deleted_managed_assets':len(ids),'sync':psync(False)}
def doctor():
 init(); probs=[]; rc=ac=0; seen={}
 for p in RECORDS.glob('HA-*/metadata.json'):
  rc+=1
  try:m=json.loads(p.read_text())
  except Exception as e: probs.append(f'{p}: invalid JSON: {e}'); continue
  for a in m.get('attachments',[]):
   ac+=1; ap=rdir(m['id'])/a['stored_relpath']
   if not ap.exists(): probs.append(f"missing attachment {a['id']}: {ap}"); continue
   h=sha(ap)
   if h!=a.get('sha256'): probs.append(f"hash mismatch {a['id']}")
   if h in seen and seen[h]!=a['id']: probs.append(f"duplicate stored content {a['id']} and {seen[h]}")
   seen[h]=a['id']
 pok,pd=photos_ok(); return {'ok':not probs,'root':str(ROOT),'records':rc,'attachments':ac,'problems':probs,'photos':{'available':pok,'detail':pd}}
def main():
 ap=argparse.ArgumentParser(prog='home-archive'); sub=ap.add_subparsers(dest='cmd',required=True); sub.add_parser('init')
 p=sub.add_parser('create');p.add_argument('--spec',required=True)
 p=sub.add_parser('add');p.add_argument('id');p.add_argument('--spec',required=True)
 p=sub.add_parser('search');p.add_argument('query');p.add_argument('--limit',type=int,default=10)
 p=sub.add_parser('show');p.add_argument('id');p=sub.add_parser('get-attachment');p.add_argument('id')
 p=sub.add_parser('set-fact');p.add_argument('id');p.add_argument('--key',required=True);p.add_argument('--value',required=True);p.add_argument('--source',default='user');p.add_argument('--confidence',default='high')
 p=sub.add_parser('remove-fact');p.add_argument('id');p.add_argument('--key',required=True);p=sub.add_parser('remove-attachment');p.add_argument('id');p=sub.add_parser('delete');p.add_argument('id')
 p=sub.add_parser('merge');p.add_argument('canonical');p.add_argument('duplicate');p=sub.add_parser('photos-sync');p.add_argument('--dry-run',action='store_true');p=sub.add_parser('photos-rebuild');p.add_argument('--dry-run',action='store_true');p.add_argument('--confirm',action='store_true');sub.add_parser('doctor'); a=ap.parse_args()
 try:
  if a.cmd=='init':emit(init())
  if a.cmd=='create':emit(create(spec(a.spec)))
  if a.cmd=='add':emit(add(a.id,spec(a.spec)))
  if a.cmd=='search':emit({'ok':True,'query':a.query,'results':search(a.query,a.limit)})
  if a.cmd=='show':emit({'ok':True,'record':load(a.id)})
  if a.cmd=='get-attachment':m,x=find_att(a.id);emit({'ok':True,'record':m['id'],'attachment':x,'path':str(rdir(m['id'])/x['stored_relpath'])})
  if a.cmd=='set-fact':emit(setfact(a.id,a.key,a.value,a.source,a.confidence))
  if a.cmd=='remove-fact':emit(rmfact(a.id,a.key))
  if a.cmd=='remove-attachment':emit(rmatt(a.id))
  if a.cmd=='delete':emit(delete(a.id))
  if a.cmd=='merge':emit(merge(a.canonical,a.duplicate))
  if a.cmd=='photos-sync':emit(psync(a.dry_run))
  if a.cmd=='photos-rebuild':emit(prebuild(a.dry_run,a.confirm))
  if a.cmd=='doctor':emit(doctor())
 except Exception as e:emit({'ok':False,'error':type(e).__name__,'detail':str(e)},1)
if __name__=='__main__':main()
