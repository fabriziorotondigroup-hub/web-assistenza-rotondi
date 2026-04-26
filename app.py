#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WEB APP - Assistenza Tecnica Macchinari
Rotondi Group Roma
"""

import os, sqlite3, uuid, math, smtplib, json
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string, session, redirect
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "rotondi-secret-2024")

DB_PATH     = "web_assistenza.db"
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
TECNICI_GID = os.environ.get("TECNICI_GROUP_ID", "-1001234567890")
GMAPS_KEY   = os.environ.get("GMAPS_KEY", "")
SEDE        = "Via di Sant'Alessandro 349, Roma, Italia"
BASE_URL    = os.environ.get("BASE_URL", "https://web-production-51bc9.up.railway.app")
SMTP_U      = os.environ.get("SMTP_USER","")
SMTP_P      = os.environ.get("SMTP_PASS","")
SMTP_F      = os.environ.get("SMTP_FROM","")
SMTP_H      = os.environ.get("SMTP_HOST","smtp.gmail.com")
SMTP_PO     = int(os.environ.get("SMTP_PORT","587"))

TARIFFE_DEFAULT = {
    "dentro_uscita":    80.0,
    "dentro_ora_extra": 40.0,
    "fuori_km":          0.70,
    "fuori_ora_viaggio": 32.0,
    "fuori_ora_lavoro":  40.0,
}

CONDIZIONI_IT_DEFAULT = (
    "L'assistenza tecnica e' un servizio a pagamento, anche se il prodotto e' in garanzia.\n\n"
    "In garanzia: parti difettose sostituite senza costo\n\n"
    "Sempre a carico del cliente:\n"
    "- Manodopera\n- Spostamento tecnico\n- Costo chiamata\n\n"
    "ZONA DI ROMA (dentro il GRA)\n"
    "- Uscita + 1h lavoro: EUR 80,00 + IVA\n"
    "- Ore successive: EUR 40,00/h + IVA\n\n"
    "FUORI ROMA (Provincia, Lazio, resto d'Italia)\n"
    "- Km trasferta: EUR 0,70/km + IVA (A/R)\n"
    "- Ore viaggio: EUR 32,00/h + IVA (A/R)\n"
    "- Ore lavoro: EUR 40,00/h + IVA\n\n"
    "Pagamento direttamente al tecnico al termine del servizio."
)

CONDIZIONI_EN_DEFAULT = (
    "Technical assistance is a paid service, even under warranty.\n\n"
    "Under warranty: defective parts replaced at no cost\n\n"
    "Always charged to customer:\n"
    "- Labour\n- Technician travel\n- Call-out fee\n\n"
    "ROME AREA (inside GRA)\n"
    "- Call-out + 1h work: EUR 80.00 + VAT\n"
    "- Additional hours: EUR 40.00/h + VAT\n\n"
    "OUTSIDE ROME\n"
    "- Travel km: EUR 0.70/km + VAT (return)\n"
    "- Travel hours: EUR 32.00/h + VAT (return)\n"
    "- Work hours: EUR 40.00/h + VAT\n\n"
    "Payment directly to the technician at end of service."
)


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS richieste_web (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                protocollo TEXT UNIQUE, nome TEXT,
                via TEXT, civico TEXT, cap TEXT, citta TEXT, provincia TEXT,
                indirizzo TEXT, telefono TEXT, email TEXT,
                marca TEXT, modello TEXT, seriale TEXT, problema TEXT,
                stato TEXT DEFAULT 'aperta', tecnico TEXT, fascia TEXT,
                data TEXT, lingua TEXT DEFAULT 'it', preventivo TEXT
            )
        """)
        for col in ["via TEXT","civico TEXT","cap TEXT","citta TEXT","provincia TEXT",
                    "seriale TEXT","email TEXT","preventivo TEXT"]:
            try: conn.execute(f"ALTER TABLE richieste_web ADD COLUMN {col}")
            except: pass
        conn.execute("CREATE TABLE IF NOT EXISTS config (chiave TEXT PRIMARY KEY, valore TEXT)")
        for k,v in TARIFFE_DEFAULT.items():
            conn.execute("INSERT OR IGNORE INTO config VALUES (?,?)", (f"tariffa_{k}", str(v)))
        conn.execute("INSERT OR IGNORE INTO config VALUES ('condizioni_it',?)", (CONDIZIONI_IT_DEFAULT,))
        conn.execute("INSERT OR IGNORE INTO config VALUES ('condizioni_en',?)", (CONDIZIONI_EN_DEFAULT,))
        conn.execute("INSERT OR IGNORE INTO config VALUES ('admin_pass',?)",
                     (os.environ.get("ADMIN_PASSWORD","rotondi2024"),))
        conn.commit()


def get_config(k, default=None):
    with sqlite3.connect(DB_PATH) as conn:
        r = conn.execute("SELECT valore FROM config WHERE chiave=?", (k,)).fetchone()
    return r[0] if r else default

def set_config(k, v):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR REPLACE INTO config VALUES (?,?)", (k, str(v)))
        conn.commit()

def get_tariffe():
    return {k: float(get_config(f"tariffa_{k}", v)) for k,v in TARIFFE_DEFAULT.items()}


def calcola_preventivo(indirizzo_cliente):
    try:
        import requests as rq
        tar = get_tariffe()
        r = rq.get("https://maps.googleapis.com/maps/api/distancematrix/json",
                   params={"origins":SEDE,"destinations":indirizzo_cliente,
                           "mode":"driving","key":GMAPS_KEY,"language":"it"}, timeout=10)
        data = r.json()
        if data.get("status") != "OK": return None
        el = data["rows"][0]["elements"][0]
        if el.get("status") != "OK": return None
        dist_km = el["distance"]["value"] / 1000
        dur_h   = el["duration"]["value"] / 3600
        if dist_km < 10:
            return {"zona":"inside_gra","costo_min":tar["dentro_uscita"],
                    "dist_label":el["distance"]["text"],"dur_label":el["duration"]["text"]}
        dist_ar=dist_km*2; dur_ar=math.ceil(dur_h*2)
        ck=dist_ar*tar["fuori_km"]; cv=dur_ar*tar["fuori_ora_viaggio"]; cl=tar["fuori_ora_lavoro"]
        return {"zona":"outside_gra","costo_min":round(ck+cv+cl,2),
                "dist_label":el["distance"]["text"],"dur_label":el["duration"]["text"],
                "dettaglio":{"km_ar":f"{dist_ar:.0f}","costo_km":f"{ck:.2f}",
                             "ore_viaggio":dur_ar,"costo_viaggio":f"{cv:.2f}",
                             "costo_lavoro":f"{cl:.2f}"}}
    except Exception as e:
        app.logger.error(f"Maps: {e}"); return None


def tg_send(testo, keyboard=None):
    try:
        import requests as rq
        p = {"chat_id":TECNICI_GID,"text":testo,"parse_mode":"Markdown"}
        if keyboard: p["reply_markup"] = json.dumps(keyboard)
        rq.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=p, timeout=10)
    except Exception as e: app.logger.error(f"TG: {e}")

def tg_photo(foto, caption):
    try:
        import requests as rq
        rq.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id":TECNICI_GID,"caption":caption},
                files={"photo":(foto.filename,foto.read(),foto.content_type)}, timeout=20)
    except Exception as e: app.logger.error(f"TG foto: {e}")

def bo_notify(testo):
    if not BOT_TOKEN: return
    ids = [x.strip() for x in os.environ.get("BACKOFFICE_IDS","").split(",") if x.strip()]
    try:
        import requests as rq
        for i in ids:
            rq.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id":i,"text":testo,"parse_mode":"Markdown"}, timeout=10)
    except Exception as e: app.logger.error(f"BO: {e}")


def send_email(to, subject, html):
    if not (to and SMTP_U and SMTP_P): return
    try:
        m = MIMEMultipart("alternative")
        m["Subject"]=subject; m["From"]=SMTP_F; m["To"]=to
        m.attach(MIMEText(html,"html"))
        with smtplib.SMTP(SMTP_H,SMTP_PO) as s:
            s.starttls(); s.login(SMTP_U,SMTP_P); s.sendmail(SMTP_F,to,m.as_string())
    except Exception as e: app.logger.error(f"Email: {e}")

def email_ricezione(email, nome, proto, lingua):
    s = {"it":f"Rotondi Group Roma - Richiesta ricevuta #{proto}",
         "en":f"Rotondi Group Roma - Request received #{proto}"}.get(lingua,f"#{proto}")
    h = f"""<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
<h1 style="color:#fff;font-size:22px;margin:0">ROTONDI GROUP ROMA</h1>
<p style="color:#aaa;font-size:13px;margin:4px 0 0">Assistenza Tecnica Macchinari</p></div>
<div style="background:#fff;padding:32px;border-radius:0 0 8px 8px">
<h2 style="color:#0d0d14">Richiesta ricevuta!</h2>
<p>Gentile <b>{nome}</b>, la sua richiesta e' stata ricevuta.</p>
<div style="background:#f8f8f8;border-radius:8px;padding:16px;margin:20px 0;border-left:4px solid #0d0d14">
<p style="color:#666;font-size:13px;margin:0 0 4px">Numero protocollo</p>
<p style="font-size:24px;font-weight:bold;color:#0d0d14;margin:0">{proto}</p></div>
<p>A breve ricevera' una email con la proposta di appuntamento.</p>
<div style="background:#fff3cd;border-radius:8px;padding:12px;margin-top:16px">
<p style="margin:0;font-size:13px">Per annullare urgentemente: <b>+39 06 41 40 0514</b></p></div>
<p style="color:#666;font-size:13px;margin-top:20px">Ufficio Roma: +39 06 41400617</p>
</div></div>"""
    send_email(email, s, h)

def email_proposta(email, nome, proto, tecnico, data_ora, lingua):
    link_si = f"{BASE_URL}/proposta/{proto}/accetta"
    link_no = f"{BASE_URL}/proposta/{proto}/rifiuta"
    s = {"it":f"Rotondi Group Roma - Proposta appuntamento #{proto}",
         "en":f"Rotondi Group Roma - Appointment proposal #{proto}"}.get(lingua,f"#{proto}")
    btn_si = "Accetto" if lingua=="it" else "Accept"
    btn_no = "Rifiuto" if lingua=="it" else "Decline"
    titolo = "Proposta di Appuntamento" if lingua=="it" else "Appointment Proposal"
    intro  = (f"Il tecnico <b>{tecnico}</b> e' disponibile il:" if lingua=="it"
              else f"Technician <b>{tecnico}</b> is available on:")
    avviso = ("Rispondere entro 24 ore. Se non risponde la richiesta tornera' ad altri tecnici."
              if lingua=="it" else "Please respond within 24 hours.")
    h = f"""<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
<h1 style="color:#fff;font-size:22px;margin:0">ROTONDI GROUP ROMA</h1>
<p style="color:#aaa;font-size:13px;margin:4px 0 0">Assistenza Tecnica Macchinari</p></div>
<div style="background:#fff;padding:32px;border-radius:0 0 8px 8px">
<h2 style="color:#0d0d14">{titolo}</h2>
<p>Gentile <b>{nome}</b>,</p><p>{intro}</p>
<div style="background:#f0f8ff;border-radius:10px;padding:20px;margin:20px 0;
text-align:center;border:2px solid #0d0d14">
<p style="font-size:13px;color:#666;margin:0 0 8px">Data e ora proposta</p>
<p style="font-size:28px;font-weight:bold;color:#0d0d14;margin:0">{data_ora}</p></div>
<p style="font-size:13px;color:#666;margin-bottom:6px"><b>Protocollo:</b> {proto}</p>
<p style="color:#888;font-size:13px;margin:12px 0">{avviso}</p>
<table style="width:100%;border-collapse:collapse;margin:24px 0"><tr>
<td style="padding:8px;text-align:center">
<a href="{link_si}" style="background:#4caf50;color:#fff;padding:18px 40px;
border-radius:10px;text-decoration:none;font-size:20px;font-weight:700;
display:inline-block">&#9989; {btn_si}</a></td>
<td style="padding:8px;text-align:center">
<a href="{link_no}" style="background:#e53935;color:#fff;padding:18px 40px;
border-radius:10px;text-decoration:none;font-size:20px;font-weight:700;
display:inline-block">&#10060; {btn_no}</a></td></tr></table>
<p style="font-size:11px;color:#bbb;text-align:center">
Se i pulsanti non funzionano:<br>Accetta: {link_si}<br>Rifiuta: {link_no}</p>
<div style="background:#fff3cd;border-radius:8px;padding:12px;margin-top:20px">
<p style="margin:0;font-size:13px">Ufficio Roma: <b>+39 06 41400617</b> —
Annullare: <b>+39 06 41 40 0514</b></p></div>
</div></div>"""
    send_email(email, s, h)

def email_esito(email, nome, proto, tecnico, data_ora, lingua, ok):
    if ok:
        s = {"it":f"Rotondi Group Roma - Appuntamento confermato #{proto}",
             "en":f"Rotondi Group Roma - Appointment confirmed #{proto}"}.get(lingua,f"#{proto}")
        h = f"""<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
<h1 style="color:#fff;font-size:22px;margin:0">ROTONDI GROUP ROMA</h1></div>
<div style="background:#fff;padding:32px;border-radius:0 0 8px 8px;text-align:center">
<div style="font-size:56px;margin-bottom:12px">&#127881;</div>
<h2 style="color:#4caf50">Appuntamento Confermato!</h2>
<p style="margin:16px 0">Gentile <b>{nome}</b>,</p>
<div style="background:#f0fff4;border-radius:10px;padding:20px;margin:20px 0;border:2px solid #4caf50">
<p style="font-size:13px;color:#666;margin:0 0 8px">Data e ora intervento</p>
<p style="font-size:26px;font-weight:bold;color:#2e7d32;margin:0">{data_ora}</p>
<p style="color:#444;margin:8px 0 0">Tecnico: <b>{tecnico}</b></p></div>
<div style="background:#fff3cd;border-radius:8px;padding:12px">
<p style="margin:0;font-size:13px">Ufficio Roma: <b>+39 06 41400617</b><br>
Annullare: <b>+39 06 41 40 0514</b></p></div></div></div>"""
    else:
        s = {"it":f"Rotondi Group Roma - Proposta rifiutata #{proto}",
             "en":f"Rotondi Group Roma - Proposal declined #{proto}"}.get(lingua,f"#{proto}")
        h = f"""<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
<h1 style="color:#fff;font-size:22px;margin:0">ROTONDI GROUP ROMA</h1></div>
<div style="background:#fff;padding:32px;border-radius:0 0 8px 8px">
<h2 style="color:#0d0d14">Proposta rifiutata</h2>
<p>Gentile <b>{nome}</b>, la Sua richiesta e' ancora aperta.
Un altro tecnico la contatterà a breve.</p>
<div style="background:#fff3cd;border-radius:8px;padding:12px;margin-top:16px">
<p style="margin:0;font-size:13px">Per info: <b>+39 06 41400617</b></p>
</div></div></div>"""
    send_email(email, s, h)


def pagina(tipo, proto, tecnico="", data_ora="", lingua="it"):
    cfg = {
        "accettata":     ("#4caf50","&#127881;","Appuntamento Confermato!",
                          f"Il tecnico <b>{tecnico}</b> interverr&agrave; il:<br><br>"
                          f"<b style='font-size:22px;color:#2e7d32'>{data_ora}</b><br><br>"
                          f"Ufficio Roma: <b>+39 06 41400617</b><br>"
                          f"Annullare: <b>+39 06 41 40 0514</b>"),
        "rifiutata":     ("#ff9800","&#8617;&#65039;","Proposta Rifiutata",
                          "La Sua richiesta &egrave; ancora aperta.<br><br>"
                          "Un altro tecnico la contatter&agrave; a breve.<br><br>"
                          "Per info: <b>+39 06 41400617</b>"),
        "gia_confermata":("#4caf50","&#9989;","Gi&agrave; Confermato",
                          f"Appuntamento gi&agrave; confermato.<br>"
                          f"Data: <b>{data_ora}</b><br>Tecnico: <b>{tecnico}</b>"),
        "gia_rifiutata": ("#888","&#8505;&#65039;","Gi&agrave; Elaborata",
                          "Questa proposta &egrave; gi&agrave; stata elaborata."),
        "non_trovata":   ("#e53935","&#9888;&#65039;","Non trovata",
                          f"Protocollo <b>{proto}</b> non trovato."),
        "non_valida":    ("#e53935","&#9888;&#65039;","Link non valido",
                          "Questo link non &egrave; pi&ugrave; valido."),
        "errore":        ("#e53935","&#10060;","Errore",
                          "Contatta l'ufficio: +39 06 41400617"),
    }
    c=cfg.get(tipo,cfg["errore"]); col,ico,tit,txt=c
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rotondi Group Roma</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f0f0f0;min-height:100vh}}
.h{{background:#0d0d14;color:#fff;padding:18px;text-align:center}}
.h h1{{font-size:18px;letter-spacing:1px}}
.w{{display:flex;align-items:center;justify-content:center;
min-height:calc(100vh - 58px);padding:24px 16px}}
.b{{background:#fff;border-radius:16px;padding:40px 28px;max-width:460px;
width:100%;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.1)}}
.bar{{height:5px;background:{col};border-radius:3px;margin-bottom:28px}}
.ico{{font-size:54px;margin-bottom:14px}}
h2{{font-size:22px;color:{col};margin-bottom:12px}}
.proto{{font-size:12px;color:#999;background:#f5f5f5;padding:5px 14px;
border-radius:20px;display:inline-block;margin-bottom:18px}}
p{{font-size:14px;color:#444;line-height:1.8}}</style></head>
<body><div class="h"><h1>ROTONDI GROUP ROMA</h1></div>
<div class="w"><div class="b">
<div class="bar"></div><div class="ico">{ico}</div><h2>{tit}</h2>
<div class="proto">Protocollo: <strong>{proto}</strong></div>
<p>{txt}</p></div></div></body></html>"""


@app.route("/")
def index():
    ci = get_config("condizioni_it", CONDIZIONI_IT_DEFAULT)
    ce = get_config("condizioni_en", CONDIZIONI_EN_DEFAULT)
    return render_template_string(HTML_FORM,
        condizioni_it=ci,
        condizioni_it_js=json.dumps(ci),
        condizioni_en_js=json.dumps(ce))


@app.route("/calcola-preventivo", methods=["POST"])
def route_prev():
    data = request.get_json(force=True)
    ind  = (data.get("indirizzo","") or "").strip()
    if not ind: return jsonify({"error":"mancante"}), 400
    p = calcola_preventivo(ind)
    return jsonify(p) if p else jsonify({"error":"errore"}), 200


@app.route("/invia", methods=["POST"])
def route_invia():
    try:
        is_mp = request.content_type and 'multipart' in request.content_type
        d  = request.form if is_mp else request.get_json(force=True)
        ft = request.files.get('foto_targhetta') if is_mp else None
        fm = request.files.get('foto_macchina')  if is_mp else None

        proto = "RG"+datetime.now().strftime("%Y%m%d%H%M%S")+uuid.uuid4().hex[:4].upper()
        via=(d.get("via","") or "").strip()
        civ=(d.get("civico","") or "").strip()
        cap=(d.get("cap","") or "").strip()
        cit=(d.get("citta","") or "").strip()
        prv=(d.get("provincia","") or "").strip().upper()
        ind=f"{via}, {civ}, {cap} {cit} ({prv}), Italia"
        lng=d.get("lingua","it")
        pj =d.get("preventivo")

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""INSERT INTO richieste_web
                (protocollo,nome,via,civico,cap,citta,provincia,indirizzo,
                 telefono,email,marca,modello,seriale,problema,data,lingua,preventivo)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (proto,d.get("nome",""),via,civ,cap,cit,prv,ind,
                 d.get("telefono",""),d.get("email",""),
                 d.get("marca",""),d.get("modello",""),
                 d.get("seriale",""),d.get("problema",""),
                 datetime.now().strftime("%d/%m/%Y %H:%M"),lng,pj))
            conn.commit()

        pt=""
        if pj:
            try:
                pv=json.loads(pj)
                if pv.get("zona")=="outside_gra":
                    pt=(f"\n💰 *Preventivo:* EUR {pv['costo_min']:.2f} + IVA"
                        f" ({pv.get('dist_label','')} — {pv.get('dur_label','')})")
                else:
                    pt=f"\n💰 *Zona Roma (GRA):* EUR {pv.get('costo_min',80):.2f} + IVA"
            except: pass

        lm="https://www.google.com/maps/search/?api=1&query="+ind.replace(" ","+")
        FL={"it":"🇮🇹","en":"🇬🇧","bn":"🇧🇩","zh":"🇨🇳","ar":"🇸🇦"}.get(lng,"🌍")
        fi=""
        if ft and ft.filename: fi+="\n📸 Foto targhetta: allegata"
        if fm and fm.filename: fi+="\n📷 Foto macchina: allegata"

        tg_send(
            f"🌐 *NUOVA RICHIESTA WEB* {FL}\n{'─'*30}\n"
            f"🔖 *Protocollo:* `{proto}`\n"
            f"👤 *Cliente:* {d.get('nome','')}\n"
            f"📍 *Indirizzo:* {ind}\n"
            f"🗺 [Google Maps]({lm})\n"
            f"📞 *Tel:* {d.get('telefono','')}\n"
            f"📧 *Email:* {d.get('email','') or '—'}\n"
            f"🏷 *Marca:* {d.get('marca','')} | *Modello:* {d.get('modello','') or '—'}\n"
            f"🔢 *Seriale:* {d.get('seriale','') or '—'}\n"
            f"🔧 *Problema:* {d.get('problema','')}"
            f"{pt}{fi}\n{'─'*30}\n"
            f"⏰ Clicca per programmare l'intervento:",
            {"inline_keyboard":[[{"text":"🗓 Scegli data e ora intervento",
                                  "callback_data":f"wfascia|{proto}|start"}]]}
        )
        if ft and ft.filename: tg_photo(ft, f"📸 Targhetta — {proto}")
        if fm and fm.filename: tg_photo(fm, f"📷 Macchina — {proto}")
        email_ricezione(d.get("email",""), d.get("nome",""), proto, lng)
        return jsonify({"protocollo":proto,"ok":True})
    except Exception as e:
        app.logger.error(f"Errore /invia: {e}")
        return jsonify({"error":str(e)}), 500


@app.route("/proposta/<proto>/accetta")
def prop_accetta(proto):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            r=conn.execute(
                "SELECT nome,tecnico,fascia,email,lingua,stato FROM richieste_web WHERE protocollo=?",
                (proto,)).fetchone()
    except: return pagina("errore",proto)
    if not r: return pagina("non_trovata",proto)
    nome,tec,dt,email,lng,stato=r; lng=lng or "it"
    if stato=="assegnata":
        return pagina("gia_confermata",proto,tec,dt,lng)
    if stato!="in_attesa_conferma":
        return pagina("non_valida",proto,lingua=lng)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE richieste_web SET stato='assegnata' WHERE protocollo=?",(proto,))
        conn.commit()
    tg_send(f"✅ *RICHIESTA WEB {proto} — CONFERMATA*\n\n👤 {nome}\n👨‍🔧 {tec}\n📅 {dt}")
    bo_notify(f"✅ *Web {proto} CONFERMATA*\n👤 {nome}\n👨‍🔧 {tec}\n📅 {dt}")
    if email: email_esito(email,nome,proto,tec,dt,lng,True)
    return pagina("accettata",proto,tec,dt,lng)


@app.route("/proposta/<proto>/rifiuta")
def prop_rifiuta(proto):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            r=conn.execute(
                "SELECT nome,tecnico,fascia,email,lingua,stato FROM richieste_web WHERE protocollo=?",
                (proto,)).fetchone()
    except: return pagina("errore",proto)
    if not r: return pagina("non_trovata",proto)
    nome,tec,dt,email,lng,stato=r; lng=lng or "it"
    if stato=="aperta":
        return pagina("gia_rifiutata",proto,lingua=lng)
    if stato!="in_attesa_conferma":
        return pagina("non_valida",proto,lingua=lng)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""UPDATE richieste_web
            SET stato='aperta',tecnico=NULL,fascia=NULL WHERE protocollo=?""",(proto,))
        conn.commit()
    tg_send(
        f"❌ *RICHIESTA WEB {proto} — PROPOSTA RIFIUTATA*\n\n"
        f"👤 {nome}\nLa richiesta e' tornata disponibile!",
        {"inline_keyboard":[[{"text":"🗓 Scegli nuova data e ora",
                              "callback_data":f"wfascia|{proto}|start"}]]}
    )
    bo_notify(f"❌ *Web {proto} RIFIUTATA*\n👤 {nome}\nTornata disponibile")
    if email: email_esito(email,nome,proto,tec,dt,lng,False)
    return pagina("rifiutata",proto,lingua=lng)


@app.route("/admin", methods=["GET","POST"])
def admin():
    if request.method=="POST" and "password" in request.form:
        pwd_inserita  = request.form["password"]
        pwd_corretta  = get_config("admin_pass","rotondi2024")
        if pwd_inserita == pwd_corretta:
            session["admin"] = True
        else:
            return render_template_string(HTML_LOGIN, errore="Password errata")
    if not session.get("admin"):
        return render_template_string(HTML_LOGIN, errore="")
    msg=""
    if request.method=="POST":
        for k in TARIFFE_DEFAULT:
            v=request.form.get(f"tariffa_{k}")
            if v:
                try: set_config(f"tariffa_{k}", float(v.replace(",",".")))
                except: pass
        for lg in ["it","en"]:
            v=request.form.get(f"condizioni_{lg}")
            if v: set_config(f"condizioni_{lg}", v)
        np=request.form.get("nuova_password","").strip()
        if np: set_config("admin_pass", np)
        msg="✅ Salvato con successo!"
    tar=get_tariffe()
    ci=get_config("condizioni_it", CONDIZIONI_IT_DEFAULT)
    ce=get_config("condizioni_en", CONDIZIONI_EN_DEFAULT)
    with sqlite3.connect(DB_PATH) as conn:
        rr=conn.execute("""
            SELECT protocollo,nome,indirizzo,telefono,marca,problema,
                   stato,tecnico,fascia,data,lingua
            FROM richieste_web ORDER BY id DESC LIMIT 50""").fetchall()
    return render_template_string(HTML_ADMIN,
        tar=tar, cond_it=ci, cond_en=ce, richieste=rr, msg=msg)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin",None); return redirect("/admin")


@app.route("/admin/sblocca/<proto>")
def admin_sblocca(proto):
    if not session.get("admin"): return redirect("/admin")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""UPDATE richieste_web
            SET stato='aperta',tecnico=NULL,fascia=NULL WHERE protocollo=?""",(proto,))
        conn.commit()
    return redirect("/admin")


@app.route("/health")
def health(): return "OK", 200


HTML_FORM = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Assistenza Tecnica - Rotondi Group Roma</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#f2f2f2;min-height:100vh}
.header{background:#0d0d14;color:#fff;padding:22px 20px;text-align:center}
.header h1{font-size:24px;font-weight:700;letter-spacing:2px}
.header p{font-size:13px;color:#aaa;margin-top:5px}
.lang-bar{background:#fff;border-bottom:2px solid #eee;padding:12px 16px;
  display:flex;justify-content:center;flex-wrap:wrap;gap:8px}
.lb{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;
  border-radius:25px;border:2px solid #ddd;background:#fff;
  font-size:14px;font-weight:600;color:#555;cursor:pointer;
  transition:all .2s;font-family:inherit}
.lb:hover{border-color:#333;color:#333}
.lb.active{background:#0d0d14;border-color:#0d0d14;color:#fff}
.lb .fl{font-size:20px}
.container{max-width:640px;margin:28px auto;padding:0 16px 80px}
.steps{display:flex;justify-content:center;gap:6px;margin-bottom:28px}
.step{width:36px;height:5px;border-radius:3px;background:#ddd;transition:background .3s}
.step.active{background:#0d0d14}.step.done{background:#4caf50}
.card{background:#fff;border-radius:14px;padding:26px;margin-bottom:18px;
  box-shadow:0 2px 12px rgba(0,0,0,.08)}
.card h2{font-size:16px;font-weight:700;color:#0d0d14;margin-bottom:18px;
  padding-bottom:12px;border-bottom:3px solid #f0f0f0}
.gdpr-box{background:#f8f9fa;border-left:4px solid #0d0d14;border-radius:0 8px 8px 0;
  padding:16px;margin-bottom:16px}
.gdpr-box .co{font-size:16px;font-weight:700;color:#0d0d14;margin-bottom:6px}
.gdpr-box .ad{font-size:13px;color:#555;margin-bottom:3px}
.gdpr-box .em{font-size:13px;color:#0066cc;margin-bottom:10px}
.gdpr-box .pt p{font-size:13px;color:#333;margin-bottom:3px}
.gdpr-box .pt strong{color:#0d0d14}
.cond-box{background:#f8f9fa;border:1px solid #e0e0e0;border-radius:10px;padding:16px;
  font-size:13px;line-height:1.8;max-height:200px;overflow-y:auto;
  white-space:pre-wrap;margin-bottom:16px;color:#333}
.chk-row{display:flex;align-items:flex-start;gap:12px;padding:14px 16px;
  background:#e8f5e9;border-radius:10px;margin-bottom:8px;
  border:2px solid #c8e6c9;cursor:pointer}
.chk-row input[type=checkbox]{
  width:22px;height:22px;margin-top:2px;flex-shrink:0;cursor:pointer}
.chk-row label{font-size:14px;color:#1b5e20;font-weight:600;
  cursor:pointer;line-height:1.4}
.field{margin-bottom:16px}
.field label{display:block;font-size:12px;font-weight:700;color:#444;
  margin-bottom:6px;text-transform:uppercase;letter-spacing:0.3px}
.field input,.field textarea{width:100%;padding:12px 14px;
  border:2px solid #e0e0e0;border-radius:10px;font-size:15px;outline:none;
  transition:border .2s;font-family:inherit;color:#222;background:#fff}
.field input:focus,.field textarea:focus{border-color:#0d0d14}
.field textarea{resize:vertical;min-height:90px;line-height:1.5}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:480px){.row2{grid-template-columns:1fr}}
.btn-main{width:100%;background:#0d0d14;color:#fff;border:none;padding:16px;
  border-radius:12px;font-size:16px;font-weight:700;cursor:pointer;
  transition:all .2s;margin-top:6px;font-family:inherit}
.btn-main:hover{background:#333}
.btn-main:disabled{opacity:.5;cursor:not-allowed}
.btn-back{width:100%;background:none;border:2px solid #ddd;color:#666;
  font-size:14px;padding:11px;border-radius:10px;cursor:pointer;
  margin-top:8px;font-family:inherit;transition:all .2s}
.btn-back:hover{border-color:#999;color:#333}
.btn-calc{width:100%;background:#37474f;color:#fff;border:none;padding:12px;
  border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;
  margin-bottom:12px;font-family:inherit;transition:all .2s}
.btn-calc:hover{background:#546e7a}
.prev-box{border-radius:12px;padding:18px;margin:12px 0;display:none;border:2px solid}
.prev-inside{background:#e8f5e9;border-color:#4caf50}
.prev-outside{background:#fff8e1;border-color:#ff9800}
.prev-title{font-size:14px;font-weight:700;margin-bottom:8px}
.prev-imp{font-size:24px;font-weight:700;margin:6px 0}
.prev-inside .prev-imp{color:#2e7d32}
.prev-outside .prev-imp{color:#e65100}
.prev-zona{font-size:13px;color:#555}
.prev-det{font-size:12px;color:#666;margin-top:6px}
.prev-nota{font-size:11px;color:#999;margin-top:6px}
.loading{display:none;text-align:center;padding:12px;font-size:13px;color:#666}
.spin{display:inline-block;width:18px;height:18px;border:2px solid #ddd;
  border-top-color:#0d0d14;border-radius:50%;
  animation:spin .7s linear infinite;vertical-align:middle;margin-right:8px}
@keyframes spin{to{transform:rotate(360deg)}}
.foto-area{border:2px dashed #ccc;border-radius:12px;padding:20px;
  text-align:center;cursor:pointer;transition:all .2s;
  background:#fafafa;margin-top:6px}
.foto-area:hover{border-color:#0d0d14;background:#f0f0f0}
.foto-area.ok{border-color:#4caf50;background:#f1f8e9;border-style:solid}
.foto-icon{font-size:32px;margin-bottom:6px}
.foto-hint{font-size:13px;color:#888}
.foto-img{width:80px;height:80px;object-fit:cover;border-radius:10px;
  margin:0 auto 6px;display:block;border:2px solid #4caf50}
.ok-wrap{text-align:center;padding:40px 20px}
.ok-ico{font-size:64px;margin-bottom:18px}
.ok-wrap h2{font-size:24px;color:#0d0d14;margin-bottom:10px}
.ok-proto{font-size:20px;font-weight:700;color:#0d0d14;background:#f0f0f0;
  padding:12px 24px;border-radius:10px;display:inline-block;
  margin:16px 0;letter-spacing:3px;border:2px solid #ddd}
.ok-wrap p{font-size:14px;color:#555;line-height:1.8;max-width:380px;margin:0 auto}
.ok-note{background:#e8f5e9;border-radius:10px;padding:14px;margin-top:18px}
.ok-note p{font-size:13px;color:#1b5e20;font-weight:600}
</style>
</head>
<body>

<div class="header">
  <h1>ROTONDI GROUP ROMA</h1>
  <p>Assistenza Tecnica Macchinari</p>
</div>

<div class="lang-bar">
  <button class="lb active" onclick="setLang('it')" id="l_it">
    <span class="fl">🇮🇹</span> Italiano
  </button>
  <button class="lb" onclick="setLang('en')" id="l_en">
    <span class="fl">🇬🇧</span> English
  </button>
  <button class="lb" onclick="setLang('bn')" id="l_bn">
    <span class="fl">🇧🇩</span> বাংলা
  </button>
  <button class="lb" onclick="setLang('zh')" id="l_zh">
    <span class="fl">🇨🇳</span> 中文
  </button>
  <button class="lb" onclick="setLang('ar')" id="l_ar">
    <span class="fl">🇸🇦</span> العربية
  </button>
</div>

<div class="container">
  <div class="steps">
    <div class="step active" id="s1"></div>
    <div class="step" id="s2"></div>
    <div class="step" id="s3"></div>
  </div>

  <!-- STEP 1 -->
  <div id="step1">
    <div class="card">
      <h2>🔒 <span id="t_gdpr_h">Privacy (GDPR)</span></h2>
      <div class="gdpr-box">
        <div class="co">🏢 Rotondi Group Srl</div>
        <div class="ad">📍 Via F.lli Rosselli 14/16 — 20019 Settimo Milanese (MI)</div>
        <div class="em">📧 segnalazioni-privacy@rotondigroup.it</div>
        <div class="pt">
          <p><strong>Finalità:</strong> gestione richiesta assistenza tecnica</p>
          <p><strong>Conservazione:</strong> massimo 2 anni</p>
          <p><strong>Diritti:</strong> accesso, rettifica, cancellazione dei dati</p>
        </div>
      </div>
      <label class="chk-row">
        <input type="checkbox" id="c_gdpr">
        <span id="t_gdpr_lbl">
          Accetto il trattamento dei dati personali ai sensi del GDPR
        </span>
      </label>
    </div>

    <div class="card">
      <h2>📋 <span id="t_cond_h">Condizioni del Servizio</span></h2>
      <div class="cond-box" id="cond_box">{{ condizioni_it }}</div>
      <label class="chk-row">
        <input type="checkbox" id="c_cond">
        <span id="t_cond_lbl">Accetto le condizioni del servizio</span>
      </label>
    </div>
    <button class="btn-main" onclick="goStep2()" id="btn1">Continua →</button>
  </div>

  <!-- STEP 2 -->
  <div id="step2" style="display:none">
    <div class="card">
      <h2>👤 <span id="t_dati_h">Dati Personali</span></h2>
      <div class="field">
        <label id="t_nome">Nome e Cognome *</label>
        <input id="nome" type="text" autocomplete="name" placeholder="Es: Mario Rossi">
      </div>
      <div class="field">
        <label id="t_email">Email</label>
        <input id="email" type="email" autocomplete="email" placeholder="nome@email.com">
      </div>
      <div class="field">
        <label id="t_tel">Telefono *</label>
        <input id="tel" type="tel" autocomplete="tel" placeholder="+39 333 1234567">
      </div>
    </div>

    <div class="card">
      <h2>📍 <span id="t_ind_h">Indirizzo Intervento</span></h2>
      <div class="field">
        <label id="t_via">Via / Piazza *</label>
        <input id="via" type="text" placeholder="Es: Via Roma" autocomplete="address-line1">
      </div>
      <div class="row2">
        <div class="field">
          <label id="t_civico">N° Civico *</label>
          <input id="civico" type="text" placeholder="Es: 10">
        </div>
        <div class="field">
          <label id="t_cap">CAP *</label>
          <input id="cap" type="text" placeholder="Es: 00100" maxlength="5">
        </div>
      </div>
      <div class="row2">
        <div class="field">
          <label id="t_citta">Città *</label>
          <input id="citta" type="text" autocomplete="address-level2" placeholder="Es: Roma">
        </div>
        <div class="field">
          <label id="t_prov">Provincia *</label>
          <input id="prov" type="text" placeholder="Es: RM" maxlength="2">
        </div>
      </div>
      <button class="btn-calc" onclick="calcolaPreventivo()" id="btn_calc">
        📍 Verifica distanza e preventivo
      </button>
      <div class="loading" id="load_p">
        <span class="spin"></span><span id="t_calc_lbl">Calcolo in corso...</span>
      </div>
      <div class="prev-box" id="prev_box">
        <div class="prev-title" id="t_prev_h">💰 Preventivo Indicativo</div>
        <p class="prev-zona" id="prev_zona"></p>
        <div class="prev-imp" id="prev_imp"></div>
        <p class="prev-det" id="prev_det"></p>
        <p class="prev-nota" id="t_prev_nota">
          Preventivo indicativo per 1h di lavoro + IVA
        </p>
      </div>
    </div>
    <button class="btn-main" onclick="goStep3()" id="btn2">Continua →</button>
    <button class="btn-back" onclick="goStep1()" id="t_back1">← Indietro</button>
  </div>

  <!-- STEP 3 -->
  <div id="step3" style="display:none">
    <div class="card">
      <h2>🏭 <span id="t_mac_h">Dati Macchina</span></h2>
      <div class="row2">
        <div class="field">
          <label id="t_marca">Marca *</label>
          <input id="marca" type="text" placeholder="Es: Samsung, LG, Bosch">
        </div>
        <div class="field">
          <label id="t_modello">Modello</label>
          <input id="modello" type="text" placeholder="Es: WW90T534">
        </div>
      </div>
      <div class="field">
        <label id="t_seriale">Numero Seriale</label>
        <input id="seriale" type="text" placeholder="Dalla targhetta del macchinario">
      </div>
      <div class="field">
        <label id="t_prob">Descrivi il Problema *</label>
        <textarea id="problema"
          placeholder="Cosa succede? Da quando? Hai già provato qualcosa?">
        </textarea>
      </div>
    </div>

    <div class="card">
      <h2>📷 <span id="t_foto_h">Foto (opzionale)</span></h2>
      <div class="field">
        <label id="t_foto_targ">📸 Foto targhetta macchina</label>
        <div class="foto-area" id="fa_targ"
             onclick="document.getElementById('fi_targ').click()">
          <div id="fp_targ">
            <div class="foto-icon">📸</div>
            <div class="foto-hint" id="fh_targ">
              Tocca per aggiungere la foto
            </div>
          </div>
        </div>
        <input type="file" id="fi_targ" accept="image/*" capture="environment"
               style="display:none"
               onchange="mostraFoto(this,'fp_targ','fa_targ','fh_targ')">
      </div>
      <div class="field">
        <label id="t_foto_mac">📷 Foto della macchina</label>
        <div class="foto-area" id="fa_mac"
             onclick="document.getElementById('fi_mac').click()">
          <div id="fp_mac">
            <div class="foto-icon">📷</div>
            <div class="foto-hint" id="fh_mac">
              Tocca per aggiungere la foto
            </div>
          </div>
        </div>
        <input type="file" id="fi_mac" accept="image/*" capture="environment"
               style="display:none"
               onchange="mostraFoto(this,'fp_mac','fa_mac','fh_mac')">
      </div>
    </div>

    <button class="btn-main" onclick="invia()" id="btn3">
      📤 Invia Richiesta
    </button>
    <button class="btn-back" onclick="goStep2back()" id="t_back2">
      ← Indietro
    </button>
  </div>

  <!-- SUCCESS -->
  <div id="stepOK" style="display:none">
    <div class="card ok-wrap">
      <div class="ok-ico">✅</div>
      <h2 id="t_ok_h">Richiesta Inviata!</h2>
      <div class="ok-proto" id="ok_proto"></div>
      <p id="t_ok_p">
        Un tecnico <strong>Rotondi Group Roma</strong> ti contatterà
        a breve con una proposta di appuntamento.<br><br>
        Riceverai una <strong>email</strong> con i pulsanti
        <strong>✅ Accetto</strong> e <strong>❌ Rifiuto</strong>.
      </p>
      <div class="ok-note">
        <p>⚠️ Per annullare urgentemente: +39 06 41 40 0514</p>
      </div>
    </div>
  </div>
</div>

<script>
var lang='it', prevData=null;
var COND_IT={{ condizioni_it_js }};
var COND_EN={{ condizioni_en_js }};

var L={
  it:{
    gdpr_h:'Privacy (GDPR)',
    gdpr_lbl:'Accetto il trattamento dei dati personali ai sensi del GDPR',
    cond_h:'Condizioni del Servizio',
    cond_lbl:'Accetto le condizioni del servizio',
    dati_h:'Dati Personali',nome:'Nome e Cognome *',email:'Email',tel:'Telefono *',
    ind_h:'Indirizzo Intervento',via:'Via / Piazza *',civico:'N\u00b0 Civico *',
    cap:'CAP *',citta:'Citt\u00e0 *',prov:'Provincia *',
    btn_calc:'\ud83d\udccd Verifica distanza e preventivo',
    calc_lbl:'Calcolo in corso...',
    prev_h:'\ud83d\udcb0 Preventivo Indicativo',
    prev_nota:'Preventivo indicativo per 1h di lavoro + IVA',
    inside:'Zona Roma (dentro GRA)',outside:'Fuori Roma',
    mac_h:'Dati Macchina',marca:'Marca *',modello:'Modello',
    seriale:'Numero Seriale',prob:'Descrivi il Problema *',
    foto_h:'Foto (opzionale)',
    foto_targ:'\ud83d\udcf8 Foto targhetta macchina',
    foto_mac:'\ud83d\udcf7 Foto della macchina',
    foto_hint:'Tocca per aggiungere la foto',
    btn1:'Continua \u2192',btn2:'Continua \u2192',
    btn3:'\ud83d\udce4 Invia Richiesta',
    back1:'\u2190 Indietro',back2:'\u2190 Indietro',
    ok_h:'Richiesta Inviata!',
    ok_p:'Un tecnico <strong>Rotondi Group Roma</strong> ti contatter\u00e0 a breve con una proposta di appuntamento.<br><br>Riceverai una <strong>email</strong> con i pulsanti <strong>\u2705 Accetto</strong> e <strong>\u274c Rifiuto</strong>.',
    err_consent:'Devi accettare privacy e condizioni per continuare',
    err_campi:'Compila tutti i campi obbligatori (*)'
  },
  en:{
    gdpr_h:'Privacy (GDPR)',
    gdpr_lbl:'I accept the processing of personal data under GDPR',
    cond_h:'Service Conditions',cond_lbl:'I accept the service conditions',
    dati_h:'Personal Details',nome:'Full Name *',email:'Email',tel:'Phone *',
    ind_h:'Service Address',via:'Street *',civico:'Number *',
    cap:'Postal Code *',citta:'City *',prov:'Province *',
    btn_calc:'\ud83d\udccd Check distance & quote',calc_lbl:'Calculating...',
    prev_h:'\ud83d\udcb0 Indicative Quote',
    prev_nota:'Indicative quote for 1h work + VAT',
    inside:'Rome area (inside GRA)',outside:'Outside Rome',
    mac_h:'Machine Details',marca:'Brand *',modello:'Model',
    seriale:'Serial Number',prob:'Describe the Problem *',
    foto_h:'Photos (optional)',
    foto_targ:'\ud83d\udcf8 Machine label photo',
    foto_mac:'\ud83d\udcf7 Machine photo',
    foto_hint:'Tap to add photo',
    btn1:'Continue \u2192',btn2:'Continue \u2192',btn3:'Send Request',
    back1:'\u2190 Back',back2:'\u2190 Back',
    ok_h:'Request Sent!',
    ok_p:'A <strong>Rotondi Group Roma</strong> technician will contact you shortly.<br><br>You will receive an <strong>email</strong> with <strong>\u2705 Accept</strong> and <strong>\u274c Decline</strong> buttons.',
    err_consent:'You must accept privacy and conditions to continue',
    err_campi:'Please fill all required fields (*)'
  },
  bn:{
    gdpr_h:'\u0997\u09cb\u09aa\u09a8\u09c0\u09af\u09bc\u09a4\u09be (GDPR)',
    gdpr_lbl:'\u0986\u09ae\u09bf GDPR \u0985\u09a8\u09c1\u09af\u09be\u09af\u09bc\u09c0 \u09b8\u09ae\u09cd\u09ae\u09a4\u09bf \u09a6\u09bf\u099a\u09cd\u099b\u09bf',
    cond_h:'\u09b6\u09b0\u09cd\u09a4\u09be\u09ac\u09b2\u09c0',
    cond_lbl:'\u0986\u09ae\u09bf \u09b6\u09b0\u09cd\u09a4\u09be\u09ac\u09b2\u09c0 \u0997\u09cd\u09b0\u09b9\u09a3 \u0995\u09b0\u099b\u09bf',
    dati_h:'\u09ac\u09cd\u09af\u0995\u09cd\u09a4\u09bf\u0997\u09a4 \u09a4\u09a5\u09cd\u09af',
    nome:'\u09aa\u09c1\u09b0\u09cb \u09a8\u09be\u09ae *',email:'\u0987\u09ae\u09c7\u0987\u09b2',tel:'\u09ab\u09cb\u09a8 *',
    ind_h:'\u09a0\u09bf\u0995\u09be\u09a8\u09be',via:'\u09b0\u09be\u09b8\u09cd\u09a4\u09be *',civico:'\u09a8\u09ae\u09cd\u09ac\u09b0 *',
    cap:'\u09aa\u09cb\u09b8\u09cd\u099f\u09be\u09b2 \u0995\u09cb\u09a1 *',citta:'\u09b6\u09b9\u09b0 *',prov:'\u09aa\u09cd\u09b0\u09a6\u09c7\u09b6 *',
    btn_calc:'\u09a6\u09c2\u09b0\u09a4\u09cd\u09ac \u09af\u09be\u099a\u09be\u0987',calc_lbl:'\u09b9\u09bf\u09b8\u09be\u09ac \u099a\u09b2\u099b\u09c7...',
    prev_h:'\u0986\u09a8\u09c1\u09ae\u09be\u09a8\u09bf\u0995 \u0996\u09b0\u099a',prev_nota:'1 \u0998\u09a3\u09cd\u099f\u09be + \u09ad\u09cd\u09af\u09be\u099f',
    inside:'\u09b0\u09cb\u09ae\u09be (GRA \u09ad\u09c7\u09a4\u09b0\u09c7)',outside:'\u09b0\u09cb\u09ae\u09be\u09b0 \u09ac\u09be\u0987\u09b0\u09c7',
    mac_h:'\u09ae\u09c7\u09b6\u09bf\u09a8\u09c7\u09b0 \u09a4\u09a5\u09cd\u09af',marca:'\u09ac\u09cd\u09b0\u09cd\u09af\u09be\u09a8\u09cd\u09a1 *',modello:'\u09ae\u09a1\u09c7\u09b2',
    seriale:'\u09b8\u09bf\u09b0\u09bf\u09af\u09bc\u09be\u09b2 \u09a8\u09ae\u09cd\u09ac\u09b0',prob:'\u09b8\u09ae\u09b8\u09cd\u09af\u09be\u09b0 \u09ac\u09bf\u09ac\u09b0\u09a3 *',
    foto_h:'\u099b\u09ac\u09bf (\u09ac\u09be\u099e\u09cd\u099b\u09be\u09ae\u09be\u09ab\u09bf\u0995)',
    foto_targ:'\u09a4\u09be\u09b0\u09bf\u0996\u09ab\u09b2\u0995\u09c7\u09b0 \u099b\u09ac\u09bf',
    foto_mac:'\u09ae\u09c7\u09b6\u09bf\u09a8\u09c7\u09b0 \u099b\u09ac\u09bf',
    foto_hint:'\u099b\u09ac\u09bf \u09af\u09cb\u0997 \u0995\u09b0\u09a4\u09c7 \u09b8\u09cd\u09aa\u09b0\u09cd\u09b6 \u0995\u09b0\u09c1\u09a8',
    btn1:'\u098f\u0997\u09bf\u09af\u09bc\u09c7 \u09af\u09be\u09a8 \u2192',btn2:'\u098f\u0997\u09bf\u09af\u09bc\u09c7 \u09af\u09be\u09a8 \u2192',btn3:'\u09aa\u09be\u09a0\u09be\u09a8',
    back1:'\u2190 \u09aa\u09c7\u099b\u09a8\u09c7',back2:'\u2190 \u09aa\u09c7\u099b\u09a8\u09c7',
    ok_h:'\u0985\u09a8\u09c1\u09b0\u09cb\u09a7 \u09aa\u09be\u09a0\u09be\u09a8\u09cb \u09b9\u09af\u09bc\u09c7\u099b\u09c7!',
    ok_p:'\u099f\u09c7\u0995\u09a8\u09bf\u09b6\u09bf\u09af\u09bc\u09be\u09a8 \u09b6\u09c0\u0998\u09cd\u09b0\u0987 \u09af\u09cb\u0997\u09be\u09af\u09cb\u0997 \u0995\u09b0\u09ac\u09c7\u09a8\u0964<br><br>\u09ac\u09be\u09a4\u09bf\u09b2: <strong>+39 06 41 40 0514</strong>',
    err_consent:'\u0997\u09cb\u09aa\u09a8\u09c0\u09af\u09bc\u09a4\u09be \u0993 \u09b6\u09b0\u09cd\u09a4\u09be\u09ac\u09b2\u09c0 \u0997\u09cd\u09b0\u09b9\u09a3 \u0995\u09b0\u09c1\u09a8',
    err_campi:'\u09b8\u09ac \u09aa\u09cd\u09b0\u09af\u09bc\u09cb\u099c\u09a8\u09c0\u09af\u09bc \u09a4\u09a5\u09cd\u09af \u09aa\u09c2\u09b0\u09a3 \u0995\u09b0\u09c1\u09a8'
  },
  zh:{
    gdpr_h:'\u9690\u79c1 (GDPR)',gdpr_lbl:'\u6211\u540c\u610f\u6839\u636eGDPR\u5904\u7406\u4e2a\u4eba\u6570\u636e',
    cond_h:'\u670d\u52a1\u6761\u6b3e',cond_lbl:'\u6211\u63a5\u53d7\u670d\u52a1\u6761\u6b3e',
    dati_h:'\u4e2a\u4eba\u4fe1\u606f',nome:'\u59d3\u540d *',email:'\u90ae\u7b71',tel:'\u7535\u8bdd *',
    ind_h:'\u670d\u52a1\u5730\u5740',via:'\u8857\u9053 *',civico:'\u95e8\u724c\u53f7 *',
    cap:'\u90ae\u653f\u7f16\u7801 *',citta:'\u57ce\u5e02 *',prov:'\u7701\u4efd\u4ee3\u7801 *',
    btn_calc:'\u9a8c\u8bc1\u8ddd\u79bb',calc_lbl:'\u8ba1\u7b97\u4e2d...',
    prev_h:'\u53c2\u8003\u62a5\u4ef7',prev_nota:'1\u5c0f\u65f6\u5de5\u4f5c\u53c2\u8003\u62a5\u4ef7 + \u589e\u5024\u7a0e',
    inside:'\u7f57\u9a6c\u5e02\u533a\uff08GRA\u5185\uff09',outside:'\u7f57\u9a6c\u5e02\u5916',
    mac_h:'\u673a\u5668\u4fe1\u606f',marca:'\u54c1\u724c *',modello:'\u578b\u53f7',
    seriale:'\u5e8f\u5217\u53f7',prob:'\u63cf\u8ff0\u95ee\u9898 *',
    foto_h:'\u7167\u7247\uff08\u53ef\u9009\uff09',foto_targ:'\u94ed\u724c\u7167\u7247',foto_mac:'\u673a\u5668\u7167\u7247',
    foto_hint:'\u70b9\u51fb\u6dfb\u52a0\u7167\u7247',
    btn1:'\u7ee7\u7eed \u2192',btn2:'\u7ee7\u7eed \u2192',btn3:'\u53d1\u9001',
    back1:'\u2190 \u8fd4\u56de',back2:'\u2190 \u8fd4\u56de',
    ok_h:'\u8bf7\u6c42\u5df2\u53d1\u9001\uff01',
    ok_p:'\u6280\u672f\u4eba\u5458\u5c06\u5f88\u5feb\u8054\u7cfb\u60a8\u3002<br><br>\u53d6\u6d88: <strong>+39 06 41 40 0514</strong>',
    err_consent:'\u8bf7\u63a5\u53d7\u9690\u79c1\u653f\u7b56\u548c\u670d\u52a1\u6761\u6b3e',
    err_campi:'\u8bf7\u586b\u5199\u6240\u6709\u5fc5\u586b\u5b57\u6bb5'
  },
  ar:{
    gdpr_h:'\u0627\u0644\u062e\u0635\u0648\u0635\u064a\u0629 (GDPR)',
    gdpr_lbl:'\u0623\u0648\u0627\u0641\u0642 \u0639\u0644\u0649 \u0645\u0639\u0627\u0644\u062c\u0629 \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0648\u0641\u0642 GDPR',
    cond_h:'\u0634\u0631\u0648\u0637 \u0627\u0644\u062e\u062f\u0645\u0629',
    cond_lbl:'\u0623\u0642\u0628\u0644 \u0634\u0631\u0648\u0637 \u0627\u0644\u062e\u062f\u0645\u0629',
    dati_h:'\u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u0634\u062e\u0635\u064a\u0629',
    nome:'\u0627\u0644\u0627\u0633\u0645 \u0627\u0644\u0643\u0627\u0645\u0644 *',email:'\u0627\u0644\u0628\u0631\u064a\u062f \u0627\u0644\u0625\u0644\u0643\u062a\u0631\u0648\u0646\u064a',tel:'\u0627\u0644\u0647\u0627\u062a\u0641 *',
    ind_h:'\u0639\u0646\u0648\u0627\u0646 \u0627\u0644\u062e\u062f\u0645\u0629',via:'\u0627\u0644\u0634\u0627\u0631\u0639 *',civico:'\u0631\u0642\u0645 \u0627\u0644\u0645\u0628\u0646\u0649 *',
    cap:'\u0627\u0644\u0631\u0645\u0632 \u0627\u0644\u0628\u0631\u064a\u062f\u064a *',citta:'\u0627\u0644\u0645\u062f\u064a\u0646\u0629 *',prov:'\u0631\u0645\u0632 \u0627\u0644\u0645\u062d\u0627\u0641\u0638\u0629 *',
    btn_calc:'\u062a\u062d\u0642\u0642 \u0645\u0646 \u0627\u0644\u0645\u0633\u0627\u0641\u0629',calc_lbl:'\u062c\u0627\u0631\u0650 \u0627\u0644\u062d\u0633\u0627\u0628...',
    prev_h:'\u0639\u0631\u0636 \u0633\u0639\u0631 \u062a\u0642\u0631\u064a\u0628\u064a',prev_nota:'\u062a\u0642\u0631\u064a\u0628\u064a \u0644\u0633\u0627\u0639\u0629 \u0639\u0645\u0644 + \u0636\u0631\u064a\u0628\u0629',
    inside:'\u0645\u0646\u0637\u0642\u0629 \u0631\u0648\u0645\u0627 (\u062f\u0627\u062e\u0644 GRA)',outside:'\u062e\u0627\u0631\u062c \u0631\u0648\u0645\u0627',
    mac_h:'\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u062c\u0647\u0627\u0632',marca:'\u0627\u0644\u0645\u0627\u0631\u0643\u0629 *',modello:'\u0627\u0644\u0645\u0648\u062f\u064a\u0644',
    seriale:'\u0627\u0644\u0631\u0642\u0645 \u0627\u0644\u062a\u0633\u0644\u0633\u0644\u064a',prob:'\u0635\u0641 \u0627\u0644\u0645\u0634\u0643\u0644\u0629 *',
    foto_h:'\u0635\u0648\u0631 (\u0627\u062e\u062a\u064a\u0627\u0631\u064a)',foto_targ:'\u0635\u0648\u0631\u0629 \u0644\u0648\u062d\u0629 \u0627\u0644\u062c\u0647\u0627\u0632',foto_mac:'\u0635\u0648\u0631\u0629 \u0627\u0644\u062c\u0647\u0627\u0632',
    foto_hint:'\u0627\u0636\u063a\u0637 \u0644\u0625\u0636\u0627\u0641\u0629 \u0635\u0648\u0631\u0629',
    btn1:'\u0645\u062a\u0627\u0628\u0639\u0629 \u2192',btn2:'\u0645\u062a\u0627\u0628\u0639\u0629 \u2192',btn3:'\u0625\u0631\u0633\u0627\u0644',
    back1:'\u2190 \u0631\u062c\u0648\u0639',back2:'\u2190 \u0631\u062c\u0648\u0639',
    ok_h:'\u062a\u0645 \u0625\u0631\u0633\u0627\u0644 \u0627\u0644\u0637\u0644\u0628!',
    ok_p:'\u0633\u064a\u062a\u0635\u0644 \u0628\u0643 \u0641\u0646\u064a \u0642\u0631\u064a\u0628\u0627\u064b.<br><br>\u0644\u0644\u0625\u0644\u063a\u0627\u0621: <strong>+39 06 41 40 0514</strong>',
    err_consent:'\u064a\u062c\u0628 \u0642\u0628\u0648\u0644 \u0633\u064a\u0627\u0633\u0629 \u0627\u0644\u062e\u0635\u0648\u0635\u064a\u0629 \u0648\u0627\u0644\u0634\u0631\u0648\u0637',
    err_campi:'\u064a\u0631\u062c\u0649 \u0645\u0644\u0621 \u062c\u0645\u064a\u0639 \u0627\u0644\u062d\u0642\u0648\u0644 \u0627\u0644\u0645\u0637\u0644\u0648\u0628\u0629'
  }
};

function setLang(l){
  lang=l;
  document.querySelectorAll('.lb').forEach(function(b){b.classList.remove('active');});
  document.getElementById('l_'+l).classList.add('active');
  var T=L[l];
  var mp={
    't_gdpr_h':'gdpr_h','t_gdpr_lbl':'gdpr_lbl',
    't_cond_h':'cond_h','t_cond_lbl':'cond_lbl',
    't_dati_h':'dati_h','t_nome':'nome','t_email':'email','t_tel':'tel',
    't_ind_h':'ind_h','t_via':'via','t_civico':'civico','t_cap':'cap',
    't_citta':'citta','t_prov':'prov',
    't_calc_lbl':'calc_lbl','t_prev_h':'prev_h','t_prev_nota':'prev_nota',
    't_mac_h':'mac_h','t_marca':'marca','t_modello':'modello',
    't_seriale':'seriale','t_prob':'prob',
    't_foto_h':'foto_h','t_foto_targ':'foto_targ','t_foto_mac':'foto_mac',
    'btn1':'btn1','btn2':'btn2','btn3':'btn3',
    't_back1':'back1','t_back2':'back2'
  };
  for(var id in mp){
    var el=document.getElementById(id);
    if(el) el.textContent=T[mp[id]];
  }
  document.getElementById('btn_calc').textContent=T.btn_calc;
  var h1=document.getElementById('fh_targ');
  var h2=document.getElementById('fh_mac');
  if(h1) h1.textContent=T.foto_hint;
  if(h2) h2.textContent=T.foto_hint;
  if(l==='it') document.getElementById('cond_box').textContent=COND_IT;
  else if(l==='en') document.getElementById('cond_box').textContent=COND_EN;
  document.getElementById('t_ok_h').textContent=T.ok_h;
  document.getElementById('t_ok_p').innerHTML=T.ok_p;
}

function updSteps(n){
  for(var i=1;i<=3;i++){
    var s=document.getElementById('s'+i);
    s.className='step'+(i<n?' done':i===n?' active':'');
  }
}

function goStep1(){
  document.getElementById('step2').style.display='none';
  document.getElementById('step1').style.display='';
  updSteps(1); window.scrollTo(0,0);
}

function goStep2(){
  if(!document.getElementById('c_gdpr').checked ||
     !document.getElementById('c_cond').checked){
    alert(L[lang].err_consent); return;
  }
  document.getElementById('step1').style.display='none';
  document.getElementById('step2').style.display='';
  updSteps(2); window.scrollTo(0,0);
}

function goStep2back(){
  document.getElementById('step3').style.display='none';
  document.getElementById('step2').style.display='';
  updSteps(2); window.scrollTo(0,0);
}

function goStep3(){
  var ff=['nome','tel','via','civico','cap','citta','prov'];
  for(var i=0;i<ff.length;i++){
    if(!document.getElementById(ff[i]).value.trim()){
      alert(L[lang].err_campi); return;
    }
  }
  document.getElementById('step2').style.display='none';
  document.getElementById('step3').style.display='';
  updSteps(3); window.scrollTo(0,0);
}

function buildInd(){
  return document.getElementById('via').value.trim()+', '+
         document.getElementById('civico').value.trim()+', '+
         document.getElementById('cap').value.trim()+' '+
         document.getElementById('citta').value.trim()+' ('+
         document.getElementById('prov').value.trim().toUpperCase()+'), Italia';
}

function calcolaPreventivo(){
  var ff=['via','civico','cap','citta','prov'];
  for(var i=0;i<ff.length;i++){
    if(!document.getElementById(ff[i]).value.trim()){
      alert(L[lang].err_campi); return;
    }
  }
  document.getElementById('load_p').style.display='block';
  document.getElementById('prev_box').style.display='none';
  fetch('/calcola-preventivo',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({indirizzo:buildInd()})
  })
  .then(function(r){return r.json();})
  .then(function(d){
    document.getElementById('load_p').style.display='none';
    if(!d||!d.zona) return;
    prevData=d;
    var box=document.getElementById('prev_box');
    var T=L[lang];
    if(d.zona==='inside_gra'){
      box.className='prev-box prev-inside';
      document.getElementById('prev_zona').textContent=
        T.inside+' \u2014 '+d.dist_label+' ('+d.dur_label+')';
      document.getElementById('prev_imp').textContent=
        'EUR '+d.costo_min.toFixed(2)+' + IVA';
      document.getElementById('prev_det').textContent='Uscita + 1h lavoro inclusa';
    } else {
      box.className='prev-box prev-outside';
      document.getElementById('prev_zona').textContent=
        T.outside+' \u2014 '+d.dist_label+' ('+d.dur_label+')';
      document.getElementById('prev_imp').textContent=
        'min. EUR '+d.costo_min.toFixed(2)+' + IVA';
      if(d.dettaglio){
        document.getElementById('prev_det').textContent=
          'Km A/R: EUR '+d.dettaglio.costo_km+
          ' | Viaggio: EUR '+d.dettaglio.costo_viaggio+
          ' | Lavoro 1h: EUR '+d.dettaglio.costo_lavoro;
      }
    }
    document.getElementById('t_prev_h').textContent=T.prev_h;
    document.getElementById('t_prev_nota').textContent=T.prev_nota;
    box.style.display='block';
  })
  .catch(function(){
    document.getElementById('load_p').style.display='none';
  });
}

function mostraFoto(inp,pvId,arId,hiId){
  var f=inp.files[0]; if(!f) return;
  var r=new FileReader();
  r.onload=function(e){
    var b=document.getElementById(pvId);
    b.innerHTML='<img class="foto-img" src="'+e.target.result+'">'
      +'<div class="foto-hint" style="color:#2e7d32;font-weight:600">'+f.name+'</div>';
  };
  r.readAsDataURL(f);
  document.getElementById(arId).classList.add('ok');
}

function invia(){
  var ff=['nome','tel','marca','problema'];
  for(var i=0;i<ff.length;i++){
    if(!document.getElementById(ff[i]).value.trim()){
      alert(L[lang].err_campi); return;
    }
  }
  var btn=document.getElementById('btn3');
  btn.disabled=true; btn.textContent='\u23f3 Invio in corso...';

  var fd=new FormData();
  fd.append('nome',     document.getElementById('nome').value.trim());
  fd.append('email',    document.getElementById('email').value.trim());
  fd.append('telefono', document.getElementById('tel').value.trim());
  fd.append('via',      document.getElementById('via').value.trim());
  fd.append('civico',   document.getElementById('civico').value.trim());
  fd.append('cap',      document.getElementById('cap').value.trim());
  fd.append('citta',    document.getElementById('citta').value.trim());
  fd.append('provincia',document.getElementById('prov').value.trim().toUpperCase());
  fd.append('indirizzo',buildInd());
  fd.append('marca',    document.getElementById('marca').value.trim());
  fd.append('modello',  document.getElementById('modello').value.trim());
  fd.append('seriale',  document.getElementById('seriale').value.trim());
  fd.append('problema', document.getElementById('problema').value.trim());
  fd.append('lingua',   lang);
  if(prevData) fd.append('preventivo',JSON.stringify(prevData));
  var ft=document.getElementById('fi_targ').files[0];
  var fm=document.getElementById('fi_mac').files[0];
  if(ft) fd.append('foto_targhetta',ft);
  if(fm) fd.append('foto_macchina',fm);

  fetch('/invia',{method:'POST',body:fd})
  .then(function(r){return r.json();})
  .then(function(d){
    if(d.protocollo){
      document.getElementById('step3').style.display='none';
      document.getElementById('stepOK').style.display='';
      document.getElementById('ok_proto').textContent=d.protocollo;
      document.getElementById('t_ok_h').textContent=L[lang].ok_h;
      document.getElementById('t_ok_p').innerHTML=L[lang].ok_p;
      document.querySelectorAll('.step').forEach(function(s){
        s.className='step done';
      });
      window.scrollTo(0,0);
    } else {
      btn.disabled=false; btn.textContent=L[lang].btn3;
      alert('Errore invio. Riprova.');
    }
  })
  .catch(function(){
    btn.disabled=false; btn.textContent=L[lang].btn3;
    alert('Errore di connessione. Riprova.');
  });
}
</script>
</body>
</html>"""


HTML_LOGIN = """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin - Rotondi Group Roma</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Arial,sans-serif;background:#f0f0f0;display:flex;
  align-items:center;justify-content:center;min-height:100vh}
.box{background:#fff;border-radius:14px;padding:44px;width:100%;
  max-width:400px;box-shadow:0 4px 24px rgba(0,0,0,.12)}
.logo{text-align:center;margin-bottom:28px}
.logo h1{font-size:18px;font-weight:700;color:#0d0d14;letter-spacing:1px}
.logo p{font-size:12px;color:#999;margin-top:4px}
input{width:100%;padding:13px 16px;border:2px solid #e0e0e0;border-radius:10px;
  font-size:15px;margin-bottom:16px;outline:none;font-family:inherit}
input:focus{border-color:#0d0d14}
button{width:100%;background:#0d0d14;color:#fff;border:none;padding:14px;
  border-radius:10px;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit}
button:hover{background:#333}
.err{color:#e53935;font-size:13px;text-align:center;margin-bottom:14px;
  background:#ffebee;padding:10px;border-radius:8px}
</style></head>
<body>
<div class="box">
  <div class="logo">
    <h1>&#128274; ROTONDI GROUP ROMA</h1>
    <p>Pannello Amministratore</p>
  </div>
  {% if errore %}<p class="err">{{ errore }}</p>{% endif %}
  <form method="POST">
    <input type="password" name="password"
           placeholder="Password amministratore" autofocus>
    <button type="submit">Accedi</button>
  </form>
</div>
</body></html>"""


HTML_ADMIN = """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin - Rotondi Group Roma</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Arial,sans-serif;background:#f0f0f0;color:#222}
.topbar{background:#0d0d14;color:#fff;padding:16px 28px;
  display:flex;align-items:center;justify-content:space-between}
.topbar h1{font-size:18px;font-weight:700}
.topbar a{color:#aaa;font-size:13px;text-decoration:none;
  padding:6px 14px;border:1px solid #555;border-radius:6px}
.topbar a:hover{color:#fff;border-color:#fff}
.container{max-width:1000px;margin:28px auto;padding:0 20px 80px}
.card{background:#fff;border-radius:12px;padding:28px;margin-bottom:22px;
  box-shadow:0 2px 10px rgba(0,0,0,.08)}
.card h2{font-size:16px;font-weight:700;color:#0d0d14;margin-bottom:20px;
  border-bottom:3px solid #f0f0f0;padding-bottom:12px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:640px){.grid2{grid-template-columns:1fr}}
.field{margin-bottom:16px}
.field label{display:block;font-size:12px;font-weight:700;color:#555;
  margin-bottom:6px;text-transform:uppercase;letter-spacing:0.3px}
input[type=number],input[type=password],textarea{width:100%;padding:11px 14px;
  border:2px solid #e0e0e0;border-radius:10px;font-size:14px;outline:none;
  font-family:inherit}
input:focus,textarea:focus{border-color:#0d0d14}
textarea{resize:vertical;min-height:140px;font-size:13px;line-height:1.7}
.btn-save{background:#0d0d14;color:#fff;border:none;padding:14px 36px;
  border-radius:10px;font-size:15px;cursor:pointer;font-weight:700;font-family:inherit}
.btn-save:hover{background:#333}
.msg{background:#e8f5e9;color:#2e7d32;padding:14px 18px;border-radius:10px;
  margin-bottom:20px;font-size:14px;font-weight:700;border-left:4px solid #4caf50}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#f5f5f5;padding:11px 10px;text-align:left;font-weight:700;
  color:#555;border-bottom:2px solid #e0e0e0;font-size:12px;
  text-transform:uppercase;letter-spacing:0.3px}
td{padding:10px;border-bottom:1px solid #f0f0f0;vertical-align:top}
tr:hover td{background:#fafafa}
.badge{display:inline-block;padding:4px 10px;border-radius:6px;
  font-size:11px;font-weight:700}
.b-open{background:#fff3cd;color:#856404}
.b-ass{background:#d4edda;color:#155724}
.b-wait{background:#d1ecf1;color:#0c5460}
a.sblocca{color:#e53935;font-size:12px;text-decoration:none;
  padding:4px 10px;border:1px solid #e53935;border-radius:6px}
a.sblocca:hover{background:#e53935;color:#fff}
</style></head>
<body>
<div class="topbar">
  <h1>&#9881;&#65039; Admin — Rotondi Group Roma</h1>
  <a href="/admin/logout">Esci</a>
</div>
<div class="container">
  {% if msg %}<div class="msg">{{ msg }}</div>{% endif %}
  <form method="POST">
    <div class="card">
      <h2>Tariffe</h2>
      <div class="grid2">
        <div class="field"><label>Uscita + 1h dentro GRA (EUR)</label>
          <input type="number" step="0.01" name="tariffa_dentro_uscita"
                 value="{{ '%.2f'|format(tar.dentro_uscita) }}"></div>
        <div class="field"><label>Ora extra lavoro (EUR/h)</label>
          <input type="number" step="0.01" name="tariffa_dentro_ora_extra"
                 value="{{ '%.2f'|format(tar.dentro_ora_extra) }}"></div>
        <div class="field"><label>Km trasferta fuori GRA (EUR/km)</label>
          <input type="number" step="0.01" name="tariffa_fuori_km"
                 value="{{ '%.2f'|format(tar.fuori_km) }}"></div>
        <div class="field"><label>Ora viaggio (EUR/h)</label>
          <input type="number" step="0.01" name="tariffa_fuori_ora_viaggio"
                 value="{{ '%.2f'|format(tar.fuori_ora_viaggio) }}"></div>
        <div class="field"><label>Ora lavoro fuori GRA (EUR/h)</label>
          <input type="number" step="0.01" name="tariffa_fuori_ora_lavoro"
                 value="{{ '%.2f'|format(tar.fuori_ora_lavoro) }}"></div>
      </div>
    </div>
    <div class="card">
      <h2>Condizioni del Servizio</h2>
      <div class="field"><label>Italiano</label>
        <textarea name="condizioni_it">{{ cond_it }}</textarea></div>
      <div class="field"><label>English</label>
        <textarea name="condizioni_en">{{ cond_en }}</textarea></div>
    </div>
    <div class="card">
      <h2>Cambia Password Admin</h2>
      <div class="field" style="max-width:340px">
        <label>Nuova password (lascia vuoto per non cambiare)</label>
        <input type="password" name="nuova_password" placeholder="Nuova password">
      </div>
    </div>
    <button type="submit" class="btn-save">Salva tutto</button>
  </form>

  <div class="card" style="margin-top:28px">
    <h2>Ultime 50 Richieste Web</h2>
    <div style="overflow-x:auto">
      <table>
        <tr>
          <th>Protocollo</th><th>Cliente</th><th>Indirizzo</th>
          <th>Tel</th><th>Marca</th><th>Problema</th>
          <th>Stato</th><th>Tecnico / Orario</th><th>Data</th><th></th>
        </tr>
        {% for r in richieste %}
        <tr>
          <td><code style="font-size:11px;color:#0066cc">{{ r[0] }}</code></td>
          <td><b>{{ r[1] }}</b></td>
          <td style="font-size:12px;color:#555">{{ r[2] }}</td>
          <td style="font-size:12px">{{ r[3] }}</td>
          <td style="font-size:12px"><b>{{ r[4] }}</b></td>
          <td style="max-width:150px;font-size:12px;color:#555">
            {{ (r[5] or '')[:55] }}{% if r[5] and r[5]|length > 55 %}...{% endif %}
          </td>
          <td>
            {% if r[6]=='aperta' %}
              <span class="badge b-open">Aperta</span>
            {% elif r[6]=='assegnata' %}
              <span class="badge b-ass">Assegnata</span>
            {% elif r[6]=='in_attesa_conferma' %}
              <span class="badge b-wait">In attesa</span>
            {% else %}
              <span class="badge b-wait">{{ r[6] }}</span>
            {% endif %}
          </td>
          <td style="font-size:12px">
            {% if r[7] %}<b>{{ r[7] }}</b><br>{% endif %}
            <span style="color:#888">{{ r[8] or '' }}</span>
          </td>
          <td style="font-size:12px;color:#888">{{ r[9] }}</td>
          <td>
            {% if r[6] != 'aperta' %}
            <a href="/admin/sblocca/{{ r[0] }}" class="sblocca"
               onclick="return confirm('Sbloccare?')">Sblocca</a>
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </table>
    </div>
  </div>
</div>
</body></html>"""


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)), debug=False)
