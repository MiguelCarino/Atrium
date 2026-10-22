#!/usr/bin/env python3
"""Emergency alerts on the desktop (emergency-alerts.service): earthquakes,
tsunamis, severe weather, civil protection -- from the official (or, where
marked, well-known unofficial) public feeds for where you live. A BACKUP to
the official channels, never instead of them: sirens, radio and the phone's
cell-broadcast alerts come first, and every alarm card says so.

    emergency-alerts.py daemon            the service
    emergency-alerts.py sources [--json]  the sources for your country (and
                                          the global ones), on or off
    emergency-alerts.py enable|disable <source>
    emergency-alerts.py place <lat> <lon> [<country code>]
    emergency-alerts.py set <key> <value>   one emergency.conf setting (below)
    emergency-alerts.py config            emergency.conf as JSON
    emergency-alerts.py status            per source: last check, last alert
    emergency-alerts.py test [--quiet]    a drill: the alarm, marked as one

~/.config/hypr/emergency.conf (key=value; written with defaults on first run):
    lat= lon= country=                   your place (default: the time zone's city)
    lang=en                              es | pt | en: what the alarm card says
    sources=                             enabled sources, comma-separated;
                                         empty = the defaults for the country
    meteoalarm_region=                   (Europe) part of your area's name,
                                         e.g. "Madrid"; empty = whole country
    nina_ars=                            (Germany) your 12-digit
                                         Regionalschlüssel
    jp_pref=                             (Japan) your prefecture, e.g. 東京都
    preventive=notify                    SASMEX "Moderado": notify | alarm | off

What each kind does:
    alarm    red card on every screen (over games), the siren looping with the
             volume raised and unmuted -- Do Not Disturb does not apply --
             spoken words, the rough time to strong shaking for an
             earthquake. "OK" / Escape ends it, or ALARM_S.
    warning  a critical notification (stays until dismissed; shows in DND)
    info     a normal notification

Every poller keeps ONE connection per server open and reuses it (HTTP
keep-alive), so a poll costs the answer itself, not a new TLS handshake.
"""
import datetime
import http.client
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.expanduser("~/.config/hypr/emergency.conf")
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                     "hypr", "emergency-alerts.json")
SIREN = os.path.expanduser("~/.config/hypr/sounds/quake-alarm.wav")
STALE_S = 180               # older than this when first seen: history, not news
ALARM_S = 90
ALARM_VOLUME = 0.8
S_WAVE_KMS = 3.5
UA = "emergency-alerts.py (personal desktop; backup to official alerting)"
DEFAULTS = {"lat": "", "lon": "", "country": "", "lang": "en", "sources": "",
            "meteoalarm_region": "", "nina_ars": "", "jp_pref": "", "preventive": "notify"}
SPANISH = ("MX", "ES", "AR", "CL", "CO", "PE", "EC", "VE", "BO", "UY", "PY", "GT", "HN", "SV", "NI",
           "CR", "PA", "CU", "DO")


def lang_for(country):
    return "es" if country in SPANISH else "pt" if country in ("BR", "PT") else "en"


def _zone_defaults():
    """The first-run place: the time zone's principal city (region.py's
    zone_place: zone1970.tab, nothing looked up), until `place` names yours.
    No zone (a bare UTC box): no place, and the location-bound sources stay
    quiet until one is set."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import region
        here = region.zone_place()
    except Exception:
        here = None
    if here:
        DEFAULTS.update(lat=str(here["lat"]), lon=str(here["lon"]), country=here["country"],
                        lang=lang_for(here["country"]))


_zone_defaults()
METEOALARM = {"AT": "austria", "BE": "belgium", "BA": "bosnia-herzegovina", "BG": "bulgaria",
              "HR": "croatia", "CY": "cyprus", "CZ": "czechia", "DK": "denmark", "EE": "estonia",
              "FI": "finland", "FR": "france", "DE": "germany", "GR": "greece", "HU": "hungary",
              "IS": "iceland", "IE": "ireland", "IL": "israel", "IT": "italy", "LV": "latvia",
              "LT": "lithuania", "LU": "luxembourg", "MT": "malta", "MD": "moldova",
              "ME": "montenegro", "NL": "netherlands", "MK": "republic-of-north-macedonia",
              "NO": "norway", "PL": "poland", "PT": "portugal", "RO": "romania", "RS": "serbia",
              "SK": "slovakia", "SI": "slovenia", "ES": "spain", "SE": "sweden", "CH": "switzerland",
              "UA": "ukraine", "GB": "united-kingdom"}
CAP11 = "{urn:oasis:names:tc:emergency:cap:1.1}"
ATOM = "{http://www.w3.org/2005/Atom}"


# -- config / state ---------------------------------------------------------------
def config():
    conf = dict(DEFAULTS)
    if os.path.exists(CONF):
        with open(CONF) as handle:
            for line in handle:
                key, sep, value = line.split("#")[0].partition("=")
                if sep:
                    conf[key.strip()] = value.strip()
    else:
        save_config(conf)
    conf["country"] = conf["country"].upper()
    return conf


def save_config(conf):
    with open(CONF, "w") as handle:
        handle.write("# Emergency alerts (scripts/emergency-alerts.py; its docstring explains).\n"
                     + "".join(f"{k}={conf.get(k, v)}\n" for k, v in DEFAULTS.items()))


def load_state():
    try:
        with open(STATE) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


STATE_LOCK = threading.Lock()


def update_state(source, **values):
    with STATE_LOCK:
        state = load_state()
        entry = state.setdefault(source, {"seen": []})
        for k, v in values.items():
            if k == "seen":
                entry["seen"] = (entry["seen"] + v)[-300:]
            else:
                entry[k] = v
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + f".tmp{threading.get_ident()}"
        with open(tmp, "w") as handle:
            json.dump(state, handle)
        os.replace(tmp, STATE)
        return entry


def km_between(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 6371 * 2 * math.asin(math.sqrt(a))


def inside(lat, lon, polygon):
    """Point in polygon; polygon = [(lat, lon), ...]."""
    hit = False
    for (a_lat, a_lon), (b_lat, b_lon) in zip(polygon, polygon[1:] + polygon[:1]):
        if (a_lon > lon) != (b_lon > lon) and lat < (b_lat - a_lat) * (lon - a_lon) / (b_lon - a_lon) + a_lat:
            hit = not hit
    return hit


def when(text):
    """ISO-ish timestamp -> epoch (now when unreadable)."""
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00").replace("/", "-")).timestamp()
    except (AttributeError, ValueError):
        return time.time()


# -- HTTP with kept-alive connections ----------------------------------------------
class Http:
    """One HTTPS connection per host, reused across polls; reopened on error."""

    def __init__(self):
        self.conns = {}

    def get(self, url, timeout=10):
        u = urllib.parse.urlsplit(url)
        path = u.path + ("?" + u.query if u.query else "")
        for attempt in (1, 2):
            conn = self.conns.get(u.netloc)
            if conn is None:
                cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
                conn = self.conns[u.netloc] = cls(u.netloc, timeout=timeout)
            try:
                conn.timeout = timeout
                conn.request("GET", path, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
                resp = conn.getresponse()
                body = resp.read()
                if resp.status >= 400:
                    raise OSError(f"HTTP {resp.status} from {u.netloc}")
                return body
            except (OSError, http.client.HTTPException):
                conn.close()
                self.conns.pop(u.netloc, None)
                if attempt == 2:
                    raise
        return b""


# -- sources --------------------------------------------------------------------------
# Each: name, where (country codes, or "*"), kind (early warning / warnings /
# reports), every (seconds), default (on by default in those countries),
# fetch(http, conf) -> [alert dicts]:
#   {id, sent, headline, text, level: alarm|warning|info|none, lat, lon, quake}
def _alert(id, sent, headline, text, level, lat=None, lon=None, quake=False):
    return {"id": str(id), "sent": sent, "headline": headline, "text": text, "level": level,
            "lat": lat, "lon": lon, "quake": quake}


def sasmex(http, conf):
    root = ET.fromstring(http.get("https://rss.sasmex.net/api/v1/alerts/latest/cap/", 2.5))
    out = []
    for alert in root.iter(CAP11 + "alert"):
        info = alert.find(CAP11 + "info")
        if info is None or alert.findtext(CAP11 + "status") != "Actual":
            continue
        text = " ".join(filter(None, (info.findtext(CAP11 + "event"), info.findtext(CAP11 + "headline")))).lower()
        sev = info.findtext(CAP11 + "severity") or ""
        if "severo" in text or "fuerte" in text or sev in ("Severe", "Extreme"):
            level = "alarm"
        elif "moderado" in text:
            level = {"alarm": "alarm", "off": "none"}.get(conf["preventive"], "warning")
        else:
            level = "info"
        lat = lon = None
        try:
            lat, lon = (float(v) for v in (info.findtext(f"{CAP11}area/{CAP11}circle") or "").split()[0].split(","))
        except (IndexError, ValueError):
            pass
        out.append(_alert(alert.findtext(CAP11 + "identifier"), when(alert.findtext(CAP11 + "sent")),
                          info.findtext(CAP11 + "headline") or "", info.findtext(CAP11 + "description") or "",
                          level, lat, lon, quake=True))
    return out


def naad(http, conf):
    """Canada's NAAD (Alert Ready): every CAP alert in Canada, kept to the
    ones whose polygon holds your place. Includes NRCan's earthquake early
    warning."""
    root = ET.fromstring(http.get("https://rss.naad-adna.pelmorex.com/", 5))
    lat, lon = float(conf["lat"]), float(conf["lon"])
    out = []
    for e in root.iter(ATOM + "entry"):
        cats = {c.get("term", "").split("=", 1)[0]: c.get("term", "").split("=", 1)[-1]
                for c in e.findall(ATOM + "category")}
        if cats.get("status") != "Actual":
            continue
        polys = []
        for p in e.iter("{http://www.georss.org/georss}polygon"):
            nums = [float(v) for v in (p.text or "").split()]
            polys.append(list(zip(nums[::2], nums[1::2])))
        if polys and not any(inside(lat, lon, p) for p in polys):
            continue
        sev, eid = cats.get("severity", ""), e.findtext(ATOM + "id") or ""
        quake = ":eew:" in eid
        level = "alarm" if (quake or sev == "Extreme") else "warning" if sev == "Severe" else "info"
        summary = re.sub(r"<[^>]+>", "  ", e.findtext(ATOM + "summary") or "")
        out.append(_alert(eid, when(e.findtext(ATOM + "updated")), e.findtext(ATOM + "title") or "",
                          summary[:300], level, quake=quake))
    return out


def nws(http, conf):
    data = json.loads(http.get(f"https://api.weather.gov/alerts/active?point={conf['lat']},{conf['lon']}", 10))
    out = []
    for f in data.get("features", []):
        p = f.get("properties", {})
        sev = p.get("severity", "")
        level = {"Extreme": "alarm", "Severe": "warning", "Moderate": "info"}.get(sev, "none")
        out.append(_alert(p.get("id"), when(p.get("sent")), p.get("headline") or p.get("event", ""),
                          (p.get("instruction") or p.get("description") or "")[:300], level))
    return out


def meteoalarm(http, conf):
    slug = METEOALARM.get(conf["country"])
    if not slug:
        return []
    root = ET.fromstring(http.get(f"https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom-{slug}", 20))
    cap = "{urn:oasis:names:tc:emergency:cap:1.2}"
    want = conf["meteoalarm_region"].lower()
    out = []
    for e in root.iter(ATOM + "entry"):
        area = e.findtext(cap + "areaDesc") or ""
        if want and want not in area.lower():
            continue
        sev = e.findtext(cap + "severity") or ""
        level = {"Extreme": "alarm", "Severe": "warning", "Moderate": "info"}.get(sev, "none")
        out.append(_alert(e.findtext(cap + "identifier") or e.findtext(ATOM + "id"),
                          when(e.findtext(cap + "sent")), e.findtext(ATOM + "title") or "", area, level))
    return out


def nina(http, conf):
    ars = conf["nina_ars"]
    if not re.fullmatch(r"\d{12}", ars):
        return []
    ars = ars[:5] + "0000000"           # the API works on district level
    data = json.loads(http.get(f"https://warnung.bund.de/api31/dashboard/{ars}.json", 10))
    out = []
    for item in data:
        d = item.get("payload", {}).get("data", {})
        sev = d.get("severity", "")
        level = {"Extreme": "alarm", "Severe": "warning", "Moderate": "info"}.get(sev, "none")
        out.append(_alert(item.get("id"), when(item.get("sent")), d.get("headline", ""), d.get("provider", ""), level))
    return out


def p2pquake(http, conf):
    """Japan: JMA's earthquake early warnings (緊急地震速報, code 556) and
    earthquake reports (551), relayed by P2PQuake -- unofficial."""
    data = json.loads(http.get("https://api.p2pquake.net/v2/history?codes=556&codes=551&limit=10", 5))
    pref = conf["jp_pref"]
    out = []
    for item in data:
        q = item.get("earthquake") or {}
        hypo = q.get("hypocenter") or {}
        if item.get("code") == 556:
            if item.get("cancelled"):
                continue
            areas = [a.get("pref", "") for a in item.get("areas") or []]
            if pref and pref not in areas:
                continue
            out.append(_alert(item.get("id"), when(item.get("time")), "緊急地震速報 (警報)",
                              f"{hypo.get('name', '')}  ·  {', '.join(sorted(set(areas)))[:200]}",
                              "alarm", hypo.get("latitude"), hypo.get("longitude"), quake=True))
        else:
            scale = q.get("maxScale") or 0
            level = "warning" if scale >= 50 else "info" if scale >= 40 else "none"
            out.append(_alert(item.get("id"), when(item.get("time")),
                              f"地震情報: {hypo.get('name', '')} M{hypo.get('magnitude', '?')}",
                              f"最大震度 {scale / 10:g}", level, hypo.get("latitude"), hypo.get("longitude")))
    return out


def tsunami(http, conf, feed):
    root = ET.fromstring(http.get(f"https://www.tsunami.gov/events/xml/{feed}Atom.xml", 10))
    out = []
    for e in root.iter(ATOM + "entry"):
        title = e.findtext(ATOM + "title") or ""
        summary = re.sub(r"<[^>]+>", " ", e.findtext(ATOM + "summary") or "")
        low = (title + " " + summary).lower()
        level = "warning" if "warning" in low and "no tsunami warning" not in low else \
                "info" if ("watch" in low or "advisory" in low) else "none"
        out.append(_alert(e.findtext(ATOM + "id"), when(e.findtext(ATOM + "updated")), title,
                          " ".join(summary.split())[:300], level))
    return out


def quakes_near(http, conf, url, parse, radius=300, mag=4.5):
    lat, lon = float(conf["lat"]), float(conf["lon"])
    out = []
    for qid, t, m, place, qlat, qlon in parse(json.loads(http.get(url, 15))):
        if m is None or qlat is None or m < mag:
            continue
        km = km_between(lat, lon, qlat, qlon)
        if km > radius:
            continue
        out.append(_alert(qid, t, f"M{m:.1f} {place}", f"~{km:.0f} km away", "info", qlat, qlon))
    return out


def usgs(http, conf):
    def parse(d):
        for f in d.get("features", []):
            p, (qlon, qlat, *_) = f["properties"], f["geometry"]["coordinates"]
            yield f["id"], p["time"] / 1000, p.get("mag"), p.get("place", ""), qlat, qlon
    return quakes_near(http, conf, "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_hour.geojson",
                       parse)


def emsc(http, conf):
    url = (f"https://www.seismicportal.eu/fdsnws/event/1/query?format=json&limit=20&minmag=4.5"
           f"&lat={conf['lat']}&lon={conf['lon']}&maxradius=2.7")

    def parse(d):
        for f in d.get("features", []):
            p = f["properties"]
            yield f.get("id"), when(p.get("time")), p.get("mag"), p.get("flynn_region", "").title(), p.get("lat"), p.get("lon")
    return quakes_near(http, conf, url, parse)


CAP12 = "{urn:oasis:names:tc:emergency:cap:1.2}"


def cap_polygons(info, ns):
    """[(lat, lon) ...] per <area><polygon> of a CAP <info>."""
    out = []
    for poly in info.iter(ns + "polygon"):
        pts = []
        for pair in (poly.text or "").split():
            try:
                a, b = pair.split(",")
                pts.append((float(a), float(b)))
            except ValueError:
                pass
        if len(pts) > 2:
            out.append(pts)
    return out


def idap(http, conf):
    """Brazil: Defesa Civil's IDAP -- the civil-protection alerts the phones
    get (cell broadcast, SMS 40199), kept to those whose area holds your
    place. 3.5 MB a fetch and no compression offered: hence every 10 min."""
    root = ET.fromstring(http.get("https://idapfile.mdr.gov.br/idap/api/rss/cap", 60))
    lat, lon = float(conf["lat"]), float(conf["lon"])
    out = []
    for alert in root.iter(CAP12 + "alert"):
        if alert.findtext(CAP12 + "status") != "Actual":
            continue
        for info in alert.findall(CAP12 + "info"):
            polys = cap_polygons(info, CAP12)
            if not any(inside(lat, lon, p) for p in polys):
                continue
            sev = info.findtext(CAP12 + "severity") or ""
            level = {"Extreme": "alarm", "Severe": "warning"}.get(sev, "info")
            out.append(_alert(alert.findtext(CAP12 + "identifier"), when(alert.findtext(CAP12 + "sent")),
                              info.findtext(CAP12 + "headline") or info.findtext(CAP12 + "event") or "",
                              (info.findtext(CAP12 + "instruction") or info.findtext(CAP12 + "description") or "")[:300],
                              level))
            break
    return out


def inmet(http, conf):
    """Brazil: INMET's weather warnings, kept to those whose polygon holds
    your place; orange (Perigo) and red (Grande Perigo) only -- the yellow
    ones cover half the country most days."""
    data = json.loads(http.get("https://apiprevmet3.inmet.gov.br/avisos/ativos", 30))
    lat, lon = float(conf["lat"]), float(conf["lon"])
    out = []
    for a in data.get("hoje", []) + data.get("futuro", []):
        try:
            geo = json.loads(a.get("poligono") or "{}")
        except ValueError:
            continue
        rings = geo.get("coordinates", [])
        if geo.get("type") == "MultiPolygon":
            rings = [r for poly in rings for r in poly[:1]]
        else:
            rings = rings[:1]
        if not any(inside(lat, lon, [(y, x) for x, y in ring]) for ring in rings):
            continue
        sev = a.get("severidade", "")
        level = {"Grande Perigo": "alarm", "Perigo": "warning"}.get(sev, "none")
        out.append(_alert(a.get("codigo") or a.get("id"), when((a.get("inicio") or "").replace(" ", "T")),
                          f"INMET: {a.get('descricao', '')} ({sev})", " ".join(a.get("riscos") or [])[:300], level))
    return out


def ideam(http, conf):
    """Colombia: IDEAM's weather / hydrology warnings. The feed is an index;
    each new entry's CAP message is fetched once for its polygon."""
    root = ET.fromstring(http.get("https://alertascap.ideam.gov.co/ospa/xml", 20))
    lat, lon = float(conf["lat"]), float(conf["lon"])
    seen = set(load_state().get("ideam", {}).get("seen", []))
    out = []
    for e in root.iter(ATOM + "entry"):
        eid = e.findtext(ATOM + "id") or ""
        if eid in seen:
            out.append(_alert(eid, 0, "", "", "none"))      # known: keep it known
            continue
        link = next((l.get("href") for l in e.findall(ATOM + "link")
                     if l.get("type") == "application/cap+xml"), eid)
        try:
            cap = ET.fromstring(http.get(link, 20))
        except (OSError, ET.ParseError):
            continue
        for info in cap.findall(CAP12 + "info"):
            polys = cap_polygons(info, CAP12)
            if polys and not any(inside(lat, lon, p) for p in polys):
                continue
            sev = info.findtext(CAP12 + "severity") or ""
            level = {"Extreme": "alarm", "Severe": "warning", "Moderate": "info"}.get(sev, "none")
            out.append(_alert(eid, when(cap.findtext(CAP12 + "sent")),
                              info.findtext(CAP12 + "event") or e.findtext(ATOM + "title") or "",
                              (info.findtext(CAP12 + "description") or "")[:300], level))
            break
        else:
            out.append(_alert(eid, 0, "", "", "none"))      # not for your place
    return out


def gdacs(http, conf):
    """UN/EC Global Disaster Alert and Coordination System: earthquakes,
    tsunamis, cyclones, floods, volcanoes, droughts, wildfires -- orange and
    red alerts within 1000 km."""
    root = ET.fromstring(http.get("https://www.gdacs.org/xml/rss.xml", 30))
    g, geo = "{http://www.gdacs.org}", "{http://www.w3.org/2003/01/geo/wgs84_pos#}"
    lat, lon = float(conf["lat"]), float(conf["lon"])
    out = []
    for item in root.iter("item"):
        level = (item.findtext(g + "alertlevel") or "").lower()
        try:
            qlat, qlon = float(item.findtext(geo + "lat")), float(item.findtext(geo + "long"))
        except (TypeError, ValueError):
            continue
        km = km_between(lat, lon, qlat, qlon)
        if level not in ("orange", "red") or km > 1000:
            continue
        out.append(_alert(item.findtext("guid") or item.findtext("link"), when(item.findtext(g + "fromdate") or ""),
                          item.findtext("title") or "", f"~{km:.0f} km away  ·  GDACS {level} alert",
                          "warning" if level == "red" else "info", qlat, qlon))
    return out


SOURCES = {
    "sasmex":     ("SASMEX earthquake early warning (CIRES, official)", ["MX"], "early warning", 3, True, sasmex),
    "naad":       ("Alert Ready / NAAD (Canada, official: all hazards, incl. NRCan quake early warning)",
                   ["CA"], "early warning + warnings", 5, True, naad),
    "p2pquake":   ("JMA quake early warning + reports via P2PQuake (Japan, unofficial relay)",
                   ["JP"], "early warning + reports", 3, True, p2pquake),
    "idap":       ("Defesa Civil alerts / IDAP (Brazil, official: what the phones get)", ["BR"],
                   "warnings", 600, True, idap),
    "inmet":      ("INMET weather warnings, orange + red (Brazil, official)", ["BR"], "warnings", 600, True, inmet),
    "ideam":      ("IDEAM weather and flood warnings (Colombia, official)", ["CO"], "warnings", 300, True, ideam),
    "nws":        ("US National Weather Service warnings (official)", ["US", "PR", "GU"], "warnings", 60, True, nws),
    "meteoalarm": ("MeteoAlarm weather warnings (Europe, national weather services)",
                   list(METEOALARM), "warnings", 300, True, meteoalarm),
    "nina":       ("NINA / MoWaS civil protection (Germany, official)", ["DE"], "warnings", 60, True, nina),
    "ptwc":       ("Tsunami messages, Pacific (NOAA PTWC, official)", ["*"], "warnings", 60, False,
                   lambda h, c: tsunami(h, c, "PHEB")),
    "ntwc":       ("Tsunami messages, US/Canada (NOAA NTWC, official)", ["US", "CA"], "warnings", 60, True,
                   lambda h, c: tsunami(h, c, "PAAQ")),
    "gdacs":      ("GDACS global disasters near you (UN / EU, orange + red)", ["*"], "warnings", 600, True, gdacs),
    "usgs":       ("USGS earthquakes near you (reports, minutes after)", ["*"], "reports", 60, False, usgs),
    "emsc":       ("EMSC earthquakes near you (reports, minutes after)", ["*"], "reports", 60, False, emsc),
}
# Reports after the fact: the best one for where you are on by default.
REPORT_DEFAULT = {"MX": "usgs", "US": "usgs", "CA": "usgs", "CO": "usgs", "BR": "usgs"}


def available(conf):
    return [s for s, (_, where, *_) in SOURCES.items() if "*" in where or conf["country"] in where]


def enabled(conf):
    if conf["sources"].strip():
        return [s for s in conf["sources"].split(",") if s.strip() in SOURCES]
    on = [s for s in available(conf) if SOURCES[s][4]]
    report = REPORT_DEFAULT.get(conf["country"], "usgs" if conf["country"] not in METEOALARM else "emsc")
    return on + ([report] if report not in on else [])


# -- what an alert does ----------------------------------------------------------------
def notify(title, body, urgency):
    subprocess.run(["notify-send", "-a", "Emergency alert", "-u", urgency, "-i", "dialog-warning", title, body],
                   capture_output=True)


def alarm(alert, conf, drill=False, quiet=False):
    text, eta = alert["text"], None
    if alert.get("lat") is not None and alert.get("quake"):
        km = km_between(float(conf["lat"]), float(conf["lon"]), alert["lat"], alert["lon"])
        eta = km / S_WAVE_KMS - (time.time() - alert["sent"])
        text += f"  ·  ~{km:.0f} km"
    spec = {"headline": alert["headline"], "text": text, "eta": eta, "drill": drill, "quake": alert.get("quake"),
            "lang": conf["lang"], "seconds": ALARM_S}
    volume, loop = None, None
    if not quiet:
        volume = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                                capture_output=True, text=True).stdout.strip()
        subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"])
        subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", str(ALARM_VOLUME)])
        lang = conf["lang"] if conf["lang"] in ("es", "pt") else "en"
        words = {"es": ("Simulacro. " if drill else "") + ("Alerta sísmica. Alerta sísmica." if alert.get("quake")
                                                           else "Alerta de emergencia."),
                 "pt": ("Simulado. " if drill else "") + ("Alerta de terremoto." if alert.get("quake")
                                                          else "Alerta de emergência."),
                 "en": ("Drill. " if drill else "") + "Emergency alert."}[lang]
        subprocess.Popen(["spd-say", "-l", lang, "-r", "-10", words],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(SIREN):
            loop = subprocess.Popen(["sh", "-c", f'while :; do pw-play "{SIREN}" || sleep 1; done'],
                                    start_new_session=True)
    try:
        subprocess.run([sys.executable, os.path.abspath(__file__), "card", json.dumps(spec)], timeout=ALARM_S + 10)
    except subprocess.TimeoutExpired:
        pass
    finally:
        if loop:
            os.killpg(loop.pid, 15)
        if volume:
            parts = volume.split()
            if len(parts) > 1:
                subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", parts[1]])
                subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if "[MUTED]" in volume else "0"])


ALARM_LOCK = threading.Lock()


def act(alert, conf):
    if alert["level"] == "alarm":
        with ALARM_LOCK:                # two sources, one quake: one card at a time
            alarm(alert, conf)
    elif alert["level"] == "warning":
        notify(alert["headline"], alert["text"], "critical")
    elif alert["level"] == "info":
        notify(alert["headline"], alert["text"], "normal")


def poller(name, conf):
    _, _, _, every, _, fetch = SOURCES[name]
    http = Http()
    first = True
    while True:
        try:
            alerts = fetch(http, conf)
            seen = set(load_state().get(name, {}).get("seen", []))
            new = [a for a in alerts if a["id"] not in seen]
            update_state(name, last_ok=time.time(), seen=[a["id"] for a in new], error="")
            for a in sorted(new, key=lambda a: a["sent"]):
                # At start, only what is still happening; afterwards, anything fresh.
                if time.time() - a["sent"] < STALE_S and a["level"] != "none":
                    print(f"emergency-alerts: {name}: {a['level']}: {a['headline']}", flush=True)
                    update_state(name, last_alert={"headline": a["headline"], "level": a["level"], "at": time.time()})
                    threading.Thread(target=act, args=(a, conf), daemon=True).start()
            first = False
        except Exception as exc:        # network down, a feed changed: keep trying
            update_state(name, error=f"{type(exc).__name__}: {exc}"[:200])
            print(f"emergency-alerts: {name}: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(every)


def daemon():
    conf = config()
    if not conf["lat"] or not conf["lon"]:
        # No place yet (no time zone to guess from): every source measures
        # distance from it, so none runs until `place` names one.
        print("emergency-alerts: no place set (emergency-alerts.py place LAT LON CC): nothing to watch",
              flush=True)
        while True:
            time.sleep(3600)
    names = enabled(conf)
    print(f"emergency-alerts: {conf['country']} {conf['lat']},{conf['lon']}: {', '.join(names) or 'nothing'}",
          flush=True)
    for name in names:
        threading.Thread(target=poller, args=(name, conf), daemon=True, name=name).start()
    while True:
        time.sleep(3600)


# -- the card ---------------------------------------------------------------------------
def card(spec):
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell

    info = json.loads(spec)
    lang = info.get("lang", "en")
    es = lang == "es"
    words = {
        "title": ("ALERTA SÍSMICA" if es else "EARTHQUAKE ALERT") if info.get("quake")
        else ("ALERTA DE EMERGENCIA" if es else "EMERGENCY ALERT"),
        "drill": "SIMULACRO  ·  ESTO ES UNA PRUEBA" if es else "DRILL  ·  THIS IS A TEST",
        "note": ("Siga su protocolo de protección civil.\nAviso de respaldo por internet: puede llegar tarde. "
                 "Las alertas oficiales (sirenas, radio, celular) mandan.") if es else
                ("Follow your emergency plan.\nInternet backup alert: it may arrive late. "
                 "Official alerts (sirens, radio, phone) come first."),
        "ok": "Entendido" if es else "OK",
        "eta": "Sacudida fuerte en ~{:.0f} s (estimado)" if es else "Strong shaking in ~{:.0f} s (estimate)",
        "now": "La sacudida puede estar llegando" if es else "Shaking may be arriving now",
    }
    if lang == "pt":
        words = {"title": "ALERTA DE TERREMOTO" if info.get("quake") else "ALERTA DE EMERGÊNCIA",
                 "drill": "SIMULADO  ·  ISTO É UM TESTE",
                 "note": "Siga o plano de proteção e defesa civil.\nAviso de reserva pela internet: pode chegar "
                         "atrasado. Os alertas oficiais (Defesa Civil no celular, rádio, sirenes) vêm primeiro.",
                 "ok": "Entendido", "eta": "Tremor forte em ~{:.0f} s (estimativa)",
                 "now": "O tremor pode estar chegando"}
    css = Gtk.CssProvider()
    css.load_from_data(b"""
        window.emergency { background-color: rgba(150, 0, 0, 0.92); }
        .e-title { color: #ffffff; font-size: 64px; font-weight: 800; }
        .e-drill { color: #ffe08a; font-size: 26px; font-weight: 700; }
        .e-text { color: #ffffff; font-size: 24px; }
        .e-eta { color: #ffffff; font-size: 40px; font-weight: 700; }
        .e-note { color: rgba(255,255,255,0.8); font-size: 16px; }
        button.e-ok { font-size: 22px; padding: 10px 40px; color: #600000;
                      background: #ffffff; border-radius: 6px; border: none; }
    """)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10)
    start, etas = time.time(), []

    def label(text, cls):
        w = Gtk.Label(label=text)
        w.get_style_context().add_class(cls)
        w.set_line_wrap(True)
        w.set_justify(Gtk.Justification.CENTER)
        return w

    display = Gdk.Display.get_default()
    for i in range(display.get_n_monitors()):
        win = Gtk.Window()
        win.get_style_context().add_class("emergency")
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "emergency-alert")
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(win, display.get_monitor(i))
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(win, edge, True)
        GtkLayerShell.set_exclusive_zone(win, -1)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.ON_DEMAND)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        if info.get("drill"):
            box.pack_start(label(words["drill"], "e-drill"), False, False, 0)
        box.pack_start(label(words["title"], "e-title"), False, False, 0)
        box.pack_start(label(info["headline"], "e-text"), False, False, 0)
        box.pack_start(label(info["text"], "e-text"), False, False, 0)
        eta = label("", "e-eta")
        etas.append(eta)
        box.pack_start(eta, False, False, 0)
        box.pack_start(label(words["note"], "e-note"), False, False, 0)
        ok = Gtk.Button(label=words["ok"])
        ok.get_style_context().add_class("e-ok")
        ok.set_halign(Gtk.Align.CENTER)
        ok.connect("clicked", lambda _b: Gtk.main_quit())
        box.pack_start(ok, False, False, 0)
        win.add(box)
        win.connect("key-press-event", lambda _w, e: e.keyval == Gdk.KEY_Escape and Gtk.main_quit())
        win.show_all()

    def tick():
        left = None if info.get("eta") is None else info["eta"] - (time.time() - start)
        text = "" if left is None else words["eta"].format(left) if left > 0 else words["now"]
        for w in etas:
            w.set_text(text)
        if time.time() - start > info.get("seconds", ALARM_S):
            Gtk.main_quit()
            return False
        return True

    tick()
    GLib.timeout_add(500, tick)
    Gtk.main()


# -- commands ------------------------------------------------------------------------------
def restart():
    subprocess.run(["systemctl", "--user", "restart", "emergency-alerts.service"], capture_output=True)


def main(argv):
    cmd = argv[0] if argv else "sources"
    conf = config()
    if cmd == "daemon":
        daemon()
    elif cmd == "card" and len(argv) == 2:
        card(argv[1])
    elif cmd == "sources":
        on = enabled(conf)
        rows = [{"id": s, "name": SOURCES[s][0], "kind": SOURCES[s][2], "on": s in on} for s in available(conf)]
        if "--json" in argv:
            print(json.dumps({"country": conf["country"], "sources": rows}))
        else:
            for r in rows:
                print(f"{'on ' if r['on'] else 'off'}  {r['id']:11} {r['kind']:24} {r['name']}")
    elif cmd in ("enable", "disable") and len(argv) == 2 and argv[1] in SOURCES:
        on = enabled(conf)
        on = sorted(set(on) | {argv[1]}) if cmd == "enable" else [s for s in on if s != argv[1]]
        conf["sources"] = ",".join(on) or "none"
        save_config(conf)
        restart()
        print(f"{argv[1]} {cmd}d; on: {', '.join(on) or 'nothing'}")
    elif cmd == "place" and len(argv) in (3, 4):
        conf["lat"], conf["lon"] = argv[1], argv[2]
        if len(argv) == 4:
            conf["country"] = argv[3].upper()
            conf["lang"] = lang_for(conf["country"])
            conf["sources"] = ""            # the new country's defaults
        save_config(conf)
        restart()
        main(["sources"])
    elif cmd == "set" and len(argv) >= 2 and argv[1] in DEFAULTS and argv[1] not in ("lat", "lon", "country"):
        conf[argv[1]] = " ".join(argv[2:])
        save_config(conf)
        restart()
    elif cmd == "config":
        print(json.dumps(conf, ensure_ascii=False))
    elif cmd == "status":
        state = load_state()
        out = {}
        for s in enabled(conf):
            e = state.get(s, {})
            out[s] = {"last_ok_s_ago": round(time.time() - e["last_ok"]) if e.get("last_ok") else None,
                      "error": e.get("error") or None, "last_alert": e.get("last_alert")}
        print(json.dumps(out, ensure_ascii=False, indent=1))
    elif cmd == "test":
        lat, lon = float(conf["lat"]), float(conf["lon"])
        es = conf["lang"] == "es"
        drill = _alert("drill", time.time(), "Simulacro: Sismo Severo en Costa de Guerrero" if es else
                       "Drill: strong earthquake", "Prueba del aviso de escritorio" if es else "Desktop alert test",
                       "alarm", lat - 2.4, lon - 0.6, quake=True)
        alarm(drill, conf, drill=True, quiet="--quiet" in argv)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
