#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WEB APP - Assistenza Tecnica Macchinari
Rotondi Group Roma — v2
"""

import os, sqlite3, uuid, math, smtplib, json, base64, threading
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string, session, redirect
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "rotondi-secret-2024")

DB_PATH     = "web_assistenza.db"
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
TECNICI_GID = os.environ.get("TECNICI_GROUP_ID", "-1001234567890")
GMAPS_KEY   = os.environ.get("GMAPS_KEY", "")
SEDE        = "Via di Sant'Alessandro 349, Roma, Italia"
SMTP_U      = os.environ.get("SMTP_USER","")
SMTP_P      = os.environ.get("SMTP_PASS","")
SMTP_F      = os.environ.get("SMTP_FROM","")
SMTP_H      = os.environ.get("SMTP_HOST","smtp.gmail.com")
SMTP_PO     = int(os.environ.get("SMTP_PORT","587"))
# Email a cui arrivano le notifiche per i tecnici (reply-to)
TECNICI_EMAIL = os.environ.get("TECNICI_EMAIL","")
# Email ufficio messa in CC su ogni assegnazione (può coincidere con TECNICI_EMAIL)
UFFICIO_EMAIL = os.environ.get("UFFICIO_EMAIL","")
BASE_URL    = os.environ.get("BASE_URL","http://localhost:5000")

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

TARIFFE_DEFAULT = {
    "dentro_uscita": 80.0,
    "dentro_ora_extra": 40.0,
    "fuori_km": 0.70,
    "fuori_ora_viaggio": 32.0,
    "fuori_ora_lavoro": 40.0,
}

CONDIZIONI_IT_DEFAULT = (
    "L'assistenza tecnica è un servizio a pagamento, anche se il prodotto è in garanzia.\n\n"
    "✅ In garanzia: parti difettose sostituite senza costo\n\n"
    "💶 Sempre a carico del cliente:\n"
    "› Manodopera › Spostamento tecnico › Costo chiamata\n\n"
    "📍 ZONA DI ROMA (dentro il GRA)\n"
    "› Uscita + 1h lavoro: € 80,00 + IVA\n"
    "› Ore successive: € 40,00/h + IVA\n\n"
    "🗺 FUORI ROMA (Provincia, Lazio, resto d'Italia)\n"
    "› Km trasferta: € 0,70/km + IVA (A/R)\n"
    "› Ore viaggio: € 32,00/h + IVA (A/R)\n"
    "› Ore lavoro: € 40,00/h + IVA\n\n"
    "Pagamento direttamente al tecnico al termine del servizio."
)

CONDIZIONI_EN_DEFAULT = (
    "Technical assistance is a paid service, even under warranty.\n\n"
    "✅ Under warranty: defective parts replaced at no cost\n\n"
    "💶 Always charged to customer:\n"
    "› Labour › Technician travel › Call-out fee\n\n"
    "📍 ROME AREA (inside GRA)\n"
    "› Call-out + 1h work: € 80.00 + VAT\n"
    "› Additional hours: € 40.00/h + VAT\n\n"
    "🗺 OUTSIDE ROME\n"
    "› Travel km: € 0.70/km + VAT (return)\n"
    "› Travel hours: € 32.00/h + VAT (return)\n"
    "› Work hours: € 40.00/h + VAT\n\n"
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
                preventivo TEXT,
                foto_paths TEXT
            )
        """)
        # Migrazioni colonne mancanti
        for col in ["via TEXT","civico TEXT","cap TEXT","citta TEXT","provincia TEXT",
                    "seriale TEXT","email TEXT","preventivo TEXT","foto_paths TEXT"]:
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
            return {
                "zona": "inside_gra",
                "costo_min": tar["dentro_uscita"],
                "testo": f"Zona Roma (dentro GRA) — uscita + 1h: EUR {tar['dentro_uscita']:.2f} + IVA",
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


def invia_telegram(testo, keyboard=None):
    try:
        import requests as rq
        payload = {"chat_id": TECNICI_GID, "text": testo, "parse_mode": "Markdown"}
        if keyboard: payload["reply_markup"] = json.dumps(keyboard)
        r = rq.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json=payload, timeout=10)
        return r.json()
    except Exception as e:
        app.logger.error(f"TG: {e}")
        return None


def invia_telegram_foto(foto_path, caption=""):
    """Invia una singola foto al gruppo Telegram"""
    try:
        import requests as rq
        if not os.path.exists(foto_path):
            return
        with open(foto_path, "rb") as f:
            rq.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                    data={"chat_id": TECNICI_GID, "caption": caption[:1024]},
                    files={"photo": f}, timeout=30)
    except Exception as e:
        app.logger.error(f"TG foto: {e}")


def _smtp_send(msg_obj, destinatario):
    """Gestisce porta 465 SSL e 587 TLS automaticamente"""
    if SMTP_PO == 465:
        import ssl
        with smtplib.SMTP_SSL(SMTP_H, SMTP_PO, context=ssl.create_default_context()) as s:
            s.login(SMTP_U, SMTP_P)
            s.sendmail(SMTP_F, destinatario, msg_obj.as_string())
    else:
        with smtplib.SMTP(SMTP_H, SMTP_PO) as s:
            s.starttls()
            s.login(SMTP_U, SMTP_P)
            s.sendmail(SMTP_F, destinatario, msg_obj.as_string())


def invia_email_cliente(email, nome, protocollo, lingua="it"):
    if not (email and SMTP_U and SMTP_P): return
    soggetto = {
        "it": f"Rotondi Group Roma — Richiesta ricevuta #{protocollo}",
        "en": f"Rotondi Group Roma — Request received #{protocollo}",
    }.get(lingua, f"Rotondi Group Roma — #{protocollo}")
    corpo = f"""
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
  <h1 style="color:#fff;font-size:22px;margin:0">ROTONDI GROUP ROMA</h1>
  <p style="color:#aaa;margin:4px 0 0;font-size:13px">Assistenza Tecnica Macchinari</p>
</div>
<div style="background:#fff;padding:32px;border-radius:0 0 8px 8px">
  <h2 style="color:#0d0d14;margin-top:0">Richiesta ricevuta!</h2>
  <p>Gentile <b>{nome}</b>,</p>
  <p>La sua richiesta di assistenza tecnica è stata ricevuta.</p>
  <div style="background:#f8f8f8;border-radius:8px;padding:16px;margin:20px 0;border-left:4px solid #0d0d14">
    <p style="margin:0 0 4px"><b>Numero protocollo:</b></p>
    <p style="font-size:24px;font-weight:bold;color:#0d0d14;margin:0">{protocollo}</p>
  </div>
  <p>Un nostro tecnico la contatterà al più presto.</p>
  <div style="background:#fff3cd;border-radius:8px;padding:12px;margin:16px 0">
    <p style="margin:0;font-size:13px"><b>Per annullare urgentemente:</b><br>
    +39 06 41 40 0514</p>
  </div>
  <p style="color:#666;font-size:13px;margin-top:24px">Ufficio Roma: +39 06 41400617</p>
</div></div>"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = soggetto; msg["From"] = SMTP_F; msg["To"] = email
        msg.attach(MIMEText(corpo, "html"))
        _smtp_send(msg, email)
    except Exception as e:
        app.logger.error(f"Email cliente: {e}")


def invia_email_tecnico(dati, protocollo, prev_text="", foto_paths=None):
    """
    Invia email di notifica ai tecnici con tutti i dati della richiesta.
    Il tecnico può rispondere direttamente per confermare la presa in carico.
    """
    if not (TECNICI_EMAIL and SMTP_U and SMTP_P):
        return
    
    indirizzo = dati.get("indirizzo", "")
    link_maps = "https://www.google.com/maps/search/?api=1&query=" + indirizzo.replace(" ", "+")
    
    # Link per assegnazione rapida via web admin
    link_admin = f"{BASE_URL}/admin"
    
    soggetto = f"[NUOVA RICHIESTA] #{protocollo} — {dati.get('marca','')} — {dati.get('citta','')} ({dati.get('provincia','')})"
    
    corpo_html = f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#f5f5f5;padding:20px">
  <div style="background:#0d0d14;padding:20px 24px;border-radius:8px 8px 0 0;text-align:center">
    <h1 style="color:#fff;font-size:20px;margin:0;letter-spacing:1px">ROTONDI GROUP ROMA</h1>
    <p style="color:#aaa;margin:4px 0 0;font-size:12px">Nuova Richiesta di Assistenza</p>
  </div>
  <div style="background:#fff;padding:28px;border-radius:0 0 8px 8px;box-shadow:0 2px 8px rgba(0,0,0,.08)">

    <div style="background:#fff8e1;border-left:4px solid #ff9800;padding:12px 16px;border-radius:4px;margin-bottom:20px">
      <p style="margin:0;font-size:13px;color:#e65100;font-weight:700">⚡ NUOVA RICHIESTA — RISPONDERE A QUESTA EMAIL PER PRENDERE IN CARICO</p>
    </div>

    <table style="width:100%;border-collapse:collapse;margin-bottom:20px">
      <tr>
        <td style="padding:8px 12px;background:#f8f8f8;font-weight:700;font-size:13px;width:40%;border-radius:4px">🔖 Protocollo</td>
        <td style="padding:8px 12px;font-size:14px;font-weight:700;color:#0d0d14;letter-spacing:1px">{protocollo}</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;background:#f8f8f8;font-weight:700;font-size:13px;border-radius:4px">👤 Cliente</td>
        <td style="padding:8px 12px;font-size:14px">{dati.get('nome','')}</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;background:#f8f8f8;font-weight:700;font-size:13px;border-radius:4px">📞 Telefono</td>
        <td style="padding:8px 12px;font-size:14px"><a href="tel:{dati.get('telefono','')}" style="color:#0d0d14;font-weight:700">{dati.get('telefono','')}</a></td>
      </tr>
      <tr>
        <td style="padding:8px 12px;background:#f8f8f8;font-weight:700;font-size:13px;border-radius:4px">📧 Email cliente</td>
        <td style="padding:8px 12px;font-size:14px">{dati.get('email','') or '—'}</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;background:#f8f8f8;font-weight:700;font-size:13px;border-radius:4px">📍 Indirizzo</td>
        <td style="padding:8px 12px;font-size:14px">{indirizzo}<br>
          <a href="{link_maps}" style="color:#1565c0;font-size:12px">🗺 Apri su Google Maps</a></td>
      </tr>
      <tr>
        <td style="padding:8px 12px;background:#f8f8f8;font-weight:700;font-size:13px;border-radius:4px">🏷 Marca</td>
        <td style="padding:8px 12px;font-size:14px">{dati.get('marca','')}</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;background:#f8f8f8;font-weight:700;font-size:13px;border-radius:4px">⚙️ Modello</td>
        <td style="padding:8px 12px;font-size:14px">{dati.get('modello','') or '—'}</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;background:#f8f8f8;font-weight:700;font-size:13px;border-radius:4px">🔢 Seriale</td>
        <td style="padding:8px 12px;font-size:14px">{dati.get('seriale','') or '—'}</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;background:#f8f8f8;font-weight:700;font-size:13px;border-radius:4px;vertical-align:top">🔧 Problema</td>
        <td style="padding:8px 12px;font-size:14px;color:#333">{dati.get('problema','')}</td>
      </tr>
      {"<tr><td style='padding:8px 12px;background:#f8f8f8;font-weight:700;font-size:13px;border-radius:4px'>💰 Preventivo</td><td style='padding:8px 12px;font-size:14px'>"+prev_text+"</td></tr>" if prev_text else ""}
    </table>

    <div style="background:#e8f5e9;border-radius:8px;padding:16px;margin:16px 0;border:1px solid #c8e6c9">
      <p style="margin:0 0 8px;font-weight:700;font-size:14px;color:#2e7d32">📋 COME PRENDERE IN CARICO:</p>
      <p style="margin:0;font-size:13px;color:#333;line-height:1.8">
        1. <b>Rispondi a questa email</b> con il tuo nome e la fascia oraria proposta<br>
        2. Oppure accedi al pannello admin: <a href="{link_admin}" style="color:#1565c0">{link_admin}</a><br>
        3. Contatta direttamente il cliente: <a href="tel:{dati.get('telefono','')}" style="color:#0d0d14"><b>{dati.get('telefono','')}</b></a>
      </p>
    </div>

    {"<p style='font-size:13px;color:#666;margin-top:16px'>📸 Foto allegate a questa email (" + str(len(foto_paths)) + " immagini)</p>" if foto_paths else ""}

    <p style="font-size:12px;color:#999;margin-top:24px;border-top:1px solid #f0f0f0;padding-top:12px">
      Rotondi Group Roma — Via di Sant'Alessandro 349, Roma<br>
      Tel: +39 06 41400617
    </p>
  </div>
</div>"""

    try:
        msg = MIMEMultipart("mixed")
        msg["Subject"] = soggetto
        msg["From"]    = SMTP_F
        msg["To"]      = TECNICI_EMAIL
        msg["Reply-To"] = TECNICI_EMAIL
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(corpo_html, "html"))
        msg.attach(alt)
        if foto_paths:
            for fp in foto_paths:
                if fp and os.path.exists(fp):
                    with open(fp, "rb") as f:
                        part = MIMEBase("image", "jpeg")
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        fname = os.path.basename(fp)
                        part.add_header("Content-Disposition", f"attachment; filename={fname}")
                        msg.attach(part)
        _smtp_send(msg, TECNICI_EMAIL)
    except Exception as e:
        app.logger.error(f"Email tecnico: {e}")


def invia_email_assegnazione(protocollo, tecnico_nome, fascia_label):
    """
    Chiamata dopo che un tecnico ha preso in carico (da Telegram o da admin).
    Manda email al CLIENTE con nome tecnico + preventivo in grassetto.
    Manda CC all'UFFICIO così sanno chi ha preso la chiamata.
    """
    if not (SMTP_U and SMTP_P):
        app.logger.warning("SMTP non configurato — email assegnazione saltata")
        return

    # Legge tutti i dati della richiesta dal DB
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("""
            SELECT nome, email, telefono, indirizzo, marca, modello,
                   seriale, problema, preventivo, lingua, protocollo
            FROM richieste_web WHERE protocollo=?
        """, (protocollo,)).fetchone()

    if not row:
        app.logger.error(f"Assegnazione email: protocollo {protocollo} non trovato")
        return

    (nome, email_cliente, telefono, indirizzo,
     marca, modello, seriale, problema,
     prev_json, lingua, proto) = row

    # ── Costruisce il blocco preventivo ──────────────────────────────────────
    prev_html = ""
    prev_plain = ""
    if prev_json:
        try:
            prev = json.loads(prev_json)
            if prev.get("zona") == "inside_gra":
                importo = f"EUR {prev.get('costo_min', 80):.2f} + IVA"
                zona_txt = "Zona Roma (dentro GRA) — uscita + 1h lavoro"
            else:
                importo = f"EUR {prev.get('costo_min', 0):.2f} + IVA (minimo)"
                zona_txt = f"Fuori Roma — {prev.get('dist_label','')} ({prev.get('dur_label','')})"

            prev_html = f"""
<div style="background:#fff8e1;border:2px solid #ff9800;border-radius:10px;padding:20px;margin:20px 0">
  <p style="margin:0 0 6px;font-size:13px;color:#e65100;font-weight:700;text-transform:uppercase;letter-spacing:.5px">
    💰 Preventivo Indicativo di Spesa
  </p>
  <p style="margin:0 0 4px;font-size:13px;color:#555">{zona_txt}</p>
  <p style="margin:8px 0 4px;font-size:28px;font-weight:900;color:#bf360c;letter-spacing:1px">
    <strong>{importo}</strong>
  </p>
  <p style="margin:8px 0 0;font-size:12px;color:#e65100;font-style:italic;border-top:1px solid #ffe082;padding-top:8px">
    ⚠️ <strong>Preventivo indicativo per manodopera e trasferta — escluse parti di ricambio.</strong><br>
    Il costo finale potrà variare in base alla durata effettiva dell'intervento.
  </p>
</div>"""
            prev_plain = f"PREVENTIVO INDICATIVO: {importo} ({zona_txt})\n⚠ Escluse parti di ricambio — costo finale può variare."
        except Exception as e:
            app.logger.error(f"Parsing preventivo: {e}")

    if not prev_html:
        prev_html = """
<div style="background:#f8f8f8;border-radius:8px;padding:14px;margin:16px 0;border:1px solid #ddd">
  <p style="margin:0;font-size:13px;color:#555">
    💰 Il tecnico le fornirà il preventivo dettagliato al momento dell'intervento.<br>
    <span style="color:#e65100;font-weight:700">⚠️ Escluse parti di ricambio.</span>
  </p>
</div>"""

    # ── Testi multilingua ─────────────────────────────────────────────────────
    TESTI = {
        "it": {
            "soggetto": f"Rotondi Group Roma — Intervento confermato #{protocollo}",
            "titolo": "Intervento Confermato",
            "saluto": f"Gentile <b>{nome}</b>,",
            "intro": "La sua richiesta di assistenza è stata presa in carico.",
            "tecnico_label": "Tecnico assegnato",
            "fascia_label": "Fascia di intervento",
            "contatto": "Il tecnico la contatterà per confermare l'orario esatto.",
            "annulla": "Per annullare urgentemente:",
            "ufficio": "Ufficio Roma:",
        },
        "en": {
            "soggetto": f"Rotondi Group Roma — Appointment confirmed #{protocollo}",
            "titolo": "Appointment Confirmed",
            "saluto": f"Dear <b>{nome}</b>,",
            "intro": "Your assistance request has been taken on board.",
            "tecnico_label": "Assigned technician",
            "fascia_label": "Scheduled slot",
            "contatto": "The technician will contact you to confirm the exact time.",
            "annulla": "To cancel urgently:",
            "ufficio": "Rome office:",
        },
    }
    T = TESTI.get(lingua, TESTI["it"])
    soggetto = T["soggetto"]

    corpo_html = f"""
<div style="font-family:Arial,sans-serif;max-width:580px;margin:0 auto">

  <!-- HEADER -->
  <div style="background:#0d0d14;padding:24px;text-align:center;border-radius:10px 10px 0 0">
    <h1 style="color:#fff;font-size:22px;margin:0;letter-spacing:1px">ROTONDI GROUP ROMA</h1>
    <p style="color:#aaa;margin:4px 0 0;font-size:13px">Assistenza Tecnica Macchinari</p>
  </div>

  <!-- BODY -->
  <div style="background:#fff;padding:32px;border-radius:0 0 10px 10px;border:1px solid #e0e0e0">

    <!-- Banner verde conferma -->
    <div style="background:#e8f5e9;border-left:5px solid #4caf50;padding:14px 18px;border-radius:6px;margin-bottom:24px">
      <p style="margin:0;font-size:16px;font-weight:700;color:#2e7d32">✅ {T["titolo"]}</p>
    </div>

    <p style="font-size:15px;line-height:1.6">{T["saluto"]}</p>
    <p style="font-size:14px;color:#444;margin:10px 0 20px;line-height:1.7">{T["intro"]}</p>

    <!-- Protocollo -->
    <div style="background:#f8f8f8;border-radius:8px;padding:14px 18px;margin-bottom:20px;border-left:4px solid #0d0d14">
      <p style="margin:0 0 4px;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:.5px">Numero Protocollo</p>
      <p style="font-size:22px;font-weight:900;color:#0d0d14;margin:0;letter-spacing:2px">{protocollo}</p>
    </div>

    <!-- Tecnico + Fascia -->
    <table style="width:100%;border-collapse:collapse;margin-bottom:20px">
      <tr>
        <td style="padding:12px 16px;background:#f0f4ff;border-radius:8px 8px 0 0;width:40%">
          <p style="margin:0;font-size:11px;color:#666;text-transform:uppercase;letter-spacing:.5px">{T["tecnico_label"]}</p>
          <p style="margin:4px 0 0;font-size:20px;font-weight:900;color:#0d0d14">👷 {tecnico_nome}</p>
        </td>
        <td style="padding:12px 16px;background:#f0f4ff;border-radius:8px 8px 0 0;border-left:3px solid #fff">
          <p style="margin:0;font-size:11px;color:#666;text-transform:uppercase;letter-spacing:.5px">{T["fascia_label"]}</p>
          <p style="margin:4px 0 0;font-size:16px;font-weight:700;color:#1565c0">{fascia_label}</p>
        </td>
      </tr>
    </table>

    <!-- Preventivo EVIDENZIATO -->
    {prev_html}

    <!-- Info macchina -->
    <div style="background:#fafafa;border-radius:8px;padding:14px 18px;margin:16px 0;border:1px solid #eee">
      <p style="margin:0 0 8px;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:.5px">Riepilogo richiesta</p>
      <p style="margin:4px 0;font-size:13px"><b>Macchina:</b> {marca} {modello or ''}</p>
      {"<p style='margin:4px 0;font-size:13px'><b>Seriale:</b> "+seriale+"</p>" if seriale else ""}
      <p style="margin:4px 0;font-size:13px"><b>Indirizzo:</b> {indirizzo}</p>
      <p style="margin:4px 0;font-size:13px"><b>Problema:</b> {problema}</p>
    </div>

    <p style="font-size:13px;color:#555;margin:16px 0">{T["contatto"]}</p>

    <!-- Annulla -->
    <div style="background:#fff3cd;border-radius:8px;padding:12px 16px;margin:16px 0;border:1px solid #ffe082">
      <p style="margin:0;font-size:13px"><b>{T["annulla"]}</b> <a href="tel:+390641400514" style="color:#0d0d14;font-weight:700">+39 06 41 40 0514</a></p>
    </div>

    <p style="color:#888;font-size:12px;margin-top:24px;border-top:1px solid #f0f0f0;padding-top:14px">
      {T["ufficio"]} <a href="tel:+390641400617" style="color:#555">+39 06 41400617</a><br>
      Rotondi Group Roma — Via di Sant'Alessandro 349, Roma
    </p>
  </div>
</div>"""

    # ── Invio ─────────────────────────────────────────────────────────────────
    destinatari = []
    if email_cliente:
        destinatari.append(("cliente", email_cliente))
    if UFFICIO_EMAIL:
        destinatari.append(("ufficio", UFFICIO_EMAIL))
    # Se UFFICIO_EMAIL non impostato, manda a TECNICI_EMAIL come fallback ufficio
    elif TECNICI_EMAIL and TECNICI_EMAIL != email_cliente:
        destinatari.append(("ufficio_fallback", TECNICI_EMAIL))

    for tipo, dest in destinatari:
        try:
            # Per l'ufficio aggiungo nel subject chi ha preso in carico
            if tipo != "cliente":
                sogg_uff = f"[ASSEGNATA {tecnico_nome}] #{protocollo} — {marca} — {nome}"
            else:
                sogg_uff = soggetto

            msg = MIMEMultipart("alternative")
            msg["Subject"] = sogg_uff
            msg["From"]    = SMTP_F
            msg["To"]      = dest
            msg.attach(MIMEText(corpo_html, "html"))
            _smtp_send(msg, dest)
            app.logger.info(f"Email assegnazione inviata a {tipo} ({dest}) — {protocollo}")
        except Exception as e:
            app.logger.error(f"Email assegnazione {tipo} ({dest}): {e}")


# ─── TELEGRAM WEBHOOK ────────────────────────────────────────────────────────

@app.route("/webhook/telegram", methods=["POST"])
def telegram_webhook():
    """
    Riceve i callback_query da Telegram quando un tecnico preme un bottone fascia.
    Aggiorna il DB e risponde con un messaggio di conferma.
    """
    try:
        update = request.get_json(force=True)
        if not update:
            return "ok"

        cb = update.get("callback_query")
        if not cb:
            return "ok"

        cb_id   = cb["id"]
        cb_data = cb.get("data","")
        from_user = cb.get("from",{})
        tecnico_nome = from_user.get("first_name","") + (" " + from_user.get("last_name","") if from_user.get("last_name") else "")

        # Formato atteso: wfascia|PROTOCOLLO|FASCIA
        parts = cb_data.split("|")
        if len(parts) == 3 and parts[0] == "wfascia":
            _, protocollo, fascia = parts

            FASCE = {
                "entro12":  "🕛 Entro le 12:00",
                "entro18":  "🕕 Entro le 18:00",
                "giornata": "📅 In giornata",
                "domani":   "📆 Entro domani",
                "programma":"🗓 Da programmare",
            }
            fascia_label = FASCE.get(fascia, fascia)

            # Aggiorna DB
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("""
                    UPDATE richieste_web
                    SET stato='assegnata', tecnico=?, fascia=?
                    WHERE protocollo=?
                """, (tecnico_nome, fascia_label, protocollo))
                conn.commit()

            # ✉️ Manda email al cliente + ufficio in background
            _p = protocollo; _t = tecnico_nome; _f = fascia_label
            threading.Thread(
                target=lambda: invia_email_assegnazione(_p, _t, _f),
                daemon=True
            ).start()

            # Risponde al callback (rimuove la rotellina di caricamento su Telegram)
            try:
                import requests as rq
                rq.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
                        json={"callback_query_id": cb_id,
                              "text": f"✅ Preso in carico da {tecnico_nome}"},
                        timeout=5)

                # Modifica il messaggio originale togliendo i bottoni e aggiungendo la conferma
                msg_id   = cb.get("message",{}).get("message_id")
                chat_id  = cb.get("message",{}).get("chat",{}).get("id")
                old_text = cb.get("message",{}).get("text","")
                new_text = old_text + f"\n\n✅ *Assegnata a {tecnico_nome}* — {fascia_label}"
                if msg_id and chat_id:
                    rq.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText",
                            json={"chat_id": chat_id, "message_id": msg_id,
                                  "text": new_text, "parse_mode": "Markdown"},
                            timeout=5)
            except Exception as e2:
                app.logger.error(f"TG answer: {e2}")

        return "ok"
    except Exception as e:
        app.logger.error(f"Webhook: {e}")
        return "ok"


# ─── ROUTES ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    cond_it = get_config("condizioni_it", CONDIZIONI_IT_DEFAULT)
    cond_en = get_config("condizioni_en", CONDIZIONI_EN_DEFAULT)
    return render_template_string(HTML_FORM,
                                  condizioni_it=cond_it,
                                  condizioni_en=cond_en)


@app.route("/calcola-preventivo", methods=["POST"])
def route_preventivo():
    data = request.get_json()
    indirizzo = data.get("indirizzo","").strip()
    if not indirizzo: return jsonify({"error":"indirizzo mancante"}), 400
    prev = calcola_preventivo(indirizzo)
    if not prev: return jsonify({"error":"impossibile calcolare"}), 200
    return jsonify(prev)


@app.route("/invia", methods=["POST"])
def route_invia():
    """
    Riceve form dati (multipart) con possibili foto allegate.
    """
    try:
        # Supporta sia JSON che multipart/form-data
        if request.content_type and "multipart" in request.content_type:
            data = request.form.to_dict()
            files = request.files.getlist("foto")
        else:
            data = request.get_json(force=True)
            files = []

        protocollo = "RG" + datetime.now().strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:4].upper()

        via       = data.get("via","").strip()
        civico    = data.get("civico","").strip()
        cap       = data.get("cap","").strip()
        citta     = data.get("citta","").strip()
        provincia = data.get("provincia","").strip().upper()
        indirizzo = f"{via}, {civico}, {cap} {citta} ({provincia}), Italia"
        lingua    = data.get("lingua","it")
        prev_json = data.get("preventivo")

        # Salva foto
        foto_paths = []
        for i, f in enumerate(files):
            if f and f.filename:
                ext = os.path.splitext(f.filename)[1].lower() or ".jpg"
                if ext not in [".jpg",".jpeg",".png",".gif",".webp",".heic"]:
                    continue
                fname = f"{protocollo}_foto{i+1}{ext}"
                fpath = os.path.join(UPLOAD_FOLDER, fname)
                f.save(fpath)
                foto_paths.append(fpath)

        foto_json = json.dumps(foto_paths) if foto_paths else None

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO richieste_web
                (protocollo,nome,via,civico,cap,citta,provincia,indirizzo,
                 telefono,email,marca,modello,seriale,problema,data,lingua,preventivo,foto_paths)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (protocollo,
                  data.get("nome",""), via, civico, cap, citta, provincia, indirizzo,
                  data.get("telefono",""), data.get("email",""),
                  data.get("marca",""), data.get("modello",""),
                  data.get("seriale",""), data.get("problema",""),
                  datetime.now().strftime("%d/%m/%Y %H:%M"), lingua, prev_json, foto_json))
            conn.commit()

        # Testo preventivo
        prev_text = ""
        if prev_json:
            try:
                prev = json.loads(prev_json)
                if prev.get("zona") == "outside_gra":
                    prev_text = f"EUR {prev['costo_min']:.2f} + IVA ({prev.get('dist_label','')} — {prev.get('dur_label','')})"
                else:
                    prev_text = f"Zona Roma (GRA): EUR {prev.get('costo_min',80):.2f} + IVA"
            except: pass

        prev_tg = (f"\n💰 *Preventivo:* {prev_text}") if prev_text else ""
        link_maps = "https://www.google.com/maps/search/?api=1&query=" + indirizzo.replace(" ","+")

        keyboard = {"inline_keyboard": [
            [{"text":"🕛 Entro le 12:00","callback_data":f"wfascia|{protocollo}|entro12"},
             {"text":"🕕 Entro le 18:00","callback_data":f"wfascia|{protocollo}|entro18"}],
            [{"text":"📅 In giornata","callback_data":f"wfascia|{protocollo}|giornata"},
             {"text":"📆 Entro domani","callback_data":f"wfascia|{protocollo}|domani"}],
            [{"text":"🗓 Da programmare","callback_data":f"wfascia|{protocollo}|programma"}],
        ]}
        FLAG = {"it":"🇮🇹","en":"🇬🇧","bn":"🇧🇩","zh":"🇨🇳","ar":"🇸🇦"}.get(lingua,"🌍")
        foto_nota = f"\n📸 *Foto:* {len(foto_paths)} immagini allegate" if foto_paths else ""
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
            f"{prev_tg}{foto_nota}\n{'─'*30}\n"
            f"⏰ Primo tecnico disponibile:"
        )

        # ── Tutte le notifiche in background: risposta immediata al cliente ──
        _lingua    = lingua
        _proto     = protocollo
        _prev_text = prev_text
        _foto      = list(foto_paths)
        _testo     = testo
        _keyboard  = keyboard
        _dati = {
            "nome":      data.get("nome",""),
            "email":     data.get("email",""),
            "telefono":  data.get("telefono",""),
            "indirizzo": indirizzo,
            "via": via, "civico": civico, "cap": cap,
            "citta": citta, "provincia": provincia,
            "marca":    data.get("marca",""),
            "modello":  data.get("modello",""),
            "seriale":  data.get("seriale",""),
            "problema": data.get("problema",""),
        }

        def _invia_tutto():
            try:
                invia_telegram(_testo, _keyboard)
                for i, fp in enumerate(_foto):
                    invia_telegram_foto(fp, caption=f"📸 Foto {i+1}/{len(_foto)} — {_proto}")
                invia_email_cliente(_dati["email"], _dati["nome"], _proto, _lingua)
                invia_email_tecnico(dati=_dati, protocollo=_proto,
                                    prev_text=_prev_text, foto_paths=_foto)
            except Exception as ex:
                app.logger.error(f"Background notifica: {ex}")

        threading.Thread(target=_invia_tutto, daemon=True).start()

        return jsonify({"protocollo": protocollo, "ok": True})

    except Exception as e:
        app.logger.error(f"Errore /invia: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/uploads/<filename>")
def serve_upload(filename):
    """Serve le foto caricate (solo admin autenticato)"""
    if not session.get("admin"):
        return "Accesso negato", 403
    from flask import send_from_directory
    return send_from_directory(UPLOAD_FOLDER, filename)


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
        msg = "✅ Salvato con successo!"
    tar = get_tariffe()
    cond_it = get_config("condizioni_it", CONDIZIONI_IT_DEFAULT)
    cond_en = get_config("condizioni_en", CONDIZIONI_EN_DEFAULT)
    with sqlite3.connect(DB_PATH) as conn:
        richieste = conn.execute("""
            SELECT protocollo,nome,indirizzo,telefono,marca,problema,stato,tecnico,fascia,data,lingua,foto_paths
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
        conn.execute("UPDATE richieste_web SET stato='aperta',tecnico=NULL,fascia=NULL WHERE protocollo=?",
                     (protocollo,)); conn.commit()
    return redirect("/admin")


@app.route("/admin/assegna/<protocollo>", methods=["POST"])
def admin_assegna(protocollo):
    """Assegna manualmente dal pannello admin"""
    if not session.get("admin"): return redirect("/admin")
    tecnico = request.form.get("tecnico","").strip()
    fascia  = request.form.get("fascia","").strip()
    if tecnico and fascia:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                UPDATE richieste_web SET stato='assegnata', tecnico=?, fascia=?
                WHERE protocollo=?
            """, (tecnico, fascia, protocollo))
            conn.commit()
        # ✉️ Stessa email in background
        _p = protocollo; _t = tecnico; _f = fascia
        threading.Thread(
            target=lambda: invia_email_assegnazione(_p, _t, _f),
            daemon=True
        ).start()
    return redirect("/admin")


@app.route("/health")
def health():
    return "OK", 200


# ─── TEMPLATES ────────────────────────────────────────────────────────────────

HTML_FORM = r"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Assistenza Tecnica — Rotondi Group Roma</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#f0f0f0;min-height:100vh}
.header{background:#0d0d14;color:#fff;padding:20px;text-align:center}
.header h1{font-size:22px;letter-spacing:1px}
.header p{font-size:13px;color:#aaa;margin-top:4px}
.lang-bar{background:#fff;border-bottom:1px solid #eee;padding:10px;text-align:center}
.lang-btn{display:inline-flex;align-items:center;gap:6px;margin:0 4px;font-size:13px;
  color:#666;text-decoration:none;cursor:pointer;padding:6px 12px;border-radius:20px;
  border:1.5px solid #ddd;background:#fff;transition:all .2s;font-family:inherit}
.lang-btn:hover{border-color:#0d0d14;color:#0d0d14}
.lang-btn.active{color:#fff;background:#0d0d14;border-color:#0d0d14;font-weight:700}
.lang-flag{font-size:18px;line-height:1}
.container{max-width:640px;margin:24px auto;padding:0 16px 60px}
.steps{display:flex;justify-content:center;gap:8px;margin-bottom:24px}
.step{width:32px;height:4px;border-radius:2px;background:#ddd;transition:background .3s}
.step.active{background:#0d0d14}.step.done{background:#4caf50}
.card{background:#fff;border-radius:12px;padding:24px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,.07)}
.card h2{font-size:15px;font-weight:700;color:#0d0d14;margin-bottom:16px;padding-bottom:10px;border-bottom:2px solid #f0f0f0}
.field{margin-bottom:14px}
label{display:block;font-size:13px;font-weight:600;color:#444;margin-bottom:5px}
input,select,textarea{width:100%;padding:10px 12px;border:1.5px solid #ddd;border-radius:8px;
  font-size:14px;outline:none;transition:border .2s;font-family:inherit}
input:focus,select:focus,textarea:focus{border-color:#0d0d14}
textarea{resize:vertical;min-height:80px}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:480px){.row2{grid-template-columns:1fr}}
.btn{width:100%;background:#0d0d14;color:#fff;border:none;padding:14px;border-radius:10px;
  font-size:15px;font-weight:700;cursor:pointer;transition:opacity .2s;margin-top:4px}
.btn:hover{opacity:.88}.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-sec{width:100%;background:none;border:none;color:#666;font-size:14px;padding:10px;cursor:pointer;margin-top:6px}
.btn-calc{width:100%;background:#555;color:#fff;border:none;padding:11px;border-radius:8px;
  font-size:14px;cursor:pointer;margin-bottom:10px;transition:opacity .2s}
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
.prev-disclaimer{font-size:11px;color:#e65100;margin-top:4px;font-style:italic}
.chk-row{display:flex;align-items:flex-start;gap:10px;margin-bottom:10px}
.chk-row input[type=checkbox]{width:18px;height:18px;margin-top:2px;flex-shrink:0;cursor:pointer}
.chk-row label{font-size:13px;color:#444;font-weight:400;cursor:pointer}
.cond-box{background:#f8f8f8;border:1px solid #ddd;border-radius:8px;padding:14px;
  font-size:13px;line-height:1.7;max-height:180px;overflow-y:auto;white-space:pre-wrap;margin-bottom:12px}
.loading{display:none;text-align:center;padding:10px;font-size:13px;color:#666}
.spin{display:inline-block;width:16px;height:16px;border:2px solid #ddd;
  border-top-color:#0d0d14;border-radius:50%;animation:spin .7s linear infinite;vertical-align:middle;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
.ok-box{text-align:center;padding:40px 20px}
.ok-icon{font-size:56px;margin-bottom:16px}
.ok-box h2{font-size:22px;color:#0d0d14;margin-bottom:8px}
.ok-proto{font-size:24px;font-weight:700;color:#0d0d14;background:#f0f0f0;
  padding:10px 24px;border-radius:8px;display:inline-block;margin:14px 0;letter-spacing:2px}
.ok-box p{font-size:14px;color:#555;line-height:1.7}
/* Upload foto */
.foto-area{border:2px dashed #ddd;border-radius:10px;padding:20px;text-align:center;
  cursor:pointer;transition:border-color .2s;background:#fafafa;position:relative}
.foto-area:hover{border-color:#0d0d14}
.foto-area input[type=file]{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%}
.foto-icon{font-size:32px;margin-bottom:8px}
.foto-area p{font-size:13px;color:#666;margin:0}
.foto-area small{font-size:11px;color:#aaa}
.foto-preview{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.foto-thumb{position:relative;width:80px;height:80px;border-radius:8px;overflow:hidden;border:1.5px solid #ddd}
.foto-thumb img{width:100%;height:100%;object-fit:cover}
.foto-thumb .rm{position:absolute;top:2px;right:2px;background:rgba(0,0,0,.7);
  color:#fff;border:none;border-radius:50%;width:20px;height:20px;
  font-size:12px;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0}
.foto-count{font-size:12px;color:#666;margin-top:8px}
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
    <span class="lang-flag">&#127463;&#127465;</span> বাংলা
  </button>
  <button class="lang-btn" onclick="setLang('zh')" id="l_zh">
    <span class="lang-flag">&#127464;&#127475;</span> 中文
  </button>
  <button class="lang-btn" onclick="setLang('ar')" id="l_ar">
    <span class="lang-flag">&#127480;&#127462;</span> العربية
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
      <h2 id="t_gdpr_h">&#128274; Privacy (GDPR)</h2>
      <div class="cond-box">Rotondi Group Srl — Via F.lli Rosselli 14/16, 20019 Settimo Milanese (MI)
segnalazioni-privacy@rotondigroup.it

I tuoi dati saranno trattati per gestire la richiesta di assistenza.
Conservazione: max 2 anni. Diritti: accesso, rettifica, cancellazione.</div>
      <div class="chk-row">
        <input type="checkbox" id="chk_gdpr">
        <label for="chk_gdpr" id="t_gdpr_lbl">Accetto il trattamento dei dati personali ai sensi del GDPR</label>
      </div>
    </div>
    <div class="card">
      <h2 id="t_cond_h">&#128203; Condizioni del Servizio</h2>
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
      <h2 id="t_dati_h">&#128100; Dati Personali</h2>
      <div class="field"><label id="t_nome">Nome e Cognome *</label>
        <input id="nome" type="text" autocomplete="name"></div>
      <div class="field"><label id="t_email">Email</label>
        <input id="email" type="email" autocomplete="email"></div>
      <div class="field"><label id="t_tel">Telefono *</label>
        <input id="telefono" type="tel" autocomplete="tel"></div>
    </div>
    <div class="card">
      <h2 id="t_ind_h">&#128205; Indirizzo Intervento</h2>
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
        <h3 id="t_prev_h">&#128176; Preventivo Indicativo</h3>
        <p id="prev_zona"></p>
        <div class="prev-importo" id="prev_imp"></div>
        <p class="prev-detail" id="prev_det"></p>
        <p class="prev-nota" id="t_prev_nota">Preventivo indicativo per 1h di lavoro + IVA</p>
        <p class="prev-disclaimer" id="t_prev_disclaimer">⚠️ Preventivo indicativo — escluse parti di ricambio</p>
      </div>
    </div>
    <button class="btn" onclick="goStep3()" id="btn2">Continua &#8594;</button>
    <button class="btn-sec" onclick="goStep1()" id="t_back1">&#8592; Indietro</button>
  </div>

  <!-- STEP 3 -->
  <div id="step3" style="display:none">
    <div class="card">
      <h2 id="t_mac_h">&#127981; Dati Macchina</h2>
      <div class="row2">
        <div class="field"><label id="t_marca">Marca *</label>
          <input id="marca" type="text" placeholder="Es: Samsung"></div>
        <div class="field"><label id="t_modello">Modello</label>
          <input id="modello" type="text"></div>
      </div>
      <div class="field"><label id="t_seriale">Numero Seriale</label>
        <input id="seriale" type="text" placeholder="Dalla targhetta"></div>
      <div class="field"><label id="t_prob">Descrivi il Problema *</label>
        <textarea id="problema" placeholder="Cosa succede? Da quando? Hai già provato qualcosa?"></textarea></div>
    </div>

    <!-- UPLOAD FOTO -->
    <div class="card">
      <h2 id="t_foto_h">&#128247; Foto (opzionale)</h2>
      <div class="foto-area" onclick="triggerFoto()" id="foto_drop">
        <input type="file" id="foto_input" accept="image/*" multiple onchange="onFotoChange(this)">
        <div class="foto-icon">&#128247;</div>
        <p id="t_foto_desc">Aggiungi foto della macchina e del problema</p>
        <small id="t_foto_hint">Max 5 foto — JPG, PNG, HEIC</small>
      </div>
      <div class="foto-preview" id="foto_preview"></div>
      <p class="foto-count" id="foto_count"></p>
    </div>

    <button class="btn" onclick="invia()" id="btn3">&#128228; Invia Richiesta</button>
    <button class="btn-sec" onclick="goStep2back()" id="t_back2">&#8592; Indietro</button>
  </div>

  <!-- SUCCESS -->
  <div id="stepOK" style="display:none">
    <div class="card ok-box">
      <div class="ok-icon">&#9989;</div>
      <h2 id="t_ok_h">Richiesta Inviata!</h2>
      <div class="ok-proto" id="ok_proto"></div>
      <p id="t_ok_p">Un tecnico Rotondi Group Roma ti contatter&#224; a breve.<br><br>
      Per annullare urgentemente:<br><strong>&#128222; +39 06 41 40 0514</strong></p>
    </div>
  </div>
</div>

<script>
var lang='it', prevData=null, fotoFiles=[];
var COND_IT = """ + json.dumps(CONDIZIONI_IT_DEFAULT) + r""";
var COND_EN = """ + json.dumps(CONDIZIONI_EN_DEFAULT) + r""";

var L={
  it:{gdpr_h:'Privacy (GDPR)',gdpr_lbl:'Accetto il trattamento dei dati personali ai sensi del GDPR',
    cond_h:'Condizioni del Servizio',cond_lbl:'Accetto le condizioni del servizio',
    dati_h:'Dati Personali',nome:'Nome e Cognome *',email:'Email',tel:'Telefono *',
    ind_h:'Indirizzo Intervento',via:'Via / Piazza *',civico:'N\u00b0 Civico *',cap:'CAP *',
    citta:'Citt\u00e0 *',prov:'Provincia *',btn_calc:'Verifica distanza e preventivo',
    calc_lbl:'Calcolo in corso...',prev_h:'Preventivo Indicativo',
    prev_nota:'Preventivo indicativo per 1h di lavoro + IVA',
    prev_disclaimer:'\u26a0\ufe0f Preventivo indicativo \u2014 escluse parti di ricambio',
    inside:'Zona Roma (dentro GRA)',outside:'Fuori Roma',
    mac_h:'Dati Macchina',marca:'Marca *',modello:'Modello',seriale:'Numero Seriale',
    prob:'Descrivi il Problema *',
    foto_h:'Foto (opzionale)',
    foto_desc:'Aggiungi foto della macchina e del problema',
    foto_hint:'Max 5 foto \u2014 JPG, PNG, HEIC',
    btn1:'Continua \u2192',btn2:'Continua \u2192',
    btn3:'Invia Richiesta',back1:'\u2190 Indietro',back2:'\u2190 Indietro',
    ok_h:'Richiesta Inviata!',
    ok_p:'Un tecnico Rotondi Group Roma ti contatter\u00e0 a breve.<br><br>Per annullare urgentemente:<br><strong>+39 06 41 40 0514</strong>',
    err_consent:'Devi accettare privacy e condizioni per continuare',
    err_campi:'Compila tutti i campi obbligatori (*)'},
  en:{gdpr_h:'Privacy (GDPR)',gdpr_lbl:'I accept the processing of personal data under GDPR',
    cond_h:'Service Conditions',cond_lbl:'I accept the service conditions',
    dati_h:'Personal Details',nome:'Full Name *',email:'Email',tel:'Phone *',
    ind_h:'Service Address',via:'Street *',civico:'Number *',cap:'Postal Code *',
    citta:'City *',prov:'Province *',btn_calc:'Check distance & quote',
    calc_lbl:'Calculating...',prev_h:'Indicative Quote',
    prev_nota:'Indicative quote for 1h work + VAT',
    prev_disclaimer:'\u26a0\ufe0f Indicative quote \u2014 spare parts not included',
    inside:'Rome area (inside GRA)',outside:'Outside Rome',
    mac_h:'Machine Details',marca:'Brand *',modello:'Model',seriale:'Serial Number',
    prob:'Describe the Problem *',
    foto_h:'Photos (optional)',
    foto_desc:'Add photos of the machine and the problem',
    foto_hint:'Max 5 photos \u2014 JPG, PNG, HEIC',
    btn1:'Continue \u2192',btn2:'Continue \u2192',
    btn3:'Send Request',back1:'\u2190 Back',back2:'\u2190 Back',
    ok_h:'Request Sent!',
    ok_p:'A Rotondi Group Roma technician will contact you shortly.<br><br>To cancel urgently:<br><strong>+39 06 41 40 0514</strong>',
    err_consent:'You must accept privacy and conditions to continue',
    err_campi:'Please fill all required fields (*)'},
  bn:{gdpr_h:'গোপনীয়তা (GDPR)',gdpr_lbl:'আমি GDPR অনুযায়ী সম্মতি দিচ্ছি',
    cond_h:'শর্তাবলী',cond_lbl:'আমি শর্তাবলী গ্রহণ করছি',
    dati_h:'ব্যক্তিগত তথ্য',nome:'পুরো নাম *',email:'ইমেইল',tel:'ফোন *',
    ind_h:'ঠিকানা',via:'রাস্তা *',civico:'নম্বর *',cap:'পোস্টাল কোড *',
    citta:'শহর *',prov:'প্রদেশ *',btn_calc:'দূরত্ব যাচাই',calc_lbl:'হিসাব...',
    prev_h:'আনুমানিক খরচ',prev_nota:'১ ঘণ্টার আনুমানিক + ভ্যাট',
    prev_disclaimer:'\u26a0\ufe0f আনুমানিক \u2014 স্পেয়ার পার্টস ছাড়া',
    inside:'রোমা (GRA ভেতরে)',outside:'রোমার বাইরে',
    mac_h:'মেশিন',marca:'ব্র্যান্ড *',modello:'মডেল',seriale:'সিরিয়াল',
    prob:'সমস্যা বর্ণনা *',
    foto_h:'ছবি (ঐচ্ছিক)',foto_desc:'মেশিন ও সমস্যার ছবি যোগ করুন',foto_hint:'সর্বোচ্চ ৫টি ছবি',
    btn1:'এগিয়ে যান \u2192',btn2:'এগিয়ে যান \u2192',
    btn3:'পাঠান',back1:'\u2190 পেছনে',back2:'\u2190 পেছনে',
    ok_h:'অনুরোধ পাঠানো হয়েছে!',
    ok_p:'টেকনিশিয়ান শীঘ্রই যোগাযোগ করবেন।<br><br>বাতিল: <strong>+39 06 41 40 0514</strong>',
    err_consent:'গোপনীয়তা ও শর্তাবলী গ্রহণ করুন',err_campi:'সব প্রয়োজনীয় তথ্য পূরণ করুন'},
  zh:{gdpr_h:'隐私 (GDPR)',gdpr_lbl:'我同意根据GDPR处理个人数据',
    cond_h:'服务条款',cond_lbl:'我接受服务条款',
    dati_h:'个人信息',nome:'姓名 *',email:'邮箱',tel:'电话 *',
    ind_h:'服务地址',via:'街道 *',civico:'门牌号 *',cap:'邮政编码 *',
    citta:'城市 *',prov:'省份代码 *',btn_calc:'验证距离',calc_lbl:'计算中...',
    prev_h:'参考报价',prev_nota:'1小时工作参考报价 + 增值税',
    prev_disclaimer:'\u26a0\ufe0f 参考报价 \u2014 不含零件费用',
    inside:'罗马市区（GRA内）',outside:'罗马市外',
    mac_h:'机器信息',marca:'品牌 *',modello:'型号',seriale:'序列号',
    prob:'描述问题 *',
    foto_h:'照片（可选）',foto_desc:'上传机器和故障照片',foto_hint:'最多5张',
    btn1:'继续 \u2192',btn2:'继续 \u2192',
    btn3:'发送',back1:'\u2190 返回',back2:'\u2190 返回',
    ok_h:'请求已发送！',
    ok_p:'技术人员将很快联系您。<br><br>取消: <strong>+39 06 41 40 0514</strong>',
    err_consent:'请接受隐私政策和服务条款',err_campi:'请填写所有必填字段'},
  ar:{gdpr_h:'الخصوصية (GDPR)',gdpr_lbl:'أوافق على معالجة البيانات وفق GDPR',
    cond_h:'شروط الخدمة',cond_lbl:'أقبل شروط الخدمة',
    dati_h:'البيانات الشخصية',nome:'الاسم الكامل *',email:'البريد الإلكتروني',tel:'الهاتف *',
    ind_h:'عنوان الخدمة',via:'الشارع *',civico:'رقم المبنى *',cap:'الرمز البريدي *',
    citta:'المدينة *',prov:'رمز المحافظة *',btn_calc:'تحقق من المسافة',calc_lbl:'جارٍ الحساب...',
    prev_h:'عرض سعر تقريبي',prev_nota:'تقريبي لساعة عمل + ضريبة',
    prev_disclaimer:'\u26a0\ufe0f تقريبي \u2014 لا يشمل قطع الغيار',
    inside:'منطقة روما (داخل GRA)',outside:'خارج روما',
    mac_h:'بيانات الجهاز',marca:'الماركة *',modello:'الموديل',seriale:'الرقم التسلسلي',
    prob:'صف المشكلة *',
    foto_h:'صور (اختياري)',foto_desc:'أضف صور الجهاز والمشكلة',foto_hint:'5 صور كحد أقصى',
    btn1:'متابعة \u2192',btn2:'متابعة \u2192',
    btn3:'إرسال',back1:'\u2190 رجوع',back2:'\u2190 رجوع',
    ok_h:'تم إرسال الطلب!',
    ok_p:'سيتصل بك فني قريباً.<br><br>للإلغاء: <strong>+39 06 41 40 0514</strong>',
    err_consent:'يجب قبول سياسة الخصوصية والشروط',err_campi:'يرجى ملء جميع الحقول المطلوبة'}
};

function setLang(l){
  lang=l;
  document.querySelectorAll('.lang-btn').forEach(function(a){a.classList.remove('active');});
  document.getElementById('l_'+l).classList.add('active');
  var t=L[l];
  var map={
    't_gdpr_h':'gdpr_h','t_gdpr_lbl':'gdpr_lbl','t_cond_h':'cond_h','t_cond_lbl':'cond_lbl',
    't_dati_h':'dati_h','t_nome':'nome','t_email':'email','t_tel':'tel',
    't_ind_h':'ind_h','t_via':'via','t_civico':'civico','t_cap':'cap',
    't_citta':'citta','t_prov':'prov','t_calc_lbl':'calc_lbl',
    't_prev_h':'prev_h','t_prev_nota':'prev_nota','t_prev_disclaimer':'prev_disclaimer',
    't_mac_h':'mac_h','t_marca':'marca','t_modello':'modello',
    't_seriale':'seriale','t_prob':'prob',
    't_foto_h':'foto_h','t_foto_desc':'foto_desc','t_foto_hint':'foto_hint',
    'btn1':'btn1','btn2':'btn2','btn3':'btn3','t_back1':'back1','t_back2':'back2'
  };
  for(var id in map){
    var el=document.getElementById(id);
    if(el) el.textContent=t[map[id]];
  }
  document.getElementById('btn_calc').textContent=t.btn_calc;
  if(l==='it') document.getElementById('cond_box').textContent=COND_IT;
  else if(l==='en') document.getElementById('cond_box').textContent=COND_EN;
}

/* ---- FOTO ---- */
function triggerFoto(){
  // già gestito dall'input sovrapposto
}
function onFotoChange(input){
  var newFiles=Array.from(input.files);
  for(var i=0;i<newFiles.length;i++){
    if(fotoFiles.length>=5) break;
    fotoFiles.push(newFiles[i]);
  }
  input.value=''; // reset per permettere ri-selezione stessa foto
  renderFoto();
}
function removeFoto(idx){
  fotoFiles.splice(idx,1);
  renderFoto();
}
function renderFoto(){
  var preview=document.getElementById('foto_preview');
  var count=document.getElementById('foto_count');
  preview.innerHTML='';
  fotoFiles.forEach(function(f,i){
    var url=URL.createObjectURL(f);
    var div=document.createElement('div');
    div.className='foto-thumb';
    div.innerHTML='<img src="'+url+'" alt="foto '+i+'"><button class="rm" onclick="removeFoto('+i+')">&#215;</button>';
    preview.appendChild(div);
  });
  count.textContent=fotoFiles.length>0?fotoFiles.length+' foto selezionat'+(fotoFiles.length===1?'a':'e'):'';
}

/* ---- STEPS ---- */
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
  if(!document.getElementById('chk_gdpr').checked||!document.getElementById('chk_cond').checked){
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
  var f=['nome','telefono','via','civico','cap','citta','provincia'];
  for(var i=0;i<f.length;i++){
    if(!document.getElementById(f[i]).value.trim()){alert(L[lang].err_campi);return;}
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
  var prv=document.getElementById('provincia').value.trim().toUpperCase();
  return via+', '+civ+', '+cap+' '+cit+' ('+prv+'), Italia';
}
function calcolaPreventivo(){
  var f=['via','civico','cap','citta','provincia'];
  for(var i=0;i<f.length;i++){
    if(!document.getElementById(f[i]).value.trim()){alert(L[lang].err_campi);return;}
  }
  document.getElementById('loading_p').style.display='block';
  document.getElementById('prev_box').style.display='none';
  fetch('/calcola-preventivo',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({indirizzo:buildInd()})})
  .then(function(r){return r.json();})
  .then(function(data){
    document.getElementById('loading_p').style.display='none';
    if(!data.zona) return;
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
    document.getElementById('t_prev_disclaimer').textContent=t.prev_disclaimer;
    box.style.display='block';
  }).catch(function(){
    document.getElementById('loading_p').style.display='none';
  });
}

/* ---- INVIA (multipart con foto) ---- */
function invia(){
  var f=['nome','telefono','marca','problema'];
  for(var i=0;i<f.length;i++){
    if(!document.getElementById(f[i]).value.trim()){alert(L[lang].err_campi);return;}
  }
  var btn=document.getElementById('btn3');
  btn.disabled=true;
  btn.textContent='\u23f3 Invio in corso...';

  var fd=new FormData();
  fd.append('nome',document.getElementById('nome').value.trim());
  fd.append('email',document.getElementById('email').value.trim());
  fd.append('telefono',document.getElementById('telefono').value.trim());
  fd.append('via',document.getElementById('via').value.trim());
  fd.append('civico',document.getElementById('civico').value.trim());
  fd.append('cap',document.getElementById('cap').value.trim());
  fd.append('citta',document.getElementById('citta').value.trim());
  fd.append('provincia',document.getElementById('provincia').value.trim().toUpperCase());
  fd.append('marca',document.getElementById('marca').value.trim());
  fd.append('modello',document.getElementById('modello').value.trim());
  fd.append('seriale',document.getElementById('seriale').value.trim());
  fd.append('problema',document.getElementById('problema').value.trim());
  fd.append('lingua',lang);
  if(prevData) fd.append('preventivo',JSON.stringify(prevData));
  fotoFiles.forEach(function(f){ fd.append('foto',f); });

  fetch('/invia',{method:'POST', body:fd})
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
      btn.disabled=false;
      btn.textContent=L[lang].btn3;
      alert('Errore invio. Riprova.');
    }
  }).catch(function(){
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
<title>Admin — Rotondi Group Roma</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Arial,sans-serif;background:#f0f0f0;display:flex;align-items:center;justify-content:center;min-height:100vh}
.box{background:#fff;border-radius:12px;padding:40px;width:100%;max-width:380px;box-shadow:0 4px 20px rgba(0,0,0,.1)}
h2{font-size:20px;margin-bottom:24px;color:#0d0d14;text-align:center}
input{width:100%;padding:12px;border:1.5px solid #ddd;border-radius:8px;font-size:15px;margin-bottom:16px;outline:none}
input:focus{border-color:#0d0d14}
button{width:100%;background:#0d0d14;color:#fff;border:none;padding:12px;border-radius:8px;font-size:15px;cursor:pointer}
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
</div></body></html>"""


HTML_ADMIN = """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin — Rotondi Group Roma</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Arial,sans-serif;background:#f0f0f0;color:#222}
.topbar{background:#0d0d14;color:#fff;padding:16px 24px;display:flex;align-items:center;justify-content:space-between}
.topbar h1{font-size:18px}
.topbar a{color:#aaa;font-size:13px;text-decoration:none}
.topbar a:hover{color:#fff}
.container{max-width:1100px;margin:24px auto;padding:0 16px 60px}
.card{background:#fff;border-radius:10px;padding:24px;margin-bottom:20px;box-shadow:0 2px 8px rgba(0,0,0,.07)}
.card h2{font-size:16px;font-weight:700;color:#0d0d14;margin-bottom:18px;border-bottom:2px solid #f0f0f0;padding-bottom:10px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:600px){.grid2{grid-template-columns:1fr}}
.field{margin-bottom:14px}
label{display:block;font-size:13px;font-weight:600;color:#555;margin-bottom:5px}
input[type=text],input[type=number],input[type=password],textarea{width:100%;padding:10px;border:1.5px solid #ddd;border-radius:8px;font-size:14px;outline:none}
input:focus,textarea:focus{border-color:#0d0d14}
textarea{resize:vertical;min-height:120px;font-family:monospace;font-size:12px}
.btn{background:#0d0d14;color:#fff;border:none;padding:12px 28px;border-radius:8px;font-size:14px;cursor:pointer;font-weight:700}
.btn:hover{opacity:.88}
.btn-sm{background:#0d0d14;color:#fff;border:none;padding:6px 12px;border-radius:6px;font-size:12px;cursor:pointer;font-weight:600}
.btn-sm:hover{opacity:.85}
.msg{background:#e8f5e9;color:#2e7d32;padding:12px 16px;border-radius:8px;margin-bottom:16px;font-size:14px;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:12px}
th{background:#f5f5f5;padding:10px 8px;text-align:left;font-weight:600;color:#555;border-bottom:2px solid #eee;white-space:nowrap}
td{padding:8px 8px;border-bottom:1px solid #f0f0f0;vertical-align:top}
tr:hover td{background:#fafafa}
.badge{display:inline-block;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:700}
.b-open{background:#fff3cd;color:#856404}
.b-ass{background:#d4edda;color:#155724}
a.sblocca{color:#e53935;font-size:12px;text-decoration:none}
a.sblocca:hover{text-decoration:underline}
.foto-row{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.foto-row a img{width:50px;height:50px;object-fit:cover;border-radius:4px;border:1px solid #ddd}
/* Modal assegna */
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:100;align-items:center;justify-content:center}
.modal-bg.open{display:flex}
.modal{background:#fff;border-radius:12px;padding:28px;width:340px;max-width:96vw}
.modal h3{font-size:16px;font-weight:700;margin-bottom:18px;color:#0d0d14}
.modal select,.modal input{width:100%;padding:10px;border:1.5px solid #ddd;border-radius:8px;font-size:14px;margin-bottom:12px;outline:none}
.modal select:focus,.modal input:focus{border-color:#0d0d14}
.modal .row{display:flex;gap:10px;margin-top:4px}
.modal .row button{flex:1}
.btn-cancel{background:#eee;color:#333;border:none;padding:10px;border-radius:8px;font-size:14px;cursor:pointer}
</style>
</head>
<body>
<div class="topbar">
  <h1>Admin — Rotondi Group Roma</h1>
  <a href="/admin/logout">Esci</a>
</div>
<div class="container">
  {% if msg %}<div class="msg">{{ msg }}</div>{% endif %}
  <form method="POST">
    <div class="card">
      <h2>Tariffe</h2>
      <div class="grid2">
        <div class="field"><label>Uscita + 1h dentro GRA (EUR)</label>
          <input type="number" step="0.01" name="tariffa_dentro_uscita" value="{{ '%.2f'|format(tar.dentro_uscita) }}"></div>
        <div class="field"><label>Ora extra lavoro (EUR)</label>
          <input type="number" step="0.01" name="tariffa_dentro_ora_extra" value="{{ '%.2f'|format(tar.dentro_ora_extra) }}"></div>
        <div class="field"><label>Km trasferta fuori GRA (EUR/km)</label>
          <input type="number" step="0.01" name="tariffa_fuori_km" value="{{ '%.2f'|format(tar.fuori_km) }}"></div>
        <div class="field"><label>Ora viaggio (EUR/h)</label>
          <input type="number" step="0.01" name="tariffa_fuori_ora_viaggio" value="{{ '%.2f'|format(tar.fuori_ora_viaggio) }}"></div>
        <div class="field"><label>Ora lavoro fuori GRA (EUR/h)</label>
          <input type="number" step="0.01" name="tariffa_fuori_ora_lavoro" value="{{ '%.2f'|format(tar.fuori_ora_lavoro) }}"></div>
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
        <th>Protocollo</th><th>Cliente</th><th>Indirizzo</th><th>Tel</th>
        <th>Marca/Modello</th><th>Problema</th><th>Stato</th><th>Tecnico</th><th>Fascia</th><th>Data</th><th>Foto</th><th>Azioni</th>
      </tr>
      {% for r in richieste %}
      <tr>
        <td><code style="font-size:11px">{{ r[0] }}</code></td>
        <td style="white-space:nowrap">{{ r[1] }}</td>
        <td style="font-size:11px;min-width:140px">{{ r[2] }}</td>
        <td style="white-space:nowrap"><a href="tel:{{ r[3] }}" style="color:#0d0d14">{{ r[3] }}</a></td>
        <td style="font-size:12px">{{ r[4] }}<br><span style="color:#888">{{ r[10] or '' }}</span></td>
        <td style="max-width:140px;font-size:11px">{{ (r[5] or '')[:60] }}{% if r[5] and r[5]|length > 60 %}...{% endif %}</td>
        <td>
          {% if r[6]=='aperta' %}<span class="badge b-open">aperta</span>
          {% elif r[6]=='assegnata' %}<span class="badge b-ass">assegnata</span>
          {% else %}<span class="badge" style="background:#d1ecf1;color:#0c5460">{{ r[6] }}</span>{% endif %}
        </td>
        <td style="font-size:12px">{{ r[7] or '—' }}</td>
        <td style="font-size:11px;white-space:nowrap">{{ r[8] or '—' }}</td>
        <td style="font-size:11px;white-space:nowrap">{{ r[9] }}</td>
        <td>
          {% if r[11] %}
            {% set foto_list = r[11] | tojson %}
            <div class="foto-row">
            {% for fp in r[11] | from_json %}
              <a href="/uploads/{{ fp.split('/')[-1] }}" target="_blank">
                <img src="/uploads/{{ fp.split('/')[-1] }}" alt="foto">
              </a>
            {% endfor %}
            </div>
          {% else %}—{% endif %}
        </td>
        <td style="white-space:nowrap">
          <button class="btn-sm" onclick="openAssegna('{{ r[0] }}','{{ r[7] or '' }}','{{ r[8] or '' }}')">Assegna</button>
          {% if r[6] != 'aperta' %}
          &nbsp;<a href="/admin/sblocca/{{ r[0] }}" class="sblocca"
             onclick="return confirm('Sbloccare questa richiesta?')">Sblocca</a>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </table>
    </div>
  </div>
</div>

<!-- Modal assegna -->
<div class="modal-bg" id="modal_bg">
  <div class="modal">
    <h3>&#128221; Assegna Richiesta</h3>
    <form method="POST" id="form_assegna">
      <input type="text" name="tecnico" id="m_tecnico" placeholder="Nome tecnico *" required>
      <select name="fascia" id="m_fascia">
        <option value="🕛 Entro le 12:00">🕛 Entro le 12:00</option>
        <option value="🕕 Entro le 18:00">🕕 Entro le 18:00</option>
        <option value="📅 In giornata">📅 In giornata</option>
        <option value="📆 Entro domani">📆 Entro domani</option>
        <option value="🗓 Da programmare">🗓 Da programmare</option>
      </select>
      <div class="row">
        <button type="submit" class="btn">Salva</button>
        <button type="button" class="btn-cancel" onclick="closeModal()">Annulla</button>
      </div>
    </form>
  </div>
</div>

<script>
function openAssegna(proto, tecnico, fascia){
  document.getElementById('form_assegna').action='/admin/assegna/'+proto;
  document.getElementById('m_tecnico').value=tecnico||'';
  var sel=document.getElementById('m_fascia');
  if(fascia){
    for(var i=0;i<sel.options.length;i++){
      if(sel.options[i].value===fascia){sel.selectedIndex=i;break;}
    }
  }
  document.getElementById('modal_bg').classList.add('open');
}
function closeModal(){
  document.getElementById('modal_bg').classList.remove('open');
}
document.getElementById('modal_bg').addEventListener('click',function(e){
  if(e.target===this) closeModal();
});
</script>
</body></html>"""


# Filtro Jinja per from_json
import json as _json
app.jinja_env.filters['from_json'] = lambda s: _json.loads(s) if s else []


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
