import os, json, hmac, hashlib, sqlite3, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl

TOKEN=os.environ.get("BOT_TOKEN","")
ORIGIN=os.environ.get("WEB_ORIGIN","https://wave-web-production.up.railway.app").rstrip("/")
DB=os.environ.get("DB_PATH","/data/wave.sqlite3")
os.makedirs(os.path.dirname(DB),exist_ok=True)
with sqlite3.connect(DB) as db:
 db.execute("CREATE TABLE IF NOT EXISTS library (user_id INTEGER PRIMARY KEY, favorites TEXT NOT NULL DEFAULT '[]', playlists TEXT NOT NULL DEFAULT '[]')")
def verify(raw):
 if not TOKEN or not raw or len(raw)>8192:return None
 try:
  params=dict(parse_qsl(raw,keep_blank_values=True,strict_parsing=True))
  received=params.pop("hash","")
  check="\n".join(f"{k}={v}" for k,v in sorted(params.items()))
  secret=hmac.new(b"WebAppData",TOKEN.encode(),hashlib.sha256).digest()
  expected=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
  if not hmac.compare_digest(expected,received):return None
  if abs(time.time()-int(params.get("auth_date","0")))>86400:return None
  user=json.loads(params["user"])
  return user if isinstance(user.get("id"),int) else None
 except (ValueError,KeyError,TypeError,json.JSONDecodeError):return None
class Handler(BaseHTTPRequestHandler):
 def respond(self,status,obj):
  payload=json.dumps(obj,ensure_ascii=False).encode()
  self.send_response(status)
  self.send_header("Content-Type","application/json; charset=utf-8")
  self.send_header("Content-Length",str(len(payload)))
  self.send_header("Cache-Control","no-store")
  if self.headers.get("Origin")==ORIGIN:
   self.send_header("Access-Control-Allow-Origin",ORIGIN)
   self.send_header("Vary","Origin")
   self.send_header("Access-Control-Allow-Headers","Content-Type,X-Telegram-Init-Data")
   self.send_header("Access-Control-Allow-Methods","GET,PUT,OPTIONS")
  self.end_headers();self.wfile.write(payload)
 def do_OPTIONS(self):self.respond(204,{})
 def do_GET(self):
  if self.path=="/health":return self.respond(200,{"ok":True})
  if self.path!="/api/library":return self.respond(404,{"error":"not_found"})
  user=verify(self.headers.get("X-Telegram-Init-Data",""))
  if not user:return self.respond(401,{"error":"unauthorized"})
  with sqlite3.connect(DB) as db:
   row=db.execute("SELECT favorites,playlists FROM library WHERE user_id=?",(user["id"],)).fetchone()
  self.respond(200,{"user":{"id":user["id"],"first_name":user.get("first_name"),"username":user.get("username")},"favorites":json.loads(row[0]) if row else [],"playlists":json.loads(row[1]) if row else []})
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
