"""Documents : recherche dans le contenu des fichiers et résumé de longs documents.

- search_in_files(query, folder, ext) : cherche des mots DANS les fichiers (texte, PDF, Word, Excel, PowerPoint),
  sans accents ni casse, tous les mots requis ; renvoie chemin + extrait. Lecture seule, 15 s max.
- summarize_file(path, focus) : résumé fidèle d'un document de n'importe quelle longueur
  (découpé en morceaux résumés en parallèle par l'IA rapide, puis synthèse) ; cache par fichier + date de modification.
"""
import os, json, time, pathlib, unicodedata, concurrent.futures as cf

BASE = pathlib.Path(__file__).parent
CACHE = BASE / "data" / "summaries.json"
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".py", ".log", ".html", ".xml", ".ini", ".srt"}
DOC_EXT = {".pdf", ".docx", ".xlsx", ".xlsm", ".pptx"}
SKIP = {"appdata", "node_modules", ".git", ".venv", "$recycle.bin", "windows", "program files", "program files (x86)"}
CHUNK, MAX_CHUNKS = 9000, 14


def _plain(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def text_of(p, pages=400):
    """Texte complet d'un fichier (aucune troncature), '' si illisible."""
    import tools
    p = pathlib.Path(p)
    try:
        if p.suffix.lower() in DOC_EXT:
            return tools._doc_text(p, pages=pages) or ""
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def search_in_files(query: str, folder: str = "~", ext: str = "", limit: int = 10):
    """Cherche des mots dans le contenu des fichiers d'un dossier (texte, PDF, Word, Excel, PowerPoint)."""
    import tools
    words = [w for w in _plain(query).split() if len(w) > 1]
    if not words:
        return "Précise les mots à chercher."
    root = tools._path(folder)
    try:   # index des fichiers (instantané, tout le dossier personnel)
        import fileindex
        if fileindex.ready():
            hits = fileindex.search(query, "" if str(folder).strip() in ("", "~") else str(root), ext, limit)
            if hits:
                return f"{len(hits)} fichier(s) pour « {query} » (index) :\n" + "\n".join(f"{p}\n   « …{s}… »" for p, s in hits)
    except Exception:
        pass
    exts = {"." + e.strip(" .").lower() for e in ext.split(",") if e.strip(" .")} or (TEXT_EXT | DOC_EXT)
    files = []
    for dp, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP and not d.startswith(".")]
        for f in fs:
            fp = os.path.join(dp, f)
            if os.path.splitext(f)[1].lower() in exts:
                try:
                    st = os.stat(fp)
                    if st.st_size < 15_000_000:
                        files.append((st.st_mtime, fp))
                except OSError:
                    pass
        if len(files) > 3000:
            break
    files.sort(reverse=True)
    t0, hits, seen = time.time(), [], 0
    fname = lambda f: _plain(os.path.basename(f)).replace("_", " ").replace("-", " ")
    named = [fp for _, fp in files if all(w in fname(fp) for w in words)][:10]   # nom du fichier : gratuit
    hits += [f"{fp}\n   (mots trouvés dans le nom)" for fp in named]
    for _, fp in files[:400]:
        if fp in named:
            continue
        if time.time() - t0 > 15 or len(hits) >= max(1, min(int(limit or 10), 30)):
            break
        seen += 1
        t = text_of(fp, pages=60)
        pt = _plain(t)
        if all(w in pt for w in words):
            i = pt.find(words[0])
            snip = " ".join(t[max(0, i - 80): i + 160].split())
            hits.append(f"{fp}\n   « …{snip}… »")
    if not hits:
        return f"Aucun fichier ne contient « {query} » ({seen} fichiers lus dans {root})."
    return f"{len(hits)} fichier(s) contenant « {query} » ({seen} lus) :\n" + "\n".join(hits)


def _cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def summarize_file(path: str, focus: str = ""):
    """Résume fidèlement un document de n'importe quelle longueur (focus = ce qui t'intéresse, facultatif)."""
    import tools, evolve
    p = tools._path(path)
    if not p.is_file():
        return tools.read_file(path)   # dossier ou introuvable : message utile
    key = f"{p}|{int(p.stat().st_mtime)}|{focus.strip().lower()}"
    c = _cache()
    if key in c:
        return c[key]
    t = text_of(p)
    if not t.strip():
        return f"Impossible d'extraire du texte de {p.name} (scan ou format non lu) : essaie screen_look ou un autre format."
    ask = f" en insistant sur : {focus}" if focus.strip() else ""
    rule = "Résume fidèlement, en français, sans rien inventer"
    if len(t) <= CHUNK * 1.3:
        out = evolve._llm(f"{rule}{ask}, en 6 à 10 points courts, le document « {p.name} » :\n\n{t}", max_tokens=900, fast=True)
    else:
        step = max(CHUNK, len(t) // MAX_CHUNKS + 1)
        parts = [t[i:i + step] for i in range(0, len(t), step)][:MAX_CHUNKS]
        def one(ix):
            i, part = ix
            return evolve._llm(f"{rule}{ask}, en 3 à 5 points, la partie {i + 1}/{len(parts)} du document « {p.name} » :\n\n{part}",
                               max_tokens=400, fast=True)
        with cf.ThreadPoolExecutor(3) as ex:
            notes = list(ex.map(one, enumerate(parts)))
        joined = "\n\n".join(f"[Partie {i + 1}]\n{n}" for i, n in enumerate(notes) if n)
        if not joined:
            return "Aucune IA disponible pour résumer en ce moment."
        out = evolve._llm(f"Voici les résumés des parties du document « {p.name} ». {rule}{ask} : "
                          f"une synthèse globale en 6 à 10 points courts, sans doublons.\n\n{joined}", max_tokens=900, fast=True)
    if not out:
        return "Aucune IA disponible pour résumer en ce moment."
    out = f"Résumé de {p.name} ({len(t) // 1000 + 1} k caractères) :\n{out.strip()}"
    c[key] = out
    try:
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(dict(list(c.items())[-200:]), ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return out


S = {"type": "string"}
SPECS = [
    ("search_in_files", "Cherche des mots DANS le contenu des fichiers (texte, PDF, Word, Excel, PowerPoint) d'un dossier (défaut : dossier personnel ; accepte Téléchargements, Documents, Bureau). ext=\"pdf,docx\" facultatif.",
     {"type": "object", "properties": {"query": S, "folder": S, "ext": S, "limit": {"type": "integer"}}, "required": ["query"]}),
    ("summarize_file", "Résume fidèlement un document de n'importe quelle longueur (PDF, Word, Excel, PowerPoint, texte). focus = sujet à privilégier (facultatif).",
     {"type": "object", "properties": {"path": S, "focus": S}, "required": ["path"]}),
]
FUNCS = {"search_in_files": search_in_files, "summarize_file": summarize_file}
DANGEROUS = set()
