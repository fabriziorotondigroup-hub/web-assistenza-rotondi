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
    "L'assistenza tecnica è un servizio a pagamento, anche se il prodotto è in garanzia.\n\n"
    "✅ In garanzia: parti difettose sostituite senza costo\n\n"
    "💶 Sempre a carico del cliente:\n"
    "- Manodopera\n- Spostamento tecnico\n- Costo chiamata\n\n"
    "📍 ZONA DI ROMA (dentro il GRA)\n"
    "- Uscita + 1h lavoro: € 80,00 + IVA\n"
    "- Ore successive: € 40,00/h + IVA\n\n"
    "🗺 FUORI ROMA (Provincia, Lazio, resto d'Italia)\n"
    "- Km trasferta: € 0,70/km + IVA (A/R)\n"
    "- Ore viaggio: € 32,00/h + IVA (A/R)\n"
    "- Ore lavoro: € 40,00/h + IVA\n\n"
    "Pagamento direttamente al tecnico al termine del servizio."
)

CONDIZIONI_EN_DEFAULT = (
    "Technical assistance is a paid service, even under warranty.\n\n"
    "✅ Under warranty: defective parts replaced at no cost\n\n"
    "💶 Always charged to customer:\n"
    "- Labour\n- Technician travel\n- Call-out fee\n\n"
    "📍 ROME AREA (inside GRA ring road)\n"
    "- Call-out + 1h work: € 80.00 + VAT\n"
    "- Additional hours: € 40.00/h + VAT\n\n"
    "🗺 OUTSIDE ROME\n"
    "- Travel km: € 0.70/km + VAT (return)\n"
    "- Travel hours: € 32.00/h + VAT (return)\n"
    "- Work hours: € 40.00/h + VAT\n\n"
    "Payment directly to the technician at end of service."
)


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS richieste_web (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                protocollo TEXT UNIQUE,
                nome       TEXT,
                via        TEXT,
                civico     TEXT,
                cap        TEXT,
                citta      TEXT,
                provincia  TEXT,
                indirizzo  TEXT,
                telefono   TEXT,
                email      TEXT,
                marca      TEXT,
                modello    TEXT,
                seriale    TEXT,
                problema   TEXT,
                stato      TEXT DEFAULT 'aperta',
                tecnico    TEXT,
                fascia     TEXT,
                data       TEXT,
                lingua     TEXT DEFAULT 'it',
                preventivo TEXT
            )
        """)
        for col in ["via TEXT","civico TEXT","cap TEXT","citta TEXT","provincia TEXT",
                    "seriale TEXT","email TEXT","preventivo TEXT"]:
            try: conn.execute(f"ALTER TABLE richieste_web ADD COLUMN {col}")
            except: pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS config (
                chiave TEXT PRIMARY KEY,
                valore TEXT
            )
        """)
        for k, v in TARIFFE_DEFAULT.items():
            conn.execute("INSERT OR IGNORE INTO config VALUES (?,?)", (f"tariffa_{k}", str(v)))
        conn.execute("INSERT OR IGNORE INTO config VALUES ('condizioni_it',?)", (CONDIZIONI_IT_DEFAULT,))
        conn.execute("INSERT OR IGNORE INTO config VALUES ('condizioni_en',?)", (CONDIZIONI_EN_DEFAULT,))
        conn.execute("INSERT OR IGNORE INTO config VALUES ('admin_pass',?)",
                     (os.environ.get("ADMIN_PASSWORD","rotondi2024"),))
        conn.commit()


def get_config(chiave, default=None):
    with sqlite3.connect(DB_PATH) as conn:
        r = conn.execute("SELECT valore FROM config WHERE chiave=?", (chiave,)).fetchone()
    return r[0] if r else default


def set_config(chiave, valore):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR REPLACE INTO config VALUES (?,?)", (chiave, str(valore)))
        conn.commit()


def get_tariffe():
    return {k: float(get_config(f"tariffa_{k}", v)) for k, v in TARIFFE_DEFAULT.items()}


def calcola_preventivo(indirizzo_cliente):
    try:
        import requests as rq
        tar = get_tariffe()
        r = rq.get("https://maps.googleapis.com/maps/api/distancematrix/json", params={
            "origins": SEDE, "destinations": indirizzo_cliente,
            "mode": "driving", "key": GMAPS_KEY, "language": "it"
        }, timeout=10)
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
        costo_km=dist_ar*tar["fuori_km"]; costo_v=dur_ar*tar["fuori_ora_viaggio"]
        costo_l=tar["fuori_ora_lavoro"]; costo=costo_km+costo_v+costo_l
        return {"zona":"outside_gra","costo_min":round(costo,2),
                "dist_label":el["distance"]["text"],"dur_label":el["duration"]["text"],
                "dettaglio":{"km_ar":f"{dist_ar:.0f}","costo_km":f"{costo_km:.2f}",
                             "ore_viaggio":dur_ar,"costo_viaggio":f"{costo_v:.2f}",
                             "costo_lavoro":f"{costo_l:.2f}"}}
    except Exception as e:
        app.logger.error(f"Maps: {e}"); return None


def invia_telegram(testo, keyboard=None):
    try:
        import requests as rq
        payload = {"chat_id":TECNICI_GID,"text":testo,"parse_mode":"Markdown"}
        if keyboard: payload["reply_markup"] = json.dumps(keyboard)
        rq.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json=payload, timeout=10)
    except Exception as e: app.logger.error(f"TG: {e}")


def invia_foto_telegram(foto_file, caption):
    try:
        import requests as rq
        rq.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id":TECNICI_GID,"caption":caption},
                files={"photo":(foto_file.filename,foto_file.read(),foto_file.content_type)},
                timeout=20)
    except Exception as e: app.logger.error(f"TG foto: {e}")


def notifica_bo(testo):
    if not BOT_TOKEN: return
    bo_ids = [x.strip() for x in os.environ.get("BACKOFFICE_IDS","").split(",") if x.strip()]
    try:
        import requests as rq
        for bo_id in bo_ids:
            rq.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id":bo_id,"text":testo,"parse_mode":"Markdown"},timeout=10)
    except Exception as e: app.logger.error(f"BO: {e}")


def invia_email(to, subject, corpo_html):
    if not (to and SMTP_U and SMTP_P): return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"]=subject; msg["From"]=SMTP_F; msg["To"]=to
        msg.attach(MIMEText(corpo_html,"html"))
        with smtplib.SMTP(SMTP_H,SMTP_PO) as s:
            s.starttls(); s.login(SMTP_U,SMTP_P); s.sendmail(SMTP_F,to,msg.as_string())
    except Exception as e: app.logger.error(f"Email: {e}")


def email_conferma_ricezione(email, nome, protocollo, lingua="it"):
    soggetto = {"it":f"Rotondi Group Roma - Richiesta ricevuta #{protocollo}",
                "en":f"Rotondi Group Roma - Request received #{protocollo}"}.get(lingua,f"#{protocollo}")
    corpo = f"""<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
  <h1 style="color:#fff;font-size:22px;margin:0">ROTONDI GROUP ROMA</h1>
  <p style="color:#aaa;font-size:13px;margin:4px 0 0">Assistenza Tecnica Macchinari</p>
</div>
<div style="background:#fff;padding:32px;border-radius:0 0 8px 8px">
  <h2 style="color:#0d0d14">Richiesta ricevuta!</h2>
  <p>Gentile <b>{nome}</b>,</p>
  <p>La sua richiesta è stata ricevuta. A breve riceverà una email con la proposta di appuntamento.</p>
  <div style="background:#f8f8f8;border-radius:8px;padding:16px;margin:20px 0;border-left:4px solid #0d0d14">
    <p style="margin:0 0 4px;color:#666;font-size:13px">Numero protocollo</p>
    <p style="font-size:24px;font-weight:bold;color:#0d0d14;margin:0">{protocollo}</p>
  </div>
  <div style="background:#fff3cd;border-radius:8px;padding:12px">
    <p style="margin:0;font-size:13px">Per annullare urgentemente: <b>+39 06 41 40 0514</b></p>
  </div>
  <p style="color:#666;font-size:13px;margin-top:20px">Ufficio Roma: +39 06 41400617</p>
</div></div>"""
    invia_email(email, soggetto, corpo)


def email_proposta_appuntamento(email, nome, protocollo, tecnico, data_ora, lingua="it"):
    link_si = f"{BASE_URL}/proposta/{protocollo}/accetta"
    link_no = f"{BASE_URL}/proposta/{protocollo}/rifiuta"
    soggetto = {"it":f"Rotondi Group Roma - Proposta appuntamento #{protocollo}",
                "en":f"Rotondi Group Roma - Appointment proposal #{protocollo}"}.get(lingua,f"#{protocollo}")
    testi = {
        "it": ("Proposta di Appuntamento",
               f"Il tecnico <b>{tecnico}</b> è disponibile il:",
               "Data e ora proposta", "Accetto", "Rifiuto",
               "Rispondere entro 24 ore. Se non risponde, la richiesta tornerà ad altri tecnici.",
               "Per informazioni: <b>+39 06 41400617</b> — Per annullare: <b>+39 06 41 40 0514</b>"),
        "en": ("Appointment Proposal",
               f"Technician <b>{tecnico}</b> is available on:",
               "Proposed date and time", "Accept", "Decline",
               "Please respond within 24 hours.",
               "Info: <b>+39 06 41400617</b>"),
    }
    T = testi.get(lingua, testi["it"])
    corpo = f"""<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
  <h1 style="color:#fff;font-size:22px;margin:0">ROTONDI GROUP ROMA</h1>
  <p style="color:#aaa;font-size:13px;margin:4px 0 0">Assistenza Tecnica Macchinari</p>
</div>
<div style="background:#fff;padding:32px;border-radius:0 0 8px 8px">
  <h2 style="color:#0d0d14">{T[0]}</h2>
  <p>Gentile <b>{nome}</b>,</p>
  <p>{T[1]}</p>
  <div style="background:#f0f8ff;border-radius:10px;padding:20px;margin:20px 0;
              text-align:center;border:2px solid #0d0d14">
    <p style="font-size:13px;color:#666;margin:0 0 8px">{T[2]}</p>
    <p style="font-size:28px;font-weight:bold;color:#0d0d14;margin:0">{data_ora}</p>
  </div>
  <p style="margin-bottom:6px;font-size:13px;color:#666"><b>Protocollo:</b> {protocollo}</p>
  <p style="color:#888;font-size:13px;margin:12px 0">{T[5]}</p>
  <table style="width:100%;border-collapse:collapse;margin:24px 0">
    <tr>
      <td style="padding:8px;text-align:center">
        <a href="{link_si}" style="background:#4caf50;color:#fff;padding:18px 40px;
           border-radius:10px;text-decoration:none;font-size:20px;font-weight:700;
           display:inline-block">✅ {T[3]}</a>
      </td>
      <td style="padding:8px;text-align:center">
        <a href="{link_no}" style="background:#e53935;color:#fff;padding:18px 40px;
           border-radius:10px;text-decoration:none;font-size:20px;font-weight:700;
           display:inline-block">❌ {T[4]}</a>
      </td>
    </tr>
  </table>
  <p style="font-size:11px;color:#bbb;text-align:center">
    Se i pulsanti non funzionano:<br>
    ✅ {link_si}<br>❌ {link_no}
  </p>
  <div style="background:#fff3cd;border-radius:8px;padding:12px;margin-top:20px">
    <p style="margin:0;font-size:13px">{T[6]}</p>
  </div>
</div></div>"""
    invia_email(email, soggetto, corpo)


def email_esito_finale(email, nome, protocollo, tecnico, data_ora, lingua, confermata):
    if confermata:
        soggetto = {"it":f"Rotondi Group Roma - Appuntamento confermato #{protocollo}",
                    "en":f"Rotondi Group Roma - Appointment confirmed #{protocollo}"}.get(lingua,f"#{protocollo}")
        corpo = f"""<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
  <h1 style="color:#fff;font-size:22px;margin:0">ROTONDI GROUP ROMA</h1>
</div>
<div style="background:#fff;padding:32px;border-radius:0 0 8px 8px;text-align:center">
  <div style="font-size:56px;margin-bottom:12px">🎉</div>
  <h2 style="color:#4caf50">Appuntamento Confermato!</h2>
  <p style="margin:16px 0">Gentile <b>{nome}</b>,</p>
  <div style="background:#f0fff4;border-radius:10px;padding:20px;margin:20px 0;border:2px solid #4caf50">
    <p style="font-size:13px;color:#666;margin:0 0 8px">Data e ora intervento</p>
    <p style="font-size:26px;font-weight:bold;color:#2e7d32;margin:0">{data_ora}</p>
    <p style="color:#444;margin:8px 0 0">Tecnico: <b>{tecnico}</b></p>
  </div>
  <div style="background:#fff3cd;border-radius:8px;padding:12px">
    <p style="margin:0;font-size:13px">Ufficio Roma: <b>+39 06 41400617</b><br>
    Per annullare: <b>+39 06 41 40 0514</b></p>
  </div>
</div></div>"""
    else:
        soggetto = {"it":f"Rotondi Group Roma - Proposta rifiutata #{protocollo}",
                    "en":f"Rotondi Group Roma - Proposal declined #{protocollo}"}.get(lingua,f"#{protocollo}")
        corpo = f"""<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
  <h1 style="color:#fff;font-size:22px;margin:0">ROTONDI GROUP ROMA</h1>
</div>
<div style="background:#fff;padding:32px;border-radius:0 0 8px 8px">
  <h2 style="color:#0d0d14">Proposta rifiutata</h2>
  <p>Gentile <b>{nome}</b>,</p>
  <p>La Sua richiesta è ancora aperta. Un altro tecnico la contatterà a breve.</p>
  <div style="background:#fff3cd;border-radius:8px;padding:12px;margin-top:16px">
    <p style="margin:0;font-size:13px">Per info: <b>+39 06 41400617</b></p>
  </div>
</div></div>"""
    invia_email(email, soggetto, corpo)


def pagina_risposta(tipo, protocollo, tecnico="", data_ora="", lingua="it"):
    cfg = {
        "accettata":     ("#4caf50","🎉","Appuntamento Confermato!",
                          f"Il tecnico <b>{tecnico}</b> interverrà il:<br><br>"
                          f"<span style='font-size:22px;font-weight:bold;color:#2e7d32'>{data_ora}</span><br><br>"
                          f"Ufficio Roma: <b>+39 06 41400617</b><br>"
                          f"Per annullare: <b>+39 06 41 40 0514</b>"),
        "rifiutata":     ("#ff9800","↩️","Proposta Rifiutata",
                          "La Sua richiesta è ancora aperta.<br><br>"
                          "Un altro tecnico la contatterà a breve.<br><br>"
                          "Per info: <b>+39 06 41400617</b>"),
        "gia_confermata":(  "#4caf50","✅","Già Confermato",
                          f"Questo appuntamento è già stato confermato.<br>"
                          f"Data: <b>{data_ora}</b> — Tecnico: <b>{tecnico}</b>"),
        "gia_rifiutata": ("#888","ℹ️","Già Rifiutata","Questa proposta è già stata elaborata."),
        "non_trovata":   ("#e53935","⚠️","Non trovata",f"Protocollo <b>{protocollo}</b> non trovato."),
        "non_valida":    ("#e53935","⚠️","Link non valido","Questo link non è più valido."),
        "errore":        ("#e53935","❌","Errore","Contatta l'ufficio: +39 06 41400617"),
    }
    c = cfg.get(tipo, cfg["errore"])
    colore, icon, titolo, testo = c
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rotondi Group Roma</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f0f0f0;min-height:100vh}}
.hdr{{background:#0d0d14;color:#fff;padding:18px;text-align:center}}
.hdr h1{{font-size:18px;letter-spacing:1px}}
.wrap{{display:flex;align-items:center;justify-content:center;
  min-height:calc(100vh - 58px);padding:24px 16px}}
.box{{background:#fff;border-radius:16px;padding:40px 28px;max-width:460px;
  width:100%;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.1)}}
.bar{{height:5px;background:{colore};border-radius:3px;margin-bottom:28px}}
.ico{{font-size:54px;margin-bottom:14px}}
h2{{font-size:22px;color:{colore};margin-bottom:12px}}
.proto{{font-size:12px;color:#999;background:#f5f5f5;padding:5px 14px;
  border-radius:20px;display:inline-block;margin-bottom:18px}}
p{{font-size:14px;color:#444;line-height:1.8}}
</style></head>
<body>
<div class="hdr"><h1>ROTONDI GROUP ROMA</h1></div>
<div class="wrap"><div class="box">
  <div class="bar"></div>
  <div class="ico">{icon}</div>
  <h2>{titolo}</h2>
  <div class="proto">Protocollo: <strong>{protocollo}</strong></div>
  <p>{testo}</p>
</div></div>
</body></html>"""


@app.route("/")
def index():
    cond_it    = get_config("condizioni_it", CONDIZIONI_IT_DEFAULT)
    cond_en    = get_config("condizioni_en", CONDIZIONI_EN_DEFAULT)
    cond_it_js = json.dumps(cond_it)
    cond_en_js = json.dumps(cond_en)
    return render_template_string(HTML_FORM,
                                  condizioni_it=cond_it,
                                  condizioni_it_js=cond_it_js,
                                  condizioni_en_js=cond_en_js)


@app.route("/calcola-preventivo", methods=["POST"])
def route_preventivo():
    data = request.get_json(force=True)
    indirizzo = data.get("indirizzo","").strip()
    if not indirizzo: return jsonify({"error":"mancante"}), 400
    prev = calcola_preventivo(indirizzo)
    return jsonify(prev) if prev else jsonify({"error":"errore calcolo"}), 200


@app.route("/invia", methods=["POST"])
def route_invia():
    try:
        is_mp = request.content_type and 'multipart' in request.content_type
        data  = request.form if is_mp else request.get_json(force=True)
        ft    = request.files.get('foto_targhetta') if is_mp else None
        fm    = request.files.get('foto_macchina')  if is_mp else None

        proto     = "RG"+datetime.now().strftime("%Y%m%d%H%M%S")+uuid.uuid4().hex[:4].upper()
        via       = (data.get("via","") or "").strip()
        civico    = (data.get("civico","") or "").strip()
        cap       = (data.get("cap","") or "").strip()
        citta     = (data.get("citta","") or "").strip()
        provincia = (data.get("provincia","") or "").strip().upper()
        indirizzo = f"{via}, {civico}, {cap} {citta} ({provincia}), Italia"
        lingua    = data.get("lingua","it")
        prev_json = data.get("preventivo")

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""INSERT INTO richieste_web
                (protocollo,nome,via,civico,cap,citta,provincia,indirizzo,
                 telefono,email,marca,modello,seriale,problema,data,lingua,preventivo)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (proto, data.get("nome",""), via, civico, cap, citta, provincia, indirizzo,
                 data.get("telefono",""), data.get("email",""),
                 data.get("marca",""), data.get("modello",""),
                 data.get("seriale",""), data.get("problema",""),
                 datetime.now().strftime("%d/%m/%Y %H:%M"), lingua, prev_json))
            conn.commit()

        prev_txt = ""
        if prev_json:
            try:
                pv = json.loads(prev_json)
                if pv.get("zona")=="outside_gra":
                    prev_txt = f"\n💰 *Preventivo:* EUR {pv['costo_min']:.2f} + IVA ({pv.get('dist_label','')} — {pv.get('dur_label','')})"
                else:
                    prev_txt = f"\n💰 *Zona Roma (GRA):* EUR {pv.get('costo_min',80):.2f} + IVA"
            except: pass

        lm = "https://www.google.com/maps/search/?api=1&query="+indirizzo.replace(" ","+")
        FLAG = {"it":"🇮🇹","en":"🇬🇧","bn":"🇧🇩","zh":"🇨🇳","ar":"🇸🇦"}.get(lingua,"🌍")
        foto_txt = ""
        if ft and ft.filename: foto_txt += "\n📸 Foto targhetta: allegata"
        if fm and fm.filename: foto_txt += "\n📷 Foto macchina: allegata"

        testo = (
            f"🌐 *NUOVA RICHIESTA WEB* {FLAG}\n{'─'*30}\n"
            f"🔖 *Protocollo:* `{proto}`\n"
            f"👤 *Cliente:* {data.get('nome','')}\n"
            f"📍 *Indirizzo:* {indirizzo}\n"
            f"🗺 [Apri su Google Maps]({lm})\n"
            f"📞 *Tel:* {data.get('telefono','')}\n"
            f"📧 *Email:* {data.get('email','') or '—'}\n"
            f"🏷 *Marca:* {data.get('marca','')} | *Modello:* {data.get('modello','') or '—'}\n"
            f"🔢 *Seriale:* {data.get('seriale','') or '—'}\n"
            f"🔧 *Problema:* {data.get('problema','')}"
            f"{prev_txt}{foto_txt}\n{'─'*30}\n"
            f"⏰ Clicca per programmare l'intervento:"
        )
        invia_telegram(testo, {"inline_keyboard":[[
            {"text":"🗓 Scegli data e ora intervento",
             "callback_data":f"wfascia|{proto}|start"}
        ]]})
        if ft and ft.filename: invia_foto_telegram(ft, f"📸 Targhetta — {proto}")
        if fm and fm.filename: invia_foto_telegram(fm, f"📷 Macchina — {proto}")
        email_conferma_ricezione(data.get("email",""), data.get("nome",""), proto, lingua)
        return jsonify({"protocollo":proto,"ok":True})
    except Exception as e:
        app.logger.error(f"Errore /invia: {e}")
        return jsonify({"error":str(e)}), 500


@app.route("/proposta/<protocollo>/accetta")
def proposta_accetta(protocollo):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            r = conn.execute(
                "SELECT nome,tecnico,fascia,email,lingua,stato FROM richieste_web WHERE protocollo=?",
                (protocollo,)).fetchone()
    except: return pagina_risposta("errore", protocollo)
    if not r: return pagina_risposta("non_trovata", protocollo)
    nome,tecnico,data_ora,email,lingua,stato = r; lingua = lingua or "it"
    if stato == "assegnata":
        return pagina_risposta("gia_confermata", protocollo, tecnico, data_ora, lingua)
    if stato != "in_attesa_conferma":
        return pagina_risposta("non_valida", protocollo, lingua=lingua)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE richieste_web SET stato='assegnata' WHERE protocollo=?", (protocollo,))
        conn.commit()
    invia_telegram(f"✅ *RICHIESTA WEB {protocollo} — CONFERMATA*\n\n👤 {nome}\n👨‍🔧 {tecnico}\n📅 {data_ora}")
    notifica_bo(f"✅ *Web {protocollo} CONFERMATA*\n👤 {nome}\n👨‍🔧 {tecnico}\n📅 {data_ora}")
    if email: email_esito_finale(email, nome, protocollo, tecnico, data_ora, lingua, True)
    return pagina_risposta("accettata", protocollo, tecnico, data_ora, lingua)


@app.route("/proposta/<protocollo>/rifiuta")
def proposta_rifiuta(protocollo):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            r = conn.execute(
                "SELECT nome,tecnico,fascia,email,lingua,stato FROM richieste_web WHERE protocollo=?",
                (protocollo,)).fetchone()
    except: return pagina_risposta("errore", protocollo)
    if not r: return pagina_risposta("non_trovata", protocollo)
    nome,tecnico,data_ora,email,lingua,stato = r; lingua = lingua or "it"
    if stato == "aperta":
        return pagina_risposta("gia_rifiutata", protocollo, lingua=lingua)
    if stato != "in_attesa_conferma":
        return pagina_risposta("non_valida", protocollo, lingua=lingua)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE richieste_web SET stato='aperta',tecnico=NULL,fascia=NULL WHERE protocollo=?",
                     (protocollo,)); conn.commit()
    invia_telegram(
        f"❌ *RICHIESTA WEB {protocollo} — PROPOSTA RIFIUTATA*\n\n👤 {nome}\nTornata disponibile!",
        {"inline_keyboard":[[{"text":"🗓 Scegli nuova data e ora",
                              "callback_data":f"wfascia|{protocollo}|start"}]]}
    )
    notifica_bo(f"❌ *Web {protocollo} RIFIUTATA*\n👤 {nome}\nTornata disponibile")
    if email: email_esito_finale(email, nome, protocollo, tecnico, data_ora, lingua, False)
    return pagina_risposta("rifiutata", protocollo, lingua=lingua)


@app.route("/admin", methods=["GET","POST"])
def admin():
    if request.method=="POST" and "password" in request.form:
        if request.form["password"]==get_config("admin_pass","rotondi2024"):
            session["admin"]=True
        else:
            return render_template_string(HTML_LOGIN, errore="Password errata")
    if not session.get("admin"):
        return render_template_string(HTML_LOGIN, errore="")
    msg=""
    if request.method=="POST":
        for k in TARIFFE_DEFAULT:
            val=request.form.get(f"tariffa_{k}")
            if val:
                try: set_config(f"tariffa_{k}", float(val.replace(",",".")))
                except: pass
        for lg in ["it","en"]:
            val=request.form.get(f"condizioni_{lg}")
            if val: set_config(f"condizioni_{lg}", val)
        np=request.form.get("nuova_password","").strip()
        if np: set_config("admin_pass", np)
        msg="✅ Salvato con successo!"
    tar=get_tariffe()
    cond_it=get_config("condizioni_it",CONDIZIONI_IT_DEFAULT)
    cond_en=get_config("condizioni_en",CONDIZIONI_EN_DEFAULT)
    with sqlite3.connect(DB_PATH) as conn:
        richieste=conn.execute("""
            SELECT protocollo,nome,indirizzo,telefono,marca,problema,
                   stato,tecnico,fascia,data,lingua
            FROM richieste_web ORDER BY id DESC LIMIT 50""").fetchall()
    return render_template_string(HTML_ADMIN,
        tar=tar,cond_it=cond_it,cond_en=cond_en,richieste=richieste,msg=msg)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin",None); return redirect("/admin")


@app.route("/admin/sblocca/<protocollo>")
def admin_sblocca(protocollo):
    if not session.get("admin"): return redirect("/admin")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE richieste_web SET stato='aperta',tecnico=NULL,fascia=NULL WHERE protocollo=?",
                     (protocollo,)); conn.commit()
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

/* HEADER */
.header{background:#0d0d14;color:#fff;padding:22px 20px;text-align:center}
.header h1{font-size:24px;font-weight:700;letter-spacing:2px;margin:0}
.header p{font-size:13px;color:#aaa;margin-top:5px}

/* BARRA LINGUA */
.lang-bar{background:#fff;border-bottom:2px solid #eee;padding:12px 16px;
  display:flex;justify-content:center;flex-wrap:wrap;gap:8px}
.lb{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;
  border-radius:25px;border:2px solid #ddd;background:#fff;
  font-size:14px;font-weight:600;color:#555;cursor:pointer;
  transition:all .2s;font-family:inherit;line-height:1}
.lb:hover{border-color:#333;color:#333;background:#f5f5f5}
.lb.active{background:#0d0d14;border-color:#0d0d14;color:#fff}
.lb .fl{font-size:22px;line-height:1}

/* CONTAINER */
.container{max-width:640px;margin:28px auto;padding:0 16px 80px}

/* STEPS */
.steps{display:flex;justify-content:center;align-items:center;gap:6px;margin-bottom:28px}
.step{width:36px;height:5px;border-radius:3px;background:#ddd;transition:background .3s}
.step.active{background:#0d0d14}.step.done{background:#4caf50}

/* CARD */
.card{background:#fff;border-radius:14px;padding:26px;margin-bottom:18px;
  box-shadow:0 2px 12px rgba(0,0,0,.08)}
.card h2{font-size:16px;font-weight:700;color:#0d0d14;margin-bottom:18px;
  padding-bottom:12px;border-bottom:3px solid #f0f0f0;display:flex;align-items:center;gap:8px}

/* GDPR BOX */
.gdpr-info{background:#f8f9fa;border-radius:10px;padding:16px;margin-bottom:14px;
  border-left:4px solid #0d0d14}
.gdpr-info .company{font-size:16px;font-weight:700;color:#0d0d14;margin-bottom:6px}
.gdpr-info .address{font-size:13px;color:#555;margin-bottom:4px}
.gdpr-info .email-info{font-size:13px;color:#0066cc}
.gdpr-info .points{margin-top:10px}
.gdpr-info .points p{font-size:13px;color:#444;margin-bottom:4px;padding-left:8px}
.gdpr-info .points strong{color:#0d0d14}

/* CONDIZIONI */
.cond-box{background:#f8f9fa;border:1px solid #e0e0e0;border-radius:10px;padding:16px;
  font-size:13px;line-height:1.8;max-height:200px;overflow-y:auto;
  white-space:pre-wrap;margin-bottom:14px;color:#333}

/* CHECKBOX */
.chk-row{display:flex;align-items:flex-start;gap:12px;margin-bottom:10px;
  background:#e8f5e9;border-radius:8px;padding:12px}
.chk-row input[type=checkbox]{width:20px;height:20px;margin-top:1px;
  flex-shrink:0;cursor:pointer;accent-color:#0d0d14}
.chk-row label{font-size:14px;color:#1b5e20;font-weight:600;cursor:pointer;line-height:1.4}

/* FORM FIELDS */
.field{margin-bottom:16px}
.field label{display:block;font-size:13px;font-weight:700;color:#333;
  margin-bottom:6px;text-transform:uppercase;letter-spacing:0.3px}
.field input,.field textarea{width:100%;padding:12px 14px;border:2px solid #e0e0e0;
  border-radius:10px;font-size:15px;outline:none;transition:border .2s;
  font-family:inherit;color:#222;background:#fff}
.field input:focus,.field textarea:focus{border-color:#0d0d14;background:#fafafa}
.field textarea{resize:vertical;min-height:90px;line-height:1.5}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:480px){.row2{grid-template-columns:1fr}}

/* BUTTONS */
.btn-main{width:100%;background:#0d0d14;color:#fff;border:none;padding:16px;
  border-radius:12px;font-size:16px;font-weight:700;cursor:pointer;
  transition:all .2s;margin-top:6px;font-family:inherit;letter-spacing:0.5px}
.btn-main:hover{background:#333;transform:translateY(-1px)}
.btn-main:disabled{opacity:.5;cursor:not-allowed;transform:none}
.btn-back{width:100%;background:none;border:2px solid #ddd;color:#666;
  font-size:14px;padding:11px;border-radius:10px;cursor:pointer;
  margin-top:8px;font-family:inherit;transition:all .2s}
.btn-back:hover{border-color:#999;color:#333}
.btn-calc{width:100%;background:#37474f;color:#fff;border:none;padding:12px;
  border-radius:10px;font-size:14px;cursor:pointer;margin-bottom:12px;
  transition:all .2s;font-family:inherit;font-weight:600}
.btn-calc:hover{background:#546e7a}

/* PREVENTIVO */
.prev-box{border-radius:12px;padding:18px;margin:12px 0;display:none;border:2px solid}
.prev-inside{background:#e8f5e9;border-color:#4caf50}
.prev-outside{background:#fff8e1;border-color:#ff9800}
.prev-title{font-size:14px;font-weight:700;margin-bottom:8px}
.prev-importo{font-size:24px;font-weight:700;margin:6px 0}
.prev-inside .prev-importo{color:#2e7d32}
.prev-outside .prev-importo{color:#e65100}
.prev-zona{font-size:13px;color:#555}
.prev-det{font-size:12px;color:#666;margin-top:6px}
.prev-nota{font-size:11px;color:#999;margin-top:6px}

/* LOADING */
.loading{display:none;text-align:center;padding:12px;font-size:13px;color:#666}
.spin{display:inline-block;width:18px;height:18px;border:2px solid #ddd;
  border-top-color:#0d0d14;border-radius:50%;animation:spin .7s linear infinite;
  vertical-align:middle;margin-right:8px}
@keyframes spin{to{transform:rotate(360deg)}}

/* FOTO */
.foto-area{border:2px dashed #ccc;border-radius:12px;padding:18px;text-align:center;
  cursor:pointer;transition:all .2s;background:#fafafa;margin-top:6px}
.foto-area:hover{border-color:#0d0d14;background:#f0f0f0}
.foto-area.ok{border-color:#4caf50;background:#f1f8e9;border-style:solid}
.foto-icon{font-size:30px;margin-bottom:6px}
.foto-hint{font-size:13px;color:#888}
.foto-img{width:80px;height:80px;object-fit:cover;border-radius:10px;
  margin:0 auto 6px;display:block;border:2px solid #4caf50}

/* SUCCESS */
.ok-wrap{text-align:center;padding:40px 20px}
.ok-ico{font-size:64px;margin-bottom:18px}
.ok-wrap h2{font-size:24px;color:#0d0d14;margin-bottom:10px}
.ok-proto{font-size:20px;font-weight:700;color:#0d0d14;background:#f0f0f0;
  padding:12px 24px;border-radius:10px;display:inline-block;
  margin:16px 0;letter-spacing:3px;border:2px solid #ddd}
.ok-wrap p{font-size:14px;color:#555;line-height:1.8;max-width:380px;margin:0 auto}
.ok-info{background:#e8f5e9;border-radius:10px;padding:16px;margin-top:20px}
.ok-info p{font-size:13px;color:#1b5e20}
</style>
</head>
<body>

<div class="header">
  <h1>ROTONDI GROUP ROMA</h1>
  <p>Assistenza Tecnica Macchinari</p>
</div>

<div class="lang-bar">
  <button class="lb active" onclick="setLang('it')" id="l_it">
    <span class="fl">🇮🇹</span><span>Italiano</span>
  </button>
  <button class="lb" onclick="setLang('en')" id="l_en">
    <span class="fl">🇬🇧</span><span>English</span>
  </button>
  <button class="lb" onclick="setLang('bn')" id="l_bn">
    <span class="fl">🇧🇩</span><span>বাংলা</span>
  </button>
  <button class="lb" onclick="setLang('zh')" id="l_zh">
    <span class="fl">🇨🇳</span><span>中文</span>
  </button>
  <button class="lb" onclick="setLang('ar')" id="l_ar">
    <span class="fl">🇸🇦</span><span>العربية</span>
  </button>
</div>

<div class="container">
  <div class="steps">
    <div class="step active" id="s1"></div>
    <div class="step" id="s2"></div>
    <div class="step" id="s3"></div>
  </div>

  <!-- ═══ STEP 1: Privacy + Condizioni ═══ -->
  <div id="step1">
    <div class="card">
      <h2>🔒 <span id="t_gdpr_h">Privacy (GDPR)</span></h2>
      <div class="gdpr-info">
        <div class="company">🏢 Rotondi Group Srl</div>
        <div class="address">📍 Via F.lli Rosselli 14/16 — 20019 Settimo Milanese (MI)</div>
        <div class="email-info">📧 segnalazioni-privacy@rotondigroup.it</div>
        <div class="points">
          <p><strong>Finalità:</strong> gestione richiesta assistenza tecnica</p>
          <p><strong>Conservazione:</strong> massimo 2 anni</p>
          <p><strong>Diritti:</strong> accesso, rettifica, cancellazione dei dati</p>
        </div>
      </div>
      <div class="chk-row">
        <input type="checkbox" id="chk_gdpr">
        <label for="chk_gdpr" id="t_gdpr_lbl">✅ Accetto il trattamento dei dati personali ai sensi del GDPR</label>
      </div>
    </div>

    <div class="card">
      <h2>📋 <span id="t_cond_h">Condizioni del Servizio</span></h2>
      <div class="cond-box" id="cond_box">{{ condizioni_it }}</div>
      <div class="chk-row">
        <input type="checkbox" id="chk_cond">
        <label for="chk_cond" id="t_cond_lbl">✅ Accetto le condizioni del servizio</label>
      </div>
    </div>
    <button class="btn-main" onclick="goStep2()" id="btn1">Continua →</button>
  </div>

  <!-- ═══ STEP 2: Dati + Indirizzo ═══ -->
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
        <input id="telefono" type="tel" autocomplete="tel" placeholder="+39 333 1234567">
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
      <div class="loading" id="loading_p">
        <span class="spin"></span><span id="t_calc_lbl">Calcolo in corso...</span>
      </div>
      <div class="prev-box" id="prev_box">
        <div class="prev-title" id="t_prev_h">💰 Preventivo Indicativo</div>
        <p class="prev-zona" id="prev_zona"></p>
        <div class="prev-importo" id="prev_imp"></div>
        <p class="prev-det" id="prev_det"></p>
        <p class="prev-nota" id="t_prev_nota">Preventivo indicativo per 1h di lavoro + IVA</p>
      </div>
    </div>

    <button class="btn-main" onclick="goStep3()" id="btn2">Continua →</button>
    <button class="btn-back" onclick="goStep1()" id="t_back1">← Indietro</button>
  </div>

  <!-- ═══ STEP 3: Macchina + Foto ═══ -->
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
        <textarea id="problema" placeholder="Cosa succede? Da quando? Hai già provato qualcosa?"></textarea>
      </div>
    </div>

    <div class="card">
      <h2>📷 <span id="t_foto_h">Foto (opzionale)</span></h2>
      <div class="field">
        <label id="t_foto_targ">📸 Foto targhetta macchina</label>
        <div class="foto-area" id="area_targ" onclick="document.getElementById('inp_targ').click()">
          <div id="prv_targ">
            <div class="foto-icon">📸</div>
            <div class="foto-hint" id="hint_targ">Tocca per aggiungere la foto</div>
          </div>
        </div>
        <input type="file" id="inp_targ" accept="image/*" capture="environment"
               style="display:none" onchange="mostraFoto(this,'prv_targ','area_targ','hint_targ')">
      </div>
      <div class="field">
        <label id="t_foto_mac">📷 Foto della macchina</label>
        <div class="foto-area" id="area_mac" onclick="document.getElementById('inp_mac').click()">
          <div id="prv_mac">
            <div class="foto-icon">📷</div>
            <div class="foto-hint" id="hint_mac">Tocca per aggiungere la foto</div>
          </div>
        </div>
        <input type="file" id="inp_mac" accept="image/*" capture="environment"
               style="display:none" onchange="mostraFoto(this,'prv_mac','area_mac','hint_mac')">
      </div>
    </div>

    <button class="btn-main" onclick="invia()" id="btn3">📤 Invia Richiesta</button>
    <button class="btn-back" onclick="goStep2back()" id="t_back2">← Indietro</button>
  </div>

  <!-- ═══ SUCCESS ═══ -->
  <div id="stepOK" style="display:none">
    <div class="card ok-wrap">
      <div class="ok-ico">✅</div>
      <h2 id="t_ok_h">Richiesta Inviata!</h2>
      <div class="ok-proto" id="ok_proto"></div>
      <p id="t_ok_p">
        Un tecnico <strong>Rotondi Group Roma</strong> ti contatterà a breve
        con una proposta di appuntamento.<br><br>
        Riceverai una <strong>email</strong> con i pulsanti
        <strong>✅ Accetto</strong> / <strong>❌ Rifiuto</strong>.
      </p>
      <div class="ok-info">
        <p>⚠️ Per annullare urgentemente: <strong>+39 06 41 40 0514</strong></p>
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
    gdpr_lbl:'✅ Accetto il trattamento dei dati personali ai sensi del GDPR',
    cond_h:'Condizioni del Servizio',
    cond_lbl:'✅ Accetto le condizioni del servizio',
    dati_h:'Dati Personali',nome:'Nome e Cognome *',email:'Email',tel:'Telefono *',
    ind_h:'Indirizzo Intervento',via:'Via / Piazza *',civico:'N° Civico *',
    cap:'CAP *',citta:'Città *',prov:'Provincia *',
    btn_calc:'📍 Verifica distanza e preventivo',calc_lbl:'Calcolo in corso...',
    prev_h:'💰 Preventivo Indicativo',prev_nota:'Preventivo indicativo per 1h di lavoro + IVA',
    inside:'Zona Roma (dentro GRA)',outside:'Fuori Roma',
    mac_h:'Dati Macchina',marca:'Marca *',modello:'Modello',seriale:'Numero Seriale',
    prob:'Descrivi il Problema *',
    foto_h:'Foto (opzionale)',foto_targ:'📸 Foto targhetta macchina',
    foto_mac:'📷 Foto della macchina',foto_hint:'Tocca per aggiungere la foto',
    btn1:'Continua →',btn2:'Continua →',btn3:'📤 Invia Richiesta',
    back1:'← Indietro',back2:'← Indietro',
    ok_h:'Richiesta Inviata!',
    ok_p:'Un tecnico <strong>Rotondi Group Roma</strong> ti contatterà a breve con una proposta di appuntamento.<br><br>Riceverai una <strong>email</strong> con i pulsanti <strong>✅ Accetto</strong> / <strong>❌ Rifiuto</strong>.',
    err_consent:'⚠️ Devi accettare privacy e condizioni per continuare',
    err_campi:'⚠️ Compila tutti i campi obbligatori (*)'
  },
  en:{
    gdpr_h:'Privacy (GDPR)',
    gdpr_lbl:'✅ I accept the processing of personal data under GDPR',
    cond_h:'Service Conditions',
    cond_lbl:'✅ I accept the service conditions',
    dati_h:'Personal Details',nome:'Full Name *',email:'Email',tel:'Phone *',
    ind_h:'Service Address',via:'Street *',civico:'Number *',
    cap:'Postal Code *',citta:'City *',prov:'Province *',
    btn_calc:'📍 Check distance & quote',calc_lbl:'Calculating...',
    prev_h:'💰 Indicative Quote',prev_nota:'Indicative quote for 1h work + VAT',
    inside:'Rome area (inside GRA)',outside:'Outside Rome',
    mac_h:'Machine Details',marca:'Brand *',modello:'Model',seriale:'Serial Number',
    prob:'Describe the Problem *',
    foto_h:'Photos (optional)',foto_targ:'📸 Machine label photo',
    foto_mac:'📷 Machine photo',foto_hint:'Tap to add photo',
    btn1:'Continue →',btn2:'Continue →',btn3:'📤 Send Request',
    back1:'← Back',back2:'← Back',
    ok_h:'Request Sent!',
    ok_p:'A <strong>Rotondi Group Roma</strong> technician will contact you shortly with an appointment proposal.<br><br>You will receive an <strong>email</strong> with <strong>✅ Accept</strong> / <strong>❌ Decline</strong> buttons.',
    err_consent:'⚠️ You must accept privacy and conditions to continue',
    err_campi:'⚠️ Please fill all required fields (*)'
  },
  bn:{
    gdpr_h:'গোপনীয়তা (GDPR)',gdpr_lbl:'✅ আমি GDPR অনুযায়ী সম্মতি দিচ্ছি',
    cond_h:'শর্তাবলী',cond_lbl:'✅ আমি শর্তাবলী গ্রহণ করছি',
    dati_h:'ব্যক্তিগত তথ্য',nome:'পুরো নাম *',email:'ইমেইল',tel:'ফোন *',
    ind_h:'ঠিকানা',via:'রাস্তা *',civico:'নম্বর *',cap:'পোস্টাল কোড *',
    citta:'শহর *',prov:'প্রদেশ *',
    btn_calc:'📍 দূরত্ব যাচাই',calc_lbl:'হিসাব চলছে...',
    prev_h:'💰 আনুমানিক খরচ',prev_nota:'১ ঘণ্টার আনুমানিক + ভ্যাট',
    inside:'রোমা (GRA ভেতরে)',outside:'রোমার বাইরে',
    mac_h:'মেশিনের তথ্য',marca:'ব্র্যান্ড *',modello:'মডেল',seriale:'সিরিয়াল নম্বর',
    prob:'সমস্যার বিবরণ *',
    foto_h:'ছবি (ঐচ্ছিক)',foto_targ:'📸 তারিখফলকের ছবি',
    foto_mac:'📷 মেশিনের ছবি',foto_hint:'ছবি যোগ করতে স্পর্শ করুন',
    btn1:'এগিয়ে যান →',btn2:'এগিয়ে যান →',btn3:'📤 পাঠান',
    back1:'← পেছনে',back2:'← পেছনে',
    ok_h:'অনুরোধ পাঠানো হয়েছে!',
    ok_p:'একজন টেকনিশিয়ান শীঘ্রই আপনাকে যোগাযোগ করবেন।<br><br>বাতিল: <strong>+39 06 41 40 0514</strong>',
    err_consent:'⚠️ গোপনীয়তা ও শর্তাবলী গ্রহণ করুন',
    err_campi:'⚠️ সব প্রয়োজনীয় তথ্য পূরণ করুন'
  },
  zh:{
    gdpr_h:'隐私 (GDPR)',gdpr_lbl:'✅ 我同意根据GDPR处理个人数据',
    cond_h:'服务条款',cond_lbl:'✅ 我接受服务条款',
    dati_h:'个人信息',nome:'姓名 *',email:'邮箱',tel:'电话 *',
    ind_h:'服务地址',via:'街道 *',civico:'门牌号 *',cap:'邮政编码 *',
    citta:'城市 *',prov:'省份代码 *',
    btn_calc:'📍 验证距离',calc_lbl:'计算中...',
    prev_h:'💰 参考报价',prev_nota:'1小时工作参考报价 + 增值税',
    inside:'罗马市区（GRA内）',outside:'罗马市外',
    mac_h:'机器信息',marca:'品牌 *',modello:'型号',seriale:'序列号',
    prob:'描述问题 *',
    foto_h:'照片（可选）',foto_targ:'📸 铭牌照片',foto_mac:'📷 机器照片',
    foto_hint:'点击添加照片',
    btn1:'继续 →',btn2:'继续 →',btn3:'📤 发送',
    back1:'← 返回',back2:'← 返回',
    ok_h:'请求已发送！',
    ok_p:'技术人员将很快联系您。<br><br>取消: <strong>+39 06 41 40 0514</strong>',
    err_consent:'⚠️ 请接受隐私政策和服务条款',
    err_campi:'⚠️ 请填写所有必填字段'
  },
  ar:{
    gdpr_h:'الخصوصية (GDPR)',gdpr_lbl:'✅ أوافق على معالجة البيانات وفق GDPR',
    cond_h:'شروط الخدمة',cond_lbl:'✅ أقبل شروط الخدمة',
    dati_h:'البيانات الشخصية',nome:'الاسم الكامل *',email:'البريد الإلكتروني',tel:'الهاتف *',
    ind_h:'عنوان الخدمة',via:'الشارع *',civico:'رقم المبنى *',cap:'الرمز البريدي *',
    citta:'المدينة *',prov:'رمز المحافظة *',
    btn_calc:'📍 تحقق من المسافة',calc_lbl:'جارٍ الحساب...',
    prev_h:'💰 عرض سعر تقريبي',prev_nota:'تقريبي لساعة عمل + ضريبة',
    inside:'منطقة روما (داخل GRA)',outside:'خارج روما',
    mac_h:'بيانات الجهاز',marca:'الماركة *',modello:'الموديل',seriale:'الرقم التسلسلي',
    prob:'صف المشكلة *',
    foto_h:'صور (اختياري)',foto_targ:'📸 صورة لوحة الجهاز',foto_mac:'📷 صورة الجهاز',
    foto_hint:'اضغط لإضافة صورة',
    btn1:'متابعة →',btn2:'متابعة →',btn3:'📤 إرسال',
    back1:'← رجوع',back2:'← رجوع',
    ok_h:'تم إرسال الطلب!',
    ok_p:'سيتصل بك فني قريباً.<br><br>للإلغاء: <strong>+39 06 41 40 0514</strong>',
    err_consent:'⚠️ يجب قبول سياسة الخصوصية والشروط',
    err_campi:'⚠️ يرجى ملء جميع الحقول المطلوبة'
  }
};

function setLang(l){
  lang=l;
  document.querySelectorAll('.lb').forEach(function(b){b.classList.remove('active');});
  document.getElementById('l_'+l).classList.add('active');
  var T=L[l];
  // Aggiorna tutti i testi
  var m={
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
  for(var id in m){
    var el=document.getElementById(id);
    if(el) el.textContent=T[m[id]];
  }
  document.getElementById('btn_calc').textContent=T.btn_calc;
  // Aggiorna hint foto solo se non ancora selezionate
  var h1=document.getElementById('hint_targ');
  var h2=document.getElementById('hint_mac');
  if(h1) h1.textContent=T.foto_hint;
  if(h2) h2.textContent=T.foto_hint;
  // Aggiorna condizioni testo
  var cb=document.getElementById('cond_box');
  if(l==='it') cb.textContent=COND_IT;
  else if(l==='en') cb.textContent=COND_EN;
  // Aggiorna pagina successo
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
  if(!document.getElementById('chk_gdpr').checked||
     !document.getElementById('chk_cond').checked){
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
  // FIX: ID corretto "prov" non "provincia"
  var campi=['nome','telefono','via','civico','cap','citta','prov'];
  for(var i=0;i<campi.length;i++){
    if(!document.getElementById(campi[i]).value.trim()){
      alert(L[lang].err_campi); return;
    }
  }
  document.getElementById('step2').style.display='none';
  document.getElementById('step3').style.display='';
  updSteps(3); window.scrollTo(0,0);
}

function buildInd(){
  var via=document.getElementById('via').value.trim();
  var civ=document.getElementById('civico').value.trim();
  var cap=document.getElementById('cap').value.trim();
  var cit=document.getElementById('citta').value.trim();
  // FIX: ID corretto "prov"
  var prv=document.getElementById('prov').value.trim().toUpperCase();
  return via+', '+civ+', '+cap+' '+cit+' ('+prv+'), Italia';
}

function calcolaPreventivo(){
  var campi=['via','civico','cap','citta','prov'];
  for(var i=0;i<campi.length;i++){
    if(!document.getElementById(campi[i]).value.trim()){
      alert(L[lang].err_campi); return;
    }
  }
  document.getElementById('loading_p').style.display='block';
  document.getElementById('prev_box').style.display='none';
  fetch('/calcola-preventivo',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({indirizzo:buildInd()})
  })
  .then(function(r){return r.json();})
  .then(function(data){
    document.getElementById('loading_p').style.display='none';
    if(!data||!data.zona) return;
    prevData=data;
    var box=document.getElementById('prev_box');
    var T=L[lang];
    if(data.zona==='inside_gra'){
      box.className='prev-box prev-inside';
      document.getElementById('prev_zona').textContent=
        T.inside+' — '+data.dist_label+' ('+data.dur_label+')';
      document.getElementById('prev_imp').textContent=
        'EUR '+data.costo_min.toFixed(2)+' + IVA';
      document.getElementById('prev_det').textContent='Uscita + 1h lavoro inclusa';
    } else {
      box.className='prev-box prev-outside';
      document.getElementById('prev_zona').textContent=
        T.outside+' — '+data.dist_label+' ('+data.dur_label+')';
      document.getElementById('prev_imp').textContent=
        'min. EUR '+data.costo_min.toFixed(2)+' + IVA';
      if(data.dettaglio){
        document.getElementById('prev_det').textContent=
          'Km A/R: EUR '+data.dettaglio.costo_km+
          ' | Viaggio: EUR '+data.dettaglio.costo_viaggio+
          ' | Lavoro 1h: EUR '+data.dettaglio.costo_lavoro;
      }
    }
    document.getElementById('t_prev_h').textContent=T.prev_h;
    document.getElementById('t_prev_nota').textContent=T.prev_nota;
    box.style.display='block';
  })
  .catch(function(){
    document.getElementById('loading_p').style.display='none';
  });
}

function mostraFoto(input,prevId,areaId,hintId){
  var file=input.files[0]; if(!file) return;
  var reader=new FileReader();
  reader.onload=function(e){
    var box=document.getElementById(prevId);
    box.innerHTML='<img class="foto-img" src="'+e.target.result+'">'
      +'<div class="foto-hint" style="color:#2e7d32;font-weight:600">'+file.name+'</div>';
  };
  reader.readAsDataURL(file);
  document.getElementById(areaId).classList.add('ok');
}

function invia(){
  var campi=['nome','telefono','marca','problema'];
  for(var i=0;i<campi.length;i++){
    if(!document.getElementById(campi[i]).value.trim()){
      alert(L[lang].err_campi); return;
    }
  }
  var btn=document.getElementById('btn3');
  btn.disabled=true;
  btn.textContent='⏳ Invio in corso...';

  var fd=new FormData();
  fd.append('nome',      document.getElementById('nome').value.trim());
  fd.append('email',     document.getElementById('email').value.trim());
  fd.append('telefono',  document.getElementById('telefono').value.trim());
  fd.append('via',       document.getElementById('via').value.trim());
  fd.append('civico',    document.getElementById('civico').value.trim());
  fd.append('cap',       document.getElementById('cap').value.trim());
  fd.append('citta',     document.getElementById('citta').value.trim());
  // FIX: ID corretto "prov"
  fd.append('provincia', document.getElementById('prov').value.trim().toUpperCase());
  fd.append('indirizzo', buildInd());
  fd.append('marca',     document.getElementById('marca').value.trim());
  fd.append('modello',   document.getElementById('modello').value.trim());
  fd.append('seriale',   document.getElementById('seriale').value.trim());
  fd.append('problema',  document.getElementById('problema').value.trim());
  fd.append('lingua',    lang);
  if(prevData) fd.append('preventivo', JSON.stringify(prevData));

  var ft=document.getElementById('inp_targ').files[0];
  var fm=document.getElementById('inp_mac').files[0];
  if(ft) fd.append('foto_targhetta', ft);
  if(fm) fd.append('foto_macchina',  fm);

  fetch('/invia',{method:'POST',body:fd})
  .then(function(r){return r.json();})
  .then(function(data){
    if(data.protocollo){
      document.getElementById('step3').style.display='none';
      document.getElementById('stepOK').style.display='';
      document.getElementById('ok_proto').textContent=data.protocollo;
      document.getElementById('t_ok_h').textContent=L[lang].ok_h;
      document.getElementById('t_ok_p').innerHTML=L[lang].ok_p;
      document.querySelectorAll('.step').forEach(function(s){
        s.className='step done';
      });
      window.scrollTo(0,0);
    } else {
      btn.disabled=false;
      btn.textContent=L[lang].btn3;
      alert('Errore invio. Riprova.');
    }
  })
  .catch(function(){
    btn.disabled=false;
    btn.textContent=L[lang].btn3;
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
.err{color:#e53935;font-size:13px;text-align:center;
  margin-bottom:14px;background:#ffebee;padding:10px;border-radius:8px}
</style></head>
<body>
<div class="box">
  <div class="logo">
    <h1>🔐 ROTONDI GROUP ROMA</h1>
    <p>Pannello Amministratore</p>
  </div>
  {% if errore %}<p class="err">{{ errore }}</p>{% endif %}
  <form method="POST">
    <input type="password" name="password" placeholder="Password amministratore" autofocus>
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
.topbar h1{font-size:18px;font-weight:700;letter-spacing:0.5px}
.topbar a{color:#aaa;font-size:13px;text-decoration:none;padding:6px 14px;
  border:1px solid #555;border-radius:6px}
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
  border:2px solid #e0e0e0;border-radius:10px;font-size:14px;outline:none;font-family:inherit}
input:focus,textarea:focus{border-color:#0d0d14}
textarea{resize:vertical;min-height:140px;font-size:13px;line-height:1.7}
.btn-save{background:#0d0d14;color:#fff;border:none;padding:14px 36px;
  border-radius:10px;font-size:15px;cursor:pointer;font-weight:700;font-family:inherit}
.btn-save:hover{background:#333}
.msg{background:#e8f5e9;color:#2e7d32;padding:14px 18px;border-radius:10px;
  margin-bottom:20px;font-size:14px;font-weight:700;border-left:4px solid #4caf50}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#f5f5f5;padding:11px 10px;text-align:left;
  font-weight:700;color:#555;border-bottom:2px solid #e0e0e0;font-size:12px;
  text-transform:uppercase;letter-spacing:0.3px}
td{padding:10px 10px;border-bottom:1px solid #f0f0f0;vertical-align:top}
tr:hover td{background:#fafafa}
.badge{display:inline-block;padding:4px 10px;border-radius:6px;
  font-size:11px;font-weight:700;letter-spacing:0.3px}
.b-open{background:#fff3cd;color:#856404}
.b-ass{background:#d4edda;color:#155724}
.b-wait{background:#d1ecf1;color:#0c5460}
a.sblocca{color:#e53935;font-size:12px;text-decoration:none;
  padding:4px 10px;border:1px solid #e53935;border-radius:6px}
a.sblocca:hover{background:#e53935;color:#fff}
</style></head>
<body>
<div class="topbar">
  <h1>⚙️ Admin — Rotondi Group Roma</h1>
  <a href="/admin/logout">Esci</a>
</div>
<div class="container">
  {% if msg %}<div class="msg">{{ msg }}</div>{% endif %}
  <form method="POST">
    <div class="card">
      <h2>💶 Tariffe</h2>
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
      <h2>📋 Condizioni del Servizio</h2>
      <div class="field"><label>🇮🇹 Italiano</label>
        <textarea name="condizioni_it">{{ cond_it }}</textarea></div>
      <div class="field"><label>🇬🇧 English</label>
        <textarea name="condizioni_en">{{ cond_en }}</textarea></div>
    </div>
    <div class="card">
      <h2>🔐 Cambia Password Admin</h2>
      <div class="field" style="max-width:340px">
        <label>Nuova password (lascia vuoto per non cambiare)</label>
        <input type="password" name="nuova_password" placeholder="Nuova password">
      </div>
    </div>
    <button type="submit" class="btn-save">💾 Salva tutto</button>
  </form>

  <div class="card" style="margin-top:28px">
    <h2>📋 Ultime 50 Richieste Web</h2>
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
            {{ (r[5] or '')[:55] }}{% if r[5] and r[5]|length > 55 %}…{% endif %}
          </td>
          <td>
            {% if r[6]=='aperta' %}<span class="badge b-open">🟡 Aperta</span>
            {% elif r[6]=='assegnata' %}<span class="badge b-ass">✅ Assegnata</span>
            {% elif r[6]=='in_attesa_conferma' %}<span class="badge b-wait">⏳ In attesa</span>
            {% else %}<span class="badge b-wait">{{ r[6] }}</span>{% endif %}
          </td>
          <td style="font-size:12px">
            {% if r[7] %}<b>{{ r[7] }}</b><br>{% endif %}
            <span style="color:#888">{{ r[8] or '' }}</span>
          </td>
          <td style="font-size:12px;color:#888">{{ r[9] }}</td>
          <td>
            {% if r[6] != 'aperta' %}
            <a href="/admin/sblocca/{{ r[0] }}" class="sblocca"
               onclick="return confirm('Sbloccare la richiesta {{ r[0] }}?')">🔓 Sblocca</a>
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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
