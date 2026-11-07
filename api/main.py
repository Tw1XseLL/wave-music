import os, json, hmac, hashlib, sqlite3, time, urllib.request, urllib.error, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit, parse_qs, urlencode, unquote
import secrets, threading

TOKEN=os.environ.get("BOT_TOKEN","").strip()
print("AUTH_CONFIG: token_format="+("valid_shape" if TOKEN.count(":")==1 and TOKEN.split(":")[0].isdigit() else "invalid_shape")+" token_length="+str(len(TOKEN)),flush=True)
ORIGIN=os.environ.get("WEB_ORIGIN","https://wave-web-production.up.railway.app").rstrip("/")
DB=os.environ.get("DB_PATH","/data/wave.sqlite3")
if TOKEN and not TOKEN.startswith("${{"):
 try:
  with urllib.request.urlopen("https://api.telegram.org/bot"+TOKEN+"/getMe",timeout=8) as response:
   identity=json.load(response)
  print("AUTH_BOT_IDENTITY: "+str(identity.get("result",{}).get("username","unknown")) if identity.get("ok") else "AUTH_CONFIG_ERROR: Telegram rejected BOT_TOKEN",flush=True)
 except urllib.error.HTTPError as exc:
  print("AUTH_CONFIG_ERROR: Telegram getMe HTTP "+str(exc.code),flush=True)
 except Exception as exc:
  print("AUTH_CONFIG_ERROR: Telegram getMe "+type(exc).__name__,flush=True)
os.makedirs(os.path.dirname(DB),exist_ok=True)
with sqlite3.connect(DB) as db:
 db.execute("CREATE TABLE IF NOT EXISTS library (user_id INTEGER PRIMARY KEY, favorites TEXT NOT NULL DEFAULT '[]', playlists TEXT NOT NULL DEFAULT '[]')")
with sqlite3.connect(DB) as db:
 db.execute("CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, title TEXT NOT NULL, visibility TEXT NOT NULL, track TEXT NOT NULL DEFAULT '{}', playing INTEGER NOT NULL DEFAULT 0, position REAL NOT NULL DEFAULT 0, updated REAL NOT NULL DEFAULT 0)")
 db.execute("CREATE TABLE IF NOT EXISTS room_members (room_id TEXT NOT NULL, user_id INTEGER NOT NULL, role TEXT NOT NULL, PRIMARY KEY(room_id,user_id))")
 db.execute("CREATE TABLE IF NOT EXISTS room_queue (room_id TEXT NOT NULL, item_id TEXT NOT NULL, title TEXT NOT NULL, artist TEXT NOT NULL, source TEXT NOT NULL, PRIMARY KEY(room_id,item_id))")
with sqlite3.connect(DB) as db:
 db.execute("CREATE TABLE IF NOT EXISTS premium_subscriptions (user_id INTEGER PRIMARY KEY, expires_at INTEGER NOT NULL DEFAULT 0)")
 db.execute("CREATE TABLE IF NOT EXISTS star_payments (charge_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, stars INTEGER NOT NULL, created_at INTEGER NOT NULL)")
with sqlite3.connect(DB) as db:
 db.execute("CREATE TABLE IF NOT EXISTS bot_preview (position INTEGER PRIMARY KEY, file_id TEXT NOT NULL)")
with sqlite3.connect(DB) as db:
 db.execute("CREATE TABLE IF NOT EXISTS bot_notifications (user_id INTEGER PRIMARY KEY, news INTEGER NOT NULL DEFAULT 1, premium INTEGER NOT NULL DEFAULT 1)")
with sqlite3.connect(DB) as db:
 db.execute("CREATE TABLE IF NOT EXISTS bot_subscribers (user_id INTEGER PRIMARY KEY, registered_at INTEGER NOT NULL)")
 db.execute("CREATE TABLE IF NOT EXISTS premium_reminders (user_id INTEGER NOT NULL, expires_at INTEGER NOT NULL, sent_at INTEGER NOT NULL, PRIMARY KEY(user_id,expires_at))")
with sqlite3.connect(DB) as db:
 db.execute("CREATE TABLE IF NOT EXISTS artist_tracks (id TEXT PRIMARY KEY, title TEXT NOT NULL, artist TEXT NOT NULL, filename TEXT NOT NULL, uploaded_at INTEGER NOT NULL)")
ARTIST_USER_ID=int(os.environ.get('WAVE_ARTIST_USER_ID','956548293'))
TRACK_DIR=os.path.join(os.path.dirname(DB),'artist_tracks')
os.makedirs(TRACK_DIR,exist_ok=True)
ROOM_LOCK=threading.RLock()
def user_id_from_token():
 return TOKEN.split(":")[0] if ":" in TOKEN else ""
def verify(raw):
 if not TOKEN or TOKEN.startswith("${{"):
  print("AUTH_CONFIG_ERROR: bot token missing or unresolved",flush=True);return None
 if not raw or len(raw)>8192:
  print("AUTH_ERROR: missing or oversized initData",flush=True);return None
 try:
  pairs=parse_qsl(raw,keep_blank_values=True,strict_parsing=True)
  params=dict(pairs)
  if len(params)!=len(pairs):
   print("AUTH_ERROR: duplicate initData keys",flush=True);return None
  received=params.pop("hash","")
  check="\n".join(f"{k}={v}" for k,v in sorted(params.items()))
  secret=hmac.new(b"WebAppData",TOKEN.encode(),hashlib.sha256).digest()
  expected=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
  if not hmac.compare_digest(expected,received):
   print("AUTH_ERROR: signature mismatch fields="+",".join(sorted(params))+" hash_present="+str(bool(received))+" token_bot_id_matches="+str(str(user_id_from_token())==str(TOKEN.split(":")[0])),flush=True);return None
  if abs(time.time()-int(params.get("auth_date","0")))>86400:
   print("AUTH_ERROR: expired initData",flush=True);return None
  user=json.loads(params["user"])
  return user if isinstance(user.get("id"),int) else None
 except (ValueError,KeyError,TypeError,json.JSONDecodeError):
  print("AUTH_ERROR: malformed initData",flush=True);return None
class Handler(BaseHTTPRequestHandler):
 def respond(self,status,obj):
  payload=json.dumps(obj,ensure_ascii=False).encode()
  self.send_response(status)
  self.send_header("Content-Type","application/json; charset=utf-8")
  self.send_header("Content-Length",str(len(payload)))
  self.send_header("Cache-Control","no-store")
  if self.headers.get("Origin","").rstrip("/")==ORIGIN:
   self.send_header("Access-Control-Allow-Origin",ORIGIN)
   self.send_header("Vary","Origin")
   self.send_header("Access-Control-Allow-Headers","Content-Type,X-Telegram-Init-Data,X-Track-Title,X-Track-Artist")
   self.send_header("Access-Control-Allow-Methods","GET,POST,PUT,OPTIONS")
  self.end_headers();self.wfile.write(payload)
 def do_OPTIONS(self):
  origin=self.headers.get("Origin","").rstrip("/")
  if origin!=ORIGIN:return self.respond(403,{"error":"origin_not_allowed"})
  self.respond(200,{"ok":True})
 def do_GET(self):
  if self.path=="/health":return self.respond(200,{"ok":True})
  path=urlsplit(self.path).path
  if path=='/api/internal/previews':
   expected=hmac.new(TOKEN.encode(),b'preview-read',hashlib.sha256).hexdigest()
   if not TOKEN or not hmac.compare_digest(self.headers.get('X-Wave-Signature',''),expected):return self.respond(403,{'error':'forbidden'})
   with sqlite3.connect(DB) as db:rows=db.execute('SELECT file_id FROM bot_preview ORDER BY position LIMIT 4').fetchall()
   return self.respond(200,{'photos':[r[0] for r in rows]})
  if path=='/api/internal/premium-due':
   expected=hmac.new(TOKEN.encode(),b'premium-due',hashlib.sha256).hexdigest()
   if not TOKEN or not hmac.compare_digest(self.headers.get('X-Wave-Signature',''),expected):return self.respond(403,{'error':'forbidden'})
   now=int(time.time())
   with sqlite3.connect(DB) as db:
    rows=db.execute('SELECT p.user_id,p.expires_at FROM premium_subscriptions p JOIN bot_subscribers s ON s.user_id=p.user_id LEFT JOIN bot_notifications n ON n.user_id=p.user_id WHERE p.expires_at>? AND p.expires_at<=? AND COALESCE(n.premium,1)=1 AND NOT EXISTS(SELECT 1 FROM premium_reminders r WHERE r.user_id=p.user_id AND r.expires_at=p.expires_at) LIMIT 200',(now,now+86400)).fetchall()
   return self.respond(200,{'due':[{'user_id':r[0],'expires_at':r[1]} for r in rows]})
  if path=='/api/internal/notification-recipients':
   kind=parse_qs(urlsplit(self.path).query).get('kind',[''])[0]
   if kind not in ('news','premium'):return self.respond(400,{'error':'invalid_kind'})
   expected=hmac.new(TOKEN.encode(),f'recipients:{kind}'.encode(),hashlib.sha256).hexdigest()
   if not TOKEN or not hmac.compare_digest(self.headers.get('X-Wave-Signature',''),expected):return self.respond(403,{'error':'forbidden'})
   with sqlite3.connect(DB) as db:
    rows=db.execute('SELECT s.user_id FROM bot_subscribers s LEFT JOIN bot_notifications n ON n.user_id=s.user_id WHERE COALESCE(n.'+kind+',1)=1').fetchall()
   return self.respond(200,{'users':[r[0] for r in rows]})
  if path=='/api/internal/notifications':
   query=parse_qs(urlsplit(self.path).query)
   try:uid=int(query.get('user_id',[''])[0])
   except (ValueError,TypeError):return self.respond(400,{'error':'invalid_user'})
   if uid<=0:return self.respond(400,{'error':'invalid_user'})
   expected=hmac.new(TOKEN.encode(),f'notifications-read:{uid}'.encode(),hashlib.sha256).hexdigest()
   if not TOKEN or not hmac.compare_digest(self.headers.get('X-Wave-Signature',''),expected):return self.respond(403,{'error':'forbidden'})
   with sqlite3.connect(DB) as db:
    row=db.execute('SELECT news,premium FROM bot_notifications WHERE user_id=?',(uid,)).fetchone()
   return self.respond(200,{'news':bool(row[0]) if row else True,'premium':bool(row[1]) if row else True})
  if path=='/api/internal/premium':
   query=parse_qs(urlsplit(self.path).query)
   try:uid=int(query.get('user_id',[''])[0])
   except (ValueError,TypeError):return self.respond(400,{'error':'invalid_user'})
   if uid<=0:return self.respond(400,{'error':'invalid_user'})
   expected=hmac.new(TOKEN.encode(),f'premium-read:{uid}'.encode(),hashlib.sha256).hexdigest()
   if not TOKEN or not hmac.compare_digest(self.headers.get('X-Wave-Signature',''),expected):return self.respond(403,{'error':'forbidden'})
   with sqlite3.connect(DB) as db:
    row=db.execute('SELECT expires_at FROM premium_subscriptions WHERE user_id=?',(uid,)).fetchone()
   expires=row[0] if row else 0
   return self.respond(200,{'active':expires>int(time.time()),'expires_at':expires})
  if path=='/api/premium':
   user=verify(self.headers.get('X-Telegram-Init-Data',''))
   if not user:return self.respond(401,{'error':'unauthorized'})
   with sqlite3.connect(DB) as db:
    row=db.execute('SELECT expires_at FROM premium_subscriptions WHERE user_id=?',(user['id'],)).fetchone()
   expires=row[0] if row else 0
   return self.respond(200,{'active':expires>int(time.time()),'expires_at':expires})
  if path=='/api/artist-tracks':
   with sqlite3.connect(DB) as db: rows=db.execute('SELECT id,title,artist FROM artist_tracks ORDER BY uploaded_at DESC LIMIT 100').fetchall()
   return self.respond(200,{'tracks':[{'id':x[0],'title':x[1],'artist':x[2],'url':'/api/artist-tracks/'+x[0]} for x in rows]})
  if path.startswith('/api/artist-tracks/'):
   track_id=path.rsplit('/',1)[-1]
   with sqlite3.connect(DB) as db: row=db.execute('SELECT filename FROM artist_tracks WHERE id=?',(track_id,)).fetchone()
   if not row:return self.respond(404,{'error':'not_found'})
   filename=os.path.join(TRACK_DIR,row[0])
   try:
    size=os.path.getsize(filename)
    start,end=0,size-1
    requested=self.headers.get('Range','').strip()
    partial=False
    if requested:
     match=re.fullmatch(r'bytes=(\\d*)-(\\d*)',requested)
     if not match or (not match.group(1) and not match.group(2)):
      self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return
     if match.group(1):
      start=int(match.group(1))
      if match.group(2):end=min(size-1,int(match.group(2)))
     else:
      start=max(0,size-int(match.group(2)))
     if start>=size or start>end:
      self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return
     partial=True
    count=end-start+1
    self.send_response(206 if partial else 200)
    self.send_header('Content-Type','audio/mpeg')
    self.send_header('Content-Length',str(count))
    self.send_header('Accept-Ranges','bytes')
    if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
    self.send_header('Cache-Control','public, max-age=3600')
    self.end_headers()
    with open(filename,'rb') as f:
     f.seek(start)
     remaining=count
     while remaining>0:
      chunk=f.read(min(65536,remaining))
      if not chunk:break
      self.wfile.write(chunk)
      remaining-=len(chunk)
   except (FileNotFoundError,BrokenPipeError,ConnectionResetError):pass
   return
  if path=='/api/catalog':return self.catalog_get()
  if path=="/api/rooms" or path.startswith("/api/rooms/"):
   return self.room_get(path)
  if self.path!="/api/library":return self.respond(404,{"error":"not_found"})
  user=verify(self.headers.get("X-Telegram-Init-Data",""))
  if not user:return self.respond(401,{"error":"unauthorized"})
  with sqlite3.connect(DB) as db:
   row=db.execute("SELECT favorites,playlists FROM library WHERE user_id=?",(user["id"],)).fetchone()
  self.respond(200,{"user":{"id":user["id"],"first_name":user.get("first_name"),"username":user.get("username")},"favorites":json.loads(row[0]) if row else [],"playlists":json.loads(row[1]) if row else []})
 def read_json(self):
  size=int(self.headers.get('Content-Length','0'))
  if not 0<size<=8192:raise ValueError('invalid_size')
  return json.loads(self.rfile.read(size))
 def catalog_get(self):
  user=verify(self.headers.get('X-Telegram-Init-Data',''))
  if not user:return self.respond(401,{'error':'unauthorized'})
  provider=parse_qs(urlsplit(self.path).query).get('provider',['audius'])[0]
  if provider=='audius':return self.audius_catalog()
  if provider!='jamendo':return self.respond(400,{'error':'unknown_provider'})
  client_id=os.environ.get('JAMENDO_CLIENT_ID','').strip()
  if not client_id:return self.respond(200,{'tracks':[],'configured':False,'provider':'jamendo'})
  query=parse_qs(urlsplit(self.path).query).get('q',[''])[0].strip()
  if not query or len(query)>100:return self.respond(400,{'error':'invalid_query'})
  url='https://api.jamendo.com/v3.0/tracks/?'+urlencode({'client_id':client_id,'format':'json','limit':25,'search':query,'include':'licenses','audioformat':'mp32'})
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'WAVE-Music/1.0'})
   with urllib.request.urlopen(req,timeout=8) as response:result=json.load(response)
   if result.get('headers',{}).get('status')!='success':return self.respond(502,{'error':'catalog_provider_error'})
   tracks=[]
   for item in result.get('results',[]):
    audio=item.get('audio','')
    if not audio.startswith('https://'):continue
    tracks.append({'id':str(item.get('id','')),'title':item.get('name',''),'artist':item.get('artist_name',''),'url':audio,'image':item.get('image',''),'license_url':item.get('license_ccurl',''),'provider':'Jamendo'})
   return self.respond(200,{'tracks':tracks,'configured':True,'provider':'jamendo'})
  except (urllib.error.URLError,ValueError,KeyError,TimeoutError):return self.respond(502,{'error':'catalog_unavailable'})
 def audius_catalog(self):
  query=parse_qs(urlsplit(self.path).query).get('q',[''])[0].strip()
  if not 1<=len(query)<=100:return self.respond(400,{'error':'invalid_query'})
  # Streaming is deliberately disabled by default until commercial rights are reviewed.
  streaming=os.environ.get('AUDIUS_STREAMING_ENABLED','false').lower()=='true'
  url='https://api.audius.co/v1/tracks/search?'+urlencode({'query':query,'limit':25})
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'WAVE-Music/1.0'})
   with urllib.request.urlopen(req,timeout=8) as response:result=json.load(response)
   tracks=[]
   for item in result.get('data',[]):
    if not isinstance(item,dict) or item.get('is_stream_gated') or item.get('is_unlisted') or item.get('is_available') is False or item.get('allowed_api_keys'):continue
    track_id=str(item.get('id',''))
    if not track_id or len(track_id)>120:continue
    artwork=item.get('artwork') or {}
    if not isinstance(artwork,dict):artwork={}
    tracks.append({'id':track_id,'title':str(item.get('title',''))[:200],'artist':str((item.get('user') or {}).get('name',''))[:200],'image':artwork.get('480x480') or artwork.get('150x150') or '', 'url':('https://api.audius.co/v1/tracks/'+track_id+'/stream' if streaming else ''),'provider':'Audius','license_url':'','streaming_enabled':streaming,'permalink':item.get('permalink','')})
   return self.respond(200,{'tracks':tracks,'configured':True,'provider':'audius','streaming_enabled':streaming})
  except (urllib.error.URLError,ValueError,KeyError,TimeoutError):return self.respond(502,{'error':'catalog_unavailable'})
 def room_get(self,path):
  user=verify(self.headers.get('X-Telegram-Init-Data',''))
  if not user:return self.respond(401,{'error':'unauthorized'})
  uid=user['id']
  with sqlite3.connect(DB) as db:
   if path=='/api/rooms':
    rows=db.execute("SELECT id,title,visibility FROM rooms WHERE visibility='public' OR id IN (SELECT room_id FROM room_members WHERE user_id=?) ORDER BY updated DESC LIMIT 100",(uid,)).fetchall()
    return self.respond(200,{'rooms':[{'id':x[0],'title':x[1],'visibility':x[2]} for x in rows]})
   parts=path.strip('/').split('/')
   if len(parts)!=3:return self.respond(404,{'error':'not_found'})
   room=db.execute('SELECT id,owner_id,title,visibility,track,playing,position,updated FROM rooms WHERE id=?',(parts[2],)).fetchone()
   if not room:return self.respond(404,{'error':'not_found'})
   role=db.execute('SELECT role FROM room_members WHERE room_id=? AND user_id=?',(room[0],uid)).fetchone()
   if not role:return self.respond(403,{'error':'join_required'})
   queue=db.execute('SELECT item_id,title,artist,source FROM room_queue WHERE room_id=? ORDER BY rowid',(room[0],)).fetchall()
   members=db.execute('SELECT user_id,role FROM room_members WHERE room_id=?',(room[0],)).fetchall()
   return self.respond(200,{'room':{'id':room[0],'owner_id':room[1],'title':room[2],'visibility':room[3],'track':json.loads(room[4]),'playing':bool(room[5]),'position':room[6],'updated':room[7],'server_time':time.time(),'effective_position':room[6]+max(0,time.time()-room[7]) if room[5] else room[6]},'role':role[0],'members':[{'user_id':m[0],'role':m[1]} for m in members],'queue':[{'id':q[0],'title':q[1],'artist':q[2],'source':q[3]} for q in queue]})
 def do_POST(self):
  path=urlsplit(self.path).path
  if path=='/api/internal/artist-upload':
   if not TOKEN:return self.respond(403,{'error':'forbidden'})
   try:
    size=int(self.headers.get('Content-Length','0'))
    if not 128<=size<=15*1024*1024:return self.respond(413,{'error':'file_too_large'})
    raw=self.rfile.read(size)
    expected=hmac.new(TOKEN.encode(),raw,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(self.headers.get('X-Wave-Signature',''),expected):return self.respond(403,{'error':'forbidden'})
    if not (raw.startswith(b'ID3') or raw[:2] in (b'\\xff\\xfb',b'\\xff\\xf3',b'\\xff\\xf2')):return self.respond(400,{'error':'invalid_mp3'})
    track_id=secrets.token_hex(12);name=track_id+'.mp3'
    with open(os.path.join(TRACK_DIR,name),'xb') as f:f.write(raw)
    with sqlite3.connect(DB) as db:db.execute('INSERT INTO artist_tracks VALUES(?,?,?,?,?)',(track_id,'Встречай, столица!','Khast',name,int(time.time())))
    return self.respond(201,{'ok':True,'id':track_id})
   except (OSError,ValueError):return self.respond(400,{'error':'upload_failed'})
  if path=='/api/artist-tracks':
   user=verify(self.headers.get('X-Telegram-Init-Data',''))
   if not user:return self.respond(401,{'error':'unauthorized'})
   if user['id']!=ARTIST_USER_ID:return self.respond(403,{'error':'artist_only'})
   try:
    size=int(self.headers.get('Content-Length','0'))
    if not 128<=size<=15*1024*1024:return self.respond(413,{'error':'file_too_large'})
    title=unquote(self.headers.get('X-Track-Title','')).strip()
    artist=self.headers.get('X-Track-Artist','').strip()
    if not title or len(title)>150 or artist!='Khast':return self.respond(400,{'error':'invalid_metadata'})
    raw=self.rfile.read(size)
    if len(raw)!=size or not (raw.startswith(b'ID3') or raw[:2] in (b'\\xff\\xfb',b'\\xff\\xf3',b'\\xff\\xf2')):return self.respond(400,{'error':'invalid_mp3'})
    track_id=secrets.token_hex(12);name=track_id+'.mp3'
    with open(os.path.join(TRACK_DIR,name),'xb') as f:f.write(raw)
    with sqlite3.connect(DB) as db:db.execute('INSERT INTO artist_tracks VALUES(?,?,?,?,?)',(track_id,title,artist,name,int(time.time())))
    return self.respond(201,{'ok':True,'id':track_id})
   except (ValueError,OSError):return self.respond(400,{'error':'upload_failed'})
  if path=='/api/internal/reminder-claim':
   try:data=self.read_json()
   except (ValueError,TypeError,json.JSONDecodeError):return self.respond(400,{'error':'invalid_json'})
   uid=data.get('user_id');expires=data.get('expires_at')
   if type(uid)!=int or uid<=0 or type(expires)!=int or expires<=0:return self.respond(400,{'error':'invalid_request'})
   payload=json.dumps(data,separators=(',',':')).encode()
   expected=hmac.new(TOKEN.encode(),payload,hashlib.sha256).hexdigest()
   if not TOKEN or not hmac.compare_digest(self.headers.get('X-Wave-Signature',''),expected):return self.respond(403,{'error':'forbidden'})
   now=int(time.time())
   with sqlite3.connect(DB) as db:
    row=db.execute('SELECT expires_at FROM premium_subscriptions WHERE user_id=?',(uid,)).fetchone()
    enabled=db.execute('SELECT premium FROM bot_notifications WHERE user_id=?',(uid,)).fetchone()
    subscribed=db.execute('SELECT 1 FROM bot_subscribers WHERE user_id=?',(uid,)).fetchone()
    if not row or row[0]!=expires or not subscribed or (enabled and not enabled[0]) or not 0<expires-now<=86400:return self.respond(200,{'claimed':False})
    cursor=db.execute('INSERT OR IGNORE INTO premium_reminders(user_id,expires_at,sent_at) VALUES(?,?,?)',(uid,expires,now))
   return self.respond(200,{'claimed':cursor.rowcount==1})
  if path=='/api/internal/subscribe':
   try:data=self.read_json()
   except (ValueError,TypeError,json.JSONDecodeError):return self.respond(400,{'error':'invalid_json'})
   uid=data.get('user_id')
   if type(uid)!=int or uid<=0:return self.respond(400,{'error':'invalid_user'})
   payload=json.dumps(data,separators=(',',':')).encode()
   expected=hmac.new(TOKEN.encode(),payload,hashlib.sha256).hexdigest()
   if not TOKEN or not hmac.compare_digest(self.headers.get('X-Wave-Signature',''),expected):return self.respond(403,{'error':'forbidden'})
   with sqlite3.connect(DB) as db:db.execute('INSERT OR IGNORE INTO bot_subscribers VALUES(?,?)',(uid,int(time.time())))
   return self.respond(200,{'ok':True})
  if path=='/api/internal/notifications':
   try:data=self.read_json()
   except (ValueError,TypeError,json.JSONDecodeError):return self.respond(400,{'error':'invalid_json'})
   uid=data.get('user_id');key=data.get('key');enabled=data.get('enabled')
   if type(uid)!=int or uid<=0 or key not in ('news','premium') or type(enabled)!=bool:return self.respond(400,{'error':'invalid_settings'})
   payload=json.dumps(data,separators=(',',':')).encode()
   expected=hmac.new(TOKEN.encode(),payload,hashlib.sha256).hexdigest()
   if not TOKEN or not hmac.compare_digest(self.headers.get('X-Wave-Signature',''),expected):return self.respond(403,{'error':'forbidden'})
   with sqlite3.connect(DB) as db:
    db.execute('INSERT OR IGNORE INTO bot_notifications(user_id) VALUES(?)',(uid,))
    db.execute('UPDATE bot_notifications SET '+key+'=? WHERE user_id=?',(int(enabled),uid))
   return self.respond(200,{'ok':True})
  if path=='/api/internal/stars':return self.stars_payment()
  if path=='/api/internal/previews':return self.preview_save()
  if path!='/api/rooms' and not path.startswith('/api/rooms/'):return self.respond(404,{'error':'not_found'})
  user=verify(self.headers.get('X-Telegram-Init-Data',''))
  if not user:return self.respond(401,{'error':'unauthorized'})
  try:data=self.read_json()
  except (ValueError,TypeError,json.JSONDecodeError):return self.respond(400,{'error':'invalid_json'})
  uid=user['id'];parts=path.strip('/').split('/')
  with ROOM_LOCK,sqlite3.connect(DB) as db:
   if path=='/api/rooms':
    title=data.get('title','Моя комната');visibility=data.get('visibility','private')
    if not isinstance(title,str) or not 1<=len(title.strip())<=80 or visibility not in ('private','public'):return self.respond(400,{'error':'invalid_room'})
    rid=secrets.token_urlsafe(9)
    db.execute('INSERT INTO rooms(id,owner_id,title,visibility,updated) VALUES(?,?,?,?,?)',(rid,uid,title.strip(),visibility,time.time()))
    db.execute('INSERT INTO room_members VALUES(?,?,?)',(rid,uid,'owner'))
    return self.respond(201,{'id':rid})
   if len(parts)!=4:return self.respond(404,{'error':'not_found'})
   rid,action=parts[2],parts[3]
   room=db.execute('SELECT owner_id,visibility FROM rooms WHERE id=?',(rid,)).fetchone()
   if not room:return self.respond(404,{'error':'not_found'})
   role_row=db.execute('SELECT role FROM room_members WHERE room_id=? AND user_id=?',(rid,uid)).fetchone()
   role=role_row[0] if role_row else None
   if action=='join':
    if role:return self.respond(200,{'role':role})
    db.execute('INSERT INTO room_members VALUES(?,?,?)',(rid,uid,'listener'))
    return self.respond(200,{'role':'listener'})
   if not role:return self.respond(403,{'error':'join_required'})
   if action=='role':
    if uid!=room[0]:return self.respond(403,{'error':'owner_only'})
    target=data.get('user_id');newrole=data.get('role')
    if type(target)!=int or target==uid or newrole not in ('dj','listener'):return self.respond(400,{'error':'invalid_role'})
    cursor=db.execute("UPDATE room_members SET role=? WHERE room_id=? AND user_id=? AND role!='owner'",(newrole,rid,target))
    if not cursor.rowcount:return self.respond(404,{'error':'member_not_found'})
   elif action=='next':
    if role not in ('owner','dj'):return self.respond(403,{'error':'dj_only'})
    item=db.execute('SELECT item_id,title,artist,source FROM room_queue WHERE room_id=? ORDER BY rowid LIMIT 1',(rid,)).fetchone()
    if not item:return self.respond(409,{'error':'queue_empty'})
    db.execute('DELETE FROM room_queue WHERE room_id=? AND item_id=?',(rid,item[0]))
    db.execute('UPDATE rooms SET track=?,playing=1,position=0,updated=? WHERE id=?',(json.dumps({'title':item[1],'artist':item[2],'source':item[3]}),time.time(),rid))
   elif action=='control':
    if role not in ('owner','dj'):return self.respond(403,{'error':'dj_only'})
    playing=data.get('playing');position=data.get('position',0)
    if type(playing)!=bool or type(position) not in (int,float) or not 0<=position<=86400:return self.respond(400,{'error':'invalid_control'})
    if not playing and 'position' not in data:
     state=db.execute('SELECT playing,position,updated FROM rooms WHERE id=?',(rid,)).fetchone()
     position=state[1]+max(0,time.time()-state[2]) if state[0] else state[1]
    db.execute('UPDATE rooms SET playing=?,position=?,updated=? WHERE id=?',(int(playing),position,time.time(),rid))
   elif action=='queue':
    if role not in ('owner','dj'):return self.respond(403,{'error':'dj_only'})
    title,artist,source=data.get('title'),data.get('artist'),data.get('source')
    if not all(isinstance(x,str) and 1<=len(x)<=200 for x in (title,artist,source)) or not source.startswith(('https://','local:')):return self.respond(400,{'error':'invalid_track'})
    if db.execute('SELECT COUNT(*) FROM room_queue WHERE room_id=?',(rid,)).fetchone()[0]>=100:return self.respond(409,{'error':'queue_full'})
    db.execute('INSERT INTO room_queue VALUES(?,?,?,?,?)',(rid,secrets.token_urlsafe(8),title,artist,source))
   else:return self.respond(404,{'error':'not_found'})
   # Keep playback clock unchanged when changing roles or queue.
   return self.respond(200,{'ok':True})
 def preview_save(self):
  try:
   size=int(self.headers.get('Content-Length','0'))
   if not 0<size<=4096:raise ValueError()
   raw=self.rfile.read(size)
   expected=hmac.new(TOKEN.encode(),raw,hashlib.sha256).hexdigest()
   if not TOKEN or not hmac.compare_digest(self.headers.get('X-Wave-Signature',''),expected):return self.respond(403,{'error':'forbidden'})
   data=json.loads(raw);photos=data['photos']
   if not isinstance(photos,list) or len(photos)>4 or any(not isinstance(x,str) or not 10<=len(x)<=500 for x in photos):raise ValueError()
   with ROOM_LOCK,sqlite3.connect(DB) as db:
    db.execute('DELETE FROM bot_preview')
    db.executemany('INSERT INTO bot_preview(position,file_id) VALUES(?,?)',list(enumerate(photos)))
   return self.respond(200,{'ok':True,'count':len(photos)})
  except (ValueError,KeyError,TypeError,json.JSONDecodeError):return self.respond(400,{'error':'invalid_previews'})
 def stars_payment(self):
  try:
   raw_size=int(self.headers.get('Content-Length','0'))
   if not 0<raw_size<=4096:raise ValueError()
   raw=self.rfile.read(raw_size)
   supplied=self.headers.get('X-Wave-Signature','')
   expected=hmac.new(TOKEN.encode(),raw,hashlib.sha256).hexdigest()
   if not TOKEN or not hmac.compare_digest(supplied,expected):return self.respond(403,{'error':'forbidden'})
   data=json.loads(raw)
   uid,charge,stars,paid_at=data['user_id'],data['charge_id'],data['stars'],data['paid_at']
   if type(uid)!=int or uid<=0 or type(charge)!=str or not 1<=len(charge)<=200 or type(stars)!=int or stars!=159 or type(paid_at)!=int or abs(time.time()-paid_at)>300:raise ValueError()
   with ROOM_LOCK,sqlite3.connect(DB) as db:
    db.execute('BEGIN IMMEDIATE')
    existing=db.execute('SELECT user_id FROM star_payments WHERE charge_id=?',(charge,)).fetchone()
    if existing:return self.respond(200,{'ok':True,'duplicate':True})
    db.execute('INSERT INTO star_payments VALUES(?,?,?,?)',(charge,uid,stars,paid_at))
    row=db.execute('SELECT expires_at FROM premium_subscriptions WHERE user_id=?',(uid,)).fetchone()
    expiry=max(int(time.time()),row[0] if row else 0)+30*86400
    db.execute('INSERT INTO premium_subscriptions VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET expires_at=excluded.expires_at',(uid,expiry))
   return self.respond(200,{'ok':True,'expires_at':expiry})
  except (ValueError,TypeError,KeyError,OverflowError,json.JSONDecodeError):return self.respond(400,{'error':'invalid_payment'})
 def do_PUT(self):
  if self.path!="/api/library":return self.respond(404,{"error":"not_found"})
  user=verify(self.headers.get("X-Telegram-Init-Data",""))
  if not user:return self.respond(401,{"error":"unauthorized"})
  try:
   size=int(self.headers.get("Content-Length","0"))
   if not 0<size<=65536:return self.respond(413,{"error":"invalid_size"})
   data=json.loads(self.rfile.read(size))
   favorites=data.get("favorites",[])
   playlists=data.get("playlists",[])
   if not isinstance(favorites,list) or len(favorites)>2000 or any(not isinstance(x,str) or len(x)>250 for x in favorites):raise ValueError()
   if not isinstance(playlists,list) or len(playlists)>100 or any(not isinstance(x,dict) or len(json.dumps(x))>4000 for x in playlists):raise ValueError()
  except (ValueError,TypeError,json.JSONDecodeError):return self.respond(400,{"error":"invalid_data"})
  with sqlite3.connect(DB) as db:
   db.execute("INSERT INTO library(user_id,favorites,playlists) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET favorites=excluded.favorites,playlists=excluded.playlists",(user["id"],json.dumps(favorites),json.dumps(playlists)))
  self.respond(200,{"saved":True})
if __name__=="__main__":
 ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","8080"))),Handler).serve_forever()
