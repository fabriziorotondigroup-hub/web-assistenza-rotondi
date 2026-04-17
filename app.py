#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify, render_template_string
import os, sqlite3, uuid, requests, smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)

BOT_TOKEN        = os.environ.get("BOT_TOKEN", "")
TECNICI_GROUP_ID = os.environ.get("TECNICI_GROUP_ID", "")
BACKOFFICE_IDS   = os.environ.get("BACKOFFICE_IDS", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "assistenza@garanzierotondi.it")
DB_PATH   = "web_assistenza.db"

def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS richieste_web (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            protocollo TEXT UNIQUE, nome TEXT, indirizzo TEXT,
            telefono TEXT, email TEXT, marca TEXT, modello TEXT,
            seriale TEXT, problema TEXT, lingua TEXT,
            stato TEXT DEFAULT 'aperta', data TEXT)""")
        c.commit()

def genera_protocollo():
    return "RG" + datetime.now().strftime("%y%m%d") + str(uuid.uuid4())[:4].upper()

def invia_telegram(text, keyboard=None):
    if not BOT_TOKEN or not TECNICI_GROUP_ID: return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    p = {"chat_id": TECNICI_GROUP_ID, "text": text, "parse_mode": "Markdown"}
    if keyboard:
        import json; p["reply_markup"] = json.dumps(keyboard)
    try:
        r = requests.post(url, json=p, timeout=10)
        return r.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"TG error: {e}"); return None

def invia_telegram_bo(text):
    if not BOT_TOKEN or not BACKOFFICE_IDS: return
    for bo in BACKOFFICE_IDS.split(","):
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": bo.strip(), "text": text, "parse_mode": "Markdown"}, timeout=10)
        except: pass

def invia_email(to, subject, html):
    if not SMTP_USER or not SMTP_PASS: return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject; msg["From"] = SMTP_FROM; msg["To"] = to
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls(); s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_FROM, to, msg.as_string())
        return True
    except Exception as e:
        print(f"Email error: {e}"); return False

HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Assistenza Tecnica — Rotondi Group Roma</title>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--dark:#0d0d14;--card:#1a1a2e;--border:rgba(255,255,255,0.09);--gold:#c9a84c;--gold2:#e8c96d;--text:#e8e6e0;--muted:rgba(232,230,224,0.55);--green:#2ea043;--red:#f85149}
body{background:var(--dark);color:var(--text);font-family:'DM Sans',sans-serif;min-height:100vh}
a{color:var(--gold)}

/* HEADER */
.hdr{background:#14141f;border-bottom:1px solid var(--border);padding:14px 24px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;backdrop-filter:blur(10px)}
.logo{font-family:'Bebas Neue',sans-serif;font-size:20px;letter-spacing:2px;color:#fff}
.logo span{color:var(--gold)}
.langs{display:flex;gap:5px}
.lb{background:rgba(255,255,255,0.05);border:1px solid var(--border);color:var(--muted);padding:5px 10px;border-radius:6px;cursor:pointer;font-size:13px;font-family:'DM Sans',sans-serif;transition:.2s}
.lb:hover,.lb.on{background:rgba(201,168,76,.15);border-color:var(--gold);color:var(--gold)}

/* MAIN */
.wrap{max-width:660px;margin:0 auto;padding:32px 20px 80px}

/* STEPS */
.stepbar{display:flex;align-items:center;margin-bottom:36px;display:none}
.sdot{width:30px;height:30px;border-radius:50%;border:2px solid var(--border);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;color:var(--muted);flex-shrink:0;transition:.3s}
.sdot.on{border-color:var(--gold);color:var(--gold);background:rgba(201,168,76,.1)}
.sdot.done{border-color:var(--green);color:var(--green);background:rgba(46,160,67,.1)}
.sline{flex:1;height:1px;background:var(--border);transition:.3s}
.sline.done{background:var(--green)}

/* SCREENS */
.sc{display:none}
.sc.on{display:block;animation:fi .35s ease}
@keyframes fi{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}

/* CONDIZIONI */
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
.bdec:hover{background:rgba(248,81,73,.2)}

/* FORM */
.ftitle{margin-bottom:26px}
.ftitle h2{font-family:'Bebas Neue',sans-serif;font-size:28px;letter-spacing:1px}
.ftitle p{color:var(--muted);margin-top:4px;font-size:14px}
.fstep{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--gold);margin-bottom:18px;display:flex;align-items:center;gap:8px}
.fstep::after{content:'';flex:1;height:1px;background:var(--border)}

.fld{margin-bottom:18px}
.fld label{display:block;font-size:13px;color:var(--muted);margin-bottom:7px;font-weight:500}
.fld input,.fld textarea,.fld select{width:100%;background:var(--card);border:1px solid var(--border);color:var(--text);padding:13px 15px;border-radius:8px;font-size:15px;font-family:'DM Sans',sans-serif;outline:none;transition:.2s}
.fld input:focus,.fld textarea:focus{border-color:var(--gold)}
.fld textarea{min-height:100px;resize:vertical}
.fld .hint{font-size:12px;color:var(--muted);margin-top:5px}
.fg2{display:grid;grid-template-columns:1fr 1fr;gap:14px}

.bnext{width:100%;background:var(--gold);color:var(--dark);border:none;padding:16px;border-radius:10px;font-size:16px;font-weight:700;cursor:pointer;font-family:'DM Sans',sans-serif;margin-top:6px;transition:.2s}
.bnext:hover{background:var(--gold2);transform:translateY(-1px)}
.bback{background:transparent;color:var(--muted);border:1px solid var(--border);padding:11px 18px;border-radius:8px;font-size:14px;cursor:pointer;margin-bottom:16px;font-family:'DM Sans',sans-serif;transition:.2s}
.bback:hover{color:var(--text);border-color:rgba(255,255,255,.2)}

/* RIEPILOGO */
.rcard{background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:hidden;margin-bottom:18px}
.rrow{display:flex;gap:14px;padding:13px 18px;border-bottom:1px solid var(--border)}
.rrow:last-child{border-bottom:none}
.rlbl{font-size:12px;color:var(--muted);min-width:90px;flex-shrink:0;padding-top:2px}
.rval{font-size:14px;line-height:1.5}

/* LOADING */
.ldr{display:none;text-align:center;padding:20px}
.spin{width:30px;height:30px;border:3px solid var(--border);border-top-color:var(--gold);border-radius:50%;animation:sp .8s linear infinite;margin:0 auto 10px}
@keyframes sp{to{transform:rotate(360deg)}}

/* SUCCESS */
.succ{text-align:center;padding:40px 0}
.succ h2{font-family:'Bebas Neue',sans-serif;font-size:32px;letter-spacing:2px;color:var(--gold);margin:16px 0 10px}
.succ p{color:var(--muted);font-size:15px;line-height:1.7;max-width:380px;margin:0 auto 16px}
.pbox{background:var(--card);border:1px solid var(--gold);border-radius:10px;padding:18px 28px;display:inline-block;margin:16px auto}
.plbl{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--gold);margin-bottom:6px}
.pcode{font-size:30px;font-weight:700;color:#fff;letter-spacing:4px;font-family:'Bebas Neue',sans-serif}

/* DECLINED */
.dec{text-align:center;padding:40px 0}
.dec h2{font-family:'Bebas Neue',sans-serif;font-size:28px;letter-spacing:1px;margin-bottom:10px}
.dec p{color:var(--muted);font-size:15px;line-height:1.7}
.brest{background:var(--card);border:1px solid var(--border);color:var(--text);padding:12px 28px;border-radius:8px;cursor:pointer;font-size:14px;margin-top:18px;font-family:'DM Sans',sans-serif;transition:.2s}
.brest:hover{border-color:var(--gold);color:var(--gold)}

@media(max-width:500px){.tgrid,.fg2,.btnrow{grid-template-columns:1fr}.langs{gap:3px}.lb{padding:5px 7px;font-size:11px}}
</style>
</head>
<body>
<div class="hdr">
  <div class="logo">ROTONDI <span>GROUP</span> ROMA</div>
  <div class="langs">
    <button class="lb on" onclick="setL('it',this)">🇮🇹</button>
    <button class="lb" onclick="setL('en',this)">🇬🇧</button>
    <button class="lb" onclick="setL('bn',this)">🇧🇩</button>
    <button class="lb" onclick="setL('zh',this)">🇨🇳</button>
    <button class="lb" onclick="setL('ar',this)">🇸🇦</button>
  </div>
</div>

<div class="wrap">
  <div class="stepbar" id="stepbar">
    <div class="sdot on" id="d1">1</div><div class="sline" id="l1"></div>
    <div class="sdot" id="d2">2</div><div class="sline" id="l2"></div>
    <div class="sdot" id="d3">3</div><div class="sline" id="l3"></div>
    <div class="sdot" id="d4">4</div>
  </div>

  <!-- S0: CONDIZIONI -->
  <div class="sc on" id="s0">
    <div class="ch">
      <h1 id="t-title">ASSISTENZA<br><em>TECNICA</em></h1>
      <p id="t-sub">Rotondi Group Roma — Leggi le condizioni prima di procedere</p>
    </div>
    <div class="cbox">
      <div class="ctitle" id="t-ctitle">Informativa sul servizio</div>
      <div class="crow"><div class="cico" style="color:#f0b429">⚠</div><div class="ctxt" id="t-c1">L'assistenza tecnica è un <b>servizio a pagamento</b>, anche se il prodotto è <b>in garanzia</b>.</div></div>
      <div class="crow"><div class="cico" style="color:#2ea043">✓</div><div class="ctxt" id="t-c2">In garanzia vengono riconosciute solo le <b>parti di ricambio difettose</b> (sostituzione senza costo).</div></div>
      <div class="crow"><div class="cico" style="color:#c9a84c">€</div><div class="ctxt" id="t-c3"><b>Sempre a carico del cliente:</b> Manodopera · Spostamento tecnico · Costo chiamata</div></div>
    </div>
    <div class="tgrid">
      <div class="tcard">
        <h4 id="t-z1">Zona di Roma</h4>
        <div class="trow"><span id="t-r1l">Uscita + 1 ora lavoro</span><span class="tv">€ 80,00 + IVA</span></div>
        <div class="trow"><span id="t-r2l">Ore successive</span><span class="tv">€ 40,00/h + IVA</span></div>
      </div>
      <div class="tcard">
        <h4 id="t-z2">Fuori Roma</h4>
        <div class="trow"><span id="t-r3l">Trasferta km</span><span class="tv">€ 0,70/km + IVA</span></div>
        <div class="trow"><span id="t-r4l">Ore viaggio</span><span class="tv">€ 32,00/h + IVA</span></div>
        <div class="trow"><span id="t-r5l">Ore lavoro</span><span class="tv">€ 40,00/h + IVA</span></div>
      </div>
    </div>
    <div class="fnote" id="t-frl">I tecnici che operano con Rotondi Group sono <b>liberi professionisti freelance indipendenti</b>, selezionati dalla nostra azienda. Non sono dipendenti Rotondi Group.</div>
    <div class="btnrow">
      <button class="bacc" onclick="go(1)" id="t-acc">✓ Accetto le condizioni</button>
      <button class="bdec" onclick="go(5)" id="t-dec">✗ Rifiuto</button>
    </div>
  </div>

  <!-- S1: DATI PERSONALI -->
  <div class="sc" id="s1">
    <button class="bback" onclick="go(0)" id="t-bk">← Indietro</button>
    <div class="ftitle"><h2 id="t-f1h">Dati personali</h2><p id="t-f1p">Inserisci i tuoi dati di contatto</p></div>
    <div class="fstep" id="t-f1s">Passo 1 di 3</div>
    <div class="fld"><label id="t-ln">Nome e cognome *</label><input id="v-nome" type="text" placeholder="Mario Rossi"></div>
    <div class="fld"><label id="t-li">Indirizzo completo *</label><input id="v-ind" type="text" placeholder="Via Roma 10, Roma"><div class="hint" id="t-hi">Via, numero civico e città</div></div>
    <div class="fg2">
      <div class="fld"><label id="t-lt">Telefono *</label><input id="v-tel" type="tel" placeholder="+39 333 1234567"></div>
      <div class="fld"><label id="t-le">Email *</label><input id="v-email" type="email" placeholder="mario@email.com"><div class="hint" id="t-he">Per ricevere la conferma</div></div>
    </div>
    <button class="bnext" onclick="step1()" id="t-f1n">Continua →</button>
  </div>

  <!-- S2: DATI MACCHINA -->
  <div class="sc" id="s2">
    <button class="bback" onclick="go(1)" id="t-bk2">← Indietro</button>
    <div class="ftitle"><h2 id="t-f2h">Dati macchina</h2><p id="t-f2p">Informazioni sul macchinario</p></div>
    <div class="fstep" id="t-f2s">Passo 2 di 3</div>
    <div class="fg2">
      <div class="fld"><label id="t-lma">Marca *</label><input id="v-marca" type="text" placeholder="Samsung, LG, Bosch..."></div>
      <div class="fld"><label id="t-lmo">Modello</label><input id="v-modello" type="text" placeholder="Es: WW80J5355FW"></div>
    </div>
    <div class="fld"><label id="t-lse">Numero seriale</label><input id="v-seriale" type="text" placeholder="Sulla targhetta della macchina"></div>
    <div class="fld"><label id="t-lpr">Descrivi il problema *</label><textarea id="v-problema" placeholder="Cosa succede? Da quando? Hai già provato qualcosa?"></textarea></div>
    <button class="bnext" onclick="step2()" id="t-f2n">Continua →</button>
  </div>

  <!-- S3: RIEPILOGO -->
  <div class="sc" id="s3">
    <button class="bback" onclick="go(2)" id="t-bk3">← Indietro</button>
    <div class="ftitle"><h2 id="t-f3h">Riepilogo</h2><p id="t-f3p">Controlla i dati prima di inviare</p></div>
    <div class="fstep" id="t-f3s">Passo 3 di 3</div>
    <div class="rcard" id="rcard"></div>
    <div class="ldr" id="ldr"><div class="spin"></div><p id="t-send">Invio in corso...</p></div>
    <button class="bnext" onclick="submit()" id="t-sub">Invia richiesta</button>
  </div>

  <!-- S4: SUCCESSO -->
  <div class="sc" id="s4">
    <div class="succ">
      <div style="font-size:52px">✅</div>
      <h2 id="t-sh">Richiesta inviata!</h2>
      <p id="t-sp">La tua richiesta è stata ricevuta. Un tecnico ti contatterà a breve.</p>
      <div class="pbox"><div class="plbl" id="t-pl">Numero protocollo</div><div class="pcode" id="t-pc">RG000000</div></div>
      <p id="t-em" style="font-size:13px;color:var(--muted);margin-top:8px"></p><br>
      <button class="brest" onclick="restart()" id="t-nr">Nuova richiesta</button>
    </div>
  </div>

  <!-- S5: RIFIUTO -->
  <div class="sc" id="s5">
    <div class="dec">
      <div style="font-size:48px;margin-bottom:14px">🙏</div>
      <h2 id="t-dh">Servizio non accettato</h2>
      <p id="t-dp">Ha scelto di non procedere. Può tornare in qualsiasi momento.</p>
      <button class="brest" onclick="restart()" id="t-dr">Torna all'inizio</button>
    </div>
  </div>
</div>

<script>
var lang='it', cur=0;

var TX={
  it:{
    'title':'ASSISTENZA<br><em>TECNICA</em>',
    'sub':'Rotondi Group Roma — Leggi le condizioni prima di procedere',
    'ctitle':'Informativa sul servizio',
    'c1':"L'assistenza tecnica è un <b>servizio a pagamento</b>, anche se il prodotto è <b>in garanzia</b>.",
    'c2':'In garanzia vengono riconosciute solo le <b>parti di ricambio difettose</b> (sostituzione senza costo).',
    'c3':'<b>Sempre a carico del cliente:</b> Manodopera · Spostamento tecnico · Costo chiamata',
    'z1':'TARIFFE ZONA DI ROMA (Dentro il Grande Raccordo Anulare)','z2':'TARIFFE PROVINCIA DI ROMA, LAZIO E RESTO D\'ITALIA',
    'r1l':'Uscita + 1 ora lavoro','r2l':'Ore successive','r3l':'Trasferta km','r4l':'Ore viaggio','r5l':'Ore lavoro',
    'frl':'I tecnici che operano con Rotondi Group sono <b>liberi professionisti freelance indipendenti</b>, selezionati dalla nostra azienda. Non sono dipendenti Rotondi Group.',
    'acc':'✓ Accetto le condizioni','dec':'✗ Rifiuto',
    'bk':'← Indietro',
    'f1h':'Dati personali','f1p':'Inserisci i tuoi dati di contatto','f1s':'Passo 1 di 3',
    'ln':'Nome e cognome *','li':'Indirizzo completo *','lt':'Telefono *','le':'Email *',
    'hi':'Via, numero civico e città','he':'Per ricevere la conferma',
    'f1n':'Continua →',
    'f2h':'Dati macchina','f2p':'Informazioni sul macchinario','f2s':'Passo 2 di 3',
    'lma':'Marca *','lmo':'Modello','lse':'Numero seriale','lpr':'Descrivi il problema *',
    'f2n':'Continua →',
    'f3h':'Riepilogo','f3p':'Controlla i dati prima di inviare','f3s':'Passo 3 di 3',
    'send':'Invio in corso...','sub':'📤 Invia richiesta',
    'sh':'Richiesta inviata!','sp':'La tua richiesta è stata ricevuta. Un tecnico Rotondi Group ti contatterà a breve.',
    'pl':'Numero protocollo','nr':'Nuova richiesta',
    'dh':'Servizio non accettato','dp':'Ha scelto di non procedere. Può tornare in qualsiasi momento.','dr':"Torna all'inizio",
    'rn':'Nome','ri':'Indirizzo','rt':'Telefono','re':'Email','rma':'Marca','rmo':'Modello','rse':'Seriale','rpr':'Problema',
    'err':'Compila tutti i campi obbligatori (*)','err2':'Compila i campi obbligatori (*)',
    'eml':'Conferma inviata a: '
  },
  en:{
    'title':'TECHNICAL<br><em>ASSISTANCE</em>',
    'sub':'Rotondi Group Roma — Read the conditions before proceeding',
    'ctitle':'Service information',
    'c1':'Technical assistance is a <b>paid service</b>, even if the product is <b>under warranty</b>.',
    'c2':'Under warranty only <b>defective spare parts</b> are replaced at no cost.',
    'c3':'<b>Always charged to customer:</b> Labour · Technician travel · Call-out fee',
    'z1':'ROME AREA RATES (Inside the Grande Raccordo Anulare ring road)','z2':'ROME PROVINCE, LAZIO AND REST OF ITALY',
    'r1l':'Call-out + 1h work','r2l':'Additional hours','r3l':'Travel km','r4l':'Travel hours','r5l':'Work hours',
    'frl':'Our technicians are <b>independent freelance professionals</b> selected by Rotondi Group. They are not company employees.',
    'acc':'✓ I Accept','dec':'✗ Decline',
    'bk':'← Back',
    'f1h':'Personal details','f1p':'Enter your contact information','f1s':'Step 1 of 3',
    'ln':'Full name *','li':'Full address *','lt':'Phone *','le':'Email *',
    'hi':'Street, number and city','he':'To receive confirmation',
    'f1n':'Continue →',
    'f2h':'Machine details','f2p':'Information about the machine','f2s':'Step 2 of 3',
    'lma':'Brand *','lmo':'Model','lse':'Serial number','lpr':'Describe the problem *',
    'f2n':'Continue →',
    'f3h':'Summary','f3p':'Check your details before sending','f3s':'Step 3 of 3',
    'send':'Sending...','sub':'📤 Send request',
    'sh':'Request sent!','sp':'Your request has been received. A Rotondi Group technician will contact you shortly.',
    'pl':'Protocol number','nr':'New request',
    'dh':'Service not accepted','dp':'You chose not to proceed. You can come back at any time.','dr':'Back to start',
    'rn':'Name','ri':'Address','rt':'Phone','re':'Email','rma':'Brand','rmo':'Model','rse':'Serial','rpr':'Problem',
    'err':'Fill all required fields (*)','err2':'Fill required fields (*)',
    'eml':'Confirmation sent to: '
  },
  bn:{
    'title':'প্রযুক্তিগত<br><em>সহায়তা</em>',
    'sub':'রোটোন্ডি গ্রুপ রোমা — এগিয়ে যাওয়ার আগে শর্তাবলী পড়ুন',
    'ctitle':'সেবার তথ্য',
    'c1':'প্রযুক্তিগত সহায়তা একটি <b>পেইড সার্ভিস</b>, এমনকি পণ্যটি <b>ওয়ারেন্টিতে</b> থাকলেও।',
    'c2':'ওয়ারেন্টিতে শুধু <b>ত্রুটিপূর্ণ যন্ত্রাংশ</b> বিনামূল্যে প্রতিস্থাপন করা হয়।',
    'c3':'<b>সর্বদা গ্রাহকের খরচ:</b> শ্রম · যাতায়াত · কল চার্জ',
    'z1':'রোমা শহরের তারিফ (গ্র্যান্ড রাকোর্দো আনুলারে রিং রোডের ভেতরে)','z2':'রোমা প্রদেশ, লাজিও এবং ইতালির বাকি অংশ',
    'r1l':'আসা + ১ ঘণ্টা','r2l':'অতিরিক্ত ঘণ্টা','r3l':'যাতায়াত কিমি','r4l':'ভ্রমণ সময়','r5l':'কাজের সময়',
    'frl':'আমাদের টেকনিশিয়ানরা <b>স্বাধীন ফ্রিল্যান্স পেশাদার</b>, রোটোন্ডি গ্রুপ কর্তৃক নির্বাচিত।',
    'acc':'✓ গ্রহণ করি','dec':'✗ প্রত্যাখ্যান',
    'bk':'← ফিরে যান',
    'f1h':'ব্যক্তিগত তথ্য','f1p':'আপনার যোগাযোগের তথ্য দিন','f1s':'ধাপ ১ এর ৩',
    'ln':'নাম এবং পদবি *','li':'সম্পূর্ণ ঠিকানা *','lt':'ফোন *','le':'ইমেইল *',
    'hi':'রাস্তা, নম্বর এবং শহর','he':'নিশ্চিতকরণ পেতে',
    'f1n':'পরবর্তী →',
    'f2h':'মেশিনের তথ্য','f2p':'মেশিন সম্পর্কে তথ্য','f2s':'ধাপ ২ এর ৩',
    'lma':'ব্র্যান্ড *','lmo':'মডেল','lse':'সিরিয়াল নম্বর','lpr':'সমস্যা বর্ণনা করুন *',
    'f2n':'পরবর্তী →',
    'f3h':'সারসংক্ষেপ','f3p':'পাঠানোর আগে তথ্য যাচাই করুন','f3s':'ধাপ ৩ এর ৩',
    'send':'পাঠানো হচ্ছে...','sub':'📤 অনুরোধ পাঠান',
    'sh':'অনুরোধ পাঠানো হয়েছে!','sp':'আপনার অনুরোধ পাওয়া গেছে। শীঘ্রই একজন টেকনিশিয়ান যোগাযোগ করবেন।',
    'pl':'প্রোটোকল নম্বর','nr':'নতুন অনুরোধ',
    'dh':'সেবা গ্রহণ করা হয়নি','dp':'আপনি এগিয়ে না যাওয়ার সিদ্ধান্ত নিয়েছেন।','dr':'শুরুতে ফিরুন',
    'rn':'নাম','ri':'ঠিকানা','rt':'ফোন','re':'ইমেইল','rma':'ব্র্যান্ড','rmo':'মডেল','rse':'সিরিয়াল','rpr':'সমস্যা',
    'err':'সব বাধ্যতামূলক ক্ষেত্র পূরণ করুন (*)','err2':'বাধ্যতামূলক ক্ষেত্র পূরণ করুন (*)',
    'eml':'নিশ্চিতকরণ পাঠানো হয়েছে: '
  },
  zh:{
    'title':'技术<br><em>援助</em>',
    'sub':'罗通迪集团罗马 — 继续前请阅读条款',
    'ctitle':'服务信息',
    'c1':'技术援助是<b>付费服务</b>，即使产品<b>在保修期内</b>也是如此。',
    'c2':'保修期内仅免费更换<b>有缺陷的零件</b>。',
    'c3':'<b>始终由客户承担：</b>人工费 · 差旅费 · 上门费',
    'z1':'罗马市区收费标准（大环城公路GRA以内）','z2':'罗马省、拉齐奥大区及意大利其他地区',
    'r1l':'上门费+1小时','r2l':'额外每小时','r3l':'差旅公里','r4l':'路途时间','r5l':'工作时间',
    'frl':'我们的技术人员是<b>独立自由职业者</b>，由罗通迪集团选派，非公司雇员。',
    'acc':'✓ 我接受','dec':'✗ 拒绝',
    'bk':'← 返回',
    'f1h':'个人信息','f1p':'输入您的联系信息','f1s':'第1步，共3步',
    'ln':'姓名 *','li':'完整地址 *','lt':'电话 *','le':'电子邮件 *',
    'hi':'街道、门牌号和城市','he':'用于接收确认',
    'f1n':'继续 →',
    'f2h':'机器信息','f2p':'关于机器的信息','f2s':'第2步，共3步',
    'lma':'品牌 *','lmo':'型号','lse':'序列号','lpr':'描述问题 *',
    'f2n':'继续 →',
    'f3h':'摘要','f3p':'发送前检查您的信息','f3s':'第3步，共3步',
    'send':'发送中...','sub':'📤 发送请求',
    'sh':'请求已发送！','sp':'您的请求已收到。罗通迪集团技术人员将很快与您联系。',
    'pl':'协议编号','nr':'新请求',
    'dh':'未接受服务','dp':'您选择不继续。随时可以返回。','dr':'返回开始',
    'rn':'姓名','ri':'地址','rt':'电话','re':'电子邮件','rma':'品牌','rmo':'型号','rse':'序列号','rpr':'问题',
    'err':'请填写所有必填字段 (*)','err2':'请填写必填字段 (*)',
    'eml':'确认已发送至: '
  },
  ar:{
    'title':'المساعدة<br><em>التقنية</em>',
    'sub':'روتوندي جروب روما — اقرأ الشروط قبل المتابعة',
    'ctitle':'معلومات الخدمة',
    'c1':'المساعدة التقنية <b>خدمة مدفوعة</b>، حتى لو كان المنتج <b>تحت الضمان</b>.',
    'c2':'الضمان يشمل فقط استبدال <b>قطع الغيار المعيبة</b> مجاناً.',
    'c3':'<b>دائماً على حساب العميل:</b> أجرة العمل · التنقل · رسوم الزيارة',
    'z1':'تعريفات منطقة روما (داخل الطريق الدائري الكبير GRA)','z2':'محافظة روما، منطقة لاتسيو وبقية إيطاليا',
    'r1l':'زيارة + ساعة عمل','r2l':'ساعات إضافية','r3l':'كيلومترات التنقل','r4l':'ساعات السفر','r5l':'ساعات العمل',
    'frl':'فنيونا <b>محترفون مستقلون فريلانس</b>، من اختيار روتوندي جروب، وليسوا موظفين في الشركة.',
    'acc':'✓ أقبل الشروط','dec':'✗ أرفض',
    'bk':'→ رجوع',
    'f1h':'البيانات الشخصية','f1p':'أدخل معلومات الاتصال','f1s':'الخطوة 1 من 3',
    'ln':'الاسم الكامل *','li':'العنوان الكامل *','lt':'الهاتف *','le':'البريد الإلكتروني *',
    'hi':'الشارع والرقم والمدينة','he':'لاستلام التأكيد',
    'f1n':'→ متابعة',
    'f2h':'بيانات الجهاز','f2p':'معلومات عن الجهاز','f2s':'الخطوة 2 من 3',
    'lma':'الماركة *','lmo':'الموديل','lse':'الرقم التسلسلي','lpr':'صف المشكلة *',
    'f2n':'→ متابعة',
    'f3h':'الملخص','f3p':'تحقق من بياناتك قبل الإرسال','f3s':'الخطوة 3 من 3',
    'send':'جارٍ الإرسال...','sub':'📤 إرسال الطلب',
    'sh':'تم إرسال الطلب!','sp':'تم استلام طلبك. سيتصل بك فني روتوندي جروب قريباً.',
    'pl':'رقم البروتوكول','nr':'طلب جديد',
    'dh':'لم تُقبل الخدمة','dp':'اخترت عدم المتابعة. يمكنك العودة في أي وقت.','dr':'العودة إلى البداية',
    'rn':'الاسم','ri':'العنوان','rt':'الهاتف','re':'البريد','rma':'الماركة','rmo':'الموديل','rse':'التسلسلي','rpr':'المشكلة',
    'err':'يرجى ملء جميع الحقول المطلوبة (*)','err2':'يرجى ملء الحقول المطلوبة (*)',
    'eml':'تم إرسال التأكيد إلى: '
  }
};

// Map translation keys to element IDs
var MAP={
  'title':'t-title','sub':'t-sub','ctitle':'t-ctitle',
  'c1':'t-c1','c2':'t-c2','c3':'t-c3',
  'z1':'t-z1','z2':'t-z2',
  'r1l':'t-r1l','r2l':'t-r2l','r3l':'t-r3l','r4l':'t-r4l','r5l':'t-r5l',
  'frl':'t-frl','acc':'t-acc','dec':'t-dec',
  'bk':'t-bk','bk2':'t-bk2','bk3':'t-bk3',
  'f1h':'t-f1h','f1p':'t-f1p','f1s':'t-f1s',
  'ln':'t-ln','li':'t-li','lt':'t-lt','le':'t-le','hi':'t-hi','he':'t-he','f1n':'t-f1n',
  'f2h':'t-f2h','f2p':'t-f2p','f2s':'t-f2s',
  'lma':'t-lma','lmo':'t-lmo','lse':'t-lse','lpr':'t-lpr','f2n':'t-f2n',
  'f3h':'t-f3h','f3p':'t-f3p','f3s':'t-f3s',
  'send':'t-send','sub':'t-sub',
  'sh':'t-sh','sp':'t-sp','pl':'t-pl','nr':'t-nr',
  'dh':'t-dh','dp':'t-dp','dr':'t-dr'
};

function setL(l,btn){
  lang=l;
  document.querySelectorAll('.lb').forEach(function(b){b.classList.remove('on')});
  btn.classList.add('on');
  applyL();
}

function applyL(){
  var t=TX[lang];
  for(var k in MAP){
    var el=document.getElementById(MAP[k]);
    if(el && t[k]!==undefined) el.innerHTML=t[k];
  }
  document.body.dir=lang==='ar'?'rtl':'ltr';
}

function go(n){
  document.getElementById('s'+cur).classList.remove('on');
  document.getElementById('s'+n).classList.add('on');
  cur=n;
  var sb=document.getElementById('stepbar');
  if(n>=1&&n<=3){sb.style.display='flex';}else{sb.style.display='none';}
  for(var i=1;i<=4;i++){
    var d=document.getElementById('d'+i);
    d.className='sdot';
    if(i<n)d.classList.add('done');
    else if(i===n)d.classList.add('on');
  }
  for(var i=1;i<=3;i++){
    var l=document.getElementById('l'+i);
    l.className='sline';
    if(i<n)l.classList.add('done');
  }
  window.scrollTo(0,0);
}

function step1(){
  var n=document.getElementById('v-nome').value.trim();
  var i=document.getElementById('v-ind').value.trim();
  var t=document.getElementById('v-tel').value.trim();
  var e=document.getElementById('v-email').value.trim();
  if(!n||!i||!t||!e){alert(TX[lang].err||'Compila tutti i campi *');return;}
  go(2);
}

function step2(){
  var m=document.getElementById('v-marca').value.trim();
  var p=document.getElementById('v-problema').value.trim();
  if(!m||!p){alert(TX[lang].err2||'Compila i campi obbligatori *');return;}
  buildR();go(3);
}

function buildR(){
  var t=TX[lang];
  var rows=[
    [t.rn,document.getElementById('v-nome').value],
    [t.ri,document.getElementById('v-ind').value],
    [t.rt,document.getElementById('v-tel').value],
    [t.re,document.getElementById('v-email').value],
    [t.rma,document.getElementById('v-marca').value],
    [t.rmo,document.getElementById('v-modello').value],
    [t.rse,document.getElementById('v-seriale').value],
    [t.rpr,document.getElementById('v-problema').value]
  ];
  var h='';
  rows.forEach(function(r){if(r[1])h+='<div class="rrow"><div class="rlbl">'+r[0]+'</div><div class="rval">'+r[1]+'</div></div>';});
  document.getElementById('rcard').innerHTML=h;
}

function submit(){
  var btn=document.getElementById('t-sub');
  var ldr=document.getElementById('ldr');
  btn.style.display='none';ldr.style.display='block';
  var d={
    lingua:lang,
    nome:document.getElementById('v-nome').value,
    indirizzo:document.getElementById('v-ind').value,
    telefono:document.getElementById('v-tel').value,
    email:document.getElementById('v-email').value,
    marca:document.getElementById('v-marca').value,
    modello:document.getElementById('v-modello').value,
    seriale:document.getElementById('v-seriale').value,
    problema:document.getElementById('v-problema').value
  };
  fetch('/api/richiesta',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)})
  .then(function(r){return r.json();})
  .then(function(res){
    ldr.style.display='none';
    if(res.ok){
      document.getElementById('t-pc').textContent=res.protocollo;
      var em=document.getElementById('t-em');
      if(res.email_sent)em.textContent=(TX[lang].eml||'Email: ')+d.email;
      go(4);
    }else{btn.style.display='block';alert('Errore: '+(res.error||'Riprova'));}
  })
  .catch(function(){ldr.style.display='none';btn.style.display='block';alert('Errore connessione. Riprova.');});
}

function restart(){
  ['v-nome','v-ind','v-tel','v-email','v-marca','v-modello','v-seriale','v-problema']
  .forEach(function(id){document.getElementById(id).value='';});
  go(0);
}

applyL();
</script>
</body>
</html>"""

@app.route('/')
def index():
    return HTML

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
    now      = datetime.now().strftime("%d/%m/%Y %H:%M")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""INSERT INTO richieste_web
            (protocollo,nome,indirizzo,telefono,email,marca,modello,seriale,problema,lingua,data)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (protocollo,nome,ind,tel,email,marca,modello,seriale,problema,lingua,now))
        conn.commit()

    FLAGS = {'it':'🇮🇹','en':'🇬🇧','bn':'🇧🇩','zh':'🇨🇳','ar':'🇸🇦'}
    flag = FLAGS.get(lingua, '🌍')
    maps = f"https://www.google.com/maps/search/?api=1&query={ind.replace(' ','+')},+Roma,+Italia"

    keyboard = {"inline_keyboard": [[
        {"text":"🕛 Entro le 12:00","callback_data":f"wfascia_{protocollo}_entro12"},
        {"text":"🕕 Entro le 18:00","callback_data":f"wfascia_{protocollo}_entro18"},
    ],[
        {"text":"📅 In giornata","callback_data":f"wfascia_{protocollo}_giornata"},
        {"text":"📆 Entro domani","callback_data":f"wfascia_{protocollo}_domani"},
    ],[
        {"text":"🗓 Da programmare","callback_data":f"wfascia_{protocollo}_programma"},
    ]]}

    testo = (
        f"🌐 *RICHIESTA WEB #{protocollo}* {flag}\n{'─'*28}\n"
        f"👤 *Cliente:* {nome}\n"
        f"📍 *Indirizzo:* {ind}\n"
        f"🗺 [Google Maps]({maps})\n"
        f"📞 *Tel:* {tel}\n"
        f"📧 *Email:* {email}\n"
        f"🏭 *Marca:* {marca} · *Modello:* {modello or '—'}\n"
        f"🔢 *Seriale:* {seriale or '—'}\n"
        f"🔧 *Problema:* {problema}\n"
        f"{'─'*28}\n"
        f"⏰ Primo tecnico disponibile — clicca:"
    )
    invia_telegram(testo, keyboard)
    invia_telegram_bo(
        f"🌐 *Nuova richiesta WEB* {flag}\n"
        f"🔖 `{protocollo}`\n👤 {nome}\n📍 {ind}\n📞 {tel}\n📧 {email}\n"
        f"🏭 {marca} {modello}\n🔧 {problema}"
    )

    # Email confirmation
    subjects = {
        'it': f'Rotondi Group Roma — Richiesta #{protocollo}',
        'en': f'Rotondi Group Roma — Request #{protocollo}',
        'bn': f'রোটোন্ডি গ্রুপ রোমা — #{protocollo}',
        'zh': f'罗通迪集团罗马 — #{protocollo}',
        'ar': f'روتوندي جروب روما — #{protocollo}'
    }
    body = f"""<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
  <h1 style="color:#fff;font-size:22px;margin:0;font-family:Georgia,serif">ROTONDI GROUP ROMA</h1>
  <p style="color:#c9a84c;margin:4px 0 0;font-size:13px">ASSISTENZA TECNICA</p>
</div>
<div style="background:#fff;padding:24px;border-radius:0 0 8px 8px">
  <h2 style="color:#0d0d14;font-size:18px">✅ Richiesta ricevuta!</h2>
  <p>Gentile <b>{nome}</b>, la sua richiesta è stata ricevuta.</p>
  <div style="background:#f5f5f5;border-radius:8px;padding:16px;margin:16px 0;text-align:center">
    <p style="font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px;margin:0 0 6px">Numero protocollo</p>
    <p style="font-size:28px;font-weight:700;color:#0d0d14;letter-spacing:4px;margin:0;font-family:Georgia,serif">{protocollo}</p>
  </div>
  <p><b>Problema:</b> {problema}</p>
  <hr style="border:none;border-top:1px solid #eee;margin:16px 0">
  <p style="color:#666;font-size:13px">Annullamenti urgenti: <b>+39 06 41 40 0514</b></p>
  <p style="color:#666;font-size:13px">Ufficio Roma: <b>+39 06 41400617</b></p>
</div></div>"""

    email_sent = invia_email(email, subjects.get(lingua, subjects['it']), body)
    return jsonify({"ok": True, "protocollo": protocollo, "email_sent": email_sent})

@app.route('/api/stato/<protocollo>')
def stato(protocollo):
    with sqlite3.connect(DB_PATH) as conn:
        r = conn.execute("SELECT protocollo,nome,stato,data FROM richieste_web WHERE protocollo=?",
                        (protocollo,)).fetchone()
    if not r: return jsonify({"ok": False, "error": "Not found"})
    return jsonify({"ok": True, "protocollo": r[0], "nome": r[1], "stato": r[2], "data": r[3]})

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
