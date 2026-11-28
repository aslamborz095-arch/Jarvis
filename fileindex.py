"""Index des fichiers du PC (SQLite FTS5) : recherche instantanée par nom et par contenu.

- Tâche de fond : 1er passage 3 min après le démarrage, puis toutes les 6 h ; seulement si RAM < 85 %.
- Parcourt le dossier personnel (OneDrive compris), ignore AppData, .git, venv, etc.
- Contenu extrait (texte, PDF ≤ 30 pages, Word, Excel, PowerPoint ; 30 000 caractères max) seulement
  pour les fichiers nouveaux ou modifiés ; fichiers disparus retirés. Pause courte entre fichiers (PC fluide).
- search(query) : résultats classés (nom, puis pertinence du contenu), extrait autour du mot.
"""
import os, re, time, sqlite3, pathlib, threading, unicodedata

BASE = pathlib.Path(__file__).parent
DB = BASE / "data" / "index.db"
SKIP = {"appdata", "node_modules", ".git", ".venv", "venv", "__pycache__", "$recycle.bin", "windows",
        "program files", "program files (x86)", "programdata", ".cache", "site-packages"}
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".py", ".log", ".html", ".xml", ".ini", ".srt"}
DOC_EXT = {".pdf", ".docx", ".xlsx", ".xlsm", ".pptx"}
MAX_TEXT, MAX_SIZE, PERIOD = 30000, 15_000_000, 6 * 3600
STATE = {"running": False, "last": None, "files": 0, "indexed": 0, "fts": None, "error": ""}
_lock = threading.Lock()


def _plain(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _db():
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(str(DB), timeout=30, check_same_thread=False)
    c.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, name TEXT, mtime REAL, size INTEGER)")
    if STATE["fts"] is None:
        try:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS body USING fts5(path UNINDEXED, name, content, tokenize='unicode61 remove_diacritics 2')")
            STATE["fts"] = True
        except sqlite3.OperationalError:
            STATE["fts"] = False
    if not STATE["fts"]:
        c.execute("CREATE TABLE IF NOT EXISTS body(path TEXT PRIMARY KEY, name TEXT, content TEXT)")
    return c


def _text(p):
    ext = p.suffix.lower()
    try:
        if ext in DOC_EXT:
            import tools
            return (tools._doc_text(p, pages=30) or "")[:MAX_TEXT]
        if ext in TEXT_EXT:
            with open(p, encoding="utf-8", errors="replace") as f:
                return f.read(MAX_TEXT)
    except Exception:
        pass
    return ""


def _user_active():
    try:
        import awareness
        return awareness.STATE.get("idle", 999) < 120 and awareness.STATE.get("app") != "Écran verrouillé"
    except Exception:
        return False


def build(root=None, throttle=0.01):
    """Met l'index à jour (incrémental). Renvoie un court bilan."""
    if not _lock.acquire(blocking=False):
        return "Indexation déjà en cours."
    STATE["running"], t0 = True, time.time()
    try:
        root = pathlib.Path(root or pathlib.Path.home())
        c = _db()
        known = dict(c.execute("SELECT path, mtime FROM files"))
        seen, new = set(), 0
        for dp, dirs, fs in os.walk(root):
            dirs[:] = [d for d in dirs if d.lower() not in SKIP and not d.startswith(".")
                       and os.path.join(dp, d) != str(BASE)]          # jamais Jarvis lui-même (journaux, index…)
            for f in fs:
                fp = os.path.join(dp, f)
                if f.endswith(("-journal", ".db-wal", ".tmp", ".crdownload")):
                    continue
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                seen.add(fp)
                if known.get(fp) == st.st_mtime:
                    continue
                if new % 50 == 49:
                    time.sleep(0.2)
                p = pathlib.Path(fp)
                t1 = time.time()
                body = _text(p) if st.st_size < MAX_SIZE and p.suffix.lower() in (TEXT_EXT | DOC_EXT) else ""
                c.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?)", (fp, f, st.st_mtime, st.st_size))
                c.execute("DELETE FROM body WHERE path=?", (fp,))
                c.execute("INSERT INTO body(path, name, content) VALUES(?,?,?)", (fp, _plain(f).replace("_", " "), body))
                new += 1
                if new % 200 == 0:
                    c.commit()
                if body and throttle:   # cycle de travail limité : le PC reste fluide
                    dt = time.time() - t1
                    time.sleep(max(throttle, dt * (4 if _user_active() else 1.5)))
        gone = [k for k in known if k not in seen]
        for k in gone:
            c.execute("DELETE FROM files WHERE path=?", (k,))
            c.execute("DELETE FROM body WHERE path=?", (k,))
        c.commit()
        STATE.update(files=len(seen), indexed=new, last=time.strftime("%Y-%m-%dT%H:%M"), error="")
        c.close()
        return f"Index à jour : {len(seen)} fichiers ({new} nouveaux ou modifiés, {len(gone)} retirés) en {int(time.time() - t0)} s."
    except Exception as e:
        STATE["error"] = f"{type(e).__name__}: {e}"
        return "Erreur d'indexation : " + STATE["error"]
    finally:
        STATE["running"] = False
        _lock.release()


def ready():
    return DB.exists() and STATE["last"] is not None or (DB.exists() and DB.stat().st_size > 50_000)


def search(query, folder="", ext="", limit=10):
    """Liste de (chemin, extrait) depuis l'index ; [] si rien."""
    words = [w for w in re.findall(r"\w+", _plain(query)) if len(w) > 1]
    if not words or not DB.exists():
        return []
    c = _db()
    exts = tuple("." + e.strip(" .").lower() for e in ext.split(",") if e.strip(" ."))
    pre = str(folder or "")
    lim = max(1, min(int(limit or 10), 30)) * 4
    try:
        if STATE["fts"]:
            q = " ".join(f'"{w}"' for w in words)
            rows = c.execute("SELECT path, snippet(body, 2, '', '', '…', 24), bm25(body, 0, 8.0, 1.0) FROM body "
                             "WHERE body MATCH ? ORDER BY 3 LIMIT ?", (q, lim)).fetchall()
        else:
            cond = " AND ".join("(lower(name)||' '||lower(content)) LIKE ?" for _ in words)
            rows = c.execute(f"SELECT path, substr(content, 1, 160), 0 FROM body WHERE {cond} LIMIT ?",
                             [f"%{w}%" for w in words] + [lim]).fetchall()
    finally:
        c.close()
    out = []
    for path, snip, _ in rows:
        if pre and not path.lower().startswith(pre.lower()):
            continue
        if exts and not path.lower().endswith(exts):
            continue
        if not os.path.exists(path):
            continue
        out.append((path, " ".join((snip or "").split())[:200]))
        if len(out) >= lim // 4:
            break
    return out


def index_now():
    """Met à jour tout de suite l'index des fichiers (recherche instantanée)."""
    if STATE["running"]:
        return "Indexation déjà en cours."
    threading.Thread(target=build, daemon=True).start()
    return "Indexation lancée en arrière-plan (quelques minutes)."


def index_status():
    """État de l'index des fichiers."""
    s = STATE
    if s["running"]:
        return "Indexation en cours…"
    if not s["last"] and DB.exists() and DB.stat().st_size > 50_000:
        s = dict(s, last=time.strftime("%Y-%m-%dT%H:%M", time.localtime(DB.stat().st_mtime)), files="?", indexed="?")
        _db().close()
    if not s["last"]:
        return "Index pas encore construit (1er passage 3 min après le démarrage)." + (f" Erreur : {s['error']}" if s["error"] else "")
    try:
        c = _db(); n = c.execute("SELECT count(*) FROM body").fetchone()[0]
        w = c.execute("SELECT count(*) FROM body WHERE length(content) > 0").fetchone()[0]; c.close()
    except Exception as e:
        n = w = f"erreur {e}"
    return (f"Index du {s['last'].replace('T', ' ')} : {s['files']} fichiers, {s['indexed']} mis à jour au dernier passage ; "
            f"{n} entrées dont {w} avec contenu ; recherche plein texte {'FTS5' if s['fts'] else 'simple'}.")


def start():
    def loop():
        time.sleep(180)
        while True:
            try:
                import psutil
                if psutil.virtual_memory().percent < 85:
                    r = build()
                    print(f"[index] {r}", flush=True)
            except Exception as e:
                print(f"[index] {e}", flush=True)
            time.sleep(PERIOD)
    threading.Thread(target=loop, daemon=True).start()


SPECS = [("index_now", "Met à jour l'index des fichiers du PC (recherche instantanée par nom et contenu).", {"type": "object", "properties": {}, "required": []}),
         ("index_status", "État de l'index des fichiers.", {"type": "object", "properties": {}, "required": []})]
FUNCS = {"index_now": index_now, "index_status": index_status}
DANGEROUS = set()
