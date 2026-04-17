#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOT TELEGRAM — Assistenza Tecnica Macchinari
Rotondi Group Roma
"""

import logging, sqlite3, asyncio, os
from datetime import datetime, timedelta
from deep_translator import GoogleTranslator
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)

BOT_TOKEN        = os.environ.get("BOT_TOKEN", "IL_TUO_TOKEN_QUI")
TECNICI_GROUP_ID = int(os.environ.get("TECNICI_GROUP_ID", "-1001234567890"))
BACKOFFICE_IDS   = [int(x) for x in os.environ.get("BACKOFFICE_IDS", "123456789").split(",")]
NOME_AZIENDA     = "Rotondi Group Roma"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

DB_PATH = "assistenza.db"

(CONDIZIONI, SCEGLI_LINGUA, NOME, INDIRIZZO, TELEFONO,
 FOTO_TARGHETTA, MARCA, MODELLO, SERIALE,
 PROBLEMA, FOTO_MACCHINA, CONFERMA) = range(12)

TESTI = {
    "it": {
                "condizioni": (
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔧  *ROTONDI GROUP SRL*\n"
            "     Filiale di Roma\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ *INFORMATIVA SUL SERVIZIO*\n\n"
            "L'assistenza tecnica Rotondi Group è un *servizio a pagamento*, "
            "anche nel caso in cui l'intervento riguardi un prodotto *in garanzia*.\n\n"
            "✅ *Cosa riconosciamo in garanzia:*\n"
            "› Le *parti di ricambio difettose* vengono sostituite senza costo\n\n"
            "💶 *Cosa è sempre a carico del cliente:*\n"
            "› Manodopera\n"
            "› Spostamento del tecnico\n"
            "› Costo della chiamata\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📍 *TARIFFE ZONA DI ROMA*\n_(Dentro il Grande Raccordo Anulare)_\n"
            "› Uscita + 1 ora di lavoro: *€ 80,00 + IVA*\n"
            "› Ore successive: *€ 40,00/ora + IVA*\n\n"
            "🗺 *TARIFFE PROVINCIA DI ROMA, LAZIO E RESTO D'ITALIA*\n"
            "› Km trasferta: *€ 0,70/km + IVA* _(A/R)_\n"
            "› Ore di viaggio: *€ 32,00/ora + IVA* _(A/R)_\n"
            "› Ore di lavoro: *€ 40,00/ora + IVA*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "_Il pagamento va effettuato direttamente al tecnico "
            "al termine del servizio._\n\n"
            "👨\u200d🔧 *I NOSTRI TECNICI*\n"
            "I tecnici che operano con Rotondi Group sono *liberi professionisti "
            "freelance indipendenti*, selezionati e incaricati dalla nostra azienda "
            "per l'assistenza e la riparazione dei nostri macchinari. "
            "Non sono dipendenti Rotondi Group.\n\n"
            "Accetti queste condizioni e vuoi procedere con la richiesta?"
        ),
        "condizioni_no": (
            "❌ *Servizio non accettato*\n\n"
            "Ha scelto di non procedere con la richiesta di assistenza.\n\n"
            "Se cambia idea può riaprire la richiesta in qualsiasi momento scrivendo /start\n\n"
            "_Rotondi Group Roma_"
        ),
        "nome":           "┌─────────────────────\n│ 👤  *DATI PERSONALI*\n└─────────────────────\n\nCome ti chiami?\n_Scrivi nome e cognome_",
        "indirizzo":      "📍 *Indirizzo di intervento*\n\n_Via, numero civico e città_",
        "telefono":       "📞 *Numero di telefono*\n\n_Ti contatteremo su questo numero_",
        "foto_targhetta": "📸 *Foto targhetta macchina*\n\n_Inquadra l\'etichetta con marca, modello e seriale_\n\nSe non riesci scrivi *salta*",
        "marca":          "🏭 *Marca della macchina*\n\n_Es: Samsung, LG, Bosch..._",
        "modello":        "🔖 *Modello della macchina*\n\n_Lo trovi sulla targhetta o nel libretto_",
        "seriale":        "🔢 *Numero seriale*\n\n_Lo trovi sulla targhetta del macchinario_",
        "problema":       "🔧 *Descrivi il problema*\n\n_Cosa succede? Da quando? Hai già provato qualcosa?_",
        "foto_macchina":  "📷 *Foto della macchina*\n\n_Una foto ci aiuta a preparare l\'intervento_\n\nSe non riesci scrivi *salta*",
        "riepilogo": (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📋  *RIEPILOGO RICHIESTA*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "👤  {nome}\n"
            "📍  {indirizzo}\n"
            "📞  {telefono}\n\n"
            "🏭  *{marca}*  ·  {modello}\n"
            "🔢  Seriale: {seriale}\n\n"
            "🔧  _{problema}_\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "È tutto corretto?"
        ),
        "si":  "✅  Confermo",
        "no":  "✏️  Correggi",
        "registrata": (
            "✅ *Richiesta ricevuta!*\n\n"
            "Gentile Cliente, la sua richiesta è stata registrata.\n"
            "Un tecnico *Rotondi Group Roma* la contatterà a breve.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💶  *TARIFFE*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📍 *TARIFFE ZONA DI ROMA* _(Dentro il Grande Raccordo Anulare)_\n"
            "› Uscita + 1h lavoro: *€ 80,00 + IVA*\n"
            "› Ore successive: *€ 40,00/h + IVA*\n\n"
            "🗺 *TARIFFE PROVINCIA DI ROMA, LAZIO E RESTO D'ITALIA*\n"
            "› Km: *€ 0,70/km + IVA* _(A/R)_\n"
            "› Viaggio: *€ 32,00/h + IVA* _(A/R)_\n"
            "› Lavoro: *€ 40,00/h + IVA*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ Per *annullare* contatti URGENTEMENTE:\n"
            "📞 +39 06 41 40 0514\n"
            "In assenza di disdetta verrà addebitato il costo di uscita.\n\n"
            "_Il Team Rotondi Group Roma_"
        ),
        "assegnata": (
            "🎯 *Tecnico assegnato!*\n\n"
            "Gentile Cliente, la sua richiesta è stata presa in carico.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👨‍🔧  *{tecnico}*\n"
            "📞  Ufficio Roma: +39 06 41400617\n"
            "⏰  Arrivo previsto: *{fascia}*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "💶  *TARIFFE*\n"
            "› Roma: Uscita + 1h → *€ 80,00 + IVA*\n"
            "› Provincia di Roma, Lazio e resto d'Italia: *€ 0,70/km + IVA (A/R)* — *€ 32,00/h viaggio + IVA* — *€ 40,00/h lavoro + IVA*\n\n"
            "_Il pagamento va effettuato direttamente al tecnico._\n"
            "_I nostri tecnici sono professionisti selezionati da Rotondi Group._\n\n"
            "⚠️ Per annullare: 📞 *+39 06 41 40 0514*\n"
            "_In assenza di disdetta verrà addebitato il costo di uscita._\n\n"
            "_Il Team Rotondi Group Roma_"
        ),
        "proposta": (
            "📅 *Proposta di appuntamento*\n\n"
            "Il tecnico *{tecnico}* propone di intervenire il:\n\n"
            "🗓  *{data_ora}*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Accetta questa proposta?\n\n"
            "⚠️ _Se rifiuta, la richiesta tornerà disponibile per altri tecnici._"
        ),
        "proposta_accettata": (
            "🎉 *Appuntamento confermato!*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👨‍🔧  *{tecnico}*\n"
            "📞  Ufficio Roma: +39 06 41400617\n"
            "🗓  *{data_ora}*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "💶  *TARIFFE*\n"
            "› Roma: Uscita + 1h → *€ 80,00 + IVA*\n"
            "› Provincia di Roma, Lazio e resto d'Italia: *€ 0,70/km + IVA (A/R)* — *€ 32,00/h viaggio + IVA* — *€ 40,00/h lavoro + IVA*\n\n"
            "⚠️ Per annullare: 📞 *+39 06 41 40 0514*\n"
            "_In assenza di disdetta verrà addebitato il costo di uscita._\n\n"
            "_Il Team Rotondi Group Roma_"
        ),
        "proposta_rifiutata": (
            "❌ *Proposta rifiutata*\n\n"
            "La sua richiesta è ancora aperta.\n"
            "Un altro tecnico la prenderà in carico a breve.\n\n"
            "_Il Team Rotondi Group Roma_"
        ),
        "riassegnazione": (
            "ℹ️ *Aggiornamento sulla sua richiesta*\n\n"
            "La sua richiesta di assistenza è stata rimessa in circolo.\n"
            "Un nuovo tecnico la prenderà in carico a breve.\n\n"
            "_Il Team Rotondi Group Roma_"
        ),
        "annulla": "❌ Operazione annullata.\n\nScrivi /start per ricominciare.",
    },
    "en": {
                "condizioni": (
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔧  *ROTONDI GROUP SRL*\n"
            "     Rome Branch\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ *SERVICE INFORMATION*\n\n"
            "Rotondi Group technical assistance is a *paid service*, "
            "even when the intervention concerns a product *under warranty*.\n\n"
            "✅ *What we cover under warranty:*\n"
            "› *Defective spare parts* are replaced at no cost\n\n"
            "💶 *What is always charged to the customer:*\n"
            "› Labour\n"
            "› Technician travel\n"
            "› Call-out fee\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📍 *ROME AREA RATES* _(Inside the Grande Raccordo Anulare ring road)_\n"
            "› Call-out + 1 hour work: *€ 80.00 + VAT*\n"
            "› Additional hours: *€ 40.00/h + VAT*\n\n"
            "🗺 *ROME PROVINCE, LAZIO AND REST OF ITALY*\n"
            "› Travel km: *€ 0.70/km + VAT* _(return)_\n"
            "› Travel hours: *€ 32.00/h + VAT* _(return)_\n"
            "› Work hours: *€ 40.00/h + VAT*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "_Payment is made directly to the technician at the end of service._\n\n"
            "👨\u200d🔧 *OUR TECHNICIANS*\n"
            "Our technicians are *independent freelance professionals*, selected and appointed by Rotondi Group. They are not company employees.\n\n"
            "Do you accept these conditions and wish to proceed?"
        ),
        "condizioni_no": (
            "❌ *Service not accepted*\n\n"
            "You have chosen not to proceed with the assistance request.\n\n"
            "If you change your mind, you can reopen the request at any time by writing /start\n\n"
            "_Rotondi Group Roma_"
        ),
        "nome":           "┌─────────────────────\n│ 👤  *PERSONAL DETAILS*\n└─────────────────────\n\nWhat is your name?\n_Write your full name_",
        "indirizzo":      "📍 *Intervention address*\n\n_Street, number and city_",
        "telefono":       "📞 *Phone number*\n\n_We will contact you on this number_",
        "foto_targhetta": "📸 *Machine label photo*\n\n_Frame the label with brand, model and serial_\n\nIf you can\'t, write *skip*",
        "marca":          "🏭 *Machine brand*\n\n_E.g: Samsung, LG, Bosch..._",
        "modello":        "🔖 *Machine model*\n\n_Find it on the label or manual_",
        "seriale":        "🔢 *Serial number*\n\n_Find it on the machine label_",
        "problema":       "🔧 *Describe the problem*\n\n_What happens? Since when? Have you tried anything?_",
        "foto_macchina":  "📷 *Machine photo*\n\n_A photo helps us prepare the intervention_\n\nIf you can\'t, write *skip*",
        "riepilogo": (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📋  *REQUEST SUMMARY*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "👤  {nome}\n"
            "📍  {indirizzo}\n"
            "📞  {telefono}\n\n"
            "🏭  *{marca}*  ·  {modello}\n"
            "🔢  Serial: {seriale}\n\n"
            "🔧  _{problema}_\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Is everything correct?"
        ),
        "si":  "✅  Confirm",
        "no":  "✏️  Correct",
        "registrata": (
            "✅ *Request received!*\n\n"
            "Dear Customer, your request has been registered.\n"
            "A *Rotondi Group Roma* technician will contact you shortly.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💶  *RATES*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📍 *ROME AREA RATES* _(Inside the Grande Raccordo Anulare ring road)_\n"
            "› Call-out + 1h work: *€ 80.00 + VAT*\n"
            "› Additional hours: *€ 40.00/h + VAT*\n\n"
            "🗺 *ROME PROVINCE, LAZIO AND REST OF ITALY*\n"
            "› Travel: *€ 0.70/km + VAT* _(return)_\n"
            "› Travel time: *€ 32.00/h + VAT*\n"
            "› Work: *€ 40.00/h + VAT*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ To *cancel* contact URGENTLY:\n"
            "📞 +39 06 41 40 0514\n\n"
            "_The Rotondi Group Roma Team_"
        ),
        "assegnata": (
            "🎯 *Technician assigned!*\n\n"
            "Dear Customer, your request has been taken on.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👨‍🔧  *{tecnico}*\n"
            "📞  Rome Office: +39 06 41400617\n"
            "⏰  Expected arrival: *{fascia}*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ To cancel: 📞 *+39 06 41 40 0514*\n\n"
            "_The Rotondi Group Roma Team_"
        ),
        "proposta": (
            "📅 *Appointment proposal*\n\n"
            "Technician *{tecnico}* proposes to intervene on:\n\n"
            "🗓  *{data_ora}*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Do you accept this proposal?\n\n"
            "⚠️ _If you decline, the request will be available for other technicians._"
        ),
        "proposta_accettata": (
            "🎉 *Appointment confirmed!*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👨‍🔧  *{tecnico}*\n"
            "📞  Rome Office: +39 06 41400617\n"
            "🗓  *{data_ora}*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ To cancel: 📞 *+39 06 41 40 0514*\n\n"
            "_The Rotondi Group Roma Team_"
        ),
        "proposta_rifiutata": (
            "❌ *Proposal declined*\n\n"
            "Your request is still open.\n"
            "Another technician will take it on shortly.\n\n"
            "_The Rotondi Group Roma Team_"
        ),
        "riassegnazione": (
            "ℹ️ *Update on your request*\n\n"
            "Your assistance request has been re-opened.\n"
            "A new technician will take it on shortly.\n\n"
            "_The Rotondi Group Roma Team_"
        ),
        "annulla": "❌ Cancelled.\n\nWrite /start to begin again.",
    },
    "bn": {
                "condizioni": (
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔧  *ROTONDI GROUP SRL*\n"
            "     রোমা শাখা\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ *সেবার তথ্য*\n\n"
            "রোটোন্ডি গ্রুপের প্রযুক্তিগত সহায়তা একটি *পেইড সার্ভিস*, "
            "এমনকি পণ্যটি *ওয়ারেন্টিতে* থাকলেও।\n\n"
            "✅ *ওয়ারেন্টিতে যা কভার করা হয়:*\n"
            "› *ত্রুটিপূর্ণ খুচরা যন্ত্রাংশ* বিনামূল্যে প্রতিস্থাপন\n\n"
            "💶 *গ্রাহককে সবসময় যা দিতে হবে:*\n"
            "› শ্রম খরচ\n"
            "› টেকনিশিয়ানের যাতায়াত\n"
            "› কল-আউট ফি\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📍 *রোমা শহরের তারিফ* _(গ্র্যান্ড রাকোর্দো আনুলারে রিং রোডের ভেতরে)_\n"
            "› আসা + ১ ঘণ্টা কাজ: *€ 80,00 + VAT*\n"
            "› অতিরিক্ত ঘণ্টা: *€ 40,00/ঘণ্টা + VAT*\n\n"
            "🗺 *রোমা প্রদেশ, লাজিও এবং ইতালির বাকি অংশ*\n"
            "› যাতায়াত: *€ 0,70/কিমি + VAT* _(A/R)_\n"
            "› ভ্রমণ সময়: *€ 32,00/ঘণ্টা + VAT*\n"
            "› কাজের সময়: *€ 40,00/ঘণ্টা + VAT*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "_পেমেন্ট সরাসরি টেকনিশিয়ানকে সার্ভিসের শেষে করতে হবে।_\n\n"
            "👨\u200d🔧 *আমাদের টেকনিশিয়ান*\n"
            "আমাদের টেকনিশিয়ানরা *স্বাধীন ফ্রিল্যান্স পেশাদার*, রোটোন্ডি গ্রুপ কর্তৃক নির্বাচিত। তারা কোম্পানির কর্মচারী নন।\n\n"
            "আপনি কি এই শর্তগুলি গ্রহণ করেন এবং এগিয়ে যেতে চান?"
        ),
        "condizioni_no": (
            "❌ *সেবা গ্রহণ করা হয়নি*\n\n"
            "আপনি সহায়তার অনুরোধ না করার সিদ্ধান্ত নিয়েছেন।\n\n"
            "মত পরিবর্তন হলে /start লিখে যেকোনো সময় আবার শুরু করুন।\n\n"
            "_রোটোন্ডি গ্রুপ রোমা_"
        ),
        "nome":           "┌─────────────────────\n│ 👤  *ব্যক্তিগত তথ্য*\n└─────────────────────\n\nআপনার নাম কি?\n_পুরো নাম লিখুন_",
        "indirizzo":      "📍 *হস্তক্ষেপের ঠিকানা*\n\n_রাস্তা, নম্বর এবং শহর_",
        "telefono":       "📞 *ফোন নম্বর*\n\n_এই নম্বরে আপনার সাথে যোগাযোগ করা হবে_",
        "foto_targhetta": "📸 *মেশিনের তারিখফলকের ছবি*\n\nসম্ভব না হলে *skip* লিখুন",
        "marca":          "🏭 *মেশিনের ব্র্যান্ড*\n\n_যেমন: Samsung, LG, Bosch..._",
        "modello":        "🔖 *মেশিনের মডেল*\n\n_তারিখফলক বা ম্যানুয়ালে পাবেন_",
        "seriale":        "🔢 *সিরিয়াল নম্বর*\n\n_মেশিনের তারিখফলকে পাবেন_",
        "problema":       "🔧 *সমস্যা বর্ণনা করুন*\n\n_কী হচ্ছে? কবে থেকে? কিছু চেষ্টা করেছেন?_",
        "foto_macchina":  "📷 *মেশিনের ছবি*\n\nসম্ভব না হলে *skip* লিখুন",
        "riepilogo": (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📋  *অনুরোধের সারসংক্ষেপ*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "👤  {nome}\n"
            "📍  {indirizzo}\n"
            "📞  {telefono}\n\n"
            "🏭  *{marca}*  ·  {modello}\n"
            "🔢  সিরিয়াল: {seriale}\n\n"
            "🔧  _{problema}_\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "সব ঠিক আছে?"
        ),
        "si":  "✅  নিশ্চিত",
        "no":  "✏️  সংশোধন",
        "registrata": (
            "✅ *অনুরোধ পাওয়া গেছে!*\n\n"
            "প্রিয় গ্রাহক, আপনার অনুরোধ নিবন্ধিত হয়েছে।\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💶  *তারিফ*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📍 *রোমা শহর:* আসার চার্জ + ১ ঘণ্টা → *€ 80,00 + VAT*\n"
            "🗺 *রোমা প্রদেশ, লাজিও এবং ইতালির বাকি অংশ:* € 0,70/কিমি + € 32,00/ঘণ্টা ভ্রমণ + IVA\n\n"
            "⚠️ বাতিল করতে: 📞 *+39 06 41 40 0514*\n\n"
            "_রোটোন্ডি গ্রুপ রোমা টিম_"
        ),
        "assegnata": (
            "🎯 *টেকনিশিয়ান নিয়োগ হয়েছে!*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👨‍🔧  *{tecnico}*\n"
            "📞  রোমা অফিস: +39 06 41400617\n"
            "⏰  আসার সময়: *{fascia}*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ বাতিল: 📞 *+39 06 41 40 0514*\n\n"
            "_রোটোন্ডি গ্রুপ রোমা টিম_"
        ),
        "proposta": (
            "📅 *অ্যাপয়েন্টমেন্ট প্রস্তাব*\n\n"
            "টেকনিশিয়ান *{tecnico}* প্রস্তাব করেছেন:\n\n"
            "🗓  *{data_ora}*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "আপনি কি এটি গ্রহণ করবেন?"
        ),
        "proposta_accettata": (
            "🎉 *অ্যাপয়েন্টমেন্ট নিশ্চিত!*\n\n"
            "👨‍🔧  *{tecnico}*\n"
            "📞  +39 06 41400617\n"
            "🗓  *{data_ora}*\n\n"
            "⚠️ বাতিল: 📞 *+39 06 41 40 0514*\n\n"
            "_রোটোন্ডি গ্রুপ রোমা টিম_"
        ),
        "proposta_rifiutata": (
            "❌ *প্রস্তাব প্রত্যাখ্যাত*\n\n"
            "আপনার অনুরোধ এখনও খোলা আছে।\n\n"
            "_রোটোন্ডি গ্রুপ রোমা টিম_"
        ),
        "riassegnazione": (
            "ℹ️ *আপনার অনুরোধের আপডেট*\n\n"
            "আপনার অনুরোধ পুনরায় খোলা হয়েছে।\n"
            "একজন নতুন টেকনিশিয়ান শীঘ্রই দায়িত্ব নেবেন।\n\n"
            "_রোটোন্ডি গ্রুপ রোমা টিম_"
        ),
        "annulla": "❌ বাতিল হয়েছে।\n\nআবার শুরু করতে /start লিখুন।",
    },
    "zh": {
                "condizioni": (
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔧  *ROTONDI GROUP SRL*\n"
            "     罗马分公司\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ *服务说明*\n\n"
            "罗通迪集团技术援助是*付费服务*，"
            "即使产品*在保修期内*也是如此。\n\n"
            "✅ *保修内容:*\n"
            "› *有缺陷的备件*免费更换\n\n"
            "💶 *始终由客户承担:*\n"
            "› 人工费\n"
            "› 技术人员差旅费\n"
            "› 上门费\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📍 *罗马市区* _(环城公路GRA内)_\n"
            "› 上门费 + 1小时工作: *€ 80,00 + 增值税*\n"
            "› 额外每小时: *€ 40,00 + 增值税*\n\n"
            "🗺 *罗马省、拉齐奥大区及意大利其他地区*\n"
            "› 差旅: *€ 0,70/公里 + 增值税* _(往返)_\n"
            "› 路途时间: *€ 32,00/小时 + 增值税*\n"
            "› 工作时间: *€ 40,00/小时 + 增值税*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "_付款直接在服务结束时向技术人员支付。_\n\n"
            "👨\u200d🔧 *我们的技术人员*\n"
            "我们的技术人员是*独立自由职业者*，由罗通迪集团选派。他们不是公司雇员。\n\n"
            "您接受这些条件并希望继续吗？"
        ),
        "condizioni_no": (
            "❌ *未接受服务*\n\n"
            "您选择不继续提交援助请求。\n\n"
            "如果您改变主意，可以随时写 /start 重新开始。\n\n"
            "_罗通迪集团罗马_"
        ),
        "nome":           "┌─────────────────────\n│ 👤  *个人信息*\n└─────────────────────\n\n您叫什么名字？\n_请写全名_",
        "indirizzo":      "📍 *干预地址*\n\n_街道、门牌号和城市_",
        "telefono":       "📞 *电话号码*\n\n_我们将通过此号码联系您_",
        "foto_targhetta": "📸 *机器铭牌照片*\n\n如果无法拍照，请写 *跳过*",
        "marca":          "🏭 *机器品牌*\n\n_如: Samsung, LG, Bosch..._",
        "modello":        "🔖 *机器型号*\n\n_在铭牌或说明书上_",
        "seriale":        "🔢 *序列号*\n\n_在机器铭牌上_",
        "problema":       "🔧 *描述问题*\n\n_发生了什么？什么时候开始的？_",
        "foto_macchina":  "📷 *机器照片*\n\n如果无法拍照，请写 *跳过*",
        "riepilogo": (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📋  *请求摘要*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "👤  {nome}\n"
            "📍  {indirizzo}\n"
            "📞  {telefono}\n\n"
            "🏭  *{marca}*  ·  {modello}\n"
            "🔢  序列号: {seriale}\n\n"
            "🔧  _{problema}_\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "一切正确吗？"
        ),
        "si":  "✅  确认",
        "no":  "✏️  更正",
        "registrata": (
            "✅ *请求已收到！*\n\n"
            "尊敬的客户，您的请求已注册。\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💶  *费率*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📍 *罗马市区:* 上门费 + 1小时 → *€ 80,00 + 增值税*\n"
            "🗺 *罗马省、拉齐奥大区及意大利其他地区:* € 0,70/公里 + € 32,00/小时路途 + 增值税\n\n"
            "⚠️ 取消请紧急联系: 📞 *+39 06 41 40 0514*\n\n"
            "_罗通迪集团罗马团队_"
        ),
        "assegnata": (
            "🎯 *已分配技术人员！*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👨‍🔧  *{tecnico}*\n"
            "📞  罗马办公室: +39 06 41400617\n"
            "⏰  预计到达: *{fascia}*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ 取消: 📞 *+39 06 41 40 0514*\n\n"
            "_罗通迪集团罗马团队_"
        ),
        "proposta": (
            "📅 *预约提议*\n\n"
            "技术人员 *{tecnico}* 提议干预时间：\n\n"
            "🗓  *{data_ora}*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "您接受此提议吗？"
        ),
        "proposta_accettata": (
            "🎉 *预约已确认！*\n\n"
            "👨‍🔧  *{tecnico}*\n"
            "📞  +39 06 41400617\n"
            "🗓  *{data_ora}*\n\n"
            "⚠️ 取消: 📞 *+39 06 41 40 0514*\n\n"
            "_罗通迪集团罗马团队_"
        ),
        "proposta_rifiutata": (
            "❌ *提议已拒绝*\n\n"
            "您的请求仍然开放。\n\n"
            "_罗通迪集团罗马团队_"
        ),
        "riassegnazione": (
            "ℹ️ *您的请求更新*\n\n"
            "您的协助请求已重新开放。\n"
            "新的技术人员将很快接手。\n\n"
            "_罗通迪集团罗马团队_"
        ),
        "annulla": "❌ 已取消。\n\n写 /start 重新开始。",
    },
    "ar": {
                "condizioni": (
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔧  *ROTONDI GROUP SRL*\n"
            "     فرع روما\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ *معلومات الخدمة*\n\n"
            "المساعدة الفنية لروتوندي جروب هي *خدمة مدفوعة*، "
            "حتى لو كان المنتج *تحت الضمان*.\n\n"
            "✅ *ما يشمله الضمان:*\n"
            "› استبدال *قطع الغيار المعيبة* مجاناً\n\n"
            "💶 *ما يتحمله العميل دائماً:*\n"
            "› أجرة العمل\n"
            "› تنقل الفني\n"
            "› رسوم الزيارة\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📍 *تعريفات منطقة روما* _(داخل الطريق الدائري الكبير GRA)_\n"
            "› زيارة + ساعة عمل: *€ 80,00 + ضريبة*\n"
            "› ساعات إضافية: *€ 40,00/ساعة + ضريبة*\n\n"
            "🗺 *محافظة روما، منطقة لاتسيو وبقية إيطاليا*\n"
            "› الكيلومترات: *€ 0,70/كم + ضريبة* _(ذهاباً وإياباً)_\n"
            "› ساعات السفر: *€ 32,00/ساعة + ضريبة*\n"
            "› ساعات العمل: *€ 40,00/ساعة + ضريبة*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "_يتم الدفع مباشرة للفني في نهاية الخدمة._\n\n"
            "👨\u200d🔧 *فنيونا*\n"
            "فنيونا *محترفون مستقلون فريلانس*، تم اختيارهم من قِبل روتوندي جروب. ليسوا موظفين في الشركة.\n\n"
            "هل تقبل هذه الشروط وتريد المتابعة?"
        ),
        "condizioni_no": (
            "❌ *لم تُقبل الخدمة*\n\n"
            "اخترت عدم المتابعة في طلب المساعدة.\n\n"
            "إذا غيرت رأيك، يمكنك إعادة الطلب في أي وقت بكتابة /start\n\n"
            "_روتوندي جروب روما_"
        ),
        "nome":           "┌─────────────────────\n│ 👤  *البيانات الشخصية*\n└─────────────────────\n\nما اسمك؟\n_اكتب الاسم الكامل_",
        "indirizzo":      "📍 *عنوان التدخل*\n\n_الشارع والرقم والمدينة_",
        "telefono":       "📞 *رقم الهاتف*\n\n_سنتواصل معك على هذا الرقم_",
        "foto_targhetta": "📸 *صورة لوحة الجهاز*\n\nإذا لم تستطع، اكتب *تخطي*",
        "marca":          "🏭 *ماركة الجهاز*\n\n_مثل: Samsung, LG, Bosch..._",
        "modello":        "🔖 *موديل الجهاز*\n\n_موجود على اللوحة أو الدليل_",
        "seriale":        "🔢 *الرقم التسلسلي*\n\n_موجود على لوحة الجهاز_",
        "problema":       "🔧 *صف المشكلة*\n\n_ماذا يحدث؟ منذ متى؟_",
        "foto_macchina":  "📷 *صورة الجهاز*\n\nإذا لم تستطع، اكتب *تخطي*",
        "riepilogo": (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📋  *ملخص الطلب*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "👤  {nome}\n"
            "📍  {indirizzo}\n"
            "📞  {telefono}\n\n"
            "🏭  *{marca}*  ·  {modello}\n"
            "🔢  الرقم التسلسلي: {seriale}\n\n"
            "🔧  _{problema}_\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "هل كل شيء صحيح؟"
        ),
        "si":  "✅  تأكيد",
        "no":  "✏️  تصحيح",
        "registrata": (
            "✅ *تم استلام طلبك!*\n\n"
            "عزيزي العميل، تم تسجيل طلبك.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💶  *التعريفات*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📍 *منطقة روما* _(داخل الطريق الدائري):_ زيارة + ساعة → *€ 80,00 + ضريبة*\n"
            "🗺 *محافظة روما، منطقة لاتسيو وبقية إيطاليا:* € 0,70/كم + € 32,00/ساعة سفر + ضريبة\n\n"
            "⚠️ للإلغاء تواصل عاجلاً: 📞 *+39 06 41 40 0514*\n\n"
            "_فريق روتوندي جروب روما_"
        ),
        "assegnata": (
            "🎯 *تم تعيين فني!*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👨‍🔧  *{tecnico}*\n"
            "📞  مكتب روما: +39 06 41400617\n"
            "⏰  الوصول المتوقع: *{fascia}*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ للإلغاء: 📞 *+39 06 41 40 0514*\n\n"
            "_فريق روتوندي جروب روما_"
        ),
        "proposta": (
            "📅 *اقتراح موعد*\n\n"
            "الفني *{tecnico}* يقترح التدخل في:\n\n"
            "🗓  *{data_ora}*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "هل تقبل هذا الاقتراح؟"
        ),
        "proposta_accettata": (
            "🎉 *تم تأكيد الموعد!*\n\n"
            "👨‍🔧  *{tecnico}*\n"
            "📞  +39 06 41400617\n"
            "🗓  *{data_ora}*\n\n"
            "⚠️ للإلغاء: 📞 *+39 06 41 40 0514*\n\n"
            "_فريق روتوندي جروب روما_"
        ),
        "proposta_rifiutata": (
            "❌ *تم رفض الاقتراح*\n\n"
            "طلبك لا يزال مفتوحاً.\n\n"
            "_فريق روتوندي جروب روما_"
        ),
        "riassegnazione": (
            "ℹ️ *تحديث طلبك*\n\n"
            "تم إعادة فتح طلب المساعدة الخاص بك.\n"
            "سيتولى فني جديد المهمة قريباً.\n\n"
            "_فريق روتوندي جروب روما_"
        ),
        "annulla": "❌ تم الإلغاء.\n\nاكتب /start للبدء من جديد.",
    },
}


FLAGS = {"it":"🇮🇹","en":"🇬🇧","bn":"🇧🇩","zh":"🇨🇳","ar":"🇸🇦"}

def t(lingua, chiave, **kwargs):
    testo = TESTI.get(lingua, TESTI["it"]).get(chiave, TESTI["it"].get(chiave, ""))
    return testo.format(azienda=NOME_AZIENDA, **kwargs)

def traduci(testo, lingua_src="auto"):
    try:
        if lingua_src == "it": return testo
        return GoogleTranslator(source="auto", target="it").translate(testo) or testo
    except Exception as e:
        log.error(f"Traduzione: {e}"); return testo

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chiamate (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id        INTEGER,
                username           TEXT,
                lingua             TEXT,
                nome_cliente       TEXT,
                indirizzo          TEXT,
                telefono           TEXT,
                problema_it        TEXT,
                problema_originale TEXT,
                stato              TEXT DEFAULT 'aperta',
                tecnico_id         INTEGER,
                tecnico_nome       TEXT,
                fascia_oraria      TEXT,
                data_apertura      TEXT,
                data_assegnazione  TEXT,
                msg_id_gruppo      INTEGER,
                marca              TEXT,
                modello            TEXT,
                seriale            TEXT,
                foto_targhetta_id  TEXT,
                foto_macchina_id   TEXT,
                data_ora_proposta  TEXT,
                tecnico_proposta_id INTEGER
            )
        """)
        for col in ["marca TEXT", "modello TEXT", "seriale TEXT",
                    "foto_targhetta_id TEXT", "foto_macchina_id TEXT",
                    "data_ora_proposta TEXT", "tecnico_proposta_id INTEGER"]:
            try:
                conn.execute(f"ALTER TABLE chiamate ADD COLUMN {col}")
            except: pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tecnici (
                telegram_id INTEGER PRIMARY KEY,
                nome        TEXT,
                telefono    TEXT
            )
        """)
        conn.commit()

def salva_chiamata(tg_id, username, lingua, nome, indirizzo, telefono,
                   prob_it, prob_orig, marca, modello, seriale,
                   foto_targhetta_id, foto_macchina_id):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("""
            INSERT INTO chiamate
            (telegram_id,username,lingua,nome_cliente,indirizzo,telefono,
             problema_it,problema_originale,data_apertura,
             marca,modello,seriale,foto_targhetta_id,foto_macchina_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (tg_id, username, lingua, nome, indirizzo, telefono,
              prob_it, prob_orig, datetime.now().strftime("%d/%m/%Y %H:%M"),
              marca, modello, seriale, foto_targhetta_id, foto_macchina_id))
        cid = cur.lastrowid
        conn.commit()
    return cid

def assegna(cid, tecnico_id, tecnico_nome, fascia):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE chiamate SET stato='assegnata', tecnico_id=?, tecnico_nome=?,
            fascia_oraria=?, data_assegnazione=? WHERE id=?
        """, (tecnico_id, tecnico_nome, fascia,
              datetime.now().strftime("%d/%m/%Y %H:%M"), cid))
        conn.commit()

def set_proposta(cid, tecnico_id, tecnico_nome, data_ora):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE chiamate SET stato='in_attesa_conferma',
            tecnico_proposta_id=?, tecnico_nome=?, data_ora_proposta=? WHERE id=?
        """, (tecnico_id, tecnico_nome, data_ora, cid))
        conn.commit()

def reset_proposta(cid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE chiamate SET stato='aperta',
            tecnico_proposta_id=NULL, tecnico_nome=NULL, data_ora_proposta=NULL WHERE id=?
        """, (cid,))
        conn.commit()

def get_chiamata(cid):
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT * FROM chiamate WHERE id=?", (cid,)).fetchone()

def aggiorna_msg_id(cid, msg_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE chiamate SET msg_id_gruppo=? WHERE id=?", (msg_id, cid))
        conn.commit()

def get_tecnico(tid):
    with sqlite3.connect(DB_PATH) as conn:
        r = conn.execute("SELECT nome, telefono FROM tecnici WHERE telegram_id=?", (tid,)).fetchone()
    return {"nome": r[0], "telefono": r[1] or ""} if r else None

def get_tecnico_nome(tid):
    t = get_tecnico(tid)
    return t["nome"] if t else None

def registra_tecnico(tid, nome, telefono=None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR REPLACE INTO tecnici VALUES (?,?,?)", (tid, nome, telefono))
        conn.commit()

def sblocca_chiamata_db(cid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE chiamate SET stato='aperta', tecnico_id=NULL, tecnico_nome=NULL,
            fascia_oraria=NULL, data_assegnazione=NULL,
            tecnico_proposta_id=NULL, data_ora_proposta=NULL WHERE id=?
        """, (cid,))
        conn.commit()

def lista_chiamate_db(limite=20):
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("""
            SELECT id,nome_cliente,indirizzo,stato,tecnico_nome,fascia_oraria,data_apertura,lingua
            FROM chiamate ORDER BY id DESC LIMIT ?
        """, (limite,)).fetchall()

# ── /start ──────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in BACKOFFICE_IDS:
        await update.message.reply_text(
            f"👩‍💼 *Benvenuta nel sistema {NOME_AZIENDA}!*\n\n"
            "Comandi disponibili:\n"
            "/lista — ultime 20 chiamate\n"
            "/aperte — chiamate non ancora assegnate\n"
            "/assegnate — chiamate già assegnate (con sblocco)\n"
            "/storico — storico per mese/anno\n"
            "/statistiche — classifica tecnici e report",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    nome_tg = get_tecnico_nome(user_id)
    if nome_tg:
        await update.message.reply_text(
            f"👨‍🔧 *Bentornato {nome_tg}!*\n\n"
            "/chiamate — le tue chiamate assegnate",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇮🇹 Italiano", callback_data="lang_it"),
         InlineKeyboardButton("🇬🇧 English",  callback_data="lang_en")],
        [InlineKeyboardButton("🇧🇩 বাংলা",    callback_data="lang_bn"),
         InlineKeyboardButton("🇨🇳 中文",      callback_data="lang_zh")],
        [InlineKeyboardButton("🇸🇦 العربية",  callback_data="lang_ar")],
    ])
    await update.message.reply_text(
        f"👋 Benvenuto / Welcome / স্বাগতম / 欢迎 / أهلاً\n\n"
        f"*{NOME_AZIENDA}*\n\n"
        f"Scegli la lingua / Choose language / ভাষা বেছে নিন / 选择语言 / اختر اللغة:",
        reply_markup=keyboard, parse_mode="Markdown"
    )
    return SCEGLI_LINGUA



async def scegli_lingua_condizioni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lingua = query.data.replace("lang_", "")
    context.user_data["lingua"] = lingua
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅  Accetto", callback_data="cond_si"),
        InlineKeyboardButton("❌  Rifiuto", callback_data="cond_no"),
    ]])
    await query.edit_message_text(
        t(lingua, "condizioni"),
        reply_markup=kb,
        parse_mode="Markdown"
    )
    return CONDIZIONI

async def gestisci_condizioni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lingua = context.user_data.get("lingua", "it")
    if query.data == "cond_no":
        await query.edit_message_text(
            t(lingua, "condizioni_no"),
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    # Accetta → vai alla raccolta dati
    await query.edit_message_text(
        f"{FLAGS[lingua]} *{NOME_AZIENDA}*\n\n" + t(lingua, "nome"),
        parse_mode="Markdown"
    )
    return NOME

async def raccogli_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lingua = context.user_data.get("lingua", "it")
    context.user_data["nome"] = context.user_data["nome_orig"] = update.message.text.strip()
    await update.message.reply_text(t(lingua, "indirizzo"), parse_mode="Markdown")
    return INDIRIZZO

async def raccogli_indirizzo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lingua = context.user_data.get("lingua", "it")
    context.user_data["indirizzo"] = traduci(update.message.text.strip(), lingua)
    await update.message.reply_text(t(lingua, "telefono"), parse_mode="Markdown")
    return TELEFONO

async def raccogli_telefono(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lingua = context.user_data.get("lingua", "it")
    context.user_data["telefono"] = update.message.text.strip()
    await update.message.reply_text(t(lingua, "foto_targhetta"), parse_mode="Markdown")
    return FOTO_TARGHETTA

async def raccogli_foto_targhetta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lingua = context.user_data.get("lingua", "it")
    context.user_data["foto_targhetta_id"] = update.message.photo[-1].file_id if update.message.photo else None
    await update.message.reply_text(t(lingua, "marca"), parse_mode="Markdown")
    return MARCA

async def raccogli_marca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lingua = context.user_data.get("lingua", "it")
    context.user_data["marca"] = traduci(update.message.text.strip(), lingua)
    await update.message.reply_text(t(lingua, "modello"), parse_mode="Markdown")
    return MODELLO

async def raccogli_modello(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lingua = context.user_data.get("lingua", "it")
    context.user_data["modello"] = traduci(update.message.text.strip(), lingua)
    await update.message.reply_text(t(lingua, "seriale"), parse_mode="Markdown")
    return SERIALE

async def raccogli_seriale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lingua = context.user_data.get("lingua", "it")
    context.user_data["seriale"] = update.message.text.strip()
    await update.message.reply_text(t(lingua, "problema"), parse_mode="Markdown")
    return PROBLEMA

async def raccogli_problema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lingua = context.user_data.get("lingua", "it")
    orig = update.message.text.strip()
    context.user_data["problema_orig"] = orig
    context.user_data["problema_it"] = traduci(orig, lingua)
    await update.message.reply_text(t(lingua, "foto_macchina"), parse_mode="Markdown")
    return FOTO_MACCHINA

async def raccogli_foto_macchina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lingua = context.user_data.get("lingua", "it")
    context.user_data["foto_macchina_id"] = update.message.photo[-1].file_id if update.message.photo else None
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(t(lingua, "si"), callback_data="conferma_si"),
        InlineKeyboardButton(t(lingua, "no"), callback_data="conferma_no"),
    ]])
    await update.message.reply_text(
        t(lingua, "riepilogo",
          nome=context.user_data["nome_orig"],
          indirizzo=context.user_data["indirizzo"],
          telefono=context.user_data["telefono"],
          marca=context.user_data.get("marca", "-"),
          modello=context.user_data.get("modello", "-"),
          seriale=context.user_data.get("seriale", "-"),
          problema=context.user_data["problema_orig"]),
        reply_markup=keyboard, parse_mode="Markdown"
    )
    return CONFERMA

async def conferma(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lingua = context.user_data.get("lingua", "it")
    if query.data == "conferma_no":
        await query.edit_message_text(t(lingua, "annulla"), parse_mode="Markdown")
        return ConversationHandler.END

    user    = query.from_user
    nome_it = traduci(context.user_data["nome_orig"], lingua)
    cid     = salva_chiamata(
        user.id, user.username or str(user.id), lingua, nome_it,
        context.user_data["indirizzo"], context.user_data["telefono"],
        context.user_data["problema_it"], context.user_data["problema_orig"],
        context.user_data.get("marca", ""), context.user_data.get("modello", ""),
        context.user_data.get("seriale", ""),
        context.user_data.get("foto_targhetta_id"),
        context.user_data.get("foto_macchina_id"),
    )
    await query.edit_message_text(t(lingua, "registrata"), parse_mode="Markdown")

    flag = FLAGS.get(lingua, "🌍")
    sezione_problema = f"🔧 *Problema (IT):* {context.user_data['problema_it']}"
    if lingua != "it":
        sezione_problema += f"\n🔧 *Originale {flag}:* {context.user_data['problema_orig']}"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕛 Entro le 12:00", callback_data=f"fascia_{cid}_entro12"),
         InlineKeyboardButton("🕕 Entro le 18:00", callback_data=f"fascia_{cid}_entro18")],
        [InlineKeyboardButton("📅 In giornata",    callback_data=f"fascia_{cid}_giornata"),
         InlineKeyboardButton("📆 Entro domani",   callback_data=f"fascia_{cid}_domani")],
        [InlineKeyboardButton("🗓 Da programmare", callback_data=f"programma_{cid}_start")],
    ])

    indirizzo_maps = context.user_data['indirizzo'].replace(' ', '+') + ",+Roma,+Italia"
    link_maps = f"https://www.google.com/maps/search/?api=1&query={indirizzo_maps}"

    testo_gruppo = (
        f"🔔 *NUOVA CHIAMATA #{cid}* {flag}\n{'─'*30}\n"
        f"👤 *Cliente:* {nome_it}\n"
        f"📍 *Indirizzo:* {context.user_data['indirizzo']}\n"
        f"🗺 [Apri su Google Maps]({link_maps})\n"
        f"📞 *Telefono:* {context.user_data['telefono']}\n"
        f"🆔 *Telegram:* @{user.username or user.id}\n"
        f"🏷 *Marca:* {context.user_data.get('marca', '-')}\n"
        f"📋 *Modello:* {context.user_data.get('modello', '-')}\n"
        f"🔢 *Seriale:* {context.user_data.get('seriale', '-')}\n"
        f"{sezione_problema}\n{'─'*30}\n"
        f"⏰ Primo tecnico disponibile: clicca quando intervieni:"
    )
    msg = await context.bot.send_message(
        chat_id=TECNICI_GROUP_ID, text=testo_gruppo,
        reply_markup=keyboard, parse_mode="Markdown"
    )
    aggiorna_msg_id(cid, msg.message_id)

    for foto, cap in [
        (context.user_data.get("foto_targhetta_id"), f"📸 Foto targhetta — Chiamata #{cid}"),
        (context.user_data.get("foto_macchina_id"),  f"📸 Foto macchina — Chiamata #{cid}"),
    ]:
        if foto:
            try: await context.bot.send_photo(chat_id=TECNICI_GROUP_ID, photo=foto, caption=cap)
            except Exception as e: log.error(f"Foto: {e}")

    for bo_id in BACKOFFICE_IDS:
        try:
            await context.bot.send_message(
                chat_id=bo_id,
                text=(f"📲 *Nuova richiesta #{cid}* {flag}\n\n"
                      f"👤 {nome_it}\n📍 {context.user_data['indirizzo']}\n"
                      f"📞 {context.user_data['telefono']}\n"
                      f"🏷 {context.user_data.get('marca','-')} — {context.user_data.get('modello','-')}\n"
                      f"🔢 Seriale: {context.user_data.get('seriale','-')}\n"
                      f"🔧 {context.user_data['problema_it']}"
                      + (f"\n🔧 Originale: {context.user_data['problema_orig']}" if lingua != "it" else "")),
                parse_mode="Markdown"
            )
        except Exception as e: log.error(f"BO notifica: {e}")

    return ConversationHandler.END

async def annulla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lingua = context.user_data.get("lingua", "it")
    await update.message.reply_text(t(lingua, "annulla"), parse_mode="Markdown")
    return ConversationHandler.END

# ── FASCIA ORARIA ────────────────────────────────
FASCE = {
    "entro12": "entro le 12:00", "entro18": "entro le 18:00",
    "giornata": "in giornata",   "domani":  "entro domani"
}

async def gestisci_fascia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parti = query.data.split("_")
    cid   = int(parti[1])
    fascia = FASCE.get(parti[2], parti[2])

    ch = get_chiamata(cid)
    if not ch:
        await query.answer("⚠️ Chiamata non trovata.", show_alert=True); return
    if ch[9] in ("assegnata", "in_attesa_conferma"):
        await query.answer("⚠️ Chiamata già presa o in attesa conferma!", show_alert=True); return

    tid = query.from_user.id
    t_nome = f"{query.from_user.first_name or ''} {query.from_user.last_name or ''}".strip()
    tecnico_db = get_tecnico(tid)
    nome_finale = tecnico_db["nome"] if tecnico_db else t_nome
    if not tecnico_db: registra_tecnico(tid, t_nome)
    assegna(cid, tid, nome_finale, fascia)

    await query.edit_message_text(
        f"✅ *CHIAMATA #{cid} — ASSEGNATA*\n{'─'*30}\n"
        f"👤 *Cliente:* {ch[4]}\n📍 *Indirizzo:* {ch[5]}\n"
        f"🔧 *Problema:* {ch[7]}\n{'─'*30}\n"
        f"👨‍🔧 *Tecnico:* {nome_finale}\n⏰ *Intervento:* {fascia}",
        parse_mode="Markdown"
    )
    await query.answer("✅ Chiamata assegnata a te!")

    for bo_id in BACKOFFICE_IDS:
        try:
            await context.bot.send_message(
                chat_id=bo_id,
                text=(f"✅ *Chiamata #{cid} assegnata*\n\n"
                      f"👤 {ch[4]}\n👨‍🔧 Tecnico: {nome_finale}\n⏰ {fascia}"),
                parse_mode="Markdown"
            )
        except: pass

    lingua_cliente = ch[3]
    try:
        await context.bot.send_message(
            chat_id=ch[1],
            text=t(lingua_cliente, "assegnata", tecnico=nome_finale, fascia=fascia),
            parse_mode="Markdown"
        )
    except Exception as e: log.error(f"Messaggio cliente: {e}")

# ── CHIAMATE WEB (email al cliente) ─────────────────
WEB_DB_PATH = "web_assistenza.db"

FASCE_IT = {
    "entro12": "Entro le 12:00",
    "entro18": "Entro le 18:00",
    "giornata": "In giornata",
    "domani": "Entro domani",
    "programma": "Da programmare"
}

async def gestisci_wfascia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parti = query.data.split("_")
    # wfascia_PROTOCOLLO_fascia
    protocollo = parti[1]
    fascia_key  = parti[2]
    fascia_it   = FASCE_IT.get(fascia_key, fascia_key)

    tid    = query.from_user.id
    t_nome = f"{query.from_user.first_name or ''} {query.from_user.last_name or ''}".strip()
    tecnico_db = get_tecnico(tid)
    nome_finale = tecnico_db["nome"] if tecnico_db else t_nome
    if not tecnico_db: registra_tecnico(tid, t_nome)

    # Leggi richiesta web dal database
    try:
        import sqlite3 as _sq
        with _sq.connect(WEB_DB_PATH) as conn:
            r = conn.execute(
                "SELECT protocollo,nome,indirizzo,telefono,email,marca,modello,problema,stato,lingua FROM richieste_web WHERE protocollo=?",
                (protocollo,)
            ).fetchone()
    except Exception as e:
        log.error(f"Web DB error: {e}")
        await query.answer("⚠️ Richiesta non trovata.", show_alert=True); return

    if not r:
        await query.answer("⚠️ Richiesta non trovata.", show_alert=True); return
    if r[8] == "assegnata":
        await query.answer("⚠️ Già assegnata!", show_alert=True); return

    # Aggiorna stato nel DB web
    try:
        with _sq.connect(WEB_DB_PATH) as conn:
            conn.execute(
                "UPDATE richieste_web SET stato=?, tecnico=?, fascia=? WHERE protocollo=?",
                ("assegnata", nome_finale, fascia_it, protocollo)
            )
            conn.commit()
    except Exception as e:
        log.error(f"Web DB update error: {e}")

    nome_cliente = r[1]
    email_cliente = r[4]
    lingua = r[9] if r[9] else "it"

    # Aggiorna messaggio nel gruppo
    await query.edit_message_text(
        f"✅ *RICHIESTA WEB #{protocollo} — ASSEGNATA*\n{'─'*30}\n"
        f"👤 *Cliente:* {nome_cliente}\n"
        f"📍 *Indirizzo:* {r[2]}\n"
        f"🔧 *Problema:* {r[7]}\n{'─'*30}\n"
        f"👨\u200d🔧 *Tecnico:* {nome_finale}\n"
        f"⏰ *Intervento:* {fascia_it}",
        parse_mode="Markdown"
    )

    # Notifica back office
    for bo_id in BACKOFFICE_IDS:
        try:
            await context.bot.send_message(
                chat_id=bo_id,
                text=(f"✅ *Richiesta WEB {protocollo} assegnata*\n\n"
                      f"👤 {nome_cliente}\n👨\u200d🔧 Tecnico: {nome_finale}\n⏰ {fascia_it}"),
                parse_mode="Markdown"
            )
        except: pass

    # Manda EMAIL al cliente web
    SMTP_HOST_W = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT_W = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER_W = os.environ.get("SMTP_USER", "")
    SMTP_PASS_W = os.environ.get("SMTP_PASS", "")
    SMTP_FROM_W = os.environ.get("SMTP_FROM", "")

    SOGGETTI = {
        "it": f"Rotondi Group Roma — Tecnico assegnato #{protocollo}",
        "en": f"Rotondi Group Roma — Technician assigned #{protocollo}",
        "bn": f"রোটোন্ডি গ্রুপ রোমা — টেকনিশিয়ান নিযুক্ত #{protocollo}",
        "zh": f"罗通迪集团罗马 — 技术人员已分配 #{protocollo}",
        "ar": f"روتوندي جروب روما — تم تعيين الفني #{protocollo}"
    }
    CORPI = {
        "it": f"""<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
  <h1 style="color:#fff;font-size:20px;margin:0">ROTONDI GROUP ROMA</h1>
  <p style="color:#c9a84c;margin:4px 0 0;font-size:13px">ASSISTENZA TECNICA</p>
</div>
<div style="background:#fff;padding:24px;border-radius:0 0 8px 8px">
  <h2 style="color:#1a1a2e;font-size:18px">👨‍🔧 Tecnico assegnato!</h2>
  <p>Gentile <b>{nome_cliente}</b>,<br>un tecnico è stato assegnato alla sua richiesta.</p>
  <div style="background:#f5f5f5;border-radius:8px;padding:16px;margin:16px 0">
    <p style="margin:0 0 8px;font-size:13px;color:#888">Protocollo: <b>{protocollo}</b></p>
    <p style="margin:0 0 8px;font-size:15px"><b>Tecnico:</b> {nome_finale}</p>
    <p style="margin:0;font-size:15px"><b>Orario intervento:</b> {fascia_it}</p>
  </div>
  <p style="color:#555;font-size:14px">Per informazioni contatti l'ufficio:<br>
  <b>+39 06 41400617</b></p>
  <p style="color:#888;font-size:13px;margin-top:16px">Per annullare: <b>+39 06 41 40 0514</b></p>
</div></div>""",
        "en": f"""<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
<div style="background:#0d0d14;padding:24px;text-align:center;border-radius:8px 8px 0 0">
  <h1 style="color:#fff;font-size:20px;margin:0">ROTONDI GROUP ROMA</h1>
  <p style="color:#c9a84c;margin:4px 0 0;font-size:13px">TECHNICAL ASSISTANCE</p>
</div>
<div style="background:#fff;padding:24px;border-radius:0 0 8px 8px">
  <h2 style="color:#1a1a2e;font-size:18px">👨‍🔧 Technician assigned!</h2>
  <p>Dear <b>{nome_cliente}</b>,<br>a technician has been assigned to your request.</p>
  <div style="background:#f5f5f5;border-radius:8px;padding:16px;margin:16px 0">
    <p style="margin:0 0 8px;font-size:13px;color:#888">Protocol: <b>{protocollo}</b></p>
    <p style="margin:0 0 8px;font-size:15px"><b>Technician:</b> {nome_finale}</p>
    <p style="margin:0;font-size:15px"><b>Intervention time:</b> {fascia_it}</p>
  </div>
  <p style="color:#555;font-size:14px">For information contact the office:<br><b>+39 06 41400617</b></p>
  <p style="color:#888;font-size:13px;margin-top:16px">To cancel: <b>+39 06 41 40 0514</b></p>
</div></div>"""
    }

    if email_cliente and SMTP_USER_W and SMTP_PASS_W:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        try:
            corpo = CORPI.get(lingua, CORPI["en"])
            soggetto = SOGGETTI.get(lingua, SOGGETTI["en"])
            msg = MIMEMultipart("alternative")
            msg["Subject"] = soggetto
            msg["From"]    = SMTP_FROM_W
            msg["To"]      = email_cliente
            msg.attach(MIMEText(corpo, "html"))
            with smtplib.SMTP(SMTP_HOST_W, SMTP_PORT_W) as s:
                s.starttls()
                s.login(SMTP_USER_W, SMTP_PASS_W)
                s.sendmail(SMTP_FROM_W, email_cliente, msg.as_string())
            log.info(f"Email inviata a {email_cliente} per {protocollo}")
        except Exception as e:
            log.error(f"Email web error: {e}")

# ── DA PROGRAMMARE ───────────────────────────────
def genera_keyboard_date(cid):
    oggi = datetime.now()
    bottoni = []
    riga = []
    for i in range(7):
        giorno = oggi + timedelta(days=i)
        label = giorno.strftime("%a %d/%m")
        data_str = giorno.strftime("%d-%m-%Y")
        riga.append(InlineKeyboardButton(label, callback_data=f"pdata_{cid}_{data_str}"))
        if len(riga) == 2:
            bottoni.append(riga); riga = []
    if riga: bottoni.append(riga)
    bottoni.append([InlineKeyboardButton("❌ Annulla", callback_data=f"pdata_{cid}_annulla")])
    return InlineKeyboardMarkup(bottoni)

def genera_keyboard_ore(cid, data_str):
    ore = ["08:00","09:00","10:00","11:00","12:00","13:00",
           "14:00","15:00","16:00","17:00","18:00","19:00"]
    bottoni = []
    riga = []
    for ora in ore:
        riga.append(InlineKeyboardButton(ora, callback_data=f"pora_{cid}_{data_str}_{ora.replace(':','')}"))
        if len(riga) == 4:
            bottoni.append(riga); riga = []
    if riga: bottoni.append(riga)
    bottoni.append([InlineKeyboardButton("⬅️ Torna alle date", callback_data=f"programma_{cid}_start")])
    return InlineKeyboardMarkup(bottoni)

async def gestisci_programma(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parti = query.data.split("_")
    cid   = int(parti[1])

    ch = get_chiamata(cid)
    if not ch:
        await query.answer("⚠️ Chiamata non trovata.", show_alert=True); return
    if ch[9] in ("assegnata",):
        await query.answer("⚠️ Chiamata già assegnata!", show_alert=True); return
    if ch[9] == "in_attesa_conferma":
        await query.answer("⚠️ Già in attesa di conferma cliente!", show_alert=True); return

    await query.edit_message_text(
        f"🗓 *Da programmare — Chiamata #{cid}*\n\n"
        f"👤 *Cliente:* {ch[4]}\n"
        f"Scegli la *data* dell'intervento:",
        reply_markup=genera_keyboard_date(cid),
        parse_mode="Markdown"
    )

async def gestisci_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parti = query.data.split("_")
    cid      = int(parti[1])
    data_str = parti[2]

    if data_str == "annulla":
        ch = get_chiamata(cid)
        if not ch: return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🕛 Entro le 12:00", callback_data=f"fascia_{cid}_entro12"),
             InlineKeyboardButton("🕕 Entro le 18:00", callback_data=f"fascia_{cid}_entro18")],
            [InlineKeyboardButton("📅 In giornata",    callback_data=f"fascia_{cid}_giornata"),
             InlineKeyboardButton("📆 Entro domani",   callback_data=f"fascia_{cid}_domani")],
            [InlineKeyboardButton("🗓 Da programmare", callback_data=f"programma_{cid}_start")],
        ])
        indirizzo_maps = ch[5].replace(' ', '+') + ",+Roma,+Italia"
        link_maps = f"https://www.google.com/maps/search/?api=1&query={indirizzo_maps}"
        await query.edit_message_text(
            f"🔔 *CHIAMATA #{cid}*\n{'─'*30}\n"
            f"👤 *Cliente:* {ch[4]}\n"
            f"📍 *Indirizzo:* {ch[5]}\n"
            f"🗺 [Apri su Google Maps]({link_maps})\n"
            f"📞 *Telefono:* {ch[6]}\n"
            f"🔧 *Problema:* {ch[7]}\n{'─'*30}\n"
            f"⏰ Primo tecnico disponibile: clicca quando intervieni:",
            reply_markup=keyboard, parse_mode="Markdown"
        )
        return

    ch = get_chiamata(cid)
    if not ch: return
    await query.edit_message_text(
        f"🗓 *Da programmare — Chiamata #{cid}*\n\n"
        f"👤 *Cliente:* {ch[4]}\n"
        f"📅 *Data selezionata:* {data_str.replace('-','/')}\n\n"
        f"Scegli l'*ora* dell'intervento:",
        reply_markup=genera_keyboard_ore(cid, data_str),
        parse_mode="Markdown"
    )

async def gestisci_ora(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parti    = query.data.split("_")
    cid      = int(parti[1])
    data_str = parti[2]
    ora_str  = parti[3]
    ora_fmt  = f"{ora_str[:2]}:{ora_str[2:]}"
    data_fmt = data_str.replace("-", "/")
    data_ora = f"{data_fmt} alle {ora_fmt}"

    ch = get_chiamata(cid)
    if not ch:
        await query.answer("⚠️ Chiamata non trovata.", show_alert=True); return
    if ch[9] in ("assegnata", "in_attesa_conferma"):
        await query.answer("⚠️ Chiamata non disponibile!", show_alert=True); return

    tid    = query.from_user.id
    t_nome = f"{query.from_user.first_name or ''} {query.from_user.last_name or ''}".strip()
    tecnico_db  = get_tecnico(tid)
    nome_finale = tecnico_db["nome"] if tecnico_db else t_nome
    if not tecnico_db: registra_tecnico(tid, t_nome)

    set_proposta(cid, tid, nome_finale, data_ora)

    await query.edit_message_text(
        f"⏳ *CHIAMATA #{cid} — IN ATTESA CONFERMA CLIENTE*\n{'─'*30}\n"
        f"👤 *Cliente:* {ch[4]}\n"
        f"📍 *Indirizzo:* {ch[5]}\n"
        f"🔧 *Problema:* {ch[7]}\n{'─'*30}\n"
        f"👨‍🔧 *Tecnico:* {nome_finale}\n"
        f"📅 *Proposta:* {data_ora}\n\n"
        f"_In attesa che il cliente accetti o rifiuti..._",
        parse_mode="Markdown"
    )

    lingua_cliente = ch[3]
    keyboard_cliente = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Accetto", callback_data=f"cprop_{cid}_si"),
        InlineKeyboardButton("❌ Rifiuto", callback_data=f"cprop_{cid}_no"),
    ]])
    try:
        await context.bot.send_message(
            chat_id=ch[1],
            text=t(lingua_cliente, "proposta", tecnico=nome_finale, data_ora=data_ora),
            reply_markup=keyboard_cliente,
            parse_mode="Markdown"
        )
    except Exception as e:
        log.error(f"Proposta cliente: {e}")

    for bo_id in BACKOFFICE_IDS:
        try:
            await context.bot.send_message(
                chat_id=bo_id,
                text=(f"⏳ *Chiamata #{cid} in attesa conferma*\n\n"
                      f"👤 {ch[4]}\n👨‍🔧 Tecnico: {nome_finale}\n📅 Proposta: {data_ora}"),
                parse_mode="Markdown"
            )
        except: pass

async def gestisci_conferma_proposta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parti    = query.data.split("_")
    cid      = int(parti[1])
    risposta = parti[2]

    ch = get_chiamata(cid)
    if not ch:
        await query.edit_message_text("⚠️ Chiamata non trovata.", parse_mode="Markdown"); return
    if ch[9] != "in_attesa_conferma":
        await query.edit_message_text("ℹ️ La proposta non è più valida.", parse_mode="Markdown"); return

    lingua_cliente = ch[3]
    data_ora       = ch[21] if len(ch) > 21 else "—"
    nome_tecnico   = ch[11] or "—"
    tecnico_id     = ch[22] if len(ch) > 22 else None

    if risposta == "si":
        assegna(cid, tecnico_id, nome_tecnico, data_ora)
        await query.edit_message_text(
            t(lingua_cliente, "proposta_accettata", tecnico=nome_tecnico, data_ora=data_ora),
            parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                chat_id=TECNICI_GROUP_ID,
                text=(f"✅ *CHIAMATA #{cid} CONFERMATA DAL CLIENTE*\n\n"
                      f"👤 {ch[4]}\n📍 {ch[5]}\n"
                      f"👨‍🔧 Tecnico: {nome_tecnico}\n📅 {data_ora}"),
                parse_mode="Markdown"
            )
        except: pass
        for bo_id in BACKOFFICE_IDS:
            try:
                await context.bot.send_message(
                    chat_id=bo_id,
                    text=(f"✅ *Chiamata #{cid} confermata dal cliente*\n\n"
                          f"👤 {ch[4]}\n👨‍🔧 {nome_tecnico}\n📅 {data_ora}"),
                    parse_mode="Markdown"
                )
            except: pass
    else:
        reset_proposta(cid)
        await query.edit_message_text(
            t(lingua_cliente, "proposta_rifiutata"),
            parse_mode="Markdown"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🕛 Entro le 12:00", callback_data=f"fascia_{cid}_entro12"),
             InlineKeyboardButton("🕕 Entro le 18:00", callback_data=f"fascia_{cid}_entro18")],
            [InlineKeyboardButton("📅 In giornata",    callback_data=f"fascia_{cid}_giornata"),
             InlineKeyboardButton("📆 Entro domani",   callback_data=f"fascia_{cid}_domani")],
            [InlineKeyboardButton("🗓 Da programmare", callback_data=f"programma_{cid}_start")],
        ])
        try:
            await context.bot.send_message(
                chat_id=TECNICI_GROUP_ID,
                text=(f"❌ *CHIAMATA #{cid} — PROPOSTA RIFIUTATA DAL CLIENTE*\n\n"
                      f"👤 {ch[4]}\n📍 {ch[5]}\n"
                      f"La chiamata è tornata disponibile per tutti i tecnici!"),
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except: pass
        for bo_id in BACKOFFICE_IDS:
            try:
                await context.bot.send_message(
                    chat_id=bo_id,
                    text=(f"❌ *Chiamata #{cid} — proposta rifiutata*\n\n"
                          f"👤 {ch[4]}\nLa chiamata è tornata libera."),
                    parse_mode="Markdown"
                )
            except: pass

# ── BACK OFFICE ──────────────────────────────────
async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in BACKOFFICE_IDS:
        await update.message.reply_text("⛔ Non autorizzato."); return
    rows = lista_chiamate_db()
    if not rows:
        await update.message.reply_text("📋 Nessuna chiamata."); return
    for r in rows:
        emoji = "🟡" if r[3] == "aperta" else ("⏳" if r[3] == "in_attesa_conferma" else "✅")
        flag  = FLAGS.get(r[7], "🌍")
        testo = f"{emoji} *#{r[0]}* {flag} — {r[1]}\n📍 {r[2]}\n"
        if r[3] in ("assegnata", "in_attesa_conferma"):
            testo += f"👨‍🔧 {r[4]} — {r[5]}\n"
        testo += f"🕐 {r[6]}"
        # Pulsante sblocco solo per chiamate assegnate o in attesa
        if r[3] in ("assegnata", "in_attesa_conferma"):
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔓 Sblocca e rimetti in circolo", callback_data=f"sblocca_{r[0]}")
            ]])
            await update.message.reply_text(testo, parse_mode="Markdown", reply_markup=kb)
        else:
            await update.message.reply_text(testo, parse_mode="Markdown")

async def aperte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in BACKOFFICE_IDS:
        await update.message.reply_text("⛔ Non autorizzato."); return
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("""
            SELECT id,nome_cliente,indirizzo,data_apertura,lingua,stato,tecnico_nome
            FROM chiamate WHERE stato IN ('aperta','in_attesa_conferma') ORDER BY id DESC
        """).fetchall()
    if not rows:
        await update.message.reply_text("✅ Nessuna chiamata aperta!"); return
    await update.message.reply_text(f"🟡 *Chiamate aperte: {len(rows)}*", parse_mode="Markdown")
    for r in rows:
        emoji = "⏳" if r[5] == "in_attesa_conferma" else "🟡"
        testo = f"{emoji} *#{r[0]}* {FLAGS.get(r[4],'🌍')} — {r[1]}\n📍 {r[2]}\n🕐 {r[3]}"
        if r[5] == "in_attesa_conferma" and r[6]:
            testo += f"\n⏳ In attesa conferma da: {r[6]}"
        await update.message.reply_text(testo, parse_mode="Markdown")

async def assegnate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in BACKOFFICE_IDS:
        await update.message.reply_text("⛔ Non autorizzato."); return
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("""
            SELECT id,nome_cliente,indirizzo,data_apertura,lingua,stato,tecnico_nome,fascia_oraria,data_ora_proposta
            FROM chiamate WHERE stato IN ('assegnata','in_attesa_conferma') ORDER BY id DESC LIMIT 20
        """).fetchall()
    if not rows:
        await update.message.reply_text("📋 Nessuna chiamata assegnata!"); return
    await update.message.reply_text(f"✅ *Chiamate assegnate: {len(rows)}*", parse_mode="Markdown")
    for r in rows:
        emoji = "⏳" if r[5] == "in_attesa_conferma" else "✅"
        orario = r[8] if r[5] == "in_attesa_conferma" else r[7]
        testo = (
            f"{emoji} *#{r[0]}* {FLAGS.get(r[4],'🌍')} — {r[1]}\n"
            f"📍 {r[2]}\n"
            f"👨‍🔧 {r[6] or '—'}\n"
            f"⏰ {orario or '—'}\n"
            f"🕐 {r[3]}"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔓 Sblocca e rimetti in circolo", callback_data=f"sblocca_{r[0]}")
        ]])
        await update.message.reply_text(testo, parse_mode="Markdown", reply_markup=kb)

async def gestisci_sblocco(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in BACKOFFICE_IDS:
        await query.answer("⛔ Non autorizzato.", show_alert=True); return

    cid = int(query.data.split("_")[1])
    ch  = get_chiamata(cid)
    if not ch:
        await query.answer("⚠️ Chiamata non trovata.", show_alert=True); return
    if ch[9] == "aperta":
        await query.answer("ℹ️ La chiamata è già libera.", show_alert=True); return

    tecnico_precedente_id   = ch[10]
    tecnico_precedente_nome = ch[11] or "—"

    sblocca_chiamata_db(cid)

    await query.edit_message_text(
        f"🔓 *CHIAMATA #{cid} — SBLOCCATA*\n{'─'*28}\n"
        f"👤 *Cliente:* {ch[4]}\n"
        f"📍 *Indirizzo:* {ch[5]}\n"
        f"🔧 *Problema:* {ch[7]}\n"
        f"{'─'*28}\n"
        f"_Rimessa in circolo dal back office_",
        parse_mode="Markdown"
    )

    # Rimanda notifica al gruppo tecnici con tutti i pulsanti
    indirizzo_maps = ch[5].replace(' ', '+') + ",+Roma,+Italia"
    link_maps = f"https://www.google.com/maps/search/?api=1&query={indirizzo_maps}"
    flag = FLAGS.get(ch[3], "🌍")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕛 Entro le 12:00", callback_data=f"fascia_{cid}_entro12"),
         InlineKeyboardButton("🕕 Entro le 18:00", callback_data=f"fascia_{cid}_entro18")],
        [InlineKeyboardButton("📅 In giornata",    callback_data=f"fascia_{cid}_giornata"),
         InlineKeyboardButton("📆 Entro domani",   callback_data=f"fascia_{cid}_domani")],
        [InlineKeyboardButton("🗓 Da programmare", callback_data=f"programma_{cid}_start")],
    ])
    try:
        await context.bot.send_message(
            chat_id=TECNICI_GROUP_ID,
            text=(
                f"🔔 *CHIAMATA #{cid} — RIASSEGNAZIONE* {flag}\n{'─'*28}\n"
                f"👤 *Cliente:* {ch[4]}\n"
                f"📍 *Indirizzo:* {ch[5]}\n"
                f"🗺 [Apri su Google Maps]({link_maps})\n"
                f"📞 *Telefono:* {ch[6]}\n"
                f"🔧 *Problema:* {ch[7]}\n"
                f"{'─'*28}\n"
                f"⚠️ _Chiamata rimessa in circolo dal back office_\n"
                f"⏰ Primo tecnico disponibile: clicca quando intervieni:"
            ),
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as e:
        log.error(f"Sblocco notifica gruppo: {e}")

    # Avvisa il tecnico precedente
    if tecnico_precedente_id:
        try:
            await context.bot.send_message(
                chat_id=tecnico_precedente_id,
                text=(
                    f"ℹ️ *Chiamata #{cid} rimessa in circolo*\n\n"
                    f"La chiamata del cliente *{ch[4]}* è stata rimessa nel circuito "
                    f"dal back office e potrà essere assegnata ad un altro tecnico.\n\n"
                    f"_Rotondi Group Roma_"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            log.error(f"Notifica tecnico precedente: {e}")

    # Avvisa il cliente
    lingua_cliente = ch[3]
    try:
        await context.bot.send_message(
            chat_id=ch[1],
            text=t(lingua_cliente, "riassegnazione"),
            parse_mode="Markdown"
        )
    except Exception as e:
        log.error(f"Notifica cliente sblocco: {e}")

async def storico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in BACKOFFICE_IDS:
        await update.message.reply_text("⛔ Non autorizzato."); return

    args = context.args  # es: /storico 01 2025 oppure /storico 2025

    now = datetime.now()

    if not args:
        # Nessun argomento: mostra menu mesi dell'anno corrente
        mesi = ["Gen","Feb","Mar","Apr","Mag","Giu","Lug","Ago","Set","Ott","Nov","Dic"]
        anno = now.year
        bottoni = []
        riga = []
        for i, m in enumerate(mesi, 1):
            riga.append(InlineKeyboardButton(f"{m} {anno}", callback_data=f"storico_{i:02d}_{anno}"))
            if len(riga) == 3:
                bottoni.append(riga); riga = []
        if riga: bottoni.append(riga)
        # Anno precedente
        bottoni.append([InlineKeyboardButton(f"📅 Anno {anno-1}", callback_data=f"storico_00_{anno-1}")])
        await update.message.reply_text(
            "📊 *Storico chiamate*\n\nScegli il mese da visualizzare:",
            reply_markup=InlineKeyboardMarkup(bottoni),
            parse_mode="Markdown"
        )
        return

    # Con argomenti: /storico MM YYYY o /storico YYYY
    try:
        if len(args) == 2:
            mese = int(args[0]); anno = int(args[1])
        elif len(args) == 1 and len(args[0]) == 4:
            mese = 0; anno = int(args[0])
        else:
            mese = int(args[0]); anno = now.year
    except:
        await update.message.reply_text("⚠️ Formato: /storico MM YYYY\nEsempio: /storico 01 2025"); return

    await _invia_storico(update.message, context, mese, anno)

async def gestisci_storico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in BACKOFFICE_IDS:
        await query.answer("⛔ Non autorizzato.", show_alert=True); return

    parti = query.data.split("_")
    mese = int(parti[1]); anno = int(parti[2])
    await _invia_storico(query.message, context, mese, anno)

async def _invia_storico(msg, context, mese, anno):
    with sqlite3.connect(DB_PATH) as conn:
        if mese == 0:
            # Anno intero
            rows = conn.execute("""
                SELECT id,nome_cliente,indirizzo,stato,tecnico_nome,fascia_oraria,
                       data_apertura,lingua,marca,modello,problema_it,data_ora_proposta
                FROM chiamate
                WHERE data_apertura LIKE ?
                ORDER BY id DESC
            """, (f"%/{anno}%",)).fetchall()
            periodo = f"Anno {anno}"
        else:
            rows = conn.execute("""
                SELECT id,nome_cliente,indirizzo,stato,tecnico_nome,fascia_oraria,
                       data_apertura,lingua,marca,modello,problema_it,data_ora_proposta
                FROM chiamate
                WHERE data_apertura LIKE ?
                ORDER BY id DESC
            """, (f"%/{mese:02d}/{anno}%",)).fetchall()
            mesi_it = ["","Gennaio","Febbraio","Marzo","Aprile","Maggio","Giugno",
                       "Luglio","Agosto","Settembre","Ottobre","Novembre","Dicembre"]
            periodo = f"{mesi_it[mese]} {anno}"

    if not rows:
        await msg.reply_text(
            f"📊 *Storico — {periodo}*\n\n_Nessuna chiamata trovata._",
            parse_mode="Markdown"
        )
        return

    # Statistiche riepilogative
    totale    = len(rows)
    assegnate = sum(1 for r in rows if r[3] == "assegnata")
    aperte    = sum(1 for r in rows if r[3] == "aperta")
    attesa    = sum(1 for r in rows if r[3] == "in_attesa_conferma")

    # Conta per tecnico
    tecnici_count = {}
    for r in rows:
        if r[4]:
            tecnici_count[r[4]] = tecnici_count.get(r[4], 0) + 1

    riepilogo = (
        f"📊 *STORICO CHIAMATE — {periodo}*\n"
        f"{'━'*28}\n\n"
        f"📈 *Totale:* {totale} chiamate\n"
        f"✅ Assegnate: {assegnate}\n"
        f"🟡 Aperte: {aperte}\n"
        f"⏳ In attesa: {attesa}\n\n"
    )
    if tecnici_count:
        riepilogo += "*Chiamate per tecnico:*\n"
        for nome, count in sorted(tecnici_count.items(), key=lambda x: -x[1]):
            riepilogo += f"  👨‍🔧 {nome}: {count}\n"
        riepilogo += "\n"

    riepilogo += f"{'━'*28}\n_Dettaglio chiamate:_"
    await msg.reply_text(riepilogo, parse_mode="Markdown")

    # Invia le chiamate in blocchi da 10 per non superare limiti Telegram
    BLOCCO = 10
    for i in range(0, len(rows), BLOCCO):
        blocco = rows[i:i+BLOCCO]
        testo = ""
        for r in blocco:
            emoji = "✅" if r[3] == "assegnata" else ("⏳" if r[3] == "in_attesa_conferma" else "🟡")
            flag  = FLAGS.get(r[7], "🌍")
            testo += f"{emoji} *#{r[0]}* {flag} — {r[1]}\n"
            testo += f"📍 {r[2]}\n"
            testo += f"🕐 {r[6]}\n"
            if r[4]:
                testo += f"👨‍🔧 {r[4]}"
                if r[5]:  testo += f" — {r[5]}"
                elif r[11]: testo += f" — {r[11]}"
                testo += "\n"
            if r[8] or r[9]:
                testo += f"🏭 {r[8] or '—'} · {r[9] or '—'}\n"
            testo += f"🔧 _{r[10][:60]}..._\n\n" if r[10] and len(r[10]) > 60 else f"🔧 _{r[10] or '—'}_\n\n"
        await msg.reply_text(testo, parse_mode="Markdown")

async def statistiche(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in BACKOFFICE_IDS:
        await update.message.reply_text("⛔ Non autorizzato."); return

    now = datetime.now()
    mese_corrente = now.strftime("%m/%Y")
    anno_corrente = str(now.year)

    with sqlite3.connect(DB_PATH) as conn:
        # Totali generali
        totale      = conn.execute("SELECT COUNT(*) FROM chiamate").fetchone()[0]
        assegnate   = conn.execute("SELECT COUNT(*) FROM chiamate WHERE stato='assegnata'").fetchone()[0]
        aperte      = conn.execute("SELECT COUNT(*) FROM chiamate WHERE stato='aperta'").fetchone()[0]
        in_attesa   = conn.execute("SELECT COUNT(*) FROM chiamate WHERE stato='in_attesa_conferma'").fetchone()[0]

        # Chiamate questo mese
        mese_tot    = conn.execute("SELECT COUNT(*) FROM chiamate WHERE data_apertura LIKE ?", (f"%/{mese_corrente}%",)).fetchone()[0]
        mese_ass    = conn.execute("SELECT COUNT(*) FROM chiamate WHERE stato='assegnata' AND data_apertura LIKE ?", (f"%/{mese_corrente}%",)).fetchone()[0]

        # Chiamate questo anno
        anno_tot    = conn.execute("SELECT COUNT(*) FROM chiamate WHERE data_apertura LIKE ?", (f"%/{anno_corrente}%",)).fetchone()[0]

        # Statistiche per tecnico (tutti i tempi)
        tecnici_rows = conn.execute("""
            SELECT tecnico_nome, COUNT(*) as totale,
                   SUM(CASE WHEN stato='assegnata' THEN 1 ELSE 0 END) as completate
            FROM chiamate
            WHERE tecnico_nome IS NOT NULL AND tecnico_nome != ''
            GROUP BY tecnico_nome
            ORDER BY totale DESC
        """).fetchall()

        # Statistiche per tecnico questo mese
        tecnici_mese = conn.execute("""
            SELECT tecnico_nome, COUNT(*) as totale
            FROM chiamate
            WHERE tecnico_nome IS NOT NULL AND tecnico_nome != ''
            AND data_apertura LIKE ?
            GROUP BY tecnico_nome
            ORDER BY totale DESC
        """, (f"%/{mese_corrente}%",)).fetchall()

        # Lingue clienti
        lingue_rows = conn.execute("""
            SELECT lingua, COUNT(*) as tot
            FROM chiamate
            GROUP BY lingua
            ORDER BY tot DESC
        """).fetchall()

        # Ultima chiamata
        ultima = conn.execute("""
            SELECT nome_cliente, data_apertura FROM chiamate ORDER BY id DESC LIMIT 1
        """).fetchone()

    LINGUE_NOMI = {"it": "🇮🇹 Italiano", "en": "🇬🇧 English", "bn": "🇧🇩 Bangla", "zh": "🇨🇳 Cinese", "ar": "🇸🇦 Arabo"}

    # ── Messaggio 1: Riepilogo generale
    msg1 = (
        f"📊 *STATISTICHE ROTONDI GROUP ROMA*\n"
        f"{'━'*30}\n\n"
        f"📅 *Questo mese ({now.strftime('%B %Y')})*\n"
        f"  › Chiamate ricevute: *{mese_tot}*\n"
        f"  › Assegnate: *{mese_ass}*\n\n"
        f"📆 *Anno {anno_corrente}*\n"
        f"  › Chiamate totali: *{anno_tot}*\n\n"
        f"🗂 *Totale storico*\n"
        f"  › Chiamate totali: *{totale}*\n"
        f"  › ✅ Assegnate: *{assegnate}*\n"
        f"  › 🟡 Aperte: *{aperte}*\n"
        f"  › ⏳ In attesa: *{in_attesa}*\n"
    )
    if ultima:
        msg1 += f"\n🕐 *Ultima chiamata:* {ultima[0]} — {ultima[1]}"
    await update.message.reply_text(msg1, parse_mode="Markdown")

    # ── Messaggio 2: Classifica tecnici
    if tecnici_rows:
        medaglie = ["🥇", "🥈", "🥉"]
        msg2 = f"👨‍🔧 *CLASSIFICA TECNICI — Storico completo*\n{'━'*30}\n\n"
        for i, (nome, tot, comp) in enumerate(tecnici_rows):
            medaglia = medaglie[i] if i < 3 else f"  {i+1}."
            barra = "█" * min(tot, 15) + "░" * max(0, 15 - min(tot, 15))
            msg2 += f"{medaglia} *{nome}*\n"
            msg2 += f"  `{barra}` *{tot}* chiamate\n\n"

        if tecnici_rows:
            top = tecnici_rows[0]
            msg2 += f"{'━'*30}\n🏆 *Tecnico più attivo:* {top[0]} con *{top[1]}* chiamate"
        await update.message.reply_text(msg2, parse_mode="Markdown")

    # ── Messaggio 3: Tecnici questo mese
    if tecnici_mese:
        msg3 = f"📅 *TECNICI — {now.strftime('%B %Y')}*\n{'━'*30}\n\n"
        for i, (nome, tot) in enumerate(tecnici_mese):
            medaglia = ["🥇","🥈","🥉"][i] if i < 3 else f"  {i+1}."
            msg3 += f"{medaglia} *{nome}*: *{tot}* chiamate\n"
        await update.message.reply_text(msg3, parse_mode="Markdown")

    # ── Messaggio 4: Lingue clienti
    if lingue_rows:
        msg4 = f"🌍 *LINGUE CLIENTI*\n{'━'*30}\n\n"
        tot_ling = sum(r[1] for r in lingue_rows)
        for lingua, cnt in lingue_rows:
            nome = LINGUE_NOMI.get(lingua, lingua)
            perc = int(cnt / tot_ling * 100) if tot_ling > 0 else 0
            barra = "█" * (perc // 7) + "░" * (14 - perc // 7)
            msg4 += f"{nome}\n  `{barra}` *{cnt}* ({perc}%)\n\n"
        await update.message.reply_text(msg4, parse_mode="Markdown")

REG_TELEFONO = 20

async def registrami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    nome = f"{user.first_name or ''} {user.last_name or ''}".strip()
    context.user_data["reg_nome"] = nome
    await update.message.reply_text(
        f"👨‍🔧 Ciao *{nome}*!\n\nPer completare la registrazione scrivi il tuo *numero di telefono*:",
        parse_mode="Markdown"
    )
    return REG_TELEFONO

async def registrami_telefono(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user     = update.effective_user
    nome     = context.user_data.get("reg_nome", user.first_name)
    telefono = update.message.text.strip()
    registra_tecnico(user.id, nome, telefono)
    await update.message.reply_text(
        f"✅ *Registrazione completata!*\n\n👤 Nome: *{nome}*\n📞 Telefono: *{telefono}*\n\n"
        f"Riceverai le notifiche nel gruppo tecnici.\nUsa /chiamate per vedere le tue chiamate.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def mie_chiamate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("""
            SELECT id,nome_cliente,indirizzo,problema_it,fascia_oraria,data_assegnazione,stato,data_ora_proposta
            FROM chiamate WHERE tecnico_id=? OR tecnico_proposta_id=? ORDER BY id DESC LIMIT 10
        """, (tid, tid)).fetchall()
    if not rows:
        await update.message.reply_text("📋 Nessuna chiamata assegnata."); return
    testo = "📋 *Le tue ultime chiamate:*\n\n"
    for r in rows:
        if r[6] == "in_attesa_conferma":
            testo += f"⏳ *#{r[0]}* — {r[1]}\n📍 {r[2]}\n🔧 {r[3]}\n📅 Proposta: {r[7]}\n\n"
        else:
            testo += f"✅ *#{r[0]}* — {r[1]}\n📍 {r[2]}\n🔧 {r[3]}\n⏰ {r[4]}\n\n"
    await update.message.reply_text(testo, parse_mode="Markdown")

async def getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 Chat ID: `{chat.id}`\n👤 User ID: `{user.id}`\n📝 Tipo: {chat.type}",
        parse_mode="Markdown"
    )

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SCEGLI_LINGUA:  [CallbackQueryHandler(scegli_lingua_condizioni, pattern="^lang_")],
            CONDIZIONI:     [CallbackQueryHandler(gestisci_condizioni, pattern="^cond_")],
            NOME:           [MessageHandler(filters.TEXT & ~filters.COMMAND, raccogli_nome)],
            INDIRIZZO:      [MessageHandler(filters.TEXT & ~filters.COMMAND, raccogli_indirizzo)],
            TELEFONO:       [MessageHandler(filters.TEXT & ~filters.COMMAND, raccogli_telefono)],
            FOTO_TARGHETTA: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, raccogli_foto_targhetta)],
            MARCA:          [MessageHandler(filters.TEXT & ~filters.COMMAND, raccogli_marca)],
            MODELLO:        [MessageHandler(filters.TEXT & ~filters.COMMAND, raccogli_modello)],
            SERIALE:        [MessageHandler(filters.TEXT & ~filters.COMMAND, raccogli_seriale)],
            PROBLEMA:       [MessageHandler(filters.TEXT & ~filters.COMMAND, raccogli_problema)],
            FOTO_MACCHINA:  [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, raccogli_foto_macchina)],
            CONFERMA:       [CallbackQueryHandler(conferma, pattern="^conferma_")],
        },
        fallbacks=[CommandHandler("annulla", annulla)]
    )

    conv_registrami = ConversationHandler(
        entry_points=[CommandHandler("registrami", registrami)],
        states={REG_TELEFONO: [MessageHandler(filters.TEXT & ~filters.COMMAND, registrami_telefono)]},
        fallbacks=[CommandHandler("annulla", annulla)]
    )

    app.add_handler(conv)
    app.add_handler(conv_registrami)
    app.add_handler(CallbackQueryHandler(gestisci_fascia,            pattern=r"^fascia_"))
    app.add_handler(CallbackQueryHandler(gestisci_wfascia,           pattern=r"^wfascia_"))
    app.add_handler(CallbackQueryHandler(gestisci_programma,         pattern=r"^programma_"))
    app.add_handler(CallbackQueryHandler(gestisci_data,              pattern=r"^pdata_"))
    app.add_handler(CallbackQueryHandler(gestisci_ora,               pattern=r"^pora_"))
    app.add_handler(CallbackQueryHandler(gestisci_conferma_proposta, pattern=r"^cprop_"))
    app.add_handler(CommandHandler("lista",    lista))
    app.add_handler(CommandHandler("aperte",   aperte))
    app.add_handler(CommandHandler("chiamate", mie_chiamate))
    app.add_handler(CommandHandler("getid",      getid))
    app.add_handler(CommandHandler("storico",      storico))
    app.add_handler(CommandHandler("statistiche", statistiche))
    app.add_handler(CallbackQueryHandler(gestisci_storico, pattern=r"^storico_"))
    app.add_handler(CommandHandler("assegnate",  assegnate))
    app.add_handler(CallbackQueryHandler(gestisci_sblocco, pattern=r"^sblocca_"))

    log.info("🤖 Bot avviato!")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
