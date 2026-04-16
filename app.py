#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web App Assistenza Tecnica — Rotondi Group Roma
Per clienti senza Telegram
"""

from flask import Flask, request, jsonify, render_template_string, send_from_directory
import os, sqlite3, asyncio, smtplib, uuid
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests

app = Flask(__name__)

BOT_TOKEN        = os.environ.get("BOT_TOKEN", "")
TECNICI_GROUP_ID = os.environ.get("TECNICI_GROUP_ID", "")
BACKOFFICE_IDS   = os.environ.get("BACKOFFICE_IDS", "")
SMTP_HOST        = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT        = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER        = os.environ.get("SMTP_USER", "")
SMTP_PASS        = os.environ.get("SMTP_PASS", "")
SMTP_FROM        = os.environ.get("SMTP_FROM", "assistenza@garanzierotondi.it")

DB_PATH = "web_assistenza.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS richieste_web (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                protocollo  TEXT UNIQUE,
                nome        TEXT,
                indirizzo   TEXT,
                telefono    TEXT,
                email       TEXT,
                marca       TEXT,
                modello     TEXT,
                seriale     TEXT,
                problema    TEXT,
                lingua      TEXT,
                stato       TEXT DEFAULT 'aperta',
                tecnico     TEXT,
                fascia      TEXT,
                data        TEXT,
                msg_id      INTEGER
            )
        """)
        conn.commit()

def genera_protocollo():
    return "RG" + datetime.now().strftime("%y%m%d") + str(uuid.uuid4())[:4].upper()

def invia_email(to_email, subject, html_body):
    if not SMTP_USER or not SMTP_PASS:
        print(f"Email non configurata — skipping: {to_email}")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_FROM
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

def invia_telegram(text, reply_markup=None):
    if not BOT_TOKEN or not TECNICI_GROUP_ID:
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TECNICI_GROUP_ID, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        import json
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(url, json=payload, timeout=10)
        data = r.json()
        return data.get("result", {}).get("message_id")
    except Exception as e:
        print(f"Telegram error: {e}")
        return None

def invia_telegram_bo(text):
    if not BOT_TOKEN or not BACKOFFICE_IDS:
        return
    for bo_id in BACKOFFICE_IDS.split(","):
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": bo_id.strip(), "text": text, "parse_mode": "Markdown"}, timeout=10)
        except: pass

# ═══════════════════════════════════════════════════════
# HTML INTERFACE
# ═══════════════════════════════════════════════════════

HTML = '''<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Assistenza Tecnica — Rotondi Group Roma</title>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600;1,300&display=swap" rel="stylesheet">
<style>
:root {
  --dark: #0d0d14;
  --dark2: #14141f;
  --card: #1a1a2e;
  --border: rgba(255,255,255,0.08);
  --gold: #c9a84c;
  --gold2: #e8c96d;
  --text: #e8e6e0;
  --muted: rgba(232,230,224,0.5);
  --green: #2ea043;
  --red: #f85149;
  --blue: #58a6ff;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { background:var(--dark); color:var(--text); font-family:'DM Sans',sans-serif; min-height:100vh; }

/* HEADER */
.header { background:var(--dark2); border-bottom:1px solid var(--border); padding:16px 24px; display:flex; align-items:center; justify-content:space-between; position:sticky; top:0; z-index:100; }
.logo { font-family:'Bebas Neue',sans-serif; font-size:22px; letter-spacing:2px; color:#fff; }
.logo span { color:var(--gold); }
.lang-btns { display:flex; gap:6px; }
.lang-btn { background:rgba(255,255,255,0.05); border:1px solid var(--border); color:var(--muted); padding:6px 10px; border-radius:6px; cursor:pointer; font-size:13px; transition:all .2s; }
.lang-btn:hover, .lang-btn.active { background:rgba(201,168,76,0.15); border-color:var(--gold); color:var(--gold); }

/* MAIN */
.main { max-width:680px; margin:0 auto; padding:32px 20px 60px; }

/* STEP INDICATOR */
.steps-bar { display:flex; align-items:center; gap:0; margin-bottom:40px; }
.step-dot { width:32px; height:32px; border-radius:50%; border:2px solid var(--border); display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:600; color:var(--muted); transition:all .3s; flex-shrink:0; }
.step-dot.active { border-color:var(--gold); color:var(--gold); background:rgba(201,168,76,0.1); }
.step-dot.done { border-color:var(--green); color:var(--green); background:rgba(46,160,67,0.1); }
.step-line { flex:1; height:1px; background:var(--border); transition:background .3s; }
.step-line.done { background:var(--green); }

/* SCREENS */
.screen { display:none; animation:fadeIn .4s ease; }
.screen.active { display:block; }
@keyframes fadeIn { from{opacity:0;transform:translateY(12px)} to{opacity:1;transform:translateY(0)} }

/* CONDIZIONI */
.cond-header { text-align:center; margin-bottom:32px; }
.cond-header h1 { font-family:'Bebas Neue',sans-serif; font-size:36px; letter-spacing:2px; line-height:1.1; }
.cond-header h1 span { color:var(--gold); }
.cond-header p { color:var(--muted); margin-top:8px; font-size:15px; }

.cond-box { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:24px; margin-bottom:16px; }
.cond-box h3 { font-size:13px; letter-spacing:2px; text-transform:uppercase; color:var(--gold); margin-bottom:16px; font-weight:500; }
.cond-row { display:flex; align-items:flex-start; gap:12px; padding:10px 0; border-bottom:1px solid var(--border); }
.cond-row:last-child { border-bottom:none; }
.cond-icon { font-size:18px; flex-shrink:0; margin-top:1px; }
.cond-text { font-size:14px; color:var(--text); line-height:1.6; }
.cond-text strong { color:#fff; font-weight:600; }

.tariffe-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:16px; }
.tariffa-card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:16px; }
.tariffa-card h4 { font-size:11px; letter-spacing:1.5px; text-transform:uppercase; color:var(--gold); margin-bottom:12px; }
.tariffa-row { display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.05); font-size:13px; }
.tariffa-row:last-child { border-bottom:none; }
.tariffa-row .val { color:#fff; font-weight:500; }

.freelance-note { background:rgba(201,168,76,0.06); border:1px solid rgba(201,168,76,0.2); border-radius:8px; padding:14px 16px; font-size:13px; color:var(--muted); line-height:1.6; margin-bottom:20px; }
.freelance-note strong { color:var(--gold); }

.btn-group { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.btn-accept { background:var(--green); color:#fff; border:none; padding:16px; border-radius:10px; font-size:15px; font-weight:600; cursor:pointer; transition:all .2s; }
.btn-accept:hover { background:#3aba4f; transform:translateY(-1px); }
.btn-decline { background:rgba(248,81,73,0.1); color:var(--red); border:1px solid rgba(248,81,73,0.3); padding:16px; border-radius:10px; font-size:15px; font-weight:500; cursor:pointer; transition:all .2s; }
.btn-decline:hover { background:rgba(248,81,73,0.2); }

/* FORM */
.form-title { margin-bottom:28px; }
.form-title h2 { font-family:'Bebas Neue',sans-serif; font-size:28px; letter-spacing:1px; }
.form-title p { color:var(--muted); margin-top:4px; font-size:14px; }
.form-step-label { font-size:11px; letter-spacing:2px; text-transform:uppercase; color:var(--gold); margin-bottom:20px; display:flex; align-items:center; gap:8px; }
.form-step-label::after { content:''; flex:1; height:1px; background:var(--border); }

.field { margin-bottom:20px; }
.field label { display:block; font-size:13px; color:var(--muted); margin-bottom:8px; font-weight:500; }
.field input, .field textarea, .field select { width:100%; background:var(--card); border:1px solid var(--border); color:var(--text); padding:13px 16px; border-radius:8px; font-size:15px; font-family:'DM Sans',sans-serif; transition:border-color .2s; outline:none; }
.field input:focus, .field textarea:focus { border-color:var(--gold); }
.field textarea { min-height:100px; resize:vertical; }
.field .hint { font-size:12px; color:var(--muted); margin-top:6px; }

.field-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }

.btn-next { width:100%; background:var(--gold); color:var(--dark); border:none; padding:16px; border-radius:10px; font-size:16px; font-weight:700; cursor:pointer; transition:all .2s; margin-top:8px; font-family:'DM Sans',sans-serif; }
.btn-next:hover { background:var(--gold2); transform:translateY(-1px); }
.btn-back { background:transparent; color:var(--muted); border:1px solid var(--border); padding:12px 20px; border-radius:8px; font-size:14px; cursor:pointer; margin-bottom:16px; transition:all .2s; font-family:'DM Sans',sans-serif; }
.btn-back:hover { color:var(--text); border-color:rgba(255,255,255,0.2); }

/* RIEPILOGO */
.riepilogo-card { background:var(--card); border:1px solid var(--border); border-radius:12px; overflow:hidden; margin-bottom:20px; }
.riepilogo-row { display:flex; gap:16px; padding:14px 20px; border-bottom:1px solid var(--border); }
.riepilogo-row:last-child { border-bottom:none; }
.riepilogo-label { font-size:12px; color:var(--muted); min-width:100px; flex-shrink:0; padding-top:2px; }
.riepilogo-val { font-size:14px; color:var(--text); line-height:1.5; }

/* SUCCESSO */
.success-screen { text-align:center; padding:40px 0; }
.success-icon { font-size:64px; margin-bottom:20px; }
.success-screen h2 { font-family:'Bebas Neue',sans-serif; font-size:32px; letter-spacing:2px; color:var(--gold); margin-bottom:12px; }
.success-screen p { color:var(--muted); font-size:15px; line-height:1.7; max-width:400px; margin:0 auto 20px; }
.protocollo-box { background:var(--card); border:1px solid var(--gold); border-radius:10px; padding:20px; display:inline-block; margin:20px auto; }
.protocollo-box .label { font-size:11px; letter-spacing:2px; text-transform:uppercase; color:var(--gold); margin-bottom:8px; }
.protocollo-box .code { font-size:28px; font-weight:700; color:#fff; letter-spacing:4px; font-family:'Bebas Neue',sans-serif; }

/* DECLINED */
.declined-screen { text-align:center; padding:40px 0; }
.declined-screen h2 { font-family:'Bebas Neue',sans-serif; font-size:28px; letter-spacing:1px; margin-bottom:12px; }
.declined-screen p { color:var(--muted); font-size:15px; line-height:1.7; }
.btn-restart { background:var(--card); border:1px solid var(--border); color:var(--text); padding:12px 28px; border-radius:8px; cursor:pointer; font-size:14px; margin-top:20px; font-family:'DM Sans',sans-serif; transition:all .2s; }
.btn-restart:hover { border-color:var(--gold); color:var(--gold); }

/* LOADING */
.loading { display:none; text-align:center; padding:20px; }
.spinner { width:32px; height:32px; border:3px solid var(--border); border-top-color:var(--gold); border-radius:50%; animation:spin .8s linear infinite; margin:0 auto 12px; }
@keyframes spin { to{transform:rotate(360deg)} }

@media(max-width:500px) {
  .tariffe-grid { grid-template-columns:1fr; }
  .field-grid { grid-template-columns:1fr; }
  .btn-group { grid-template-columns:1fr; }
  .lang-btns { gap:4px; }
  .lang-btn { padding:5px 7px; font-size:12px; }
}
</style>
</head>
<body>

<div class="header">
  <div class="logo">ROTONDI <span>GROUP</span> ROMA</div>
  <div class="lang-btns">
    <button class="lang-btn active" onclick="setLang('it')">🇮🇹</button>
    <button class="lang-btn" onclick="setLang('en')">🇬🇧</button>
    <button class="lang-btn" onclick="setLang('bn')">🇧🇩</button>
    <button class="lang-btn" onclick="setLang('zh')">🇨🇳</button>
    <button class="lang-btn" onclick="setLang('ar')">🇸🇦</button>
  </div>
</div>

<div class="main">
  <!-- Step bar -->
  <div class="steps-bar" id="stepsBar" style="display:none">
    <div class="step-dot active" id="sd1">1</div>
    <div class="step-line" id="sl1"></div>
    <div class="step-dot" id="sd2">2</div>
    <div class="step-line" id="sl2"></div>
    <div class="step-dot" id="sd3">3</div>
    <div class="step-line" id="sl3"></div>
    <div class="step-dot" id="sd4">4</div>
  </div>

  <!-- SCREEN 0: CONDIZIONI -->
  <div class="screen active" id="screen0">
    <div class="cond-header">
      <h1 id="c-title">ASSISTENZA<br><span>TECNICA</span></h1>
      <p id="c-sub">Rotondi Group Roma — Leggi le condizioni prima di procedere</p>
    </div>

    <div class="cond-box">
      <h3 id="c-info-title">Informativa sul servizio</h3>
      <div class="cond-row">
        <div class="cond-icon">⚠️</div>
        <div class="cond-text" id="c-paid"></div>
      </div>
      <div class="cond-row">
        <div class="cond-icon">✅</div>
        <div class="cond-text" id="c-warranty"></div>
      </div>
      <div class="cond-row">
        <div class="cond-icon">💶</div>
        <div class="cond-text" id="c-charge"></div>
      </div>
    </div>

    <div class="tariffe-grid">
      <div class="tariffa-card">
        <h4 id="c-zone1">Zona di Roma</h4>
        <div class="tariffa-row"><span id="c-r1l">Uscita + 1 ora</span><span class="val">€ 80,00 + IVA</span></div>
        <div class="tariffa-row"><span id="c-r2l">Ore successive</span><span class="val">€ 40,00/h + IVA</span></div>
      </div>
      <div class="tariffa-card">
        <h4 id="c-zone2">Fuori Roma</h4>
        <div class="tariffa-row"><span id="c-r3l">Trasferta</span><span class="val">€ 0,70/km + IVA</span></div>
        <div class="tariffa-row"><span id="c-r4l">Ore viaggio</span><span class="val">€ 32,00/h + IVA</span></div>
        <div class="tariffa-row"><span id="c-r5l">Ore lavoro</span><span class="val">€ 40,00/h + IVA</span></div>
      </div>
    </div>

    <div class="freelance-note" id="c-freelance"></div>

    <div class="btn-group">
      <button class="btn-accept" onclick="acceptConditions()" id="c-accept">✅ Accetto</button>
      <button class="btn-decline" onclick="declineConditions()" id="c-decline">❌ Rifiuto</button>
    </div>
  </div>

  <!-- SCREEN 1: DATI PERSONALI -->
  <div class="screen" id="screen1">
    <button class="btn-back" onclick="goTo(0)" id="f-back">← Indietro</button>
    <div class="form-title">
      <h2 id="f1-title">Dati personali</h2>
      <p id="f1-sub">Inserisci i tuoi dati di contatto</p>
    </div>
    <div class="form-step-label" id="f1-step">Passo 1 di 3</div>
    <div class="field">
      <label id="l-nome">Nome e cognome *</label>
      <input type="text" id="inp-nome" placeholder="Mario Rossi">
    </div>
    <div class="field">
      <label id="l-indirizzo">Indirizzo completo *</label>
      <input type="text" id="inp-indirizzo" placeholder="Via Roma 10, Roma">
      <div class="hint" id="h-indirizzo">Via, numero civico e città</div>
    </div>
    <div class="field-grid">
      <div class="field">
        <label id="l-telefono">Telefono *</label>
        <input type="tel" id="inp-telefono" placeholder="+39 333 1234567">
      </div>
      <div class="field">
        <label id="l-email">Email *</label>
        <input type="email" id="inp-email" placeholder="mario@email.com">
        <div class="hint" id="h-email">Per ricevere la conferma</div>
      </div>
    </div>
    <button class="btn-next" onclick="nextStep1()" id="f1-next">Continua →</button>
  </div>

  <!-- SCREEN 2: DATI MACCHINA -->
  <div class="screen" id="screen2">
    <button class="btn-back" onclick="goTo(1)" id="f-back2">← Indietro</button>
    <div class="form-title">
      <h2 id="f2-title">Dati macchina</h2>
      <p id="f2-sub">Informazioni sul macchinario</p>
    </div>
    <div class="form-step-label" id="f2-step">Passo 2 di 3</div>
    <div class="field-grid">
      <div class="field">
        <label id="l-marca">Marca *</label>
        <input type="text" id="inp-marca" placeholder="Samsung, LG, Bosch...">
      </div>
      <div class="field">
        <label id="l-modello">Modello</label>
        <input type="text" id="inp-modello" placeholder="Es: WW80J5355FW">
      </div>
    </div>
    <div class="field">
      <label id="l-seriale">Numero seriale</label>
      <input type="text" id="inp-seriale" placeholder="Sulla targhetta della macchina">
    </div>
    <div class="field">
      <label id="l-problema">Descrivi il problema *</label>
      <textarea id="inp-problema" placeholder="Cosa succede? Da quando? Hai già provato qualcosa?"></textarea>
    </div>
    <button class="btn-next" onclick="nextStep2()" id="f2-next">Continua →</button>
  </div>

  <!-- SCREEN 3: RIEPILOGO -->
  <div class="screen" id="screen3">
    <button class="btn-back" onclick="goTo(2)" id="f-back3">← Indietro</button>
    <div class="form-title">
      <h2 id="f3-title">Riepilogo</h2>
      <p id="f3-sub">Controlla i dati prima di inviare</p>
    </div>
    <div class="form-step-label" id="f3-step">Passo 3 di 3</div>

    <div class="riepilogo-card" id="riepilogoCard"></div>

    <div class="loading" id="loadingDiv">
      <div class="spinner"></div>
      <p id="l-sending">Invio in corso...</p>
    </div>

    <button class="btn-next" onclick="submitForm()" id="f3-submit">📤 Invia richiesta</button>
  </div>

  <!-- SCREEN 4: SUCCESSO -->
  <div class="screen" id="screen4">
    <div class="success-screen">
      <div class="success-icon">✅</div>
      <h2 id="s-title">Richiesta inviata!</h2>
      <p id="s-msg">La tua richiesta è stata ricevuta. Un tecnico Rotondi Group ti contatterà a breve.</p>
      <div class="protocollo-box">
        <div class="label" id="s-proto-label">Numero protocollo</div>
        <div class="code" id="s-proto-code">RG000000</div>
      </div>
      <p id="s-email-msg" style="font-size:13px;color:var(--muted);margin-top:8px"></p>
      <br>
      <button class="btn-restart" onclick="restart()" id="s-new">Nuova richiesta</button>
    </div>
  </div>

  <!-- SCREEN 5: RIFIUTO -->
  <div class="screen" id="screen5">
    <div class="declined-screen">
      <div style="font-size:48px;margin-bottom:16px">🙏</div>
      <h2 id="d-title">Servizio non accettato</h2>
      <p id="d-msg">Ha scelto di non procedere. Se cambia idea può tornare in qualsiasi momento.</p>
      <button class="btn-restart" onclick="restart()" id="d-restart">Torna all'inizio</button>
    </div>
  </div>

</div>

<script>
const T = {
  it: {
    'c-title':'ASSISTENZA<br><span>TECNICA</span>',
    'c-sub':'Rotondi Group Roma — Leggi le condizioni prima di procedere',
    'c-info-title':'Informativa sul servizio',
    'c-paid':'L\'assistenza tecnica è un <strong>servizio a pagamento</strong>, anche se il prodotto è <strong>in garanzia</strong>.',
    'c-warranty':'In garanzia vengono riconosciute solo le <strong>parti di ricambio difettose</strong> (sostituzione senza costo).',
    'c-charge':'<strong>Sempre a carico del cliente:</strong> Manodopera · Spostamento tecnico · Costo chiamata',
    'c-zone1':'Zona di Roma','c-zone2':'Fuori Roma (Latina, Frosinone, Rieti, Viterbo...)',
    'c-r1l':'Uscita + 1 ora lavoro','c-r2l':'Ore successive',
    'c-r3l':'Trasferta km','c-r4l':'Ore di viaggio','c-r5l':'Ore di lavoro',
    'c-freelance':'👨‍🔧 I tecnici che operano con Rotondi Group sono <strong>liberi professionisti freelance indipendenti</strong>, selezionati dalla nostra azienda. Non sono dipendenti Rotondi Group.',
    'c-accept':'✅  Accetto le condizioni','c-decline':'❌  Rifiuto',
    'f-back':'← Indietro','f-back2':'← Indietro','f-back3':'← Indietro',
    'f1-title':'Dati personali','f1-sub':'Inserisci i tuoi dati di contatto','f1-step':'Passo 1 di 3',
    'l-nome':'Nome e cognome *','l-indirizzo':'Indirizzo completo *',
    'l-telefono':'Telefono *','l-email':'Email *',
    'h-indirizzo':'Via, numero civico e città','h-email':'Per ricevere la conferma',
    'f1-next':'Continua →',
    'f2-title':'Dati macchina','f2-sub':'Informazioni sul macchinario','f2-step':'Passo 2 di 3',
    'l-marca':'Marca *','l-modello':'Modello','l-seriale':'Numero seriale','l-problema':'Descrivi il problema *',
    'f2-next':'Continua →',
    'f3-title':'Riepilogo','f3-sub':'Controlla i dati prima di inviare','f3-step':'Passo 3 di 3',
    'l-sending':'Invio in corso...','f3-submit':'📤 Invia richiesta',
    's-title':'Richiesta inviata!','s-msg':'La tua richiesta è stata ricevuta. Un tecnico Rotondi Group ti contatterà a breve.',
    's-proto-label':'Numero protocollo','s-new':'Nuova richiesta',
    'd-title':'Servizio non accettato','d-msg':'Ha scelto di non procedere. Se cambia idea può tornare in qualsiasi momento.',
    'd-restart':'Torna all\'inizio',
    'r-nome':'Nome','r-indirizzo':'Indirizzo','r-tel':'Telefono','r-email':'Email',
    'r-marca':'Marca','r-modello':'Modello','r-seriale':'Seriale','r-problema':'Problema',
  },
  en: {
    'c-title':'TECHNICAL<br><span>ASSISTANCE</span>',
    'c-sub':'Rotondi Group Roma — Read the conditions before proceeding',
    'c-info-title':'Service information',
    'c-paid':'Technical assistance is a <strong>paid service</strong>, even if the product is <strong>under warranty</strong>.',
    'c-warranty':'Under warranty only <strong>defective spare parts</strong> are replaced (no cost).',
    'c-charge':'<strong>Always charged to customer:</strong> Labour · Technician travel · Call-out fee',
    'c-zone1':'Rome area','c-zone2':'Outside Rome',
    'c-r1l':'Call-out + 1h work','c-r2l':'Additional hours',
    'c-r3l':'Travel km','c-r4l':'Travel hours','c-r5l':'Work hours',
    'c-freelance':'👨‍🔧 Our technicians are <strong>independent freelance professionals</strong> selected by Rotondi Group. They are not company employees.',
    'c-accept':'✅  I Accept','c-decline':'❌  Decline',
    'f-back':'← Back','f-back2':'← Back','f-back3':'← Back',
    'f1-title':'Personal details','f1-sub':'Enter your contact information','f1-step':'Step 1 of 3',
    'l-nome':'Full name *','l-indirizzo':'Full address *',
    'l-telefono':'Phone *','l-email':'Email *',
    'h-indirizzo':'Street, number and city','h-email':'To receive confirmation',
    'f1-next':'Continue →',
    'f2-title':'Machine details','f2-sub':'Information about the machine','f2-step':'Step 2 of 3',
    'l-marca':'Brand *','l-modello':'Model','l-seriale':'Serial number','l-problema':'Describe the problem *',
    'f2-next':'Continue →',
    'f3-title':'Summary','f3-sub':'Check your details before sending','f3-step':'Step 3 of 3',
    'l-sending':'Sending...','f3-submit':'📤 Send request',
    's-title':'Request sent!','s-msg':'Your request has been received. A Rotondi Group technician will contact you shortly.',
    's-proto-label':'Protocol number','s-new':'New request',
    'd-title':'Service not accepted','d-msg':'You chose not to proceed. You can come back at any time.',
    'd-restart':'Back to start',
    'r-nome':'Name','r-indirizzo':'Address','r-tel':'Phone','r-email':'Email',
    'r-marca':'Brand','r-modello':'Model','r-seriale':'Serial','r-problema':'Problem',
  },
  bn: {
    'c-title':'প্রযুক্তিগত<br><span>সহায়তা</span>',
    'c-sub':'রোটোন্ডি গ্রুপ রোমা — এগিয়ে যাওয়ার আগে শর্তাবলী পড়ুন',
    'c-info-title':'সেবার তথ্য',
    'c-paid':'প্রযুক্তিগত সহায়তা একটি <strong>পেইড সার্ভিস</strong>, এমনকি পণ্যটি <strong>ওয়ারেন্টিতে</strong> থাকলেও।',
    'c-warranty':'ওয়ারেন্টিতে শুধু <strong>ত্রুটিপূর্ণ যন্ত্রাংশ</strong> বিনামূল্যে প্রতিস্থাপন করা হয়।',
    'c-charge':'<strong>সর্বদা গ্রাহকের খরচ:</strong> শ্রম · যাতায়াত · কল চার্জ',
    'c-zone1':'রোমা এলাকা','c-zone2':'রোমার বাইরে',
    'c-r1l':'আসা + ১ ঘণ্টা','c-r2l':'অতিরিক্ত ঘণ্টা',
    'c-r3l':'যাতায়াত কিমি','c-r4l':'ভ্রমণ সময়','c-r5l':'কাজের সময়',
    'c-freelance':'👨‍🔧 আমাদের টেকনিশিয়ানরা <strong>স্বাধীন ফ্রিল্যান্স পেশাদার</strong>, রোটোন্ডি গ্রুপ কর্তৃক নির্বাচিত।',
    'c-accept':'✅  গ্রহণ করি','c-decline':'❌  প্রত্যাখ্যান',
    'f-back':'← ফিরে যান','f-back2':'← ফিরে যান','f-back3':'← ফিরে যান',
    'f1-title':'ব্যক্তিগত তথ্য','f1-sub':'আপনার যোগাযোগের তথ্য দিন','f1-step':'ধাপ ১ এর ৩',
    'l-nome':'নাম এবং পদবি *','l-indirizzo':'সম্পূর্ণ ঠিকানা *',
    'l-telefono':'ফোন *','l-email':'ইমেইল *',
    'h-indirizzo':'রাস্তা, নম্বর এবং শহর','h-email':'নিশ্চিতকরণ পেতে',
    'f1-next':'পরবর্তী →',
    'f2-title':'মেশিনের তথ্য','f2-sub':'মেশিন সম্পর্কে তথ্য','f2-step':'ধাপ ২ এর ৩',
    'l-marca':'ব্র্যান্ড *','l-modello':'মডেল','l-seriale':'সিরিয়াল নম্বর','l-problema':'সমস্যা বর্ণনা করুন *',
    'f2-next':'পরবর্তী →',
    'f3-title':'সারসংক্ষেপ','f3-sub':'পাঠানোর আগে তথ্য যাচাই করুন','f3-step':'ধাপ ৩ এর ৩',
    'l-sending':'পাঠানো হচ্ছে...','f3-submit':'📤 অনুরোধ পাঠান',
    's-title':'অনুরোধ পাঠানো হয়েছে!','s-msg':'আপনার অনুরোধ পাওয়া গেছে। শীঘ্রই একজন টেকনিশিয়ান যোগাযোগ করবেন।',
    's-proto-label':'প্রোটোকল নম্বর','s-new':'নতুন অনুরোধ',
    'd-title':'সেবা গ্রহণ করা হয়নি','d-msg':'আপনি এগিয়ে না যাওয়ার সিদ্ধান্ত নিয়েছেন।',
    'd-restart':'শুরুতে ফিরুন',
    'r-nome':'নাম','r-indirizzo':'ঠিকানা','r-tel':'ফোন','r-email':'ইমেইল',
    'r-marca':'ব্র্যান্ড','r-modello':'মডেল','r-seriale':'সিরিয়াল','r-problema':'সমস্যা',
  },
  zh: {
    'c-title':'技术<br><span>援助</span>',
    'c-sub':'罗通迪集团罗马 — 继续前请阅读条款',
    'c-info-title':'服务信息',
    'c-paid':'技术援助是<strong>付费服务</strong>，即使产品<strong>在保修期内</strong>也是如此。',
    'c-warranty':'保修期内仅免费更换<strong>有缺陷的零件</strong>。',
    'c-charge':'<strong>始终由客户承担：</strong>人工费 · 差旅费 · 上门费',
    'c-zone1':'罗马地区','c-zone2':'罗马以外地区',
    'c-r1l':'上门费+1小时','c-r2l':'额外每小时',
    'c-r3l':'差旅公里','c-r4l':'路途时间','c-r5l':'工作时间',
    'c-freelance':'👨‍🔧 我们的技术人员是<strong>独立自由职业者</strong>，由罗通迪集团选派，非公司雇员。',
    'c-accept':'✅  我接受','c-decline':'❌  拒绝',
    'f-back':'← 返回','f-back2':'← 返回','f-back3':'← 返回',
    'f1-title':'个人信息','f1-sub':'输入您的联系信息','f1-step':'第1步，共3步',
    'l-nome':'姓名 *','l-indirizzo':'完整地址 *',
    'l-telefono':'电话 *','l-email':'电子邮件 *',
    'h-indirizzo':'街道、门牌号和城市','h-email':'用于接收确认',
    'f1-next':'继续 →',
    'f2-title':'机器信息','f2-sub':'关于机器的信息','f2-step':'第2步，共3步',
    'l-marca':'品牌 *','l-modello':'型号','l-seriale':'序列号','l-problema':'描述问题 *',
    'f2-next':'继续 →',
    'f3-title':'摘要','f3-sub':'发送前检查您的信息','f3-step':'第3步，共3步',
    'l-sending':'发送中...','f3-submit':'📤 发送请求',
    's-title':'请求已发送！','s-msg':'您的请求已收到。罗通迪集团技术人员将很快与您联系。',
    's-proto-label':'协议编号','s-new':'新请求',
    'd-title':'未接受服务','d-msg':'您选择不继续。随时可以返回。',
    'd-restart':'返回开始',
    'r-nome':'姓名','r-indirizzo':'地址','r-tel':'电话','r-email':'电子邮件',
    'r-marca':'品牌','r-modello':'型号','r-seriale':'序列号','r-problema':'问题',
  },
  ar: {
    'c-title':'المساعدة<br><span>التقنية</span>',
    'c-sub':'روتوندي جروب روما — اقرأ الشروط قبل المتابعة',
    'c-info-title':'معلومات الخدمة',
    'c-paid':'المساعدة التقنية <strong>خدمة مدفوعة</strong>، حتى لو كان المنتج <strong>تحت الضمان</strong>.',
    'c-warranty':'الضمان يشمل فقط استبدال <strong>قطع الغيار المعيبة</strong> مجاناً.',
    'c-charge':'<strong>دائماً على حساب العميل:</strong> أجرة العمل · التنقل · رسوم الزيارة',
    'c-zone1':'منطقة روما','c-zone2':'خارج روما',
    'c-r1l':'زيارة + ساعة عمل','c-r2l':'ساعات إضافية',
    'c-r3l':'كيلومترات التنقل','c-r4l':'ساعات السفر','c-r5l':'ساعات العمل',
    'c-freelance':'👨‍🔧 فنيونا <strong>محترفون مستقلون فريلانس</strong>، من اختيار روتوندي جروب، وليسوا موظفين في الشركة.',
    'c-accept':'✅  أقبل الشروط','c-decline':'❌  أرفض',
    'f-back':'→ رجوع','f-back2':'→ رجوع','f-back3':'→ رجوع',
    'f1-title':'البيانات الشخصية','f1-sub':'أدخل معلومات الاتصال','f1-step':'الخطوة 1 من 3',
    'l-nome':'الاسم الكامل *','l-indirizzo':'العنوان الكامل *',
    'l-telefono':'الهاتف *','l-email':'البريد الإلكتروني *',
    'h-indirizzo':'الشارع والرقم والمدينة','h-email':'لاستلام التأكيد',
    'f1-next':'→ متابعة',
    'f2-title':'بيانات الجهاز','f2-sub':'معلومات عن الجهاز','f2-step':'الخطوة 2 من 3',
    'l-marca':'الماركة *','l-modello':'الموديل','l-seriale':'الرقم التسلسلي','l-problema':'صف المشكلة *',
    'f2-next':'→ متابعة',
    'f3-title':'الملخص','f3-sub':'تحقق من بياناتك قبل الإرسال','f3-step':'الخطوة 3 من 3',
    'l-sending':'جارٍ الإرسال...','f3-submit':'📤 إرسال الطلب',
    's-title':'تم إرسال الطلب!','s-msg':'تم استلام طلبك. سيتصل بك فني روتوندي جروب قريباً.',
    's-proto-label':'رقم البروتوكول','s-new':'طلب جديد',
    'd-title':'لم تُقبل الخدمة','d-msg':'اخترت عدم المتابعة. يمكنك العودة في أي وقت.',
    'd-restart':'العودة إلى البداية',
    'r-nome':'الاسم','r-indirizzo':'العنوان','r-tel':'الهاتف','r-email':'البريد',
    'r-marca':'الماركة','r-modello':'الموديل','r-seriale':'التسلسلي','r-problema':'المشكلة',
  }
};

let lang = 'it';
let currentScreen = 0;

function setLang(l) {
  lang = l;
  document.querySelectorAll('.lang-btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  applyLang();
}

function applyLang() {
  const t = T[lang];
  for (const [id, val] of Object.entries(t)) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = val;
  }
  // RTL for Arabic
  document.body.style.direction = lang === 'ar' ? 'rtl' : 'ltr';
}

function goTo(n) {
  document.getElementById('screen' + currentScreen).classList.remove('active');
  document.getElementById('screen' + n).classList.add('active');
  currentScreen = n;
  updateSteps(n);
  window.scrollTo(0, 0);
}

function updateSteps(n) {
  const bar = document.getElementById('stepsBar');
  if (n === 0 || n >= 4) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';
  for (let i = 1; i <= 4; i++) {
    const dot = document.getElementById('sd' + i);
    dot.className = 'step-dot';
    if (i < n) dot.classList.add('done');
    else if (i === n) dot.classList.add('active');
  }
  for (let i = 1; i <= 3; i++) {
    const line = document.getElementById('sl' + i);
    line.className = 'step-line';
    if (i < n) line.classList.add('done');
  }
}

function acceptConditions() { goTo(1); }
function declineConditions() { goTo(5); }

function nextStep1() {
  const nome = document.getElementById('inp-nome').value.trim();
  const ind  = document.getElementById('inp-indirizzo').value.trim();
  const tel  = document.getElementById('inp-telefono').value.trim();
  const email = document.getElementById('inp-email').value.trim();
  if (!nome || !ind || !tel || !email) {
    alert(lang === 'it' ? 'Compila tutti i campi obbligatori *' :
          lang === 'en' ? 'Fill all required fields *' :
          lang === 'bn' ? 'সব বাধ্যতামূলক ক্ষেত্র পূরণ করুন *' :
          lang === 'zh' ? '请填写所有必填字段 *' : 'يرجى ملء جميع الحقول المطلوبة *');
    return;
  }
  goTo(2);
}

function nextStep2() {
  const marca   = document.getElementById('inp-marca').value.trim();
  const problema = document.getElementById('inp-problema').value.trim();
  if (!marca || !problema) {
    alert(lang === 'it' ? 'Compila i campi obbligatori *' : 'Fill required fields *');
    return;
  }
  buildRiepilogo();
  goTo(3);
}

function buildRiepilogo() {
  const t = T[lang];
  const data = [
    [t['r-nome'],   document.getElementById('inp-nome').value],
    [t['r-indirizzo'], document.getElementById('inp-indirizzo').value],
    [t['r-tel'],    document.getElementById('inp-telefono').value],
    [t['r-email'],  document.getElementById('inp-email').value],
    [t['r-marca'],  document.getElementById('inp-marca').value],
    [t['r-modello'],document.getElementById('inp-modello').value],
    [t['r-seriale'],document.getElementById('inp-seriale').value],
    [t['r-problema'],document.getElementById('inp-problema').value],
  ];
  let html = '';
  data.forEach(([label, val]) => {
    if (val) html += `<div class="riepilogo-row"><div class="riepilogo-label">${label}</div><div class="riepilogo-val">${val}</div></div>`;
  });
  document.getElementById('riepilogoCard').innerHTML = html;
}

function submitForm() {
  const btn = document.getElementById('f3-submit');
  const loading = document.getElementById('loadingDiv');
  btn.style.display = 'none';
  loading.style.display = 'block';

  const payload = {
    lingua:   lang,
    nome:     document.getElementById('inp-nome').value,
    indirizzo:document.getElementById('inp-indirizzo').value,
    telefono: document.getElementById('inp-telefono').value,
    email:    document.getElementById('inp-email').value,
    marca:    document.getElementById('inp-marca').value,
    modello:  document.getElementById('inp-modello').value,
    seriale:  document.getElementById('inp-seriale').value,
    problema: document.getElementById('inp-problema').value,
  };

  fetch('/api/richiesta', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  })
  .then(r => r.json())
  .then(data => {
    loading.style.display = 'none';
    if (data.ok) {
      document.getElementById('s-proto-code').textContent = data.protocollo;
      const emailMsg = document.getElementById('s-email-msg');
      if (data.email_sent) {
        emailMsg.textContent = lang === 'it' ? `Conferma inviata a: ${payload.email}` :
                               lang === 'en' ? `Confirmation sent to: ${payload.email}` :
                               lang === 'bn' ? `নিশ্চিতকরণ পাঠানো হয়েছে: ${payload.email}` :
                               lang === 'zh' ? `确认已发送至: ${payload.email}` :
                               `تم إرسال التأكيد إلى: ${payload.email}`;
      }
      goTo(4);
    } else {
      btn.style.display = 'block';
      alert('Errore: ' + (data.error || 'Riprova'));
    }
  })
  .catch(err => {
    loading.style.display = 'none';
    btn.style.display = 'block';
    alert('Errore di connessione. Riprova.');
  });
}

function restart() {
  ['inp-nome','inp-indirizzo','inp-telefono','inp-email',
   'inp-marca','inp-modello','inp-seriale','inp-problema'].forEach(id => {
    document.getElementById(id).value = '';
  });
  goTo(0);
}

// Init
applyLang();
</script>
</body>
</html>'''

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/api/richiesta', methods=['POST'])
def nuova_richiesta():
    data = request.json
    if not data:
        return jsonify({"ok": False, "error": "No data"})

    protocollo = genera_protocollo()
    lingua  = data.get('lingua', 'it')
    nome    = data.get('nome', '')
    ind     = data.get('indirizzo', '')
    tel     = data.get('telefono', '')
    email   = data.get('email', '')
    marca   = data.get('marca', '')
    modello = data.get('modello', '')
    seriale = data.get('seriale', '')
    problema = data.get('problema', '')
    now     = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Salva DB
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO richieste_web
            (protocollo,nome,indirizzo,telefono,email,marca,modello,seriale,problema,lingua,data)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (protocollo, nome, ind, tel, email, marca, modello, seriale, problema, lingua, now))
        conn.commit()

    FLAGS = {'it':'🇮🇹','en':'🇬🇧','bn':'🇧🇩','zh':'🇨🇳','ar':'🇸🇦'}
    flag = FLAGS.get(lingua, '🌍')
    maps_link = f"https://www.google.com/maps/search/?api=1&query={ind.replace(' ', '+')},+Roma,+Italia"

    # Notifica gruppo tecnici
    keyboard = {"inline_keyboard": [[
        {"text": "🕛 Entro le 12:00", "callback_data": f"wfascia_{protocollo}_entro12"},
        {"text": "🕕 Entro le 18:00", "callback_data": f"wfascia_{protocollo}_entro18"},
    ],[
        {"text": "📅 In giornata",    "callback_data": f"wfascia_{protocollo}_giornata"},
        {"text": "📆 Entro domani",   "callback_data": f"wfascia_{protocollo}_domani"},
    ],[
        {"text": "🗓 Da programmare", "callback_data": f"wfascia_{protocollo}_programma"},
    ]]}

    testo = (
        f"🌐 *RICHIESTA WEB #{protocollo}* {flag}\n{'─'*28}\n"
        f"👤 *Cliente:* {nome}\n"
        f"📍 *Indirizzo:* {ind}\n"
        f"🗺 [Apri su Google Maps]({maps_link})\n"
        f"📞 *Telefono:* {tel}\n"
        f"📧 *Email:* {email}\n"
        f"🏭 *Marca:* {marca}  ·  *Modello:* {modello}\n"
        f"🔢 *Seriale:* {seriale or '—'}\n"
        f"🔧 *Problema:* {problema}\n"
        f"{'─'*28}\n"
        f"⏰ Primo tecnico disponibile: clicca quando intervieni:"
    )
    msg_id = invia_telegram(testo, keyboard)

    # Notifica back office
    invia_telegram_bo(
        f"🌐 *Nuova richiesta WEB* {flag}\n\n"
        f"🔖 Protocollo: `{protocollo}`\n"
        f"👤 {nome}\n📍 {ind}\n📞 {tel}\n📧 {email}\n"
        f"🏭 {marca} — {modello}\n🔧 {problema}"
    )

    # Email al cliente
    SOGGETTI = {'it': f'Rotondi Group Roma — Richiesta ricevuta #{protocollo}',
                'en': f'Rotondi Group Roma — Request received #{protocollo}',
                'bn': f'রোটোন্ডি গ্রুপ রোমা — অনুরোধ পাওয়া গেছে #{protocollo}',
                'zh': f'罗通迪集团罗马 — 已收到请求 #{protocollo}',
                'ar': f'روتوندي جروب روما — تم استلام طلبك #{protocollo}'}

    CORPI = {'it': f"""
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;background:#f5f5f5;padding:20px">
<div style="background:#1a1a2e;padding:24px;border-radius:8px 8px 0 0;text-align:center">
  <h1 style="color:#fff;font-size:20px;margin:0">ROTONDI GROUP ROMA</h1>
  <p style="color:#c9a84c;margin:4px 0 0;font-size:13px">ASSISTENZA TECNICA</p>
</div>
<div style="background:#fff;padding:24px;border-radius:0 0 8px 8px">
  <h2 style="color:#1a1a2e;font-size:18px">✅ Richiesta ricevuta!</h2>
  <p style="color:#555">Gentile <strong>{nome}</strong>,<br>
  La sua richiesta di assistenza è stata ricevuta. Un tecnico la contatterà a breve.</p>
  <div style="background:#f8f8f8;border-radius:8px;padding:16px;margin:16px 0">
    <p style="margin:0 0 8px;font-size:13px;color:#888;text-transform:uppercase;letter-spacing:1px">Numero protocollo</p>
    <p style="font-size:28px;font-weight:700;color:#1a1a2e;letter-spacing:4px;margin:0">{protocollo}</p>
  </div>
  <p style="color:#555;font-size:14px"><strong>Problema segnalato:</strong> {problema}</p>
  <hr style="border:none;border-top:1px solid #eee;margin:16px 0">
  <p style="color:#888;font-size:13px">Per annullare: <strong>+39 06 41 40 0514</strong></p>
  <p style="color:#888;font-size:13px">Ufficio Roma: <strong>+39 06 41400617</strong></p>
</div>
</div>""",
'en': f"""
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;background:#f5f5f5;padding:20px">
<div style="background:#1a1a2e;padding:24px;border-radius:8px 8px 0 0;text-align:center">
  <h1 style="color:#fff;font-size:20px;margin:0">ROTONDI GROUP ROMA</h1>
  <p style="color:#c9a84c;margin:4px 0 0;font-size:13px">TECHNICAL ASSISTANCE</p>
</div>
<div style="background:#fff;padding:24px;border-radius:0 0 8px 8px">
  <h2 style="color:#1a1a2e;font-size:18px">✅ Request received!</h2>
  <p style="color:#555">Dear <strong>{nome}</strong>,<br>
  Your assistance request has been received. A technician will contact you shortly.</p>
  <div style="background:#f8f8f8;border-radius:8px;padding:16px;margin:16px 0">
    <p style="margin:0 0 8px;font-size:13px;color:#888;text-transform:uppercase;letter-spacing:1px">Protocol number</p>
    <p style="font-size:28px;font-weight:700;color:#1a1a2e;letter-spacing:4px;margin:0">{protocollo}</p>
  </div>
  <p style="color:#555;font-size:14px"><strong>Problem reported:</strong> {problema}</p>
  <hr style="border:none;border-top:1px solid #eee;margin:16px 0">
  <p style="color:#888;font-size:13px">To cancel: <strong>+39 06 41 40 0514</strong></p>
</div></div>"""}

    corpo = CORPI.get(lingua, CORPI['en'])
    soggetto = SOGGETTI.get(lingua, SOGGETTI['en'])
    email_sent = invia_email(email, soggetto, corpo)

    return jsonify({"ok": True, "protocollo": protocollo, "email_sent": email_sent})

@app.route('/api/stato/<protocollo>')
def stato_richiesta(protocollo):
    with sqlite3.connect(DB_PATH) as conn:
        r = conn.execute("""
            SELECT protocollo, nome, stato, tecnico, fascia, data
            FROM richieste_web WHERE protocollo=?
        """, (protocollo,)).fetchone()
    if not r:
        return jsonify({"ok": False, "error": "Not found"})
    return jsonify({"ok": True, "protocollo": r[0], "nome": r[1],
                    "stato": r[2], "tecnico": r[3], "fascia": r[4], "data": r[5]})

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
