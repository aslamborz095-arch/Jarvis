"""Gmail + Google Agenda (OAuth, stocké sur le PC uniquement)."""
import os, json, time, base64, pathlib, datetime, urllib.parse
from email.mime.text import MIMEText

import httpx

BASE = pathlib.Path(__file__).parent
CLIENT = BASE / "data" / "google_client.json"
TOKEN = BASE / "data" / "google_token.json"
REDIRECT = "http://127.0.0.1:8765/api/google/callback"
SCOPES = "https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/drive.file"
TZ = "Europe/Paris"


def _client():
    d = json.loads(CLIENT.read_text())
    return d.get("installed") or d.get("web") or d


def save_client(raw):
    d = json.loads(raw)
    c = d.get("installed") or d.get("web") or d
    if "client_id" not in c or "client_secret" not in c:
        raise ValueError("Fichier JSON invalide : client_id / client_secret manquants.")
    CLIENT.parent.mkdir(exist_ok=True)
    CLIENT.write_text(json.dumps(d))


def status():
    return {"client": CLIENT.exists(), "connected": TOKEN.exists()}


def auth_url():
    c = _client()
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": c["client_id"], "redirect_uri": REDIRECT, "response_type": "code",
        "scope": SCOPES, "access_type": "offline", "prompt": "consent"})


def callback(code):
    c = _client()
    r = httpx.post("https://oauth2.googleapis.com/token", data={
        "code": code, "client_id": c["client_id"], "client_secret": c["client_secret"],
        "redirect_uri": REDIRECT, "grant_type": "authorization_code"}, timeout=20)
    r.raise_for_status()
    t = r.json(); t["expires_at"] = time.time() + t.get("expires_in", 3600) - 60
    t["scopes"] = t.get("scope", "")
    TOKEN.write_text(json.dumps(t))


def _token():
    if not TOKEN.exists():
        raise RuntimeError("Google n'est pas connecté : bouton ⚙ de Jarvis → Connecter Google.")
    t = json.loads(TOKEN.read_text())
    if time.time() > t.get("expires_at", 0):
        c = _client()
        r = httpx.post("https://oauth2.googleapis.com/token", data={
            "client_id": c["client_id"], "client_secret": c["client_secret"],
            "refresh_token": t["refresh_token"], "grant_type": "refresh_token"}, timeout=20)
        if r.status_code != 200:
            raise RuntimeError("Connexion Google expirée : reconnecte Google dans ⚙.")
        n = r.json(); t["access_token"] = n["access_token"]; t["expires_at"] = time.time() + n.get("expires_in", 3600) - 60
        TOKEN.write_text(json.dumps(t))
    return t["access_token"]


def _api(method, url, **kw):
    r = httpx.request(method, url, headers={"Authorization": f"Bearer {_token()}"}, timeout=30, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"Google {r.status_code} : {r.text[:200]}")
    return r.json() if r.text else {}


G = "https://gmail.googleapis.com/gmail/v1/users/me"
C = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


# ---------- Gmail ----------
def gmail_search(query: str = "is:unread", max_results: int = 8):
    """Cherche des mails (syntaxe Gmail : is:unread, from:x, subject:y, newer_than:2d…)."""
    ids = _api("GET", f"{G}/messages", params={"q": query, "maxResults": min(int(max_results), 20)}).get("messages", [])
    if not ids:
        return "Aucun mail."
    out = []
    for m in ids:
        d = _api("GET", f"{G}/messages/{m['id']}", params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]})
        h = {x["name"]: x["value"] for x in d.get("payload", {}).get("headers", [])}
        out.append(f"[{m['id']}] {h.get('Date', '')[:22]} — {h.get('From', '')} — {h.get('Subject', '(sans objet)')}\n   {d.get('snippet', '')[:160]}")
    return "\n".join(out)


def _body(p):
    if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(p["body"]["data"]).decode("utf-8", "replace")
    for sub in p.get("parts", []) or []:
        t = _body(sub)
        if t:
            return t
    return ""


def gmail_read(message_id: str):
    d = _api("GET", f"{G}/messages/{message_id}", params={"format": "full"})
    h = {x["name"]: x["value"] for x in d["payload"].get("headers", [])}
    return f"De : {h.get('From')}\nObjet : {h.get('Subject')}\nDate : {h.get('Date')}\n\n{(_body(d['payload']) or d.get('snippet', ''))[:5000]}"


def _raw(to, subject, body):
    m = MIMEText(body, "plain", "utf-8"); m["To"] = to; m["Subject"] = subject
    return base64.urlsafe_b64encode(m.as_bytes()).decode()


def gmail_draft(to: str, subject: str, body: str):
    _api("POST", f"{G}/drafts", json={"message": {"raw": _raw(to, subject, body)}})
    return f"Brouillon créé pour {to} (Gmail → Brouillons)."


def gmail_send(to: str, subject: str, body: str):
    _api("POST", f"{G}/messages/send", json={"raw": _raw(to, subject, body)})
    return f"Mail envoyé à {to}."


# ---------- Agenda ----------
def calendar_list(days: int = 7):
    now = datetime.datetime.now(datetime.timezone.utc)
    items = _api("GET", C, params={"timeMin": now.isoformat(), "timeMax": (now + datetime.timedelta(days=int(days))).isoformat(),
                                   "singleEvents": "true", "orderBy": "startTime", "maxResults": 30}).get("items", [])
    if not items:
        return "Aucun rendez-vous."
    return "\n".join(f"[{e['id']}] {(e['start'].get('dateTime') or e['start'].get('date'))[:16].replace('T', ' ')} — {e.get('summary', '(sans titre)')}"
                     + (f" @ {e['location']}" if e.get("location") else "") for e in items)


def calendar_add(title: str, start: str, end: str = "", description: str = "", location: str = ""):
    """start/end au format AAAA-MM-JJTHH:MM (heure de Paris). Fin par défaut : +1 h."""
    s = datetime.datetime.fromisoformat(start)
    e = datetime.datetime.fromisoformat(end) if end else s + datetime.timedelta(hours=1)
    ev = _api("POST", C, json={"summary": title, "description": description, "location": location,
                               "start": {"dateTime": s.isoformat(timespec="minutes") + ":00", "timeZone": TZ},
                               "end": {"dateTime": e.isoformat(timespec="minutes") + ":00", "timeZone": TZ}})
    return f"Ajouté à l'agenda : {title}, {s:%d/%m %H:%M} ({ev.get('id')})."


def calendar_delete(event_id: str):
    httpx.delete(f"{C}/{event_id}", headers={"Authorization": f"Bearer {_token()}"}, timeout=20)
    return "Rendez-vous supprimé."


S, I = {"type": "string"}, {"type": "integer"}
def _p(props, req=None):
    return {"type": "object", "properties": props, "required": req if req is not None else list(props)}

SPECS = [
    ("gmail_search", "Cherche/liste des mails Gmail (query syntaxe Gmail, défaut : non lus).", _p({"query": S, "max_results": I}, [])),
    ("gmail_read", "Lit un mail Gmail par son id.", _p({"message_id": S})),
    ("gmail_draft", "Crée un brouillon Gmail.", _p({"to": S, "subject": S, "body": S})),
    ("gmail_send", "Envoie un mail Gmail.", _p({"to": S, "subject": S, "body": S})),
    ("calendar_list", "Liste les rendez-vous Google Agenda des prochains jours.", _p({"days": I}, [])),
    ("calendar_add", "Ajoute un rendez-vous (start AAAA-MM-JJTHH:MM, heure de Paris).", _p({"title": S, "start": S, "end": S, "description": S, "location": S}, ["title", "start"])),
    ("calendar_delete", "Supprime un rendez-vous par son id.", _p({"event_id": S})),
]
FUNCS = {n: globals()[n] for n, _, _ in SPECS}
DANGEROUS = {"gmail_send", "calendar_delete"}
