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
    "- Uscita + 1h lavoro: 80,00 EUR + IVA\n"
    "- Ore successive: 40,00 EUR/h + IVA\n\n"
    "FUORI ROMA (Provincia, Lazio, resto d'Italia)\n"
    "- Km trasferta: 0,70 EUR/km + IVA (A/R)\n"
    "- Ore viaggio: 32,00 EUR/h + IVA (A/R)\n"
    "- Ore lavoro: 40,00 EUR/h + IVA\n\n"
    "Pagamento direttamente al tecnico al termine del servizio."
)

CONDIZIONI_EN_DEFAULT = (
    "Technical assistance is a paid service, even under warranty.\n\n"
    "Under warranty: defective parts replaced at no cost\n\n"
    "Always charged to customer:\n"
    "- Labour\n- Technician travel\n- Call-out fee\n\n"
    "ROME AREA (inside GRA ring road)\n"
    "- Call-out + 1h work: 80.00 EUR + VAT\n"
    "- Additional hours: 40.00 EUR/h + VAT\n\n"
    "OUTSIDE ROME\n"
    "- Travel km: 0.70 EUR/km + VAT (return)\n"
    "- Travel hours: 32.00 EUR/h + VAT (return)\n"
    "- Work hours: 40.00 EUR/h + VAT\n\n"
    "Payment directly to the technician at end of service."
)


# ── DATABASE ──────────────────────────────────────────────────────────────────
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


# ── PREVENTIVO ────────────────────────────────────────────────────────────────
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
            return {
                "zona": "inside_gra",
                "costo_min": tar["dentro_uscita"],
                "dist_label": el["distance"]["text"],
                "dur_label":  el["duration"]["text"]
            }
        dist_ar  = dist_km * 2
        dur_ar   = math.ceil(dur_h * 2)
        costo_km = dist_ar * tar["fuori_km"]
        costo_v  = dur_ar  * tar["fuori_ora_viaggio"]
        costo_l  = tar["fuori_ora_lavoro"]
        costo    = costo_km + costo_v + costo_l
        return {
            "zona": "outside_gra",
            "costo_min": round(costo, 2),
            "dist_label": el["distance"]["text"],
            "dur_label":  el["duration"]["text"],
            "dettaglio": {
                "km_ar":         f"{dist_ar:.0f}",
                "costo_km":      f"{costo_km:.2f}",
                "ore_viaggio":   dur_ar,
                "costo_viaggio": f"{costo_v:.2f}",
                "costo_lavoro":  f"{costo_l:.2f}"
            }
        }
    except Exception as e:
        app.logger.error(f"Maps: {e}"); return None


# ── TELEGRAM ──────────────────────────────────────────────────────────────────
def invia_telegram(testo, keyboard=None):
    try:
        import requests as rq
        payload = {"chat_id": TECNICI_GID, "text": testo, "parse_mode": "Markdown"}
        if keyboard: payload["reply_markup"] = json.dumps(keyboard)
        rq.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json=payload, timeout=10)
    except Exception as e:
        app.logger.error(f"TG: {e}")


def invia_foto_telegram(foto_file, caption):
    try:
        import requests as rq
        rq.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id": TECNICI_GID, "caption": caption},
            files={"photo": (foto_file.filename, foto_file.read(), foto_file.content_type)},
            timeout=20
        )
    except Exception as e:
        app.logger.error(f"TG foto: {e}")


def notifica_tg(testo, keyboard=None):
    """Alias per invia_telegram"""
    invia_telegram(testo, keyboard)


def notifica_bo(testo):
    """Notifica back office via Telegram"""
    if not BOT_TOKEN: return
    bo_ids = [x.strip() for x in os.environ.get("BACKOFFICE_IDS","").split(",") if x.strip()]
    try:
        import requests as rq
        for bo_id in bo_ids:
            rq.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id": bo_id, "text": testo, "parse_mode": "Markdown"},
                    timeout=10)
    except Exception as e:
        app.logger.error(f"BO notifica: {e}")


# ── EMAIL ─────────────────────────────────────────────────────────────────────
def invia_email_cliente(email, nome, protocollo, lingua="it"):
    """Email di conferma ricezione richiesta"""
    if not (email and SMTP_U and SMTP_P): return
    soggetto = {
        "it": f"Rotondi Group Roma - Richiesta ricevuta #{protocollo}",
        "en": f"Rotondi Group Roma - Request received #{protocollo}",
    }.get(lingua, f"Rotondi Group Roma - #{protocollo}")
    corpo = f"""
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
  <h1 style="color:#fff;font-size:22px;margin:0">ROTONDI GROUP ROMA</h1>
  <p style="color:#aaa;font-size:13px;margin:4px 0 0">Assistenza Tecnica Macchinari</p>
</div>
<div style="background:#fff;padding:32px;border-radius:0 0 8px 8px">
  <h2 style="color:#0d0d14;margin-top:0">Richiesta ricevuta!</h2>
  <p>Gentile <b>{nome}</b>,</p>
  <p>La sua richiesta di assistenza tecnica e' stata ricevuta.</p>
  <div style="background:#f8f8f8;border-radius:8px;padding:16px;margin:20px 0;border-left:4px solid #0d0d14">
    <p style="margin:0 0 4px"><b>Numero protocollo:</b></p>
    <p style="font-size:24px;font-weight:bold;color:#0d0d14;margin:0">{protocollo}</p>
  </div>
  <p>Un nostro tecnico la contattara' al piu' presto con una proposta di appuntamento.</p>
  <div style="background:#fff3cd;border-radius:8px;padding:12px;margin:16px 0">
    <p style="margin:0;font-size:13px">
      <b>Per annullare urgentemente:</b><br>+39 06 41 40 0514
    </p>
  </div>
  <p style="color:#666;font-size:13px;margin-top:24px">Ufficio Roma: +39 06 41400617</p>
  <p style="color:#999;font-size:11px;border-top:1px solid #eee;padding-top:16px;margin-top:24px">
    Rotondi Group Srl - Via F.lli Rosselli 14/16, 20019 Settimo Milanese (MI)
  </p>
</div></div>"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = soggetto; msg["From"] = SMTP_F; msg["To"] = email
        msg.attach(MIMEText(corpo, "html"))
        with smtplib.SMTP(SMTP_H, SMTP_PO) as s:
            s.starttls(); s.login(SMTP_U, SMTP_P)
            s.sendmail(SMTP_F, email, msg.as_string())
    except Exception as e:
        app.logger.error(f"Email conferma: {e}")


def invia_email_proposta(email, nome, protocollo, tecnico, data_ora, lingua="it"):
    """Email con proposta appuntamento e link accetta/rifiuta"""
    if not (email and SMTP_U and SMTP_P): return
    link_accetta = f"{BASE_URL}/proposta/{protocollo}/accetta"
    link_rifiuta = f"{BASE_URL}/proposta/{protocollo}/rifiuta"
    soggetti = {
        "it": f"Rotondi Group Roma - Proposta appuntamento #{protocollo}",
        "en": f"Rotondi Group Roma - Appointment proposal #{protocollo}",
    }
    corpo_it = f"""
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
  <h1 style="color:#fff;font-size:22px;margin:0">ROTONDI GROUP ROMA</h1>
  <p style="color:#aaa;font-size:13px;margin:4px 0 0">Assistenza Tecnica Macchinari</p>
</div>
<div style="background:#fff;padding:32px;border-radius:0 0 8px 8px">
  <h2 style="color:#0d0d14;margin-top:0">Proposta di Appuntamento</h2>
  <p>Gentile <b>{nome}</b>,</p>
  <p>Il tecnico <b>{tecnico}</b> e' disponibile per intervenire il:</p>
  <div style="background:#f0f8ff;border-radius:10px;padding:20px;margin:20px 0;
              text-align:center;border:2px solid #0d0d14">
    <p style="font-size:13px;color:#666;margin:0 0 8px">Data e ora proposta</p>
    <p style="font-size:26px;font-weight:bold;color:#0d0d14;margin:0">{data_ora}</p>
  </div>
  <p style="margin-bottom:6px"><b>Protocollo:</b> {protocollo}</p>
  <p style="color:#666;font-size:13px;margin:16px 0">
    La preghiamo di rispondere entro 24 ore.
    Se non risponde, la richiesta tornera' disponibile per altri tecnici.
  </p>
  <table style="width:100%;border-collapse:collapse;margin:24px 0">
    <tr>
      <td style="padding:8px;text-align:center">
        <a href="{link_accetta}"
           style="background:#4caf50;color:#fff;padding:16px 36px;border-radius:8px;
                  text-decoration:none;font-size:18px;font-weight:700;display:inline-block">
          Accetto
        </a>
      </td>
      <td style="padding:8px;text-align:center">
        <a href="{link_rifiuta}"
           style="background:#e53935;color:#fff;padding:16px 36px;border-radius:8px;
                  text-decoration:none;font-size:18px;font-weight:700;display:inline-block">
          Rifiuto
        </a>
      </td>
    </tr>
  </table>
  <p style="font-size:12px;color:#999;text-align:center">
    Se i pulsanti non funzionano, copia questi link nel browser:<br>
    Accetta: {link_accetta}<br>
    Rifiuta: {link_rifiuta}
  </p>
  <div style="background:#fff3cd;border-radius:8px;padding:12px;margin-top:24px">
    <p style="margin:0;font-size:13px">
      Per informazioni: <b>+39 06 41400617</b><br>
      Per annullare: <b>+39 06 41 40 0514</b>
    </p>
  </div>
  <p style="color:#999;font-size:11px;border-top:1px solid #eee;padding-top:16px;margin-top:24px">
    Rotondi Group Srl - Via F.lli Rosselli 14/16, 20019 Settimo Milanese (MI)
  </p>
</div></div>"""

    corpo_en = f"""
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
  <h1 style="color:#fff;font-size:22px;margin:0">ROTONDI GROUP ROMA</h1>
  <p style="color:#aaa;font-size:13px;margin:4px 0 0">Technical Assistance</p>
</div>
<div style="background:#fff;padding:32px;border-radius:0 0 8px 8px">
  <h2 style="color:#0d0d14;margin-top:0">Appointment Proposal</h2>
  <p>Dear <b>{nome}</b>,</p>
  <p>Technician <b>{tecnico}</b> is available on:</p>
  <div style="background:#f0f8ff;border-radius:10px;padding:20px;margin:20px 0;
              text-align:center;border:2px solid #0d0d14">
    <p style="font-size:13px;color:#666;margin:0 0 8px">Proposed date and time</p>
    <p style="font-size:26px;font-weight:bold;color:#0d0d14;margin:0">{data_ora}</p>
  </div>
  <p style="margin-bottom:6px"><b>Protocol:</b> {protocollo}</p>
  <p style="color:#666;font-size:13px;margin:16px 0">
    Please respond within 24 hours.
  </p>
  <table style="width:100%;border-collapse:collapse;margin:24px 0">
    <tr>
      <td style="padding:8px;text-align:center">
        <a href="{link_accetta}"
           style="background:#4caf50;color:#fff;padding:16px 36px;border-radius:8px;
                  text-decoration:none;font-size:18px;font-weight:700;display:inline-block">
          Accept
        </a>
      </td>
      <td style="padding:8px;text-align:center">
        <a href="{link_rifiuta}"
           style="background:#e53935;color:#fff;padding:16px 36px;border-radius:8px;
                  text-decoration:none;font-size:18px;font-weight:700;display:inline-block">
          Decline
        </a>
      </td>
    </tr>
  </table>
  <p style="font-size:12px;color:#999;text-align:center">
    If buttons don't work:<br>
    Accept: {link_accetta}<br>
    Decline: {link_rifiuta}
  </p>
  <div style="background:#fff3cd;border-radius:8px;padding:12px;margin-top:24px">
    <p style="margin:0;font-size:13px">Info: <b>+39 06 41400617</b></p>
  </div>
</div></div>"""

    corpo   = corpo_en if lingua == "en" else corpo_it
    oggetto = soggetti.get(lingua, soggetti["it"])
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = oggetto; msg["From"] = SMTP_F; msg["To"] = email
        msg.attach(MIMEText(corpo, "html"))
        with smtplib.SMTP(SMTP_H, SMTP_PO) as s:
            s.starttls(); s.login(SMTP_U, SMTP_P)
            s.sendmail(SMTP_F, email, msg.as_string())
        app.logger.info(f"Email proposta inviata a {email} per {protocollo}")
    except Exception as e:
        app.logger.error(f"Email proposta: {e}")


def invia_email_conferma_finale(email, nome, protocollo, tecnico, data_ora, lingua, confermata):
    """Email finale: appuntamento confermato o rifiutato"""
    if not (email and SMTP_U and SMTP_P): return
    if confermata:
        soggetto = {"it": f"Rotondi Group Roma - Appuntamento confermato #{protocollo}",
                    "en": f"Rotondi Group Roma - Appointment confirmed #{protocollo}"}.get(lingua, f"#{protocollo}")
        corpo_it = f"""
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
  <h1 style="color:#fff;font-size:22px;margin:0">ROTONDI GROUP ROMA</h1>
</div>
<div style="background:#fff;padding:32px;border-radius:0 0 8px 8px">
  <div style="text-align:center;margin-bottom:24px">
    <div style="font-size:48px">&#127881;</div>
    <h2 style="color:#4caf50;margin:8px 0">Appuntamento Confermato!</h2>
  </div>
  <p>Gentile <b>{nome}</b>,</p>
  <p>Il Suo appuntamento e' confermato:</p>
  <div style="background:#f0fff4;border-radius:10px;padding:20px;margin:20px 0;
              text-align:center;border:2px solid #4caf50">
    <p style="font-size:13px;color:#666;margin:0 0 8px">Data e ora intervento</p>
    <p style="font-size:26px;font-weight:bold;color:#2e7d32;margin:0">{data_ora}</p>
    <p style="font-size:14px;color:#444;margin:8px 0 0">Tecnico: <b>{tecnico}</b></p>
  </div>
  <div style="background:#fff3cd;border-radius:8px;padding:12px;margin-top:16px">
    <p style="margin:0;font-size:13px">
      Ufficio Roma: <b>+39 06 41400617</b><br>
      Per annullare: <b>+39 06 41 40 0514</b>
    </p>
  </div>
</div></div>"""
        corpo = corpo_it
    else:
        soggetto = {"it": f"Rotondi Group Roma - Proposta rifiutata #{protocollo}",
                    "en": f"Rotondi Group Roma - Proposal declined #{protocollo}"}.get(lingua, f"#{protocollo}")
        corpo = f"""
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
  <h1 style="color:#fff;font-size:22px;margin:0">ROTONDI GROUP ROMA</h1>
</div>
<div style="background:#fff;padding:32px;border-radius:0 0 8px 8px">
  <h2 style="color:#0d0d14;margin-top:0">Proposta rifiutata</h2>
  <p>Gentile <b>{nome}</b>,</p>
  <p>La Sua richiesta e' ancora aperta. Un altro tecnico la contattara' a breve.</p>
  <div style="background:#fff3cd;border-radius:8px;padding:12px;margin-top:16px">
    <p style="margin:0;font-size:13px">Per info: <b>+39 06 41400617</b></p>
  </div>
</div></div>"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = soggetto; msg["From"] = SMTP_F; msg["To"] = email
        msg.attach(MIMEText(corpo, "html"))
        with smtplib.SMTP(SMTP_H, SMTP_PO) as s:
            s.starttls(); s.login(SMTP_U, SMTP_P)
            s.sendmail(SMTP_F, email, msg.as_string())
    except Exception as e:
        app.logger.error(f"Email conferma finale: {e}")


# ── PAGINA RISPOSTA ───────────────────────────────────────────────────────────
def pagina_risposta(tipo, protocollo, tecnico="", data_ora="", lingua="it"):
    contenuti = {
        "accettata": {
            "it": ("&#127881;", "Appuntamento Confermato!", "#4caf50",
                   f"Il tecnico <b>{tecnico}</b> interverr&agrave; il:<br><br>"
                   f"<strong style='font-size:22px;color:#2e7d32'>{data_ora}</strong><br><br>"
                   f"Per informazioni: <b>+39 06 41400617</b><br>"
                   f"Per annullare: <b>+39 06 41 40 0514</b>"),
            "en": ("&#127881;", "Appointment Confirmed!", "#4caf50",
                   f"Technician <b>{tecnico}</b> will intervene on:<br><br>"
                   f"<strong style='font-size:22px;color:#2e7d32'>{data_ora}</strong><br><br>"
                   f"Info: <b>+39 06 41400617</b><br>To cancel: <b>+39 06 41 40 0514</b>"),
        },
        "rifiutata": {
            "it": ("&#8617;&#65039;", "Proposta Rifiutata", "#ff9800",
                   "La Sua richiesta &egrave; ancora aperta.<br><br>"
                   "Un altro tecnico la contatter&agrave; a breve con una nuova proposta.<br><br>"
                   "Per info: <b>+39 06 41400617</b>"),
            "en": ("&#8617;&#65039;", "Proposal Declined", "#ff9800",
                   "Your request is still open.<br><br>"
                   "Another technician will contact you shortly.<br><br>"
                   "Info: <b>+39 06 41400617</b>"),
        },
        "gia_confermata": {
            "it": ("&#9989;", "Gi&agrave; Confermato", "#4caf50",
                   f"Questo appuntamento &egrave; gi&agrave; stato confermato.<br><br>"
                   f"Data: <b>{data_ora}</b><br>Tecnico: <b>{tecnico}</b>"),
            "en": ("&#9989;", "Already Confirmed", "#4caf50",
                   f"This appointment is already confirmed.<br><br>"
                   f"Date: <b>{data_ora}</b><br>Technician: <b>{tecnico}</b>"),
        },
        "gia_rifiutata": {
            "it": ("&#8505;&#65039;", "Gi&agrave; Rifiutata", "#666",
                   "Questa proposta &egrave; gi&agrave; stata rifiutata."),
            "en": ("&#8505;&#65039;", "Already Declined", "#666",
                   "This proposal has already been declined."),
        },
        "non_trovata": {
            "it": ("&#9888;&#65039;", "Richiesta non trovata", "#e53935",
                   f"Il protocollo <b>{protocollo}</b> non &egrave; stato trovato."),
            "en": ("&#9888;&#65039;", "Request not found", "#e53935",
                   f"Protocol <b>{protocollo}</b> was not found."),
        },
        "non_valida": {
            "it": ("&#9888;&#65039;", "Link non valido", "#e53935",
                   "Questo link non &egrave; pi&ugrave; valido o &egrave; gi&agrave; stato utilizzato."),
            "en": ("&#9888;&#65039;", "Invalid link", "#e53935",
                   "This link is no longer valid or has already been used."),
        },
        "errore": {
            "it": ("&#10060;", "Errore", "#e53935",
                   "Si &egrave; verificato un errore. Contatta l'ufficio: +39 06 41400617"),
            "en": ("&#10060;", "Error", "#e53935",
                   "An error occurred. Contact us: +39 06 41400617"),
        },
    }
    c = contenuti.get(tipo, contenuti["errore"])
    d = c.get(lingua, c.get("it"))
    icon, titolo, colore, testo = d
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rotondi Group Roma</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f0f0f0;min-height:100vh}}
.header{{background:#0d0d14;color:#fff;padding:18px;text-align:center}}
.header h1{{font-size:18px;letter-spacing:1px}}
.wrap{{display:flex;align-items:center;justify-content:center;min-height:calc(100vh - 60px);padding:24px 16px}}
.box{{background:#fff;border-radius:16px;padding:40px 32px;max-width:460px;
  width:100%;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.1)}}
.bar{{height:5px;background:{colore};border-radius:3px;margin-bottom:28px}}
.icon{{font-size:56px;margin-bottom:16px}}
h2{{font-size:24px;color:{colore};margin-bottom:12px}}
.proto{{font-size:13px;color:#999;margin-bottom:20px;background:#f5f5f5;
  padding:6px 14px;border-radius:20px;display:inline-block}}
p{{font-size:15px;color:#444;line-height:1.7}}
</style>
</head>
<body>
<div class="header"><h1>ROTONDI GROUP ROMA</h1></div>
<div class="wrap">
  <div class="box">
    <div class="bar"></div>
    <div class="icon">{icon}</div>
    <h2>{titolo}</h2>
    <div class="proto">Protocollo: <strong>{protocollo}</strong></div>
    <p>{testo}</p>
  </div>
</div>
</body></html>"""


# ── ROUTES ────────────────────────────────────────────────────────────────────
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
    if not indirizzo: return jsonify({"error":"indirizzo mancante"}), 400
    prev = calcola_preventivo(indirizzo)
    if not prev: return jsonify({"error":"impossibile calcolare"}), 200
    return jsonify(prev)


@app.route("/invia", methods=["POST"])
def route_invia():
    try:
        is_multipart = request.content_type and 'multipart' in request.content_type
        if is_multipart:
            data           = request.form
            foto_targhetta = request.files.get('foto_targhetta')
            foto_macchina  = request.files.get('foto_macchina')
        else:
            data           = request.get_json(force=True)
            foto_targhetta = None
            foto_macchina  = None

        protocollo = "RG" + datetime.now().strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:4].upper()
        via       = (data.get("via","") or "").strip()
        civico    = (data.get("civico","") or "").strip()
        cap       = (data.get("cap","") or "").strip()
        citta     = (data.get("citta","") or "").strip()
        provincia = (data.get("provincia","") or "").strip().upper()
        indirizzo = f"{via}, {civico}, {cap} {citta} ({provincia}), Italia"
        lingua    = data.get("lingua","it")
        prev_json = data.get("preventivo")

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO richieste_web
                (protocollo,nome,via,civico,cap,citta,provincia,indirizzo,
                 telefono,email,marca,modello,seriale,problema,data,lingua,preventivo)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (protocollo,
                  data.get("nome",""), via, civico, cap, citta, provincia, indirizzo,
                  data.get("telefono",""), data.get("email",""),
                  data.get("marca",""), data.get("modello",""),
                  data.get("seriale",""), data.get("problema",""),
                  datetime.now().strftime("%d/%m/%Y %H:%M"), lingua, prev_json))
            conn.commit()

        prev_text = ""
        if prev_json:
            try:
                prev = json.loads(prev_json)
                if prev.get("zona") == "outside_gra":
                    prev_text = (f"\n💰 *Preventivo:* EUR {prev['costo_min']:.2f} + IVA"
                                 f" ({prev.get('dist_label','')} — {prev.get('dur_label','')})")
                else:
                    prev_text = f"\n💰 *Zona Roma (GRA):* EUR {prev.get('costo_min',80):.2f} + IVA"
            except: pass

        link_maps = "https://www.google.com/maps/search/?api=1&query=" + indirizzo.replace(" ","+")
        FLAG = {"it":"🇮🇹","en":"🇬🇧","bn":"🇧🇩","zh":"🇨🇳","ar":"🇸🇦"}.get(lingua,"🌍")
        foto_info = ""
        if foto_targhetta and foto_targhetta.filename: foto_info += "\n📸 Foto targhetta: allegata"
        if foto_macchina  and foto_macchina.filename:  foto_info += "\n📷 Foto macchina: allegata"

        testo = (
            f"🌐 *NUOVA RICHIESTA WEB* {FLAG}\n{'─'*30}\n"
            f"🔖 *Protocollo:* `{protocollo}`\n"
            f"👤 *Cliente:* {data.get('nome','')}\n"
            f"📍 *Indirizzo:* {indirizzo}\n"
            f"🗺 [Apri su Google Maps]({link_maps})\n"
            f"📞 *Tel:* {data.get('telefono','')}\n"
            f"📧 *Email:* {data.get('email','') or '—'}\n"
            f"🏷 *Marca:* {data.get('marca','')} | *Modello:* {data.get('modello','') or '—'}\n"
            f"🔢 *Seriale:* {data.get('seriale','') or '—'}\n"
            f"🔧 *Problema:* {data.get('problema','')}"
            f"{prev_text}{foto_info}\n{'─'*30}\n"
            f"⏰ Clicca per programmare l'intervento:"
        )
        # Unico pulsante: scegli data e ora
        keyboard = {"inline_keyboard": [[
            {"text": "🗓 Scegli data e ora intervento",
             "callback_data": f"wfascia|{protocollo}|start"}
        ]]}
        invia_telegram(testo, keyboard)

        # Foto al gruppo
        if foto_targhetta and foto_targhetta.filename:
            invia_foto_telegram(foto_targhetta, f"📸 Targhetta — {protocollo}")
        if foto_macchina and foto_macchina.filename:
            invia_foto_telegram(foto_macchina, f"📷 Macchina — {protocollo}")

        # Email conferma al cliente
        invia_email_cliente(data.get("email",""), data.get("nome",""), protocollo, lingua)

        return jsonify({"protocollo": protocollo, "ok": True})

    except Exception as e:
        app.logger.error(f"Errore /invia: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/proposta/<protocollo>/accetta")
def proposta_accetta(protocollo):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            r = conn.execute(
                "SELECT nome,tecnico,fascia,email,lingua,stato"
                " FROM richieste_web WHERE protocollo=?",
                (protocollo,)).fetchone()
    except:
        return pagina_risposta("errore", protocollo)
    if not r: return pagina_risposta("non_trovata", protocollo)
    nome, tecnico, data_ora, email, lingua, stato = r
    lingua = lingua or "it"
    if stato == "assegnata":
        return pagina_risposta("gia_confermata", protocollo, tecnico, data_ora, lingua)
    if stato != "in_attesa_conferma":
        return pagina_risposta("non_valida", protocollo, lingua=lingua)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE richieste_web SET stato='assegnata' WHERE protocollo=?", (protocollo,))
        conn.commit()

    # Notifica gruppo tecnici
    notifica_tg(
        f"✅ *RICHIESTA WEB {protocollo} — CONFERMATA*\n\n"
        f"👤 {nome}\n👨‍🔧 {tecnico}\n📅 {data_ora}"
    )
    # Notifica back office
    notifica_bo(
        f"✅ *Web {protocollo} CONFERMATA*\n"
        f"👤 {nome}\n👨‍🔧 {tecnico}\n📅 {data_ora}"
    )
    # Email conferma finale al cliente
    if email:
        invia_email_conferma_finale(email, nome, protocollo, tecnico, data_ora, lingua, True)

    return pagina_risposta("accettata", protocollo, tecnico, data_ora, lingua)


@app.route("/proposta/<protocollo>/rifiuta")
def proposta_rifiuta(protocollo):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            r = conn.execute(
                "SELECT nome,tecnico,fascia,email,lingua,stato"
                " FROM richieste_web WHERE protocollo=?",
                (protocollo,)).fetchone()
    except:
        return pagina_risposta("errore", protocollo)
    if not r: return pagina_risposta("non_trovata", protocollo)
    nome, tecnico, data_ora, email, lingua, stato = r
    lingua = lingua or "it"
    if stato == "aperta":
        return pagina_risposta("gia_rifiutata", protocollo, lingua=lingua)
    if stato != "in_attesa_conferma":
        return pagina_risposta("non_valida", protocollo, lingua=lingua)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE richieste_web SET stato='aperta', tecnico=NULL, fascia=NULL
            WHERE protocollo=?
        """, (protocollo,))
        conn.commit()

    # Notifica gruppo tecnici con pulsante per riprogrammare
    notifica_tg(
        f"❌ *RICHIESTA WEB {protocollo} — PROPOSTA RIFIUTATA*\n\n"
        f"👤 {nome}\n"
        f"La richiesta e' tornata disponibile!",
        keyboard={"inline_keyboard": [[
            {"text": "🗓 Scegli nuova data e ora",
             "callback_data": f"wfascia|{protocollo}|start"}
        ]]}
    )
    # Notifica back office
    notifica_bo(
        f"❌ *Web {protocollo} RIFIUTATA*\n"
        f"👤 {nome}\n👨‍🔧 {tecnico}\nTornata disponibile"
    )
    # Email conferma rifiuto al cliente
    if email:
        invia_email_conferma_finale(email, nome, protocollo, tecnico, data_ora, lingua, False)

    return pagina_risposta("rifiutata", protocollo, lingua=lingua)


# ── ADMIN ─────────────────────────────────────────────────────────────────────
@app.route("/admin", methods=["GET","POST"])
def admin():
    if request.method == "POST" and "password" in request.form:
        if request.form["password"] == get_config("admin_pass","rotondi2024"):
            session["admin"] = True
        else:
            return render_template_string(HTML_LOGIN, errore="Password errata")
    if not session.get("admin"):
        return render_template_string(HTML_LOGIN, errore="")
    msg = ""
    if request.method == "POST":
        for k in TARIFFE_DEFAULT:
            val = request.form.get(f"tariffa_{k}")
            if val:
                try: set_config(f"tariffa_{k}", float(val.replace(",",".")))
                except: pass
        for lang in ["it","en"]:
            val = request.form.get(f"condizioni_{lang}")
            if val: set_config(f"condizioni_{lang}", val)
        np = request.form.get("nuova_password","").strip()
        if np: set_config("admin_pass", np)
        msg = "Salvato con successo!"
    tar     = get_tariffe()
    cond_it = get_config("condizioni_it", CONDIZIONI_IT_DEFAULT)
    cond_en = get_config("condizioni_en", CONDIZIONI_EN_DEFAULT)
    with sqlite3.connect(DB_PATH) as conn:
        richieste = conn.execute("""
            SELECT protocollo,nome,indirizzo,telefono,marca,problema,
                   stato,tecnico,fascia,data,lingua
            FROM richieste_web ORDER BY id DESC LIMIT 50
        """).fetchall()
    return render_template_string(HTML_ADMIN,
        tar=tar, cond_it=cond_it, cond_en=cond_en,
        richieste=richieste, msg=msg)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None); return redirect("/admin")


@app.route("/admin/sblocca/<protocollo>")
def admin_sblocca(protocollo):
    if not session.get("admin"): return redirect("/admin")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE richieste_web SET stato='aperta', tecnico=NULL, fascia=NULL
            WHERE protocollo=?
        """, (protocollo,)); conn.commit()
    return redirect("/admin")


@app.route("/health")
def health():
    return "OK", 200


# ── HTML FORM ─────────────────────────────────────────────────────────────────
HTML_FORM = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Assistenza Tecnica - Rotondi Group Roma</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#f0f0f0;min-height:100vh}
.header{background:#0d0d14;color:#fff;padding:20px;text-align:center}
.header h1{font-size:22px;letter-spacing:1px}
.header p{font-size:13px;color:#aaa;margin-top:4px}
.lang-bar{background:#fff;border-bottom:1px solid #eee;padding:10px;
  text-align:center;display:flex;justify-content:center;flex-wrap:wrap;gap:6px}
.lang-btn{display:inline-flex;align-items:center;gap:5px;font-size:13px;
  color:#555;cursor:pointer;padding:6px 12px;border-radius:20px;
  border:1.5px solid #ddd;background:#fff;transition:all .2s;font-family:inherit;line-height:1}
.lang-btn:hover{border-color:#0d0d14;color:#0d0d14}
.lang-btn.active{color:#fff;background:#0d0d14;border-color:#0d0d14;font-weight:700}
.lang-flag{font-size:20px}
.container{max-width:640px;margin:24px auto;padding:0 16px 60px}
.steps{display:flex;justify-content:center;gap:8px;margin-bottom:24px}
.step{width:32px;height:4px;border-radius:2px;background:#ddd;transition:background .3s}
.step.active{background:#0d0d14}.step.done{background:#4caf50}
.card{background:#fff;border-radius:12px;padding:24px;margin-bottom:16px;
  box-shadow:0 2px 8px rgba(0,0,0,.07)}
.card h2{font-size:15px;font-weight:700;color:#0d0d14;margin-bottom:16px;
  padding-bottom:10px;border-bottom:2px solid #f0f0f0}
.field{margin-bottom:14px}
label{display:block;font-size:13px;font-weight:600;color:#444;margin-bottom:5px}
input,textarea{width:100%;padding:10px 12px;border:1.5px solid #ddd;border-radius:8px;
  font-size:14px;outline:none;transition:border .2s;font-family:inherit}
input:focus,textarea:focus{border-color:#0d0d14}
textarea{resize:vertical;min-height:80px}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:480px){.row2{grid-template-columns:1fr}}
.btn{width:100%;background:#0d0d14;color:#fff;border:none;padding:14px;
  border-radius:10px;font-size:15px;font-weight:700;cursor:pointer;
  transition:opacity .2s;margin-top:4px;font-family:inherit}
.btn:hover{opacity:.88}.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-sec{width:100%;background:none;border:none;color:#666;font-size:14px;
  padding:10px;cursor:pointer;margin-top:6px;font-family:inherit}
.btn-calc{width:100%;background:#444;color:#fff;border:none;padding:11px;
  border-radius:8px;font-size:14px;cursor:pointer;margin-bottom:10px;
  transition:opacity .2s;font-family:inherit}
.btn-calc:hover{opacity:.88}
.prev-box{border-radius:10px;padding:16px;margin:10px 0;display:none;border:1.5px solid}
.prev-inside{background:#e8f5e9;border-color:#4caf50}
.prev-outside{background:#fff8e1;border-color:#ff9800}
.prev-box h3{font-size:14px;font-weight:700;margin-bottom:6px}
.prev-importo{font-size:22px;font-weight:700;margin:6px 0}
.prev-inside .prev-importo{color:#2e7d32}
.prev-outside .prev-importo{color:#e65100}
.prev-detail{font-size:12px;color:#666;margin-top:4px}
.prev-nota{font-size:11px;color:#999;margin-top:6px}
.chk-row{display:flex;align-items:flex-start;gap:10px;margin-bottom:10px}
.chk-row input[type=checkbox]{width:18px;height:18px;margin-top:2px;flex-shrink:0;cursor:pointer}
.chk-row label{font-size:13px;color:#444;font-weight:400;cursor:pointer}
.cond-box{background:#f8f8f8;border:1px solid #ddd;border-radius:8px;padding:14px;
  font-size:13px;line-height:1.7;max-height:180px;overflow-y:auto;
  white-space:pre-wrap;margin-bottom:12px}
.loading{display:none;text-align:center;padding:10px;font-size:13px;color:#666}
.spin{display:inline-block;width:16px;height:16px;border:2px solid #ddd;
  border-top-color:#0d0d14;border-radius:50%;animation:spin .7s linear infinite;
  vertical-align:middle;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
.foto-area{border:2px dashed #ddd;border-radius:10px;padding:14px;text-align:center;
  cursor:pointer;transition:border .2s;background:#fafafa;margin-top:4px}
.foto-area:hover{border-color:#0d0d14;background:#f5f5f5}
.foto-area.has-foto{border-color:#4caf50;background:#f1f8e9}
.foto-preview-img{width:72px;height:72px;object-fit:cover;border-radius:8px;
  margin:0 auto 6px;display:block}
.foto-hint{font-size:13px;color:#888}
.foto-icon{font-size:26px;margin-bottom:4px}
.ok-box{text-align:center;padding:40px 20px}
.ok-icon{font-size:56px;margin-bottom:16px}
.ok-box h2{font-size:22px;color:#0d0d14;margin-bottom:8px}
.ok-proto{font-size:22px;font-weight:700;color:#0d0d14;background:#f0f0f0;
  padding:10px 20px;border-radius:8px;display:inline-block;margin:14px 0;letter-spacing:2px}
.ok-box p{font-size:14px;color:#555;line-height:1.7}
</style>
</head>
<body>
<div class="header">
  <h1>ROTONDI GROUP ROMA</h1>
  <p>Assistenza Tecnica Macchinari</p>
</div>

<div class="lang-bar">
  <button class="lang-btn active" onclick="setLang('it')" id="l_it">
    <span class="lang-flag">&#127470;&#127481;</span> Italiano
  </button>
  <button class="lang-btn" onclick="setLang('en')" id="l_en">
    <span class="lang-flag">&#127468;&#127463;</span> English
  </button>
  <button class="lang-btn" onclick="setLang('bn')" id="l_bn">
    <span class="lang-flag">&#127463;&#127465;</span> &#2476;&#2494;&#2434;&#2482;&#2494;
  </button>
  <button class="lang-btn" onclick="setLang('zh')" id="l_zh">
    <span class="lang-flag">&#127464;&#127475;</span> &#20013;&#25991;
  </button>
  <button class="lang-btn" onclick="setLang('ar')" id="l_ar">
    <span class="lang-flag">&#127480;&#127462;</span> &#1575;&#1604;&#1593;&#1585;&#1576;&#1610;&#1577;
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
      <h2 id="t_gdpr_h">Privacy (GDPR)</h2>
      <div class="cond-box">Rotondi Group Srl
Via F.lli Rosselli 14/16, 20019 Settimo Milanese (MI)
segnalazioni-privacy@rotondigroup.it

I tuoi dati saranno trattati per gestire la richiesta di assistenza tecnica.
Conservazione: max 2 anni. Diritti: accesso, rettifica, cancellazione.</div>
      <div class="chk-row">
        <input type="checkbox" id="chk_gdpr">
        <label for="chk_gdpr" id="t_gdpr_lbl">Accetto il trattamento dei dati personali ai sensi del GDPR</label>
      </div>
    </div>
    <div class="card">
      <h2 id="t_cond_h">Condizioni del Servizio</h2>
      <div class="cond-box" id="cond_box">{{ condizioni_it }}</div>
      <div class="chk-row">
        <input type="checkbox" id="chk_cond">
        <label for="chk_cond" id="t_cond_lbl">Accetto le condizioni del servizio</label>
      </div>
    </div>
    <button class="btn" onclick="goStep2()" id="btn1">Continua &#8594;</button>
  </div>

  <!-- STEP 2 -->
  <div id="step2" style="display:none">
    <div class="card">
      <h2 id="t_dati_h">Dati Personali</h2>
      <div class="field"><label id="t_nome">Nome e Cognome *</label>
        <input id="nome" type="text" autocomplete="name"></div>
      <div class="field"><label id="t_email">Email</label>
        <input id="email" type="email" autocomplete="email"></div>
      <div class="field"><label id="t_tel">Telefono *</label>
        <input id="telefono" type="tel" autocomplete="tel"></div>
    </div>
    <div class="card">
      <h2 id="t_ind_h">Indirizzo Intervento</h2>
      <div class="field"><label id="t_via">Via / Piazza *</label>
        <input id="via" type="text" placeholder="Es: Via Roma" autocomplete="address-line1"></div>
      <div class="row2">
        <div class="field"><label id="t_civico">N&#176; Civico *</label>
          <input id="civico" type="text" placeholder="Es: 10"></div>
        <div class="field"><label id="t_cap">CAP *</label>
          <input id="cap" type="text" placeholder="Es: 00100" maxlength="5"></div>
      </div>
      <div class="row2">
        <div class="field"><label id="t_citta">Citt&#224; *</label>
          <input id="citta" type="text" autocomplete="address-level2"></div>
        <div class="field"><label id="t_prov">Provincia *</label>
          <input id="provincia" type="text" placeholder="RM" maxlength="2"></div>
      </div>
      <button class="btn-calc" onclick="calcolaPreventivo()" id="btn_calc">
        &#128205; Verifica distanza e preventivo
      </button>
      <div class="loading" id="loading_p">
        <span class="spin"></span><span id="t_calc_lbl">Calcolo in corso...</span>
      </div>
      <div class="prev-box" id="prev_box">
        <h3 id="t_prev_h">Preventivo Indicativo</h3>
        <p id="prev_zona"></p>
        <div class="prev-importo" id="prev_imp"></div>
        <p class="prev-detail" id="prev_det"></p>
        <p class="prev-nota" id="t_prev_nota">Preventivo indicativo per 1h di lavoro + IVA</p>
      </div>
    </div>
    <button class="btn" onclick="goStep3()" id="btn2">Continua &#8594;</button>
    <button class="btn-sec" onclick="goStep1()" id="t_back1">&#8592; Indietro</button>
  </div>

  <!-- STEP 3 -->
  <div id="step3" style="display:none">
    <div class="card">
      <h2 id="t_mac_h">Dati Macchina</h2>
      <div class="row2">
        <div class="field"><label id="t_marca">Marca *</label>
          <input id="marca" type="text" placeholder="Es: Samsung, LG, Bosch"></div>
        <div class="field"><label id="t_modello">Modello</label>
          <input id="modello" type="text" placeholder="Es: WW90T534"></div>
      </div>
      <div class="field"><label id="t_seriale">Numero Seriale</label>
        <input id="seriale" type="text" placeholder="Dalla targhetta del macchinario"></div>
      <div class="field"><label id="t_prob">Descrivi il Problema *</label>
        <textarea id="problema" placeholder="Cosa succede? Da quando? Hai gia provato qualcosa?"></textarea></div>
    </div>
    <div class="card">
      <h2 id="t_foto_h">Foto (opzionale)</h2>
      <div class="field">
        <label id="t_foto_targ">Foto targhetta macchina</label>
        <div class="foto-area" id="area_targhetta"
             onclick="document.getElementById('inp_targhetta').click()">
          <div id="prev_targhetta">
            <div class="foto-icon">&#128248;</div>
            <div class="foto-hint" id="hint_targhetta">Tocca per aggiungere la foto</div>
          </div>
        </div>
        <input type="file" id="inp_targhetta" accept="image/*" capture="environment"
               style="display:none"
               onchange="mostraFoto(this,'prev_targhetta','area_targhetta','hint_targhetta')">
      </div>
      <div class="field">
        <label id="t_foto_mac">Foto della macchina</label>
        <div class="foto-area" id="area_macchina"
             onclick="document.getElementById('inp_macchina').click()">
          <div id="prev_macchina">
            <div class="foto-icon">&#128247;</div>
            <div class="foto-hint" id="hint_macchina">Tocca per aggiungere la foto</div>
          </div>
        </div>
        <input type="file" id="inp_macchina" accept="image/*" capture="environment"
               style="display:none"
               onchange="mostraFoto(this,'prev_macchina','area_macchina','hint_macchina')">
      </div>
    </div>
    <button class="btn" onclick="invia()" id="btn3">Invia Richiesta</button>
    <button class="btn-sec" onclick="goStep2back()" id="t_back2">&#8592; Indietro</button>
  </div>

  <!-- SUCCESS -->
  <div id="stepOK" style="display:none">
    <div class="card ok-box">
      <div class="ok-icon">&#9989;</div>
      <h2 id="t_ok_h">Richiesta Inviata!</h2>
      <div class="ok-proto" id="ok_proto"></div>
      <p id="t_ok_p">Un tecnico Rotondi Group Roma ti contatter&#224; a breve con una proposta di appuntamento.<br><br>
        Riceverai una email con i pulsanti per <b>Accettare</b> o <b>Rifiutare</b> la proposta.<br><br>
        Per annullare urgentemente:<br>
        <strong>&#128222; +39 06 41 40 0514</strong>
      </p>
    </div>
  </div>
</div>

<script>
var lang = 'it';
var prevData = null;
var COND_IT = {{ condizioni_it_js }};
var COND_EN = {{ condizioni_en_js }};

var L = {
  it:{
    gdpr_h:'Privacy (GDPR)',gdpr_lbl:'Accetto il trattamento dei dati personali ai sensi del GDPR',
    cond_h:'Condizioni del Servizio',cond_lbl:'Accetto le condizioni del servizio',
    dati_h:'Dati Personali',nome:'Nome e Cognome *',email:'Email',tel:'Telefono *',
    ind_h:'Indirizzo Intervento',via:'Via / Piazza *',civico:'N\u00b0 Civico *',cap:'CAP *',
    citta:'Citt\u00e0 *',prov:'Provincia *',
    btn_calc:'Verifica distanza e preventivo',calc_lbl:'Calcolo in corso...',
    prev_h:'Preventivo Indicativo',prev_nota:'Preventivo indicativo per 1h di lavoro + IVA',
    inside:'Zona Roma (dentro GRA)',outside:'Fuori Roma',
    mac_h:'Dati Macchina',marca:'Marca *',modello:'Modello',seriale:'Numero Seriale',
    prob:'Descrivi il Problema *',
    foto_h:'Foto (opzionale)',foto_targ:'Foto targhetta macchina',foto_mac:'Foto della macchina',
    foto_hint:'Tocca per aggiungere la foto',
    btn1:'Continua \u2192',btn2:'Continua \u2192',btn3:'Invia Richiesta',
    back1:'\u2190 Indietro',back2:'\u2190 Indietro',
    ok_h:'Richiesta Inviata!',
    ok_p:'Un tecnico Rotondi Group Roma ti contatter\u00e0 a breve con una proposta di appuntamento.<br><br>Riceverai una <b>email</b> con i pulsanti per <b>Accettare</b> o <b>Rifiutare</b> la proposta.<br><br>Per annullare urgentemente:<br><strong>+39 06 41 40 0514</strong>',
    err_consent:'Devi accettare privacy e condizioni per continuare',
    err_campi:'Compila tutti i campi obbligatori (*)'
  },
  en:{
    gdpr_h:'Privacy (GDPR)',gdpr_lbl:'I accept the processing of personal data under GDPR',
    cond_h:'Service Conditions',cond_lbl:'I accept the service conditions',
    dati_h:'Personal Details',nome:'Full Name *',email:'Email',tel:'Phone *',
    ind_h:'Service Address',via:'Street *',civico:'Number *',cap:'Postal Code *',
    citta:'City *',prov:'Province *',
    btn_calc:'Check distance & quote',calc_lbl:'Calculating...',
    prev_h:'Indicative Quote',prev_nota:'Indicative quote for 1h work + VAT',
    inside:'Rome area (inside GRA)',outside:'Outside Rome',
    mac_h:'Machine Details',marca:'Brand *',modello:'Model',seriale:'Serial Number',
    prob:'Describe the Problem *',
    foto_h:'Photos (optional)',foto_targ:'Machine label photo',foto_mac:'Machine photo',
    foto_hint:'Tap to add photo',
    btn1:'Continue \u2192',btn2:'Continue \u2192',btn3:'Send Request',
    back1:'\u2190 Back',back2:'\u2190 Back',
    ok_h:'Request Sent!',
    ok_p:'A Rotondi Group Roma technician will contact you shortly with an appointment proposal.<br><br>You will receive an <b>email</b> with buttons to <b>Accept</b> or <b>Decline</b> the proposal.<br><br>To cancel urgently:<br><strong>+39 06 41 40 0514</strong>',
    err_consent:'You must accept privacy and conditions to continue',
    err_campi:'Please fill all required fields (*)'
  },
  bn:{
    gdpr_h:'\u0997\u09cb\u09aa\u09a8\u09c0\u09af\u09bc\u09a4\u09be',gdpr_lbl:'GDPR \u0985\u09a8\u09c1\u09af\u09be\u09af\u09bc\u09c0 \u09b8\u09ae\u09cd\u09ae\u09a4\u09bf \u09a6\u09bf\u099a\u09cd\u099b\u09bf',
    cond_h:'\u09b6\u09b0\u09cd\u09a4\u09be\u09ac\u09b2\u09c0',cond_lbl:'\u09b6\u09b0\u09cd\u09a4\u09be\u09ac\u09b2\u09c0 \u0997\u09cd\u09b0\u09b9\u09a3 \u0995\u09b0\u099b\u09bf',
    dati_h:'\u09ac\u09cd\u09af\u0995\u09cd\u09a4\u09bf\u0997\u09a4 \u09a4\u09a5\u09cd\u09af',nome:'\u09aa\u09c1\u09b0\u09cb \u09a8\u09be\u09ae *',email:'\u0987\u09ae\u09c7\u0987\u09b2',tel:'\u09ab\u09cb\u09a8 *',
    ind_h:'\u09a0\u09bf\u0995\u09be\u09a8\u09be',via:'\u09b0\u09be\u09b8\u09cd\u09a4\u09be *',civico:'\u09a8\u09ae\u09cd\u09ac\u09b0 *',cap:'\u09aa\u09cb\u09b8\u09cd\u099f\u09be\u09b2 \u0995\u09cb\u09a1 *',
    citta:'\u09b6\u09b9\u09b0 *',prov:'\u09aa\u09cd\u09b0\u09a6\u09c7\u09b6 *',
    btn_calc:'\u09a6\u09c2\u09b0\u09a4\u09cd\u09ac \u09af\u09be\u099a\u09be\u0987',calc_lbl:'\u09b9\u09bf\u09b8\u09be\u09ac...',
    prev_h:'\u0986\u09a8\u09c1\u09ae\u09be\u09a8\u09bf\u0995 \u0996\u09b0\u099a',prev_nota:'1 \u0998\u09a3\u09cd\u099f\u09be + \u09ad\u09cd\u09af\u09be\u099f',
    inside:'\u09b0\u09cb\u09ae\u09be (GRA \u09ad\u09c7\u09a4\u09b0\u09c7)',outside:'\u09b0\u09cb\u09ae\u09be\u09b0 \u09ac\u09be\u0987\u09b0\u09c7',
    mac_h:'\u09ae\u09c7\u09b6\u09bf\u09a8',marca:'\u09ac\u09cd\u09b0\u09cd\u09af\u09be\u09a8\u09cd\u09a1 *',modello:'\u09ae\u09a1\u09c7\u09b2',seriale:'\u09b8\u09bf\u09b0\u09bf\u09af\u09bc\u09be\u09b2',
    prob:'\u09b8\u09ae\u09b8\u09cd\u09af\u09be \u09ac\u09b0\u09cd\u09a3\u09a8\u09be *',
    foto_h:'\u099b\u09ac\u09bf (\u09ac\u09be\u099e\u09cd\u099b\u09be\u09ae\u09be\u09ab\u09bf\u0995)',foto_targ:'\u09a4\u09be\u09b0\u09bf\u0996\u09ab\u09b2\u0995\u09c7\u09b0 \u099b\u09ac\u09bf',foto_mac:'\u09ae\u09c7\u09b6\u09bf\u09a8\u09c7\u09b0 \u099b\u09ac\u09bf',
    foto_hint:'\u099b\u09ac\u09bf \u09af\u09cb\u0997 \u0995\u09b0\u09a4\u09c7 \u09b8\u09cd\u09aa\u09b0\u09cd\u09b6 \u0995\u09b0\u09c1\u09a8',
    btn1:'\u098f\u0997\u09bf\u09af\u09bc\u09c7 \u09af\u09be\u09a8 \u2192',btn2:'\u098f\u0997\u09bf\u09af\u09bc\u09c7 \u09af\u09be\u09a8 \u2192',btn3:'\u09aa\u09be\u09a0\u09be\u09a8',
    back1:'\u2190 \u09aa\u09c7\u099b\u09a8\u09c7',back2:'\u2190 \u09aa\u09c7\u099b\u09a8\u09c7',
    ok_h:'\u0985\u09a8\u09c1\u09b0\u09cb\u09a7 \u09aa\u09be\u09a0\u09be\u09a8\u09cb \u09b9\u09af\u09bc\u09c7\u099b\u09c7!',
    ok_p:'\u098f\u0995\u099c\u09a8 \u099f\u09c7\u0995\u09a8\u09bf\u09b6\u09bf\u09af\u09bc\u09be\u09a8 \u09b6\u09c0\u0998\u09cd\u09b0\u0987 \u09af\u09cb\u0997\u09be\u09af\u09cb\u0997 \u0995\u09b0\u09ac\u09c7\u09a8\u0964<br><br>\u09ac\u09be\u09a4\u09bf\u09b2: <strong>+39 06 41 40 0514</strong>',
    err_consent:'\u0997\u09cb\u09aa\u09a8\u09c0\u09af\u09bc\u09a4\u09be \u0993 \u09b6\u09b0\u09cd\u09a4\u09be\u09ac\u09b2\u09c0 \u0997\u09cd\u09b0\u09b9\u09a3 \u0995\u09b0\u09c1\u09a8',
    err_campi:'\u09b8\u09ac \u09aa\u09cd\u09b0\u09af\u09bc\u09cb\u099c\u09a8\u09c0\u09af\u09bc \u09a4\u09a5\u09cd\u09af \u09aa\u09c2\u09b0\u09a3 \u0995\u09b0\u09c1\u09a8'
  },
  zh:{
    gdpr_h:'\u9690\u79c1 (GDPR)',gdpr_lbl:'\u6211\u540c\u610f\u6839\u636eGDPR\u5904\u7406\u4e2a\u4eba\u6570\u636e',
    cond_h:'\u670d\u52a1\u6761\u6b3e',cond_lbl:'\u6211\u63a5\u53d7\u670d\u52a1\u6761\u6b3e',
    dati_h:'\u4e2a\u4eba\u4fe1\u606f',nome:'\u59d3\u540d *',email:'\u90ae\u7b71',tel:'\u7535\u8bdd *',
    ind_h:'\u670d\u52a1\u5730\u5740',via:'\u8857\u9053 *',civico:'\u95e8\u724c\u53f7 *',cap:'\u90ae\u653f\u7f16\u7801 *',
    citta:'\u57ce\u5e02 *',prov:'\u7701\u4efd\u4ee3\u7801 *',
    btn_calc:'\u9a8c\u8bc1\u8ddd\u79bb',calc_lbl:'\u8ba1\u7b97\u4e2d...',
    prev_h:'\u53c2\u8003\u62a5\u4ef7',prev_nota:'1\u5c0f\u65f6\u5de5\u4f5c\u53c2\u8003\u62a5\u4ef7 + \u589e\u5024\u7a0e',
    inside:'\u7f57\u9a6c\u5e02\u533a\uff08GRA\u5185\uff09',outside:'\u7f57\u9a6c\u5e02\u5916',
    mac_h:'\u673a\u5668\u4fe1\u606f',marca:'\u54c1\u724c *',modello:'\u578b\u53f7',seriale:'\u5e8f\u5217\u53f7',
    prob:'\u63cf\u8ff0\u95ee\u9898 *',
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
    gdpr_h:'\u0627\u0644\u062e\u0635\u0648\u0635\u064a\u0629 (GDPR)',gdpr_lbl:'\u0623\u0648\u0627\u0641\u0642 \u0639\u0644\u0649 \u0645\u0639\u0627\u0644\u062c\u0629 \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0648\u0641\u0642 GDPR',
    cond_h:'\u0634\u0631\u0648\u0637 \u0627\u0644\u062e\u062f\u0645\u0629',cond_lbl:'\u0623\u0642\u0628\u0644 \u0634\u0631\u0648\u0637 \u0627\u0644\u062e\u062f\u0645\u0629',
    dati_h:'\u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u0634\u062e\u0635\u064a\u0629',nome:'\u0627\u0644\u0627\u0633\u0645 \u0627\u0644\u0643\u0627\u0645\u0644 *',email:'\u0627\u0644\u0628\u0631\u064a\u062f \u0627\u0644\u0625\u0644\u0643\u062a\u0631\u0648\u0646\u064a',tel:'\u0627\u0644\u0647\u0627\u062a\u0641 *',
    ind_h:'\u0639\u0646\u0648\u0627\u0646 \u0627\u0644\u062e\u062f\u0645\u0629',via:'\u0627\u0644\u0634\u0627\u0631\u0639 *',civico:'\u0631\u0642\u0645 \u0627\u0644\u0645\u0628\u0646\u0649 *',cap:'\u0627\u0644\u0631\u0645\u0632 \u0627\u0644\u0628\u0631\u064a\u062f\u064a *',
    citta:'\u0627\u0644\u0645\u062f\u064a\u0646\u0629 *',prov:'\u0631\u0645\u0632 \u0627\u0644\u0645\u062d\u0627\u0641\u0638\u0629 *',
    btn_calc:'\u062a\u062d\u0642\u0642 \u0645\u0646 \u0627\u0644\u0645\u0633\u0627\u0641\u0629',calc_lbl:'\u062c\u0627\u0631\u0650 \u0627\u0644\u062d\u0633\u0627\u0628...',
    prev_h:'\u0639\u0631\u0636 \u0633\u0639\u0631 \u062a\u0642\u0631\u064a\u0628\u064a',prev_nota:'\u062a\u0642\u0631\u064a\u0628\u064a \u0644\u0633\u0627\u0639\u0629 \u0639\u0645\u0644 + \u0636\u0631\u064a\u0628\u0629',
    inside:'\u0645\u0646\u0637\u0642\u0629 \u0631\u0648\u0645\u0627 (\u062f\u0627\u062e\u0644 GRA)',outside:'\u062e\u0627\u0631\u062c \u0631\u0648\u0645\u0627',
    mac_h:'\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u062c\u0647\u0627\u0632',marca:'\u0627\u0644\u0645\u0627\u0631\u0643\u0629 *',modello:'\u0627\u0644\u0645\u0648\u062f\u064a\u0644',seriale:'\u0627\u0644\u0631\u0642\u0645 \u0627\u0644\u062a\u0633\u0644\u0633\u0644\u064a',
    prob:'\u0635\u0641 \u0627\u0644\u0645\u0634\u0643\u0644\u0629 *',
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
  document.querySelectorAll('.lang-btn').forEach(function(b){b.classList.remove('active');});
  document.getElementById('l_'+l).classList.add('active');
  var t=L[l];
  var map={
    't_gdpr_h':'gdpr_h','t_gdpr_lbl':'gdpr_lbl','t_cond_h':'cond_h','t_cond_lbl':'cond_lbl',
    't_dati_h':'dati_h','t_nome':'nome','t_email':'email','t_tel':'tel',
    't_ind_h':'ind_h','t_via':'via','t_civico':'civico','t_cap':'cap','t_citta':'citta','t_prov':'prov',
    't_calc_lbl':'calc_lbl','t_prev_h':'prev_h','t_prev_nota':'prev_nota',
    't_mac_h':'mac_h','t_marca':'marca','t_modello':'modello','t_seriale':'seriale','t_prob':'prob',
    't_foto_h':'foto_h','t_foto_targ':'foto_targ','t_foto_mac':'foto_mac',
    'btn1':'btn1','btn2':'btn2','btn3':'btn3','t_back1':'back1','t_back2':'back2'
  };
  for(var id in map){var el=document.getElementById(id);if(el)el.textContent=t[map[id]];}
  document.getElementById('btn_calc').textContent=t.btn_calc;
  var h1=document.getElementById('hint_targhetta');
  var h2=document.getElementById('hint_macchina');
  if(h1)h1.textContent=t.foto_hint;
  if(h2)h2.textContent=t.foto_hint;
  if(l==='it') document.getElementById('cond_box').textContent=COND_IT;
  else if(l==='en') document.getElementById('cond_box').textContent=COND_EN;
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
  updSteps(1);window.scrollTo(0,0);
}
function goStep2(){
  if(!document.getElementById('chk_gdpr').checked||!document.getElementById('chk_cond').checked){
    alert(L[lang].err_consent);return;
  }
  document.getElementById('step1').style.display='none';
  document.getElementById('step2').style.display='';
  updSteps(2);window.scrollTo(0,0);
}
function goStep2back(){
  document.getElementById('step3').style.display='none';
  document.getElementById('step2').style.display='';
  updSteps(2);window.scrollTo(0,0);
}
function goStep3(){
  var campi=['nome','telefono','via','civico','cap','citta','provincia'];
  for(var i=0;i<campi.length;i++){
    if(!document.getElementById(campi[i]).value.trim()){alert(L[lang].err_campi);return;}
  }
  document.getElementById('step2').style.display='none';
  document.getElementById('step3').style.display='';
  updSteps(3);window.scrollTo(0,0);
}
function buildInd(){
  var via=document.getElementById('via').value.trim();
  var civ=document.getElementById('civico').value.trim();
  var cap=document.getElementById('cap').value.trim();
  var cit=document.getElementById('citta').value.trim();
  var prv=document.getElementById('provincia').value.trim().toUpperCase();
  return via+', '+civ+', '+cap+' '+cit+' ('+prv+'), Italia';
}
function calcolaPreventivo(){
  var campi=['via','civico','cap','citta','provincia'];
  for(var i=0;i<campi.length;i++){
    if(!document.getElementById(campi[i]).value.trim()){alert(L[lang].err_campi);return;}
  }
  document.getElementById('loading_p').style.display='block';
  document.getElementById('prev_box').style.display='none';
  fetch('/calcola-preventivo',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({indirizzo:buildInd()})})
  .then(function(r){return r.json();})
  .then(function(data){
    document.getElementById('loading_p').style.display='none';
    if(!data.zona)return;
    prevData=data;
    var box=document.getElementById('prev_box');
    var t=L[lang];
    if(data.zona==='inside_gra'){
      box.className='prev-box prev-inside';
      document.getElementById('prev_zona').textContent=t.inside+' \u2014 '+data.dist_label+' ('+data.dur_label+')';
      document.getElementById('prev_imp').textContent='EUR '+data.costo_min.toFixed(2)+' + IVA';
      document.getElementById('prev_det').textContent='Uscita + 1h lavoro';
    } else {
      box.className='prev-box prev-outside';
      document.getElementById('prev_zona').textContent=t.outside+' \u2014 '+data.dist_label+' ('+data.dur_label+')';
      document.getElementById('prev_imp').textContent='min. EUR '+data.costo_min.toFixed(2)+' + IVA';
      if(data.dettaglio){
        document.getElementById('prev_det').textContent=
          'Km A/R: EUR '+data.dettaglio.costo_km+
          ' | Viaggio A/R: EUR '+data.dettaglio.costo_viaggio+
          ' | Lavoro 1h: EUR '+data.dettaglio.costo_lavoro;
      }
    }
    document.getElementById('t_prev_h').textContent=t.prev_h;
    document.getElementById('t_prev_nota').textContent=t.prev_nota;
    box.style.display='block';
  }).catch(function(){document.getElementById('loading_p').style.display='none';});
}
function mostraFoto(input,prevId,areaId,hintId){
  var file=input.files[0];if(!file)return;
  var reader=new FileReader();
  reader.onload=function(e){
    var box=document.getElementById(prevId);
    box.innerHTML='<img class="foto-preview-img" src="'+e.target.result+'"><div class="foto-hint" style="color:#444">'+file.name+'</div>';
  };
  reader.readAsDataURL(file);
  document.getElementById(areaId).classList.add('has-foto');
}
function invia(){
  var campi=['nome','telefono','marca','problema'];
  for(var i=0;i<campi.length;i++){
    if(!document.getElementById(campi[i]).value.trim()){alert(L[lang].err_campi);return;}
  }
  var btn=document.getElementById('btn3');
  btn.disabled=true;btn.textContent='\u23f3 Invio in corso...';
  var fd=new FormData();
  fd.append('nome',document.getElementById('nome').value.trim());
  fd.append('email',document.getElementById('email').value.trim());
  fd.append('telefono',document.getElementById('telefono').value.trim());
  fd.append('via',document.getElementById('via').value.trim());
  fd.append('civico',document.getElementById('civico').value.trim());
  fd.append('cap',document.getElementById('cap').value.trim());
  fd.append('citta',document.getElementById('citta').value.trim());
  fd.append('provincia',document.getElementById('provincia').value.trim().toUpperCase());
  fd.append('indirizzo',buildInd());
  fd.append('marca',document.getElementById('marca').value.trim());
  fd.append('modello',document.getElementById('modello').value.trim());
  fd.append('seriale',document.getElementById('seriale').value.trim());
  fd.append('problema',document.getElementById('problema').value.trim());
  fd.append('lingua',lang);
  if(prevData)fd.append('preventivo',JSON.stringify(prevData));
  var ft=document.getElementById('inp_targhetta').files[0];
  var fm=document.getElementById('inp_macchina').files[0];
  if(ft)fd.append('foto_targhetta',ft);
  if(fm)fd.append('foto_macchina',fm);
  fetch('/invia',{method:'POST',body:fd})
  .then(function(r){return r.json();})
  .then(function(data){
    if(data.protocollo){
      document.getElementById('step3').style.display='none';
      document.getElementById('stepOK').style.display='';
      document.getElementById('ok_proto').textContent=data.protocollo;
      document.getElementById('t_ok_h').textContent=L[lang].ok_h;
      document.getElementById('t_ok_p').innerHTML=L[lang].ok_p;
      document.querySelectorAll('.step').forEach(function(s){s.className='step done';});
      window.scrollTo(0,0);
    } else {
      btn.disabled=false;btn.textContent=L[lang].btn3;
      alert('Errore invio. Riprova.');
    }
  }).catch(function(){
    btn.disabled=false;btn.textContent=L[lang].btn3;
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
.box{background:#fff;border-radius:12px;padding:40px;width:100%;
  max-width:380px;box-shadow:0 4px 20px rgba(0,0,0,.1)}
h2{font-size:20px;margin-bottom:24px;color:#0d0d14;text-align:center}
input{width:100%;padding:12px;border:1.5px solid #ddd;border-radius:8px;
  font-size:15px;margin-bottom:16px;outline:none}
input:focus{border-color:#0d0d14}
button{width:100%;background:#0d0d14;color:#fff;border:none;padding:12px;
  border-radius:8px;font-size:15px;cursor:pointer}
.err{color:#e53935;font-size:13px;text-align:center;margin-bottom:12px}
</style></head>
<body>
<div class="box">
  <h2>Admin Rotondi Group</h2>
  {% if errore %}<p class="err">{{ errore }}</p>{% endif %}
  <form method="POST">
    <input type="password" name="password" placeholder="Password" autofocus>
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
.topbar{background:#0d0d14;color:#fff;padding:16px 24px;
  display:flex;align-items:center;justify-content:space-between}
.topbar h1{font-size:18px}
.topbar a{color:#aaa;font-size:13px;text-decoration:none}
.topbar a:hover{color:#fff}
.container{max-width:960px;margin:24px auto;padding:0 16px 60px}
.card{background:#fff;border-radius:10px;padding:24px;margin-bottom:20px;
  box-shadow:0 2px 8px rgba(0,0,0,.07)}
.card h2{font-size:16px;font-weight:700;color:#0d0d14;margin-bottom:18px;
  border-bottom:2px solid #f0f0f0;padding-bottom:10px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:600px){.grid2{grid-template-columns:1fr}}
.field{margin-bottom:14px}
label{display:block;font-size:13px;font-weight:600;color:#555;margin-bottom:5px}
input[type=number],input[type=password],textarea{width:100%;padding:10px;
  border:1.5px solid #ddd;border-radius:8px;font-size:14px;outline:none}
input:focus,textarea:focus{border-color:#0d0d14}
textarea{resize:vertical;min-height:130px;font-size:13px;line-height:1.6}
.btn{background:#0d0d14;color:#fff;border:none;padding:12px 28px;
  border-radius:8px;font-size:14px;cursor:pointer;font-weight:700}
.btn:hover{opacity:.88}
.msg{background:#e8f5e9;color:#2e7d32;padding:12px 16px;border-radius:8px;
  margin-bottom:16px;font-size:14px;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#f5f5f5;padding:10px 8px;text-align:left;
  font-weight:600;color:#555;border-bottom:2px solid #eee}
td{padding:9px 8px;border-bottom:1px solid #f0f0f0;vertical-align:top}
tr:hover td{background:#fafafa}
.badge{display:inline-block;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:700}
.b-open{background:#fff3cd;color:#856404}
.b-ass{background:#d4edda;color:#155724}
.b-wait{background:#d1ecf1;color:#0c5460}
a.sblocca{color:#e53935;font-size:12px;text-decoration:none}
a.sblocca:hover{text-decoration:underline}
</style></head>
<body>
<div class="topbar">
  <h1>Admin - Rotondi Group Roma</h1>
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
      <div class="field" style="max-width:320px">
        <label>Nuova password (lascia vuoto per non cambiare)</label>
        <input type="password" name="nuova_password" placeholder="Nuova password">
      </div>
    </div>
    <button type="submit" class="btn">Salva tutto</button>
  </form>
  <div class="card" style="margin-top:24px">
    <h2>Ultime 50 Richieste Web</h2>
    <div style="overflow-x:auto">
      <table>
        <tr>
          <th>Protocollo</th><th>Cliente</th><th>Indirizzo</th>
          <th>Tel</th><th>Marca</th><th>Problema</th>
          <th>Stato</th><th>Tecnico</th><th>Data</th><th></th>
        </tr>
        {% for r in richieste %}
        <tr>
          <td><code style="font-size:11px">{{ r[0] }}</code></td>
          <td>{{ r[1] }}</td>
          <td style="font-size:12px">{{ r[2] }}</td>
          <td>{{ r[3] }}</td>
          <td>{{ r[4] }}</td>
          <td style="max-width:140px;font-size:12px">
            {{ (r[5] or '')[:50] }}{% if r[5] and r[5]|length > 50 %}...{% endif %}
          </td>
          <td>
            {% if r[6]=='aperta' %}<span class="badge b-open">aperta</span>
            {% elif r[6]=='assegnata' %}<span class="badge b-ass">assegnata</span>
            {% elif r[6]=='in_attesa_conferma' %}<span class="badge b-wait">in attesa</span>
            {% else %}<span class="badge b-wait">{{ r[6] }}</span>{% endif %}
          </td>
          <td style="font-size:12px">{{ r[7] or '-' }}<br><small>{{ r[8] or '' }}</small></td>
          <td style="font-size:12px">{{ r[9] }}</td>
          <td>
            {% if r[6] != 'aperta' %}
            <a href="/admin/sblocca/{{ r[0] }}" class="sblocca"
               onclick="return confirm('Sbloccare questa richiesta?')">Sblocca</a>
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
