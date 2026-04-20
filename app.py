#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify, render_template_string, session, redirect
import os, sqlite3, uuid, requests, smtplib, json, hashlib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps

# ── PATH DATABASE ─────────────────────────────────
DATA_DIR = os.environ.get("DATA_DIR", "/data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "web_assistenza.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "rotondi_secret_2024_xyz")

BOT_TOKEN        = os.environ.get("BOT_TOKEN", "")
TECNICI_GROUP_ID = os.environ.get("TECNICI_GROUP_ID", "")
BACKOFFICE_IDS   = os.environ.get("BACKOFFICE_IDS", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "")
GMAPS_KEY = os.environ.get("GMAPS_KEY", "")
SEDE      = "Via di Sant'Alessandro 349, Roma, Italia"
ADMIN_PWD_HASH_DEFAULT = hashlib.sha256("RotondiRoma01!!".encode()).hexdigest()

DEFAULT_TARIFFE = {
    "roma_uscita": 80.0, "roma_ora_succ": 40.0,
    "fuori_km": 0.70, "fuori_viaggio": 32.0, "fuori_lavoro": 40.0
}

DEFAULT_CONDIZIONI = {
    "it": {
        "c1": "L'assistenza tecnica e' un servizio a pagamento, anche se il prodotto e' in garanzia.",
        "c2": "In garanzia vengono riconosciute solo le parti di ricambio difettose (sostituzione senza costo).",
        "c3": "Sempre a carico del cliente: Manodopera - Spostamento tecnico - Costo chiamata",
        "freelance": "I tecnici che operano con Rotondi Group sono liberi professionisti freelance indipendenti, selezionati dalla nostra azienda. Non sono dipendenti Rotondi Group."
    },
    "en": {
        "c1": "Technical assistance is a paid service, even if the product is under warranty.",
        "c2": "Under warranty only defective spare parts are replaced at no cost.",
        "c3": "Always charged to customer: Labour - Technician travel - Call-out fee",
        "freelance": "Our technicians are independent freelance professionals selected by Rotondi Group. They are not company employees."
    },
    "bn": {
        "c1": "prozyuktiga sahayata akti paid service, omanki ponyo warranty te thakleo.",
        "c2": "warranty te shudhu trutipurno jontrangsho binamulyay protisthapan kora hoy.",
        "c3": "sorboda grahoker khoroch: shrom - jatayat - kol charge",
        "freelance": "amader technician ra swadhin freelance professional, Rotondi Group kortrik nirbachit."
    },
    "zh": {
        "c1": "技术援助是付费服务，即使产品在保修期内也是如此。",
        "c2": "保修期内仅免费更换有缺陷的零件。",
        "c3": "始终由客户承担：人工费 - 差旅费 - 上门费",
        "freelance": "我们的技术人员是独立自由职业者，由罗通迪集团选派，非公司雇员。"
    },
    "ar": {
        "c1": "المساعدة التقنية خدمة مدفوعة، حتى لو كان المنتج تحت الضمان.",
        "c2": "الضمان يشمل فقط استبدال قطع الغيار المعيبة مجانا.",
        "c3": "دائما على حساب العميل: اجرة العمل - التنقل - رسوم الزيارة",
        "freelance": "فنيونا محترفون مستقلون فريلانس، من اختيار روتوندي جروب، وليسوا موظفين."
    }
}

def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS richieste_web (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            protocollo TEXT UNIQUE, nome TEXT, indirizzo TEXT,
            telefono TEXT, email TEXT, marca TEXT, modello TEXT,
            seriale TEXT, problema TEXT, lingua TEXT,
            stato TEXT DEFAULT 'aperta', data TEXT, tecnico TEXT, fascia TEXT)""")
        c.execute("CREATE TABLE IF NOT EXISTS impostazioni (chiave TEXT PRIMARY KEY, valore TEXT)")
        c.commit()
        for k, v in DEFAULT_TARIFFE.items():
            c.execute("INSERT OR IGNORE INTO impostazioni VALUES (?,?)", ("tariffa_"+k, str(v)))
        for lang, testi in DEFAULT_CONDIZIONI.items():
            for campo, testo in testi.items():
                c.execute("INSERT OR IGNORE INTO impostazioni VALUES (?,?)", ("cond_"+lang+"_"+campo, testo))
        c.commit()

def get_setting(key, default=None):
    with sqlite3.connect(DB_PATH) as c:
        r = c.execute("SELECT valore FROM impostazioni WHERE chiave=?", (key,)).fetchone()
    return r[0] if r else default

def set_setting(key, value):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("INSERT OR REPLACE INTO impostazioni VALUES (?,?)", (key, str(value)))
        c.commit()

def get_tariffe():
    return {k: float(get_setting("tariffa_"+k, DEFAULT_TARIFFE[k])) for k in DEFAULT_TARIFFE}

def get_condizioni(lang):
    result = {}
    for campo in ["c1","c2","c3","freelance"]:
        result[campo] = get_setting("cond_"+lang+"_"+campo, DEFAULT_CONDIZIONI.get(lang,{}).get(campo,""))
    return result

def genera_protocollo():
    return "RG" + datetime.now().strftime("%y%m%d") + str(uuid.uuid4())[:4].upper()

def calcola_preventivo(indirizzo_cliente):
    try:
        params = {
            "origins": SEDE,
            "destinations": indirizzo_cliente,
            "mode": "driving",
            "key": GMAPS_KEY,
            "language": "it"
        }
        r = requests.get("https://maps.googleapis.com/maps/api/distancematrix/json", params=params, timeout=10)
        data = r.json()
        if data.get("status") != "OK": return None
        element = data["rows"][0]["elements"][0]
        if element.get("status") != "OK": return None
        dist_km = element["distance"]["value"] / 1000
        dur_h   = element["duration"]["value"] / 3600
        t = get_tariffe()
        if dist_km < 10:
            costo = t["roma_uscita"]
            zona = "Zona di Roma (dentro GRA)"
            dettaglio = "Uscita + 1h lavoro: " + str(t["roma_uscita"]) + " + IVA"
        else:
            dist_ar  = dist_km * 2
            dur_ar   = dur_h * 2
            costo_km = dist_ar * t["fuori_km"]
            costo_v  = dur_ar * t["fuori_viaggio"]
            costo_l  = t["fuori_lavoro"]
            costo    = costo_km + costo_v + costo_l
            zona = "Provincia di Roma, Lazio e resto d'Italia"
            dettaglio = (
                "Km A/R (" + str(round(dist_ar,0)) + "km x " + str(t["fuori_km"]) + "): " + str(round(costo_km,2)) + "\n"
                "Viaggio A/R (" + str(round(dur_ar,1)) + "h x " + str(t["fuori_viaggio"]) + "): " + str(round(costo_v,2)) + "\n"
                "1h lavoro: " + str(t["fuori_lavoro"])
            )
        return {
            "zona": zona,
            "dist_km": round(dist_km, 1),
            "dist_km_ar": round(dist_km*2, 1),
            "dur_h": round(dur_h, 1),
            "costo_min": round(costo, 2),
            "dettaglio": dettaglio,
            "dest_label": element["distance"]["text"],
            "dur_label": element["duration"]["text"]
        }
    except Exception as e:
        print("Maps error: " + str(e))
        return None

def invia_telegram(text, keyboard=None):
    if not BOT_TOKEN or not TECNICI_GROUP_ID: return None
    p = {"chat_id": TECNICI_GROUP_ID, "text": text, "parse_mode": "Markdown"}
    if keyboard: p["reply_markup"] = json.dumps(keyboard)
    try:
        r = requests.post("https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage", json=p, timeout=10)
        return r.json().get("result", {}).get("message_id")
    except: return None

def invia_telegram_bo(text):
    if not BOT_TOKEN or not BACKOFFICE_IDS: return
    for bo in BACKOFFICE_IDS.split(","):
        try:
            requests.post("https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage",
                json={"chat_id": bo.strip(), "text": text, "parse_mode": "Markdown"}, timeout=10)
        except: pass

def invia_email(to, subject, html):
    if not SMTP_USER or not SMTP_PASS: return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_FROM, to, msg.as_string())
        return True
    except Exception as e:
        print("Email error: " + str(e))
        return False

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect("/admin/login")
        return f(*args, **kwargs)
    return decorated

HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Assistenza Tecnica - Rotondi Group Roma</title>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--dark:#0d0d14;--dark2:#14141f;--card:#1a1a2e;--border:rgba(255,255,255,0.09);--gold:#c9a84c;--gold2:#e8c96d;--text:#e8e6e0;--muted:rgba(232,230,224,0.55);--green:#2ea043;--red:#f85149}
body{background:var(--dark);color:var(--text);font-family:'DM Sans',sans-serif;min-height:100vh}
.hdr{background:var(--dark2);border-bottom:1px solid var(--border);padding:14px 24px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}
.logo{font-family:'Bebas Neue',sans-serif;font-size:20px;letter-spacing:2px;color:#fff}
.logo span{color:var(--gold)}
.langs{display:flex;gap:5px}
.lb{background:rgba(255,255,255,0.05);border:1px solid var(--border);color:var(--muted);padding:5px 10px;border-radius:6px;cursor:pointer;font-size:13px;font-family:'DM Sans',sans-serif;transition:.2s}
.lb:hover,.lb.on{background:rgba(201,168,76,.15);border-color:var(--gold);color:var(--gold)}
.wrap{max-width:660px;margin:0 auto;padding:32px 20px 80px}
.stepbar{display:none;align-items:center;margin-bottom:36px}
.sdot{width:30px;height:30px;border-radius:50%;border:2px solid var(--border);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;color:var(--muted);flex-shrink:0;transition:.3s}
.sdot.on{border-color:var(--gold);color:var(--gold);background:rgba(201,168,76,.1)}
.sdot.done{border-color:var(--green);color:var(--green);background:rgba(46,160,67,.1)}
.sline{flex:1;height:1px;background:var(--border);transition:.3s}
.sline.done{background:var(--green)}
.sc{display:none}
.sc.on{display:block;animation:fi .35s ease}
@keyframes fi{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.ch{text-align:center;margin-bottom:28px}
.ch h1{font-family:'Bebas Neue',sans-serif;font-size:38px;letter-spacing:2px;line-height:1}
.ch h1 em{color:var(--gold);font-style:normal}
.ch p{color:var(--muted);margin-top:8px;font-size:15px}
.cbox{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:22px;margin-bottom:14px}
.ctitle{font-size:12px;letter-spacing:2px;text-transform:uppercase;color:var(--gold);margin-bottom:16px;font-weight:500}
.crow{display:flex;gap:14px;padding:11px 0;border-bottom:1px solid var(--border)}
.crow:last-child{border-bottom:none}
.cico{font-size:18px;flex-shrink:0;width:26px;text-align:center;margin-top:1px}
.ctxt{font-size:14px;color:var(--text);line-height:1.65}
.ctxt b{color:#fff}
.tgrid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px}
.tcard{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px}
.tcard h4{font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:var(--gold);margin-bottom:12px}
.trow{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.05);font-size:13px}
.trow:last-child{border-bottom:none}
.trow .tv{color:#fff;font-weight:500}
.fnote{background:rgba(201,168,76,.06);border:1px solid rgba(201,168,76,.2);border-radius:8px;padding:14px 16px;font-size:13px;color:var(--muted);line-height:1.6;margin-bottom:18px}
.fnote b{color:var(--gold)}
.btnrow{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.bacc{background:var(--green);color:#fff;border:none;padding:16px;border-radius:10px;font-size:15px;font-weight:600;cursor:pointer;font-family:'DM Sans',sans-serif;transition:.2s}
.bacc:hover{background:#38b34a;transform:translateY(-1px)}
.bdec{background:rgba(248,81,73,.1);color:var(--red);border:1px solid rgba(248,81,73,.3);padding:16px;border-radius:10px;font-size:15px;font-weight:500;cursor:pointer;font-family:'DM Sans',sans-serif;transition:.2s}
.ftitle{margin-bottom:26px}
.ftitle h2{font-family:'Bebas Neue',sans-serif;font-size:28px;letter-spacing:1px}
.ftitle p{color:var(--muted);margin-top:4px;font-size:14px}
.fstep{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--gold);margin-bottom:18px;display:flex;align-items:center;gap:8px}
.fstep::after{content:'';flex:1;height:1px;background:var(--border)}
.fld{margin-bottom:18px}
.fld label{display:block;font-size:13px;color:var(--muted);margin-bottom:7px;font-weight:500}
.fld input,.fld textarea{width:100%;background:var(--card);border:1px solid var(--border);color:var(--text);padding:13px 15px;border-radius:8px;font-size:15px;font-family:'DM Sans',sans-serif;outline:none;transition:.2s}
.fld input:focus,.fld textarea:focus{border-color:var(--gold)}
.fld textarea{min-height:100px;resize:vertical}
.fld .hint{font-size:12px;color:var(--muted);margin-top:5px}
.fg2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.bnext{width:100%;background:var(--gold);color:var(--dark);border:none;padding:16px;border-radius:10px;font-size:16px;font-weight:700;cursor:pointer;font-family:'DM Sans',sans-serif;margin-top:6px;transition:.2s}
.bnext:hover{background:var(--gold2);transform:translateY(-1px)}
.bback{background:transparent;color:var(--muted);border:1px solid var(--border);padding:11px 18px;border-radius:8px;font-size:14px;cursor:pointer;margin-bottom:16px;font-family:'DM Sans',sans-serif;transition:.2s}
.rcard{background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:hidden;margin-bottom:18px}
.rrow{display:flex;gap:14px;padding:13px 18px;border-bottom:1px solid var(--border)}
.rrow:last-child{border-bottom:none}
.rlbl{font-size:12px;color:var(--muted);min-width:90px;flex-shrink:0;padding-top:2px}
.rval{font-size:14px;line-height:1.5}
.ldr{display:none;text-align:center;padding:20px}
.spin{width:30px;height:30px;border:3px solid var(--border);border-top-color:var(--gold);border-radius:50%;animation:sp .8s linear infinite;margin:0 auto 10px}
@keyframes sp{to{transform:rotate(360deg)}}
.succ,.dec{text-align:center;padding:40px 0}
.succ h2,.dec h2{font-family:'Bebas Neue',sans-serif;font-size:32px;letter-spacing:2px;color:var(--gold);margin:16px 0 10px}
.succ p,.dec p{color:var(--muted);font-size:15px;line-height:1.7;max-width:380px;margin:0 auto 16px}
.pbox{background:var(--card);border:1px solid var(--gold);border-radius:10px;padding:18px 28px;display:inline-block;margin:16px auto}
.plbl{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--gold);margin-bottom:6px}
.pcode{font-size:30px;font-weight:700;color:#fff;letter-spacing:4px;font-family:'Bebas Neue',sans-serif}
.brest{background:var(--card);border:1px solid var(--border);color:var(--text);padding:12px 28px;border-radius:8px;cursor:pointer;font-size:14px;margin-top:18px;font-family:'DM Sans',sans-serif;transition:.2s}
.brest:hover{border-color:var(--gold);color:var(--gold)}
.prev-box{background:rgba(201,168,76,.06);border:1px solid rgba(201,168,76,.3);border-radius:10px;padding:18px;margin-bottom:18px;display:none}
.prev-box.show{display:block;animation:fi .3s ease}
.prev-title{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--gold);margin-bottom:10px}
.prev-zona{font-size:15px;font-weight:600;color:#fff;margin-bottom:6px}
.prev-detail{font-size:13px;color:var(--muted);line-height:1.8;white-space:pre-line;margin-bottom:10px}
.prev-total{background:rgba(201,168,76,.15);border-radius:8px;padding:12px 16px;display:flex;justify-content:space-between;align-items:center}
.prev-total-label{font-size:13px;color:var(--muted)}
.prev-total-val{font-size:20px;font-weight:700;color:var(--gold)}
.prev-note{font-size:11px;color:var(--muted);margin-top:8px;font-style:italic}
.prev-loading{text-align:center;padding:12px;color:var(--muted);font-size:13px;display:none;background:var(--card);border-radius:8px;margin-bottom:12px}
@media(max-width:500px){.tgrid,.btnrow,.fg2{grid-template-columns:1fr}.langs{gap:3px}.lb{padding:5px 7px;font-size:11px}}
</style>
</head>
<body>
<div class="hdr">
  <div class="logo">ROTONDI <span>GROUP</span> ROMA</div>
  <div class="langs">
    <button class="lb on" onclick="setL('it',this)">IT</button>
    <button class="lb" onclick="setL('en',this)">EN</button>
    <button class="lb" onclick="setL('bn',this)">BD</button>
    <button class="lb" onclick="setL('zh',this)">CN</button>
    <button class="lb" onclick="setL('ar',this)">SA</button>
  </div>
</div>
<div class="wrap">
  <div class="stepbar" id="stepbar">
    <div class="sdot on" id="d1">1</div><div class="sline" id="l1"></div>
    <div class="sdot" id="d2">2</div><div class="sline" id="l2"></div>
    <div class="sdot" id="d3">3</div><div class="sline" id="l3"></div>
    <div class="sdot" id="d4">4</div>
  </div>

  <div class="sc on" id="s0">
    <div class="ch">
      <h1 id="t-title">ASSISTENZA<br><em>TECNICA</em></h1>
      <p id="t-sub">Rotondi Group Roma</p>
    </div>
    <div class="cbox">
      <div class="ctitle" id="t-ctitle">Informativa sul servizio</div>
      <div class="crow"><div class="cico" style="color:#f0b429">!</div><div class="ctxt" id="t-c1"></div></div>
      <div class="crow"><div class="cico" style="color:#2ea043">v</div><div class="ctxt" id="t-c2"></div></div>
      <div class="crow"><div class="cico" style="color:#c9a84c">E</div><div class="ctxt" id="t-c3"></div></div>
    </div>
    <div class="tgrid">
      <div class="tcard">
        <h4 id="t-z1">ZONA DI ROMA</h4>
        <div class="trow"><span id="t-r1l">Uscita + 1 ora</span><span class="tv" id="t-r1v">80,00 + IVA</span></div>
        <div class="trow"><span id="t-r2l">Ore successive</span><span class="tv" id="t-r2v">40,00/h + IVA</span></div>
      </div>
      <div class="tcard">
        <h4 id="t-z2">FUORI ROMA</h4>
        <div class="trow"><span id="t-r3l">Km</span><span class="tv" id="t-r3v">0,70/km + IVA</span></div>
        <div class="trow"><span id="t-r4l">Viaggio</span><span class="tv" id="t-r4v">32,00/h + IVA</span></div>
        <div class="trow"><span id="t-r5l">Lavoro</span><span class="tv" id="t-r5v">40,00/h + IVA</span></div>
      </div>
    </div>
    <div class="fnote" id="t-frl"></div>
    <div class="btnrow">
      <button class="bacc" onclick="go(1)" id="t-acc">Accetto</button>
      <button class="bdec" onclick="go(5)" id="t-dec">Rifiuto</button>
    </div>
  </div>

  <div class="sc" id="s1">
    <button class="bback" onclick="go(0)" id="t-bk">Indietro</button>
    <div class="ftitle"><h2 id="t-f1h">Dati personali</h2><p id="t-f1p">Inserisci i tuoi dati</p></div>
    <div class="fstep" id="t-f1s">Passo 1 di 3</div>
    <div class="fld"><label id="t-ln">Nome e cognome *</label><input id="v-nome" type="text"></div>
    <div class="fld">
      <label id="t-li">Indirizzo completo *</label>
      <input id="v-ind" type="text" placeholder="Via Roma 10, Roma" oninput="schedPrev()">
      <div class="hint" id="t-hi">Via, numero civico e citta</div>
    </div>
    <div class="prev-loading" id="prev-loading">Calcolo preventivo in corso...</div>
    <div class="prev-box" id="prev-box">
      <div class="prev-title">PREVENTIVO INDICATIVO</div>
      <div class="prev-zona" id="prev-zona"></div>
      <div class="prev-detail" id="prev-detail"></div>
      <div class="prev-total">
        <span class="prev-total-label">Costo minimo stimato (1h lavoro)</span>
        <span class="prev-total-val" id="prev-total"></span>
      </div>
      <div class="prev-note">* Preventivo indicativo + IVA. Il costo finale dipende dal tempo effettivo di intervento.</div>
    </div>
    <div class="fg2">
      <div class="fld"><label id="t-lt">Telefono *</label><input id="v-tel" type="tel"></div>
      <div class="fld"><label id="t-le">Email *</label><input id="v-email" type="email"><div class="hint" id="t-he">Per la conferma</div></div>
    </div>
    <button class="bnext" onclick="step1()" id="t-f1n">Continua</button>
  </div>

  <div class="sc" id="s2">
    <button class="bback" onclick="go(1)" id="t-bk2">Indietro</button>
    <div class="ftitle"><h2 id="t-f2h">Dati macchina</h2><p id="t-f2p">Informazioni sul macchinario</p></div>
    <div class="fstep" id="t-f2s">Passo 2 di 3</div>
    <div class="fg2">
      <div class="fld"><label id="t-lma">Marca *</label><input id="v-marca" type="text"></div>
      <div class="fld"><label id="t-lmo">Modello</label><input id="v-modello" type="text"></div>
    </div>
    <div class="fld"><label id="t-lse">Seriale</label><input id="v-seriale" type="text"></div>
    <div class="fld"><label id="t-lpr">Problema *</label><textarea id="v-problema"></textarea></div>
    <button class="bnext" onclick="step2()" id="t-f2n">Continua</button>
  </div>

  <div class="sc" id="s3">
    <button class="bback" onclick="go(2)" id="t-bk3">Indietro</button>
    <div class="ftitle"><h2 id="t-f3h">Riepilogo</h2><p id="t-f3p">Controlla prima di inviare</p></div>
    <div class="fstep" id="t-f3s">Passo 3 di 3</div>
    <div class="rcard" id="rcard"></div>
    <div class="ldr" id="ldr"><div class="spin"></div><p>Invio in corso...</p></div>
    <button class="bnext" onclick="submitForm()" id="t-sub">Invia richiesta</button>
  </div>

  <div class="sc" id="s4">
    <div class="succ">
      <div style="font-size:52px">OK</div>
      <h2 id="t-sh">Richiesta inviata!</h2>
      <p id="t-sp">Riceverai conferma a breve.</p>
      <div class="pbox"><div class="plbl" id="t-pl">Protocollo</div><div class="pcode" id="t-pc">RG000000</div></div>
      <p id="t-em" style="font-size:13px;color:var(--muted);margin-top:8px"></p><br>
      <button class="brest" onclick="restart()">Nuova richiesta</button>
    </div>
  </div>

  <div class="sc" id="s5">
    <div class="dec">
      <div style="font-size:48px;margin-bottom:14px">OK</div>
      <h2 id="t-dh">Servizio non accettato</h2>
      <p id="t-dp">Puo tornare in qualsiasi momento.</p>
      <button class="brest" onclick="restart()">Torna</button>
    </div>
  </div>
</div>

<script>
var lang='it',cur=0,prevTimer=null,prevData=null;

var TX={
  it:{title:'ASSISTENZA<br><em>TECNICA</em>',sub:'Rotondi Group Roma - Leggi le condizioni prima di procedere',ctitle:'Informativa sul servizio',z1:'TARIFFE ZONA DI ROMA (dentro il Grande Raccordo Anulare)',z2:"TARIFFE PROVINCIA DI ROMA, LAZIO E RESTO D'ITALIA",r1l:'Uscita + 1 ora lavoro',r2l:'Ore successive',r3l:'Trasferta km',r4l:'Ore viaggio',r5l:'Ore lavoro',acc:'Accetto le condizioni',dec:'Rifiuto',bk:'Indietro',f1h:'Dati personali',f1p:'Inserisci i tuoi dati di contatto',f1s:'Passo 1 di 3',ln:'Nome e cognome *',li:'Indirizzo completo *',lt:'Telefono *',le:'Email *',hi:'Via, numero civico e citta',he:'Per ricevere la conferma',f1n:'Continua',f2h:'Dati macchina',f2p:'Informazioni sul macchinario',f2s:'Passo 2 di 3',lma:'Marca *',lmo:'Modello',lse:'Numero seriale',lpr:'Descrivi il problema *',f2n:'Continua',f3h:'Riepilogo',f3p:'Controlla i dati prima di inviare',f3s:'Passo 3 di 3',sub:'Invia richiesta',sh:'Richiesta inviata!',sp:'La tua richiesta e stata ricevuta. Un tecnico Rotondi Group ti contatterà a breve.',pl:'Numero protocollo',dh:'Servizio non accettato',dp:'Ha scelto di non procedere. Puo tornare in qualsiasi momento.',rn:'Nome',ri:'Indirizzo',rt:'Telefono',re:'Email',rma:'Marca',rmo:'Modello',rse:'Seriale',rpr:'Problema'},
  en:{title:'TECHNICAL<br><em>ASSISTANCE</em>',sub:'Rotondi Group Roma - Read conditions before proceeding',ctitle:'Service information',z1:'ROME AREA RATES (inside GRA ring road)',z2:'ROME PROVINCE, LAZIO AND REST OF ITALY',r1l:'Call-out + 1h work',r2l:'Additional hours',r3l:'Travel km',r4l:'Travel hours',r5l:'Work hours',acc:'I Accept',dec:'Decline',bk:'Back',f1h:'Personal details',f1p:'Enter your contact information',f1s:'Step 1 of 3',ln:'Full name *',li:'Full address *',lt:'Phone *',le:'Email *',hi:'Street, number and city',he:'To receive confirmation',f1n:'Continue',f2h:'Machine details',f2p:'Information about the machine',f2s:'Step 2 of 3',lma:'Brand *',lmo:'Model',lse:'Serial number',lpr:'Describe the problem *',f2n:'Continue',f3h:'Summary',f3p:'Check your details before sending',f3s:'Step 3 of 3',sub:'Send request',sh:'Request sent!',sp:'Your request has been received. A technician will contact you shortly.',pl:'Protocol number',dh:'Service not accepted',dp:'You chose not to proceed.',rn:'Name',ri:'Address',rt:'Phone',re:'Email',rma:'Brand',rmo:'Model',rse:'Serial',rpr:'Problem'},
  bn:{title:'ASSISTENZA<br><em>TECNICA</em>',sub:'Rotondi Group Roma',ctitle:'Service Info',z1:'ROME AREA',z2:'OUTSIDE ROME',r1l:'Uscita+1h',r2l:'Extra ore',r3l:'Km',r4l:'Viaggio',r5l:'Lavoro',acc:'Accetto',dec:'Rifiuto',bk:'Back',f1h:'Personal',f1p:'Contact info',f1s:'Step 1/3',ln:'Name *',li:'Address *',lt:'Phone *',le:'Email *',hi:'Street city',he:'Confirmation',f1n:'Next',f2h:'Machine',f2p:'Machine info',f2s:'Step 2/3',lma:'Brand *',lmo:'Model',lse:'Serial',lpr:'Problem *',f2n:'Next',f3h:'Summary',f3p:'Check before send',f3s:'Step 3/3',sub:'Send',sh:'Sent!',sp:'Request received.',pl:'Protocol',dh:'Not accepted',dp:'You declined.',rn:'Name',ri:'Address',rt:'Phone',re:'Email',rma:'Brand',rmo:'Model',rse:'Serial',rpr:'Problem'},
  zh:{title:'技术<br><em>援助</em>',sub:'罗通迪集团罗马',ctitle:'服务信息',z1:'罗马市区收费标准',z2:'罗马省及意大利其他地区',r1l:'上门+1小时',r2l:'额外每小时',r3l:'差旅公里',r4l:'路途时间',r5l:'工作时间',acc:'我接受',dec:'拒绝',bk:'返回',f1h:'个人信息',f1p:'输入联系信息',f1s:'第1步共3步',ln:'姓名 *',li:'地址 *',lt:'电话 *',le:'邮件 *',hi:'街道门牌城市',he:'用于接收确认',f1n:'继续',f2h:'机器信息',f2p:'关于机器',f2s:'第2步共3步',lma:'品牌 *',lmo:'型号',lse:'序列号',lpr:'描述问题 *',f2n:'继续',f3h:'摘要',f3p:'发送前检查',f3s:'第3步共3步',sub:'发送',sh:'已发送！',sp:'请求已收到。',pl:'协议编号',dh:'未接受服务',dp:'您选择不继续。',rn:'姓名',ri:'地址',rt:'电话',re:'邮件',rma:'品牌',rmo:'型号',rse:'序列号',rpr:'问题'},
  ar:{title:'المساعدة<br><em>التقنية</em>',sub:'روتوندي جروب روما',ctitle:'معلومات الخدمة',z1:'تعريفات منطقة روما',z2:'محافظة روما ولاتسيو وبقية ايطاليا',r1l:'زيارة+ساعة',r2l:'ساعات اضافية',r3l:'كيلومترات',r4l:'ساعات السفر',r5l:'ساعات العمل',acc:'اقبل',dec:'ارفض',bk:'رجوع',f1h:'البيانات الشخصية',f1p:'ادخل معلومات الاتصال',f1s:'الخطوة 1 من 3',ln:'الاسم *',li:'العنوان *',lt:'الهاتف *',le:'البريد *',hi:'الشارع والمدينة',he:'لاستلام التاكيد',f1n:'متابعة',f2h:'بيانات الجهاز',f2p:'معلومات الجهاز',f2s:'الخطوة 2 من 3',lma:'الماركة *',lmo:'الموديل',lse:'الرقم التسلسلي',lpr:'صف المشكلة *',f2n:'متابعة',f3h:'الملخص',f3p:'تحقق قبل الارسال',f3s:'الخطوة 3 من 3',sub:'ارسال',sh:'تم الارسال!',sp:'تم استلام طلبك.',pl:'رقم البروتوكول',dh:'لم تقبل الخدمة',dp:'اخترت عدم المتابعة.',rn:'الاسم',ri:'العنوان',rt:'الهاتف',re:'البريد',rma:'الماركة',rmo:'الموديل',rse:'التسلسلي',rpr:'المشكلة'}
};

var MAP={title:'t-title',sub:'t-sub',ctitle:'t-ctitle',z1:'t-z1',z2:'t-z2',r1l:'t-r1l',r2l:'t-r2l',r3l:'t-r3l',r4l:'t-r4l',r5l:'t-r5l',acc:'t-acc',dec:'t-dec',bk:'t-bk',f1h:'t-f1h',f1p:'t-f1p',f1s:'t-f1s',ln:'t-ln',li:'t-li',lt:'t-lt',le:'t-le',hi:'t-hi',he:'t-he',f1n:'t-f1n',f2h:'t-f2h',f2p:'t-f2p',f2s:'t-f2s',lma:'t-lma',lmo:'t-lmo',lse:'t-lse',lpr:'t-lpr',f2n:'t-f2n',f3h:'t-f3h',f3p:'t-f3p',f3s:'t-f3s',sub:'t-sub',sh:'t-sh',sp:'t-sp',pl:'t-pl',dh:'t-dh',dp:'t-dp'};

function setL(l,btn){lang=l;document.querySelectorAll('.lb').forEach(function(b){b.classList.remove('on')});btn.classList.add('on');applyL();}

function applyL(){
  var t=TX[lang];
  for(var k in MAP){var el=document.getElementById(MAP[k]);if(el&&t[k]!==undefined)el.innerHTML=t[k];}
  document.body.dir=lang==='ar'?'rtl':'ltr';
  loadCondizioni();
  loadTariffe();
}

function loadCondizioni(){
  fetch('/api/condizioni/'+lang).then(function(r){return r.json();}).then(function(d){
    if(d.ok){
      var e1=document.getElementById('t-c1');if(e1)e1.textContent=d.c1;
      var e2=document.getElementById('t-c2');if(e2)e2.textContent=d.c2;
      var e3=document.getElementById('t-c3');if(e3)e3.textContent=d.c3;
      var e4=document.getElementById('t-frl');if(e4)e4.textContent=d.freelance;
    }
  }).catch(function(){});
}

function loadTariffe(){
  fetch('/api/tariffe').then(function(r){return r.json();}).then(function(d){
    if(d.ok){
      var t=d.tariffe;
      var e;
      e=document.getElementById('t-r1v');if(e)e.textContent='€ '+t.roma_uscita.toFixed(2)+' + IVA';
      e=document.getElementById('t-r2v');if(e)e.textContent='€ '+t.roma_ora_succ.toFixed(2)+'/h + IVA';
      e=document.getElementById('t-r3v');if(e)e.textContent='€ '+t.fuori_km.toFixed(2)+'/km + IVA';
      e=document.getElementById('t-r4v');if(e)e.textContent='€ '+t.fuori_viaggio.toFixed(2)+'/h + IVA';
      e=document.getElementById('t-r5v');if(e)e.textContent='€ '+t.fuori_lavoro.toFixed(2)+'/h + IVA';
    }
  }).catch(function(){});
}

function go(n){
  document.getElementById('s'+cur).classList.remove('on');
  document.getElementById('s'+n).classList.add('on');cur=n;
  var sb=document.getElementById('stepbar');
  sb.style.display=(n>=1&&n<=3)?'flex':'none';
  for(var i=1;i<=4;i++){var d=document.getElementById('d'+i);d.className='sdot';if(i<n)d.classList.add('done');else if(i===n)d.classList.add('on');}
  for(var i=1;i<=3;i++){var l=document.getElementById('l'+i);l.className='sline';if(i<n)l.classList.add('done');}
  window.scrollTo(0,0);
}

function schedPrev(){
  clearTimeout(prevTimer);
  document.getElementById('prev-box').classList.remove('show');
  var ind=document.getElementById('v-ind').value.trim();
  if(ind.length<8){document.getElementById('prev-loading').style.display='none';return;}
  document.getElementById('prev-loading').style.display='block';
  prevTimer=setTimeout(function(){calcPrev(ind);},1500);
}

function calcPrev(ind){
  fetch('/api/preventivo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({indirizzo:ind})})
  .then(function(r){return r.json();})
  .then(function(d){
    document.getElementById('prev-loading').style.display='none';
    if(d.ok&&d.preventivo){
      var p=d.preventivo;prevData=p;
      document.getElementById('prev-zona').textContent=p.zona+' ('+p.dest_label+' - '+p.dur_label+')';
      document.getElementById('prev-detail').textContent=p.dettaglio;
      document.getElementById('prev-total').textContent='€ '+p.costo_min.toFixed(2)+' + IVA';
      document.getElementById('prev-box').classList.add('show');
    }
  }).catch(function(){document.getElementById('prev-loading').style.display='none';});
}

function step1(){
  var n=document.getElementById('v-nome').value.trim();
  var i=document.getElementById('v-ind').value.trim();
  var t=document.getElementById('v-tel').value.trim();
  var e=document.getElementById('v-email').value.trim();
  if(!n||!i||!t||!e){alert('Compila tutti i campi *');return;}
  go(2);
}

function step2(){
  var m=document.getElementById('v-marca').value.trim();
  var p=document.getElementById('v-problema').value.trim();
  if(!m||!p){alert('Compila i campi obbligatori *');return;}
  buildR();go(3);
}

function buildR(){
  var t=TX[lang];
  var rows=[[t.rn,document.getElementById('v-nome').value],[t.ri,document.getElementById('v-ind').value],[t.rt,document.getElementById('v-tel').value],[t.re,document.getElementById('v-email').value],[t.rma,document.getElementById('v-marca').value],[t.rmo,document.getElementById('v-modello').value],[t.rse,document.getElementById('v-seriale').value],[t.rpr,document.getElementById('v-problema').value]];
  if(prevData)rows.push(['Preventivo','€ '+prevData.costo_min.toFixed(2)+' + IVA ('+prevData.zona+')']);
  var h='';
  rows.forEach(function(r){if(r[1])h+='<div class="rrow"><div class="rlbl">'+r[0]+'</div><div class="rval">'+r[1]+'</div></div>';});
  document.getElementById('rcard').innerHTML=h;
}

function submitForm(){
  var btn=document.getElementById('t-sub');
  var ldr=document.getElementById('ldr');
  btn.style.display='none';ldr.style.display='block';
  var d={lingua:lang,nome:document.getElementById('v-nome').value,indirizzo:document.getElementById('v-ind').value,telefono:document.getElementById('v-tel').value,email:document.getElementById('v-email').value,marca:document.getElementById('v-marca').value,modello:document.getElementById('v-modello').value,seriale:document.getElementById('v-seriale').value,problema:document.getElementById('v-problema').value,preventivo:prevData};
  fetch('/api/richiesta',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)})
  .then(function(r){return r.json();})
  .then(function(res){
    ldr.style.display='none';
    if(res.ok){document.getElementById('t-pc').textContent=res.protocollo;if(res.email_sent)document.getElementById('t-em').textContent='Email inviata a: '+d.email;go(4);}
    else{btn.style.display='block';alert('Errore: '+(res.error||'Riprova'));}
  }).catch(function(){ldr.style.display='none';btn.style.display='block';alert('Errore connessione.');});
}

function restart(){
  ['v-nome','v-ind','v-tel','v-email','v-marca','v-modello','v-seriale','v-problema'].forEach(function(id){document.getElementById(id).value='';});
  prevData=null;
  document.getElementById('prev-box').classList.remove('show');
  go(0);
}

applyL();
</script>
</body>
</html>"""

ADMIN_LOGIN_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin - Rotondi Group</title>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d0d14;color:#e8e6e0;font-family:'DM Sans',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}
.box{background:#1a1a2e;border:1px solid rgba(255,255,255,0.09);border-radius:16px;padding:40px;width:100%;max-width:380px;text-align:center}
.logo{font-family:'Bebas Neue',sans-serif;font-size:22px;letter-spacing:2px;margin-bottom:4px}
.logo span{color:#c9a84c}
.sub{color:rgba(232,230,224,0.55);font-size:14px;margin-bottom:28px}
input{width:100%;background:#0d0d14;border:1px solid rgba(255,255,255,0.09);color:#e8e6e0;padding:13px 16px;border-radius:8px;font-size:16px;font-family:'DM Sans',sans-serif;outline:none;margin-bottom:12px;text-align:center;letter-spacing:4px}
input:focus{border-color:#c9a84c}
button{width:100%;background:#c9a84c;color:#0d0d14;border:none;padding:14px;border-radius:8px;font-size:15px;font-weight:700;cursor:pointer;font-family:'DM Sans',sans-serif}
.err{color:#f85149;font-size:13px;margin-top:10px}
</style></head><body>
<div class="box">
  <div class="logo">ROTONDI <span>GROUP</span> ROMA</div>
  <div class="sub">Pannello amministratore</div>
  <form method="POST" action="/admin/login">
    <input type="password" name="password" placeholder="Password" autofocus>
    <button type="submit">Accedi</button>
  </form>
  {% if error %}<div class="err">Password errata. Riprova.</div>{% endif %}
</div></body></html>"""

ADMIN_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin - Rotondi Group</title>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--dark:#0d0d14;--dark2:#14141f;--card:#1a1a2e;--border:rgba(255,255,255,0.09);--gold:#c9a84c;--text:#e8e6e0;--muted:rgba(232,230,224,0.55);--green:#2ea043;--red:#f85149}
body{background:var(--dark);color:var(--text);font-family:'DM Sans',sans-serif;min-height:100vh}
.hdr{background:var(--dark2);border-bottom:1px solid var(--border);padding:14px 28px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}
.logo{font-family:'Bebas Neue',sans-serif;font-size:18px;letter-spacing:2px}
.logo span{color:var(--gold)}
.badge{background:rgba(201,168,76,.12);border:1px solid rgba(201,168,76,.25);color:var(--gold);padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600}
.btn-exit{background:rgba(248,81,73,.1);color:var(--red);border:1px solid rgba(248,81,73,.25);padding:6px 14px;border-radius:6px;font-size:13px;cursor:pointer;font-family:'DM Sans',sans-serif;text-decoration:none}
.main{max-width:900px;margin:0 auto;padding:28px 20px 60px}
.tabs{display:flex;gap:4px;background:var(--card);border:1px solid var(--border);border-radius:10px;padding:4px;margin-bottom:28px}
.tab{flex:1;padding:10px 8px;border-radius:7px;font-size:13px;font-weight:500;cursor:pointer;text-align:center;color:var(--muted);transition:.2s;border:none;background:transparent;font-family:'DM Sans',sans-serif}
.tab.on{background:var(--gold);color:var(--dark);font-weight:700}
.sec{display:none}.sec.on{display:block}
.sec-title{font-family:'Bebas Neue',sans-serif;font-size:24px;letter-spacing:1px;margin-bottom:4px}
.sec-sub{color:var(--muted);font-size:14px;margin-bottom:22px}
.info{background:rgba(201,168,76,.07);border:1px solid rgba(201,168,76,.18);border-radius:8px;padding:14px 16px;font-size:13px;color:var(--muted);margin-bottom:20px;line-height:1.6}
.info b{color:var(--gold)}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}
.acard{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px}
.acard h3{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--gold);margin-bottom:16px;font-weight:500}
.af{margin-bottom:14px}.af label{display:block;font-size:13px;color:var(--muted);margin-bottom:6px}
.af-u{position:relative}.af-u input{width:100%;background:#0d0d14;border:1px solid var(--border);color:var(--text);padding:11px 50px 11px 14px;border-radius:8px;font-size:14px;font-family:'DM Sans',sans-serif;outline:none;transition:.2s}
.af-u input:focus{border-color:var(--gold)}.af-u span{position:absolute;right:12px;top:50%;transform:translateY(-50%);color:var(--muted);font-size:12px}
.af textarea{width:100%;background:#0d0d14;border:1px solid var(--border);color:var(--text);padding:11px 14px;border-radius:8px;font-size:14px;font-family:'DM Sans',sans-serif;outline:none;min-height:80px;resize:vertical;line-height:1.5;transition:.2s}
.af textarea:focus{border-color:var(--gold)}
.ltabs{display:flex;gap:5px;margin-bottom:14px;flex-wrap:wrap}
.ltb{background:rgba(255,255,255,.04);border:1px solid var(--border);color:var(--muted);padding:5px 13px;border-radius:6px;cursor:pointer;font-size:13px;font-family:'DM Sans',sans-serif;transition:.2s}
.ltb.on{border-color:var(--gold);color:var(--gold);background:rgba(201,168,76,.1)}
.lsc{display:none}.lsc.on{display:block}
.save-row{display:flex;align-items:center;gap:14px;margin-top:18px;flex-wrap:wrap}
.btn-save{background:var(--green);color:#fff;border:none;padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;font-family:'DM Sans',sans-serif;transition:.2s}
.btn-save:hover{background:#38b34a}
.sav-ok{color:var(--green);font-size:13px;display:none;font-weight:500}
.sav-err{color:var(--red);font-size:13px;display:none;font-weight:500}
.stats-row{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px}
.scard{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px;text-align:center}
.snum{font-family:'Bebas Neue',sans-serif;font-size:40px;color:var(--gold);line-height:1}
.slbl{font-size:12px;color:var(--muted);margin-top:4px}
.prev-box-a{background:#080810;border:1px solid var(--border);border-radius:8px;padding:16px;margin-top:14px}
.prow{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.05);font-size:13px}
.prow:last-child{border-bottom:none}
.prow strong{color:#fff}
@media(max-width:600px){.g2,.stats-row{grid-template-columns:1fr 1fr}.tabs{flex-direction:column}}
</style></head>
<body>
<div class="hdr">
  <div class="logo">ROTONDI <span>GROUP</span> ROMA <span style="font-size:11px;color:var(--muted);margin-left:8px">ADMIN</span></div>
  <div style="display:flex;gap:10px;align-items:center">
    <span class="badge">Amministratore</span>
    <a href="/admin/logout" class="btn-exit">Esci</a>
  </div>
</div>
<div class="main">
  <div class="stats-row">
    <div class="scard"><div class="snum" id="st-tot" style="color:#fff">-</div><div class="slbl">Chiamate totali</div></div>
    <div class="scard"><div class="snum" id="st-mese">-</div><div class="slbl">Questo mese</div></div>
    <div class="scard"><div class="snum" id="st-ass" style="color:var(--green)">-</div><div class="slbl">Assegnate</div></div>
    <div class="scard"><div class="snum" id="st-open" style="color:var(--red)">-</div><div class="slbl">Aperte ora</div></div>
  </div>
  <div class="tabs">
    <button class="tab on" onclick="apTab(0,this)">Tariffe</button>
    <button class="tab" onclick="apTab(1,this)">Condizioni</button>
    <button class="tab" onclick="apTab(2,this)">Password</button>
  </div>

  <div class="sec on" id="apt0">
    <div class="sec-title">Gestione Tariffe</div>
    <p class="sec-sub">Modifica le tariffe - aggiornamento immediato su sito web</p>
    <div class="info"><b>Nota:</b> Le tariffe vengono aggiornate in tempo reale sulla pagina web e nel calcolo preventivo.</div>
    <div class="g2">
      <div class="acard">
        <h3>Zona di Roma (dentro GRA)</h3>
        <div class="af"><label>Uscita + 1 ora di lavoro</label><div class="af-u"><input type="number" id="a-t1" min="0" step="1" oninput="updatePrev()"><span>EUR+IVA</span></div></div>
        <div class="af"><label>Ore successive alla prima</label><div class="af-u"><input type="number" id="a-t2" min="0" step="1" oninput="updatePrev()"><span>EUR/h+IVA</span></div></div>
      </div>
      <div class="acard">
        <h3>Fuori Roma</h3>
        <div class="af"><label>Trasferta km (A/R)</label><div class="af-u"><input type="number" id="a-t3" min="0" step="0.05" oninput="updatePrev()"><span>EUR/km+IVA</span></div></div>
        <div class="af"><label>Ore di viaggio (A/R)</label><div class="af-u"><input type="number" id="a-t4" min="0" step="1" oninput="updatePrev()"><span>EUR/h+IVA</span></div></div>
        <div class="af"><label>Ore di lavoro</label><div class="af-u"><input type="number" id="a-t5" min="0" step="1" oninput="updatePrev()"><span>EUR/h+IVA</span></div></div>
      </div>
    </div>
    <div class="acard">
      <h3>Anteprima - Esempio cliente a Latina (~60km da Roma)</h3>
      <div class="prev-box-a" id="prevBox"></div>
    </div>
    <div class="save-row">
      <button class="btn-save" onclick="saveTariffe()">Salva tariffe</button>
      <span class="sav-ok" id="sav1">Tariffe aggiornate!</span>
      <span class="sav-err" id="err1">Errore salvataggio</span>
    </div>
  </div>

  <div class="sec" id="apt1">
    <div class="sec-title">Testo Condizioni</div>
    <p class="sec-sub">Modifica il testo delle condizioni</p>
    <div class="ltabs">
      <button class="ltb on" onclick="lTab(0,this)">Italiano</button>
      <button class="ltb" onclick="lTab(1,this)">English</button>
      <button class="ltb" onclick="lTab(2,this)">Bangla</button>
      <button class="ltb" onclick="lTab(3,this)">Cinese</button>
      <button class="ltb" onclick="lTab(4,this)">Arabo</button>
    </div>
    <div id="cond-content"></div>
    <div class="save-row">
      <button class="btn-save" onclick="saveCondizioni()">Salva condizioni</button>
      <span class="sav-ok" id="sav2">Condizioni aggiornate!</span>
      <span class="sav-err" id="err2">Errore salvataggio</span>
    </div>
  </div>

  <div class="sec" id="apt2">
    <div class="sec-title">Sicurezza</div>
    <p class="sec-sub">Cambia la password del pannello admin</p>
    <div class="acard" style="max-width:440px">
      <h3>Cambia password</h3>
      <div class="af"><label>Password attuale</label><input type="password" id="p-old" style="width:100%;background:#0d0d14;border:1px solid var(--border);color:var(--text);padding:11px 14px;border-radius:8px;font-size:14px;font-family:'DM Sans',sans-serif;outline:none"></div>
      <div class="af"><label>Nuova password</label><input type="password" id="p-new" style="width:100%;background:#0d0d14;border:1px solid var(--border);color:var(--text);padding:11px 14px;border-radius:8px;font-size:14px;font-family:'DM Sans',sans-serif;outline:none"></div>
      <div class="af"><label>Conferma nuova password</label><input type="password" id="p-conf" style="width:100%;background:#0d0d14;border:1px solid var(--border);color:var(--text);padding:11px 14px;border-radius:8px;font-size:14px;font-family:'DM Sans',sans-serif;outline:none"></div>
      <div class="save-row">
        <button class="btn-save" onclick="changePwd()">Cambia password</button>
        <span class="sav-ok" id="sav3">Password aggiornata!</span>
        <span class="sav-err" id="err3">Errore</span>
      </div>
    </div>
  </div>
</div>
<script>
var condLangs=['it','en','bn','zh','ar'];
var condLang='it';
var condData={};

function apTab(n,btn){document.querySelectorAll('.tab').forEach(function(t){t.classList.remove('on')});document.querySelectorAll('.sec').forEach(function(s){s.classList.remove('on')});btn.classList.add('on');document.getElementById('apt'+n).classList.add('on');}
function lTab(n,btn){document.querySelectorAll('.ltb').forEach(function(t){t.classList.remove('on')});btn.classList.add('on');condLang=condLangs[n];renderCondForm();}

fetch('/api/tariffe').then(function(r){return r.json();}).then(function(d){
  if(d.ok){var t=d.tariffe;document.getElementById('a-t1').value=t.roma_uscita;document.getElementById('a-t2').value=t.roma_ora_succ;document.getElementById('a-t3').value=t.fuori_km;document.getElementById('a-t4').value=t.fuori_viaggio;document.getElementById('a-t5').value=t.fuori_lavoro;updatePrev();}
});

fetch('/api/admin/stats').then(function(r){return r.json();}).then(function(d){
  if(d.ok){document.getElementById('st-tot').textContent=d.tot;document.getElementById('st-mese').textContent=d.mese;document.getElementById('st-ass').textContent=d.assegnate;document.getElementById('st-open').textContent=d.aperte;}
}).catch(function(){});

condLangs.forEach(function(l){
  fetch('/api/condizioni/'+l).then(function(r){return r.json();}).then(function(d){if(d.ok){condData[l]=d;if(l===condLang)renderCondForm();}});
});

function renderCondForm(){
  var d=condData[condLang];
  if(!d){document.getElementById('cond-content').innerHTML='<p style="color:var(--muted);padding:20px">Caricamento...</p>';return;}
  var labels={it:['Italiano','Riga 1 - Servizio a pagamento','Riga 2 - Garanzia','Riga 3 - A carico del cliente','Nota tecnici freelance'],en:['English','Row 1','Row 2','Row 3','Freelance note'],bn:['Bangla','Row 1','Row 2','Row 3','Freelance'],zh:['Cinese','第1行','第2行','第3行','自由职业'],ar:['Arabo','السطر 1','السطر 2','السطر 3','الفريلانس']};
  var lb=labels[condLang];
  var dir=condLang==='ar'?'rtl':'ltr';
  document.getElementById('cond-content').innerHTML='<div class="acard"><h3>'+lb[0]+'</h3><div class="af"><label>'+lb[1]+'</label><textarea id="cc1" dir="'+dir+'">'+escH(d.c1)+'</textarea></div><div class="af"><label>'+lb[2]+'</label><textarea id="cc2" dir="'+dir+'">'+escH(d.c2)+'</textarea></div><div class="af"><label>'+lb[3]+'</label><textarea id="cc3" dir="'+dir+'">'+escH(d.c3)+'</textarea></div><div class="af"><label>'+lb[4]+'</label><textarea id="cc4" dir="'+dir+'">'+escH(d.freelance)+'</textarea></div></div>';
}

function escH(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):''}

function updatePrev(){
  var t1=parseFloat(document.getElementById('a-t1').value)||0;
  var t2=parseFloat(document.getElementById('a-t2').value)||0;
  var t3=parseFloat(document.getElementById('a-t3').value)||0;
  var t4=parseFloat(document.getElementById('a-t4').value)||0;
  var t5=parseFloat(document.getElementById('a-t5').value)||0;
  var ex_km=120,ex_h=2;
  var ex_costo=ex_km*t3+ex_h*t4+t5;
  document.getElementById('prevBox').innerHTML='<div class="prow"><span>Zona Roma - uscita+1h</span><strong>EUR '+t1.toFixed(2)+' + IVA</strong></div><div class="prow"><span>Latina - 120km A/R x EUR '+t3.toFixed(2)+'</span><strong>EUR '+(ex_km*t3).toFixed(2)+'</strong></div><div class="prow"><span>Viaggio 2h A/R x EUR '+t4.toFixed(2)+'</span><strong>EUR '+(ex_h*t4).toFixed(2)+'</strong></div><div class="prow"><span>1h lavoro</span><strong>EUR '+t5.toFixed(2)+'</strong></div><div class="prow" style="font-weight:600"><span>Totale Latina (1h lavoro)</span><strong style="color:var(--gold)">EUR '+ex_costo.toFixed(2)+' + IVA</strong></div>';
}

function saveTariffe(){
  var data={roma_uscita:parseFloat(document.getElementById('a-t1').value),roma_ora_succ:parseFloat(document.getElementById('a-t2').value),fuori_km:parseFloat(document.getElementById('a-t3').value),fuori_viaggio:parseFloat(document.getElementById('a-t4').value),fuori_lavoro:parseFloat(document.getElementById('a-t5').value)};
  fetch('/api/admin/tariffe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}).then(function(r){return r.json();}).then(function(d){
    var ok=document.getElementById('sav1'),err=document.getElementById('err1');
    if(d.ok){ok.style.display='inline';setTimeout(function(){ok.style.display='none'},3000);}
    else{err.style.display='inline';setTimeout(function(){err.style.display='none'},3000);}
  });
}

function saveCondizioni(){
  var data={lang:condLang,c1:document.getElementById('cc1').value,c2:document.getElementById('cc2').value,c3:document.getElementById('cc3').value,freelance:document.getElementById('cc4').value};
  fetch('/api/admin/condizioni',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}).then(function(r){return r.json();}).then(function(d){
    var ok=document.getElementById('sav2'),err=document.getElementById('err2');
    if(d.ok){condData[condLang]=d.condizioni;ok.style.display='inline';setTimeout(function(){ok.style.display='none'},3000);}
    else{err.style.display='inline';setTimeout(function(){err.style.display='none'},3000);}
  });
}

function changePwd(){
  var o=document.getElementById('p-old').value,n=document.getElementById('p-new').value,c=document.getElementById('p-conf').value;
  if(n!==c){alert('Le password non coincidono');return;}
  if(n.length<6){alert('Minimo 6 caratteri');return;}
  fetch('/api/admin/password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({old_pwd:o,new_pwd:n})}).then(function(r){return r.json();}).then(function(d){
    var ok=document.getElementById('sav3'),err=document.getElementById('err3');
    if(d.ok){['p-old','p-new','p-conf'].forEach(function(id){document.getElementById(id).value='';});ok.style.display='inline';setTimeout(function(){ok.style.display='none'},3000);}
    else{err.textContent='Errore: '+d.error;err.style.display='inline';setTimeout(function(){err.style.display='none'},3000);}
  });
}
</script>
</body></html>"""

@app.route('/')
def index():
    return HTML

@app.route('/api/tariffe')
def api_tariffe():
    return jsonify({"ok": True, "tariffe": get_tariffe()})

@app.route('/api/condizioni/<lang>')
def api_condizioni(lang):
    d = get_condizioni(lang)
    d["ok"] = True
    return jsonify(d)

@app.route('/api/preventivo', methods=['POST'])
def api_preventivo():
    data = request.json
    if not data: return jsonify({"ok": False})
    ind = data.get('indirizzo', '')
    if not ind: return jsonify({"ok": False})
    prev = calcola_preventivo(ind)
    return jsonify({"ok": True, "preventivo": prev})

@app.route('/api/richiesta', methods=['POST'])
def nuova_richiesta():
    data = request.json
    if not data: return jsonify({"ok": False, "error": "No data"})
    protocollo = genera_protocollo()
    lingua   = data.get('lingua', 'it')
    nome     = data.get('nome', '')
    ind      = data.get('indirizzo', '')
    tel      = data.get('telefono', '')
    email    = data.get('email', '')
    marca    = data.get('marca', '')
    modello  = data.get('modello', '')
    seriale  = data.get('seriale', '')
    problema = data.get('problema', '')
    prev     = data.get('preventivo')
    now      = datetime.now().strftime("%d/%m/%Y %H:%M")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""INSERT INTO richieste_web
            (protocollo,nome,indirizzo,telefono,email,marca,modello,seriale,problema,lingua,data)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (protocollo,nome,ind,tel,email,marca,modello,seriale,problema,lingua,now))
        conn.commit()
    FLAGS = {'it':'IT','en':'EN','bn':'BD','zh':'CN','ar':'AR'}
    flag = FLAGS.get(lingua, 'XX')
    maps = "https://www.google.com/maps/search/?api=1&query=" + ind.replace(' ','+') + ",+Italia"
    prev_text = ""
    if prev:
        prev_text = "\nPreventivo: EUR " + str(prev.get('costo_min',0)) + " + IVA (" + prev.get('zona','') + " - " + prev.get('dest_label','') + ")"
    keyboard = {"inline_keyboard": [[
        {"text":"Entro le 12:00","callback_data":"wfascia_"+protocollo+"_entro12"},
        {"text":"Entro le 18:00","callback_data":"wfascia_"+protocollo+"_entro18"},
    ],[
        {"text":"In giornata","callback_data":"wfascia_"+protocollo+"_giornata"},
        {"text":"Entro domani","callback_data":"wfascia_"+protocollo+"_domani"},
    ],[
        {"text":"Da programmare","callback_data":"wfascia_"+protocollo+"_programma"},
    ]]}
    testo = (
        "RICHIESTA WEB #" + protocollo + " [" + flag + "]\n" + "-"*28 + "\n"
        "Cliente: " + nome + "\n"
        "Indirizzo: " + ind + "\n"
        "Maps: " + maps + "\n"
        "Tel: " + tel + "\n"
        "Email: " + email + "\n"
        "Marca: " + marca + " - Modello: " + (modello or "-") + "\n"
        "Seriale: " + (seriale or "-") + "\n"
        "Problema: " + problema +
        prev_text + "\n" + "-"*28 + "\n"
        "Clicca per assegnarti:"
    )
    invia_telegram(testo, keyboard)
    invia_telegram_bo("Nuova WEB [" + flag + "]\n" + protocollo + "\n" + nome + "\n" + ind + "\n" + tel + "\n" + email + "\n" + marca + " " + modello + "\n" + problema + prev_text)
    subjects = {
        'it': 'Rotondi Group Roma - Richiesta #' + protocollo,
        'en': 'Rotondi Group Roma - Request #' + protocollo,
        'bn': 'Rotondi Group Roma - #' + protocollo,
        'zh': 'Rotondi Group Roma - #' + protocollo,
        'ar': 'Rotondi Group Roma - #' + protocollo
    }
    prev_html = ""
    if prev:
        prev_html = "<p><b>Preventivo indicativo:</b> EUR " + str(prev.get('costo_min',0)) + " + IVA (" + prev.get('zona','') + ")</p>"
    body = """<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
  <h1 style="color:#fff;font-size:20px;margin:0">ROTONDI GROUP ROMA</h1>
  <p style="color:#c9a84c;margin:4px 0 0;font-size:13px">ASSISTENZA TECNICA</p>
</div>
<div style="background:#fff;padding:24px;border-radius:0 0 8px 8px">
  <h2 style="color:#1a1a2e">Richiesta ricevuta!</h2>
  <p>Gentile <b>""" + nome + """</b>, la sua richiesta e stata ricevuta.</p>
  <div style="background:#f5f5f5;border-radius:8px;padding:16px;margin:16px 0;text-align:center">
    <p style="font-size:12px;color:#888;margin:0 0 6px">Numero protocollo</p>
    <p style="font-size:28px;font-weight:700;color:#1a1a2e;letter-spacing:4px;margin:0">""" + protocollo + """</p>
  </div>
  <p><b>Problema:</b> """ + problema + """</p>
  """ + prev_html + """
  <hr style="border:none;border-top:1px solid #eee;margin:16px 0">
  <p style="color:#666;font-size:13px">Annullamenti urgenti: <b>+39 06 41 40 0514</b></p>
  <p style="color:#666;font-size:13px">Ufficio Roma: <b>+39 06 41400617</b></p>
</div></div>"""
    email_sent = invia_email(email, subjects.get(lingua, subjects['it']), body)
    return jsonify({"ok": True, "protocollo": protocollo, "email_sent": email_sent})

@app.route('/api/stato/<protocollo>')
def stato(protocollo):
    with sqlite3.connect(DB_PATH) as conn:
        r = conn.execute("SELECT protocollo,nome,stato,data FROM richieste_web WHERE protocollo=?", (protocollo,)).fetchone()
    if not r: return jsonify({"ok": False})
    return jsonify({"ok": True, "protocollo": r[0], "nome": r[1], "stato": r[2], "data": r[3]})

@app.route('/admin')
@login_required
def admin():
    return render_template_string(ADMIN_HTML)

@app.route('/admin/login', methods=['GET','POST'])
def admin_login():
    error = False
    if request.method == 'POST':
        pwd = request.form.get('password','')
        stored_hash = get_setting('admin_pwd_hash', ADMIN_PWD_HASH_DEFAULT)
        if hashlib.sha256(pwd.encode()).hexdigest() == stored_hash:
            session['admin_logged_in'] = True
            return redirect('/admin')
        error = True
    return render_template_string(ADMIN_LOGIN_HTML, error=error)

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect('/admin/login')

@app.route('/api/admin/stats')
@login_required
def admin_stats():
    with sqlite3.connect(DB_PATH) as conn:
        tot    = conn.execute("SELECT COUNT(*) FROM richieste_web").fetchone()[0]
        mese   = conn.execute("SELECT COUNT(*) FROM richieste_web WHERE data LIKE ?", (datetime.now().strftime("%m/%Y")[-7:]+"%",)).fetchone()[0]
        ass    = conn.execute("SELECT COUNT(*) FROM richieste_web WHERE stato='assegnata'").fetchone()[0]
        aperte = conn.execute("SELECT COUNT(*) FROM richieste_web WHERE stato='aperta'").fetchone()[0]
    return jsonify({"ok": True, "tot": tot, "mese": mese, "assegnate": ass, "aperte": aperte})

@app.route('/api/admin/tariffe', methods=['POST'])
@login_required
def admin_save_tariffe():
    data = request.json
    if not data: return jsonify({"ok": False})
    for k in DEFAULT_TARIFFE:
        if k in data:
            set_setting("tariffa_"+k, data[k])
    return jsonify({"ok": True})

@app.route('/api/admin/condizioni', methods=['POST'])
@login_required
def admin_save_condizioni():
    data = request.json
    if not data: return jsonify({"ok": False})
    lang = data.get('lang', 'it')
    for campo in ['c1','c2','c3','freelance']:
        if campo in data:
            set_setting("cond_"+lang+"_"+campo, data[campo])
    cond = get_condizioni(lang)
    cond['ok'] = True
    return jsonify({"ok": True, "condizioni": cond})

@app.route('/api/admin/password', methods=['POST'])
@login_required
def admin_change_pwd():
    data = request.json
    if not data: return jsonify({"ok": False})
    old_pwd = data.get('old_pwd','')
    new_pwd = data.get('new_pwd','')
    stored_hash = get_setting('admin_pwd_hash', ADMIN_PWD_HASH_DEFAULT)
    if hashlib.sha256(old_pwd.encode()).hexdigest() != stored_hash:
        return jsonify({"ok": False, "error": "Password attuale errata"})
    if len(new_pwd) < 6:
        return jsonify({"ok": False, "error": "Minimo 6 caratteri"})
    set_setting('admin_pwd_hash', hashlib.sha256(new_pwd.encode()).hexdigest())
    return jsonify({"ok": True})

init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
