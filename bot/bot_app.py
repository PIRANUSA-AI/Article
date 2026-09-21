import asyncio
import html
import json
import logging
import re
import socket
import time
import traceback
from pathlib import Path

from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, LinkPreviewOptions, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, TimedOut
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters

import config
import drafts
import media_server
import pipeline
import qwen_client
import settings_store
import telegram_view as view
import transcript_source
import utils_text
import video_source
import wordpress_push

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s | %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("piranusa.bot")

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
REACTIONS = ("\U0001F440", "\U0001F44D", "❤️")
MAX_ALBUM = 8
MIN_COMPOSE_CHARS = 200

INTENTS = [
    "transcribe",
    "raw_transcript",
    "compose",
    "revise",
    "titles",
    "set_lang",
    "set_proxy",
    "set_brief",
    "set_frame",
    "search_time",
    "status",
    "help",
    "cancel",
    "other",
]

INTENT_SYSTEM = (
    "Kamu router niat untuk bot Telegram internal yang menulis artikel WordPress dari video YouTube, foto, atau catatan. "
    "Klasifikasikan pesan user ke SATU intent dari daftar ini:\n"
    + json.dumps(INTENTS, ensure_ascii=False)
    + "\n\nArti:\n"
    "transcribe: user memberi link atau ID YouTube dan ingin artikel.\n"
    "raw_transcript: user hanya minta teks transkrip mentah, tanpa artikel.\n"
    "compose: user menempel bahan tulisan (catatan, poin rapat, rilis, deskripsi produk) dan ingin dijadikan artikel.\n"
    "revise: user minta mengubah artikel yang barusan dibuat, misalnya judul, paragraf, gaya, panjang, atau gambar, tanpa memberi link baru.\n"
    "titles: user ingin melihat atau memilih opsi judul.\n"
    "set_lang: user minta ganti bahasa subtitle.\n"
    "set_proxy: user memberi alamat proxy.\n"
    "set_brief: user memberi arahan gaya atau sudut pandang untuk artikel berikutnya.\n"
    "set_frame: user minta cuplikan diambil pada detik atau menit tertentu.\n"
    "search_time: user mencari kapan sebuah kata diucapkan.\n"
    "publish: user menyuruh menayangkan/mempublikasikan draf terakhir, misalnya 'yaudah publish', 'terbitkan', 'sebar', 'tayangkan', 'go public'.\n"
    "status: user menanyakan kondisi bot.\n"
    "help: user minta panduan.\n"
    "cancel: user membatalkan proses.\n"
    "other: selain itu.\n\n"
    'Balas JSON: {"intent": string, "video_id": string|null, "languages": [string]|null, '
    '"seconds": int|null, "keyword": string|null, "proxy": string|null, "brief": string|null, "reply": string|null}\n'
    "video_id berisi 11 karakter ID saja. seconds adalah hasil konversi timestamp. "
    "reply hanya untuk intent other, bahasa Indonesia santai, maksimal dua kalimat, tanpa tanda hubung, jangan mengarang fakta."
)

HELP_TEXT = (
    "<b>Bot Artikel Piranusa</b>\n\n"
    "Yang bisa kamu kirim:\n"
    "• <b>Link YouTube</b>: bot ambil transkrip dan cuplikan video, lalu menulis artikel.\n"
    "• <b>Foto</b>, satu atau beberapa sekaligus: bot membaca isi foto lalu menulis artikel. Isi caption kalau ada konteks.\n"
    "• <b>Foto plus link YouTube di caption</b>: artikel dari video, fotomu jadi gambar utama.\n"
    "• <b>Teks panjang</b> seperti catatan, poin rapat, atau rilis: langsung dijadikan artikel.\n\n"
    "Setelah draf jadi, tombol di kartu draf dipakai untuk memilih judul, melihat isi, mengganti gambar utama, publish, atau minta file XML.\n"
    "Mau revisi? Balas kartu draf atau pesan isi artikel dengan permintaanmu. "
    "Kirim foto sebagai balasan untuk menambah gambar. Tulis <i>jadikan gambar utama</i> di caption kalau foto itu untuk sampul.\n\n"
    "<b>Perintah</b>\n"
    "/artikel link : artikel dari video\n"
    "/transkrip link : teks transkrip saja\n"
    "/draf : kartu draf terakhir\n"
    "/revisi permintaan : revisi draf terakhir\n"
    "/judul : pilihan judul draf terakhir\n"
    "/selesai : keluar dari mode revisi\n"
    "/cari kata : menit kemunculan kata di video terakhir\n"
    "/bahasa id en : prioritas bahasa subtitle\n"
    "/frame 3:20 : cuplikan di menit itu ikut ditawarkan untuk isi artikel\n"
    "/brief arahan : gaya atau sudut pandang artikel berikutnya\n"
    "/proxy url : proxy kalau IP server diblokir YouTube\n"
    "/base url : URL publik bot untuk mode XML\n"
    "/wp url user password : sambungkan ke WordPress\n"
    "/mode push, xml, atau both : cara kirim hasil\n"
    "/wppost draft atau publish : status awal artikel di WordPress\n"
    "/kunci : lihat kunci akses, /kunci baru untuk ganti\n"
    "/status : kondisi bot\n"
    "/batal : hentikan proses yang berjalan"
)


class JobFailed(Exception):
    pass


class State:
    def __init__(self):
        self.busy = {}
        self.last_video = {}
        self.last_draft = {}
        self.edit_target = {}
        self.albums = {}

    @staticmethod
    def key(update):
        chat = update.effective_chat
        user = update.effective_user
        return "%s:%s" % (chat.id, getattr(user, "id", "anon"))


STATE = State()


def esc(text):
    return html.escape(str(text or ""), quote=False)


def authorized(update):
    user = update.effective_user
    if not user:
        return False
    if settings_store.get("allow_all", False):
        return True
    if config.ALLOWED_USER_IDS and user.id in config.ALLOWED_USER_IDS:
        return True
    return settings_store.is_unlocked(user.id)


async def key_gate(update):
    if authorized(update):
        return True
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return False
    given = (message.text or "").strip().upper()
    if given.startswith("/KUNCI"):
        given = given[6:].strip()
    given = given.replace(" ", "")
    if given and given == settings_store.app_key():
        settings_store.unlock(user.id)
        try:
            await message.delete()
        except Exception:
            pass
        await message.chat.send_message(
            "Kunci benar, akses dibuka. Kirim link YouTube, foto, atau teks panjang.",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
        return False
    log.info("akses ditolak user_id=%s", user.id)
    await reply(message, "Bot ini terkunci. Kirim dulu kunci aksesnya, 6 karakter, minta ke tim.")
    return False


def current_draft_id(key):
    return STATE.last_draft.get(key) or drafts.latest_for(key)


async def reply(message, text, reply_markup=None):
    try:
        return await message.reply_text(text, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW, reply_markup=reply_markup)
    except BadRequest:
        return await message.reply_text(re.sub(r"<[^>]+>", "", text), link_preview_options=NO_PREVIEW, reply_markup=reply_markup)


async def safe_edit(target, text, reply_markup=None):
    try:
        if target.photo:
            await target.edit_caption(caption=text[:1024], parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        else:
            await target.edit_text(text, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW, reply_markup=reply_markup)
        return True
    except BadRequest as exc:
        if "not modified" in str(exc).lower():
            return True
        try:
            await target.edit_text(re.sub(r"<[^>]+>", "", text), reply_markup=reply_markup)
            return True
        except Exception:
            return False
    except Exception:
        return False


async def react_user(message, emojis=REACTIONS):
    for emoji in emojis:
        try:
            await message.set_reaction(emoji)
            return emoji
        except Exception:
            continue
    return None


def start_task(update, coro):
    key = STATE.key(update)
    existing = STATE.busy.get(key)
    if existing and not existing.done():
        coro.close()
        return False
    task = asyncio.create_task(coro)
    STATE.busy[key] = task

    def cleanup(finished):
        if STATE.busy.get(key) is finished:
            STATE.busy.pop(key, None)

    task.add_done_callback(cleanup)
    return True


async def busy_notice(message):
    await reply(message, "Masih ada proses yang jalan. Tunggu sebentar atau kirim /batal.")


INTERNAL_MARKERS = ("qwen", "dashscope", "openai", "yt-dlp", "ytt-api", "youtube-transcript", "ffmpeg", "json", "traceback", "http")


def public_error(detail):
    lowered = (detail or "").lower()
    if "requestblocked" in lowered or "ipblocked" in lowered or "429" in lowered and "youtube" in lowered:
        return "YouTube sedang menolak akses dari server ini. Kirim <code>/proxy http://user:pass@host:port</code>, lalu kirim ulang linknya."
    if "subtitle" in lowered or "transkrip tidak tersedia" in lowered or "transcript" in lowered:
        return "Transkrip video ini tidak bisa diambil. Coba <code>/bahasa en</code> atau video lain."
    if "timed out" in lowered or "timeout" in lowered:
        return "Prosesnya kelamaan. Coba kirim ulang sebentar lagi."
    if "login wordpress" in lowered or "wordpress" in lowered or "post" in lowered and "http" in lowered:
        return "WordPress menolak permintaan: <code>%s</code>" % esc(detail[:200])
    if any(marker in lowered for marker in INTERNAL_MARKERS):
        return "Ada kendala di proses internal. Coba kirim ulang sebentar lagi."
    return esc(detail[:300])


async def tracked(status, title, fn):
    steps = []

    def on_progress(text):
        if not steps or steps[-1] != text:
            steps.append(text)

    started = time.time()
    worker = asyncio.create_task(asyncio.to_thread(fn, on_progress))
    shown = 0
    try:
        while not worker.done():
            await asyncio.sleep(1.2)
            if len(steps) != shown:
                shown = len(steps)
                await safe_edit(status, view.progress_text(title, list(steps)))
        result = worker.result()
    except asyncio.CancelledError:
        await safe_edit(status, "Dibatalkan.")
        raise
    except Exception as exc:
        detail = str(exc)[:600]
        log.error("job gagal: %s\n%s", detail, traceback.format_exc())
        failed = public_error(detail)
        await safe_edit(status, view.progress_text(title, list(steps) or ["mulai"], failed=failed))
        raise JobFailed(detail)
    log.info("%s selesai dalam %.1f detik", title, time.time() - started)
    return result


def public_base():
    base = (settings_store.get("public_base") or config.PUBLIC_BASE_URL or "").strip().rstrip("/")
    if base:
        return base
    port = media_server.start()
    if config.PUBLIC_BASE_URL_AUTO:
        return "http://%s:%d" % (local_ip(), port)
    return ""


def local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        sock.close()


async def send_card(message, draft, headline="Draf siap"):
    settings = settings_store.all_values()
    text = view.card_text(draft, headline)
    markup = view.card_keyboard(draft, wordpress_push.ready(settings))
    featured = next((img for img in draft["images"] if img["role"] == "featured"), None)
    sent = None
    plain_length = len(re.sub(r"<[^>]+>", "", text))
    if featured and Path(featured["path"]).exists() and plain_length <= 1000:
        try:
            with open(featured["path"], "rb") as handle:
                sent = await message.reply_photo(photo=handle, caption=text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except TimedOut as exc:
            log.warning("kartu foto timeout, tidak dikirim ulang supaya tidak dobel: %s", exc)
            return None
        except Exception as exc:
            log.warning("kartu foto gagal: %s", exc)
            sent = None
    if sent is None:
        sent = await reply(message, text, reply_markup=markup)
    drafts.remember_message(draft["id"], sent.chat_id, sent.message_id)
    return sent


async def send_files(message, draft):
    base = public_base()
    result = await asyncio.to_thread(pipeline.build_files, draft, base)
    xml_path = Path(result["xml_path"])
    caption = "File WordPress XML. Import lewat Tools, Import, WordPress."
    if base:
        caption += " Centang Download and import file attachments supaya gambar ikut."
    with open(xml_path, "rb") as handle:
        await message.reply_document(document=handle, filename=xml_path.name, caption=caption)
    if result.get("zip_path") and not base:
        zip_path = Path(result["zip_path"])
        with open(zip_path, "rb") as handle:
            await message.reply_document(
                document=handle,
                filename=zip_path.name,
                caption="Paket offline: XML plus folder gambar. Ekstrak ke document root dulu, lalu import XML tanpa centang download attachments.",
            )
    md_path = Path(result["markdown"])
    with open(md_path, "rb") as handle:
        await message.reply_document(document=handle, filename="artikel_%s.md" % draft["id"], caption="Versi Markdown.")


async def sync_wordpress(draft, settings, force=False):
    if not (draft.get("wp") or {}).get("post_id") or not wordpress_push.ready(settings):
        drafts.save(draft)
        return None
    try:
        if not force and await asyncio.to_thread(wordpress_push.changed_on_site, draft, settings):
            drafts.save(draft)
            return "conflict"
        await asyncio.to_thread(wordpress_push.push, draft, settings)
        drafts.save(draft)
        return "ok"
    except Exception as exc:
        log.error("sync WP gagal: %s", exc)
        drafts.save(draft)
        return "Gagal memperbarui WordPress: %s" % str(exc)[:300]


def sync_note(result):
    if result == "ok":
        return "\nWordPress sudah ikut diperbarui."
    if result == "conflict":
        return "\n\nArtikel di WordPress sudah diedit manual sejak terakhir dikirim bot. Perubahan ini tersimpan di bot tapi belum dikirim. Tekan tombol timpa kalau memang mau menggantinya."
    if result:
        return "\n" + esc(result)
    return ""


async def create_article(update, title, **kwargs):
    message = update.effective_message
    key = STATE.key(update)
    settings = settings_store.all_values()
    kwargs.setdefault("brief", settings.get("brief") or None)
    kwargs.setdefault("frame_seconds", settings.get("frame"))
    status = await reply(message, view.progress_text(title, ["Menyiapkan"]))
    try:
        draft = await tracked(status, title, lambda progress: pipeline.create(owner=key, on_progress=progress, **kwargs))
    except JobFailed:
        return
    STATE.last_draft[key] = draft["id"]
    STATE.edit_target.pop(key, None)
    await deliver(message, draft, status, settings)


async def deliver(message, draft, status, settings):
    mode = settings.get("publish_mode") or "push"
    ready = wordpress_push.ready(settings)
    notes = []
    if mode in ("push", "both"):
        if ready:
            await safe_edit(status, "<b>Artikel selesai ditulis.</b>\nMengirim ke WordPress...")
            try:
                await asyncio.to_thread(wordpress_push.push, draft, settings)
                drafts.save(draft)
            except Exception as exc:
                log.error("push WP gagal: %s", exc)
                notes.append("Push ke WordPress gagal: <code>%s</code>\nFile XML dikirim sebagai gantinya." % esc(str(exc)[:300]))
                mode = "xml"
        else:
            notes.append("WordPress belum tersambung, pakai /wp dulu. Sementara file XML dikirim.")
            mode = "xml"
    await safe_edit(status, "<b>Selesai.</b> Kartu draf ada di bawah.")
    drafts.remember_message(draft["id"], status.chat_id, status.message_id)
    await send_card(message, draft)
    if mode in ("xml", "both"):
        await send_files(message, draft)
    for note in notes:
        await reply(message, note)


async def revision_job(update, draft_id, instruction, image_path=None):
    message = update.effective_message
    key = STATE.key(update)
    draft = drafts.load(draft_id)
    if not draft:
        await reply(message, "Draf itu sudah tidak ada di bot.")
        return
    STATE.last_draft[key] = draft_id
    title = "Menambah foto ke draf" if image_path else "Merevisi draf"
    status = await reply(message, view.progress_text(title, ["Membaca permintaanmu"]))
    drafts.remember_message(draft_id, status.chat_id, status.message_id)
    outcome = None
    try:
        if image_path:
            outcome = await tracked(status, title, lambda progress: pipeline.add_image(draft, image_path, instruction))
            note = outcome["note"]
            if not outcome.get("featured") and not outcome.get("placed"):
                note += " Foto disimpan, tapi belum ketemu bagian yang cocok. Sebutkan bagiannya kalau mau dipasang."
        else:
            note = await tracked(status, title, lambda progress: pipeline.revise(draft, instruction))
    except JobFailed:
        return
    result = await sync_wordpress(draft, settings_store.all_values())
    text = "<b>Revisi selesai.</b>\n%s%s\n\nBalas pesan ini kalau masih ada yang mau diubah." % (esc(note), sync_note(result))
    await safe_edit(status, text, reply_markup=view.after_edit_keyboard(draft, conflict=result == "conflict"))
    if outcome and outcome.get("featured"):
        await send_card(message, draft, "Gambar utama baru")


async def start_revision(update, draft_id, instruction, image_path=None):
    if not start_task(update, revision_job(update, draft_id, instruction, image_path)):
        await busy_notice(update.effective_message)


async def raw_job(update, video_id):
    message = update.effective_message
    status = await reply(message, "Mengambil transkrip <code>%s</code>..." % esc(video_id))
    try:
        transcript = await asyncio.to_thread(transcript_source.fetch, video_id)
    except Exception as exc:
        log.error("transkrip gagal: %s", exc)
        await safe_edit(status, "Gagal mengambil transkrip. %s" % public_error(str(exc)))
        return
    text = transcript_source.as_plain_text(transcript["snippets"])
    out = config.JOBS_DIR / ("%s_transkrip.txt" % video_id)
    out.write_text(text, encoding="utf-8")
    await safe_edit(status, "Transkrip siap.")
    with open(out, "rb") as handle:
        await message.reply_document(
            document=handle,
            filename="transkrip_%s.txt" % video_id,
            caption="Transkrip mentah, bahasa %s, %d segmen." % (transcript.get("language"), len(transcript["snippets"])),
        )


async def classify(text, has_draft):
    video_id = utils_text.extract_video_id(text)
    context_blob = json.dumps({"video_id_terdeteksi": video_id, "ada_draf_aktif": has_draft, "panjang_pesan": len(text or "")}, ensure_ascii=False)
    prompt = "Konteks: %s\n\nPesan user:\n%s" % (context_blob, (text or "")[:1500])
    try:
        data, model = qwen_client.chat_json(INTENT_SYSTEM, prompt, models=qwen_client.fast_models(), temperature=0.0, max_tokens=400)
        if not isinstance(data, dict):
            raise ValueError("bukan dict")
        data["_model"] = model
        return data
    except Exception as exc:
        log.warning("intent Qwen gagal, pakai aturan regex: %s", exc)
        return fallback_intent(text, video_id)


def fallback_intent(text, video_id):
    lowered = (text or "").strip().lower()
    if lowered in ("help", "bantuan"):
        return {"intent": "help"}
    if any(word in lowered for word in ("batal", "stop", "cancel")):
        return {"intent": "cancel"}
    if video_id:
        wants_raw = re.search(r"transkrip(nya| aja| saja| mentah)?\b", lowered) and "artikel" not in lowered and "wp" not in lowered
        return {"intent": "raw_transcript" if wants_raw else "transcribe", "video_id": video_id}
    if len(lowered) >= MIN_COMPOSE_CHARS:
        return {"intent": "compose"}
    if "judul" in lowered:
        return {"intent": "titles"}
    langs = settings_store.normalize_langs(text)
    if re.search(r"bahasa|subtitle|lang", lowered) and langs:
        return {"intent": "set_lang", "languages": langs}
    stamp = video_source.parse_timestamp(lowered)
    if stamp is not None and re.search(r"frame|gambar|screenshot", lowered):
        return {"intent": "set_frame", "seconds": stamp}
    if "proxy" in lowered:
        return {"intent": "set_proxy", "proxy": text.strip()}
    if "status" in lowered or "konfigurasi" in lowered:
        return {"intent": "status"}
    if "menit berapa" in lowered or lowered.startswith("cari "):
        return {"intent": "search_time", "keyword": re.sub(r"^(cari|carikan)\s+", "", lowered)}
    return {"intent": "other", "reply": "Belum kebaca maksudnya. Kirim link YouTube, foto, atau catatan panjang untuk dijadikan artikel. Ketik /help untuk panduan."}


async def on_message(update, context):
    message = update.effective_message
    if not message or not message.text:
        return
    if not await key_gate(update):
        return
    await react_user(message)
    key = STATE.key(update)
    text = message.text
    video_id = utils_text.extract_video_id(text)

    target = None
    if message.reply_to_message:
        target = drafts.for_message(message.chat_id, message.reply_to_message.message_id)
    if not target and not video_id:
        target = STATE.edit_target.get(key)
    if target and not video_id:
        await start_revision(update, target, text)
        return

    if video_id:
        STATE.last_video[key] = video_id
    await message.chat.send_action(ChatAction.TYPING)
    data = await classify(text, bool(current_draft_id(key)))
    intent = data.get("intent") if data.get("intent") in INTENTS else "other"
    log.info("intent=%s model=%s user=%s", intent, data.get("_model", "fallback"), message.from_user.id)

    if intent in ("transcribe", "raw_transcript"):
        target_video = data.get("video_id") or video_id or STATE.last_video.get(key)
        if not target_video or not utils_text.PLAIN_ID_PATTERN.match(str(target_video)):
            target_video = video_id or STATE.last_video.get(key)
        if not target_video:
            await reply(message, "Butuh link atau ID YouTube. Contoh: <code>/artikel https://youtu.be/dQw4w9WgXcQ</code>")
            return
        STATE.last_video[key] = target_video
        if intent == "raw_transcript":
            job = raw_job(update, target_video)
        else:
            extra = utils_text.URL_PATTERN.sub("", text).strip()
            job = create_article(update, "Menulis artikel dari video", video_id=target_video, caption=extra if len(extra) > 15 else "")
        if not start_task(update, job):
            await busy_notice(message)
    elif intent == "compose":
        if len(text) < MIN_COMPOSE_CHARS:
            await reply(message, "Bahannya masih terlalu pendek untuk jadi artikel. Tempel catatan yang lebih lengkap, atau kirim link YouTube atau foto.")
            return
        if not start_task(update, create_article(update, "Menulis artikel dari catatan", text=text)):
            await busy_notice(message)
    elif intent == "revise":
        draft_id = current_draft_id(key)
        if not draft_id:
            await reply(message, "Belum ada draf untuk direvisi. Kirim link YouTube, foto, atau catatan dulu.")
            return
        await start_revision(update, draft_id, text)
    elif intent == "titles":
        await show_titles(message, current_draft_id(key))
    elif intent == "set_lang":
        langs = data.get("languages") or settings_store.normalize_langs(text)
        if langs:
            settings_store.set_value("languages", langs)
            await reply(message, "Prioritas subtitle: <code>%s</code>." % esc(", ".join(langs)))
        else:
            await reply(message, "Sebutkan kode bahasanya, misal <code>/bahasa id en</code>.")
    elif intent == "set_proxy":
        context.args = (data.get("proxy") or text).split()
        await cmd_proxy(update, context)
    elif intent == "set_brief":
        context.args = (data.get("brief") or text).split()
        await cmd_brief(update, context)
    elif intent == "set_frame":
        seconds = data.get("seconds")
        if seconds is None:
            seconds = video_source.parse_timestamp(text)
        if seconds is not None:
            settings_store.set_value("frame", int(seconds))
            await reply(message, "Cuplikan di <code>%02d:%02d</code> akan ikut ditawarkan untuk isi artikel berikutnya." % (int(seconds) // 60, int(seconds) % 60))
        else:
            await reply(message, "Sebutkan waktunya, misal <code>/frame 3:20</code>.")
    elif intent == "search_time":
        context.args = (str(data.get("keyword") or text)).split()
        await cmd_search(update, context)
    elif intent == "status":
        await cmd_status(update, context)
    elif intent == "cancel":
        await cmd_cancel(update, context)
    elif intent == "help":
        await cmd_help(update, context)
    else:
        await reply(message, esc(data.get("reply")) or "Belum kebaca maksudnya. Ketik /help untuk panduan.")


async def download_image(message):
    if message.photo:
        tg_file = await message.photo[-1].get_file()
        suffix = ".jpg"
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        tg_file = await message.document.get_file()
        suffix = Path(message.document.file_name or "gambar.jpg").suffix.lower() or ".jpg"
    else:
        return None
    dest = config.INBOX_DIR / ("%s_%s%s" % (message.chat_id, message.message_id, suffix))
    await tg_file.download_to_drive(custom_path=dest)
    return dest


async def on_photo(update, context):
    message = update.effective_message
    if not message:
        return
    if not await key_gate(update):
        return
    key = STATE.key(update)
    try:
        path = await download_image(message)
    except Exception as exc:
        await reply(message, "Gambarnya gagal diunduh: <code>%s</code>" % esc(str(exc)[:200]))
        return
    if not path:
        await reply(message, "Format file ini belum didukung. Kirim sebagai foto atau file JPG/PNG.")
        return
    caption = (message.caption or "").strip()

    if message.media_group_id:
        album = STATE.albums.setdefault(message.media_group_id, {"update": update, "paths": [], "caption": ""})
        album["paths"].append((message.message_id, path))
        if caption:
            album["caption"] = caption
        if not album.get("task"):
            album["task"] = asyncio.create_task(flush_album(message.media_group_id))
        return

    await react_user(message)
    target = None
    if message.reply_to_message:
        target = drafts.for_message(message.chat_id, message.reply_to_message.message_id)
    if not target:
        target = STATE.edit_target.get(key)
    if target and not utils_text.extract_video_id(caption):
        await start_revision(update, target, caption, image_path=path)
        return
    await start_image_job(update, [path], caption)


async def flush_album(group_id):
    await asyncio.sleep(2.5)
    album = STATE.albums.pop(group_id, None)
    if not album:
        return
    update = album["update"]
    await react_user(update.effective_message)
    paths = [p for _, p in sorted(album["paths"])]
    if len(paths) > MAX_ALBUM:
        await reply(update.effective_message, "Ada %d foto, yang dipakai %d foto pertama." % (len(paths), MAX_ALBUM))
        paths = paths[:MAX_ALBUM]
    await start_image_job(update, paths, album["caption"])


async def start_image_job(update, paths, caption):
    video_id = utils_text.extract_video_id(caption)
    if video_id:
        rest = utils_text.URL_PATTERN.sub("", caption).strip()
        STATE.last_video[STATE.key(update)] = video_id
        job = create_article(update, "Menulis artikel dari video dan foto", video_id=video_id, image_paths=paths, caption=rest)
    else:
        label = "foto" if len(paths) == 1 else "%d foto" % len(paths)
        job = create_article(update, "Menulis artikel dari %s" % label, image_paths=paths, caption=caption)
    if not start_task(update, job):
        await busy_notice(update.effective_message)


async def show_titles(message, draft_id):
    draft = drafts.load(draft_id) if draft_id else None
    if not draft:
        await reply(message, "Belum ada draf. Kirim link YouTube, foto, atau catatan dulu.")
        return
    sent = await reply(message, view.titles_text(draft), reply_markup=view.titles_keyboard(draft))
    drafts.remember_message(draft["id"], sent.chat_id, sent.message_id)


async def show_featured_picker(message, draft):
    candidates = pipeline.featured_candidates(draft)
    if not candidates:
        await reply(message, "Draf ini belum punya gambar. Kirim foto sebagai balasan kartu draf untuk menambahkannya.")
        return
    media = []
    handles = []
    try:
        for index, img in enumerate(candidates):
            handle = open(img["path"], "rb")
            handles.append(handle)
            media.append(InputMediaPhoto(media=handle, caption=view.candidate_caption(index, img)))
        if len(media) == 1:
            await message.reply_photo(photo=handles[0], caption=view.candidate_caption(0, candidates[0]))
        else:
            await message.reply_media_group(media=media)
    finally:
        for handle in handles:
            handle.close()
    sent = await reply(
        message,
        "<b>Pilih gambar utama</b>\nNomor sesuai urutan foto di atas. Mau pakai foto lain? Balas kartu draf dengan foto dan caption <i>jadikan gambar utama</i>.",
        reply_markup=view.featured_keyboard(draft, candidates),
    )
    drafts.remember_message(draft["id"], sent.chat_id, sent.message_id)


async def on_button(update, context):
    query = update.callback_query
    if not authorized(update):
        await query.answer("Bot terkunci. Kirim kunci aksesnya di chat dulu.", show_alert=True)
        return
    data = view.parse_cb(query.data)
    if not data:
        await query.answer()
        return
    draft = drafts.load(data["draft"])
    if not draft:
        await query.answer("Draf ini sudah tidak ada di bot.", show_alert=True)
        return
    key = STATE.key(update)
    STATE.last_draft[key] = draft["id"]
    action = data["action"]
    arg = data["arg"]
    message = query.message
    settings = settings_store.all_values()
    try:
        await handle_button(query, message, draft, action, arg, settings, key)
    except Exception as exc:
        log.error("tombol %s gagal: %s\n%s", action, exc, traceback.format_exc())
        await reply(message, "Tombolnya gagal dijalankan. %s" % public_error(str(exc)))


async def handle_button(query, message, draft, action, arg, settings, key):
    if action == "close":
        await query.answer()
        try:
            await message.delete()
        except Exception:
            await message.edit_reply_markup(reply_markup=None)
    elif action == "card":
        await query.answer()
        await send_card(message, draft, "Menu draf")
    elif action == "tt":
        await query.answer()
        await show_titles(message, draft["id"])
    elif action == "t":
        index = int(arg or 0)
        options = draft["article"].get("title_options") or []
        if index >= len(options):
            await query.answer("Opsi judul itu sudah tidak ada.", show_alert=True)
            return
        if options[index]["title"] == draft["article"]["title"]:
            await query.answer("Judul itu sedang dipakai.")
            return
        await query.answer("Mengganti judul...")
        pipeline.choose_title(draft, index)
        result = await sync_wordpress(draft, settings)
        await safe_edit(message, view.titles_text(draft) + "\n" + sync_note(result), reply_markup=view.titles_keyboard(draft))
        if result == "conflict":
            await reply(message, "Judul tersimpan di bot tapi belum dikirim.", reply_markup=view.after_edit_keyboard(draft, conflict=True))
    elif action == "tn":
        await query.answer("Sebentar, bikin judul baru...")
        await safe_edit(message, view.titles_text(draft) + "\n\n<i>Membuat lima judul baru...</i>", reply_markup=view.titles_keyboard(draft))
        await asyncio.to_thread(pipeline.new_titles, draft)
        await safe_edit(message, view.titles_text(draft), reply_markup=view.titles_keyboard(draft))
    elif action == "v":
        await query.answer()
        for chunk in view.preview_chunks(draft):
            sent = await reply(message, chunk)
            drafts.remember_message(draft["id"], sent.chat_id, sent.message_id)
        tail = await reply(message, "Balas salah satu pesan di atas untuk revisi. Contoh: <i>bagian 2 dibuat jadi langkah bernomor</i>.", reply_markup=view.after_edit_keyboard(draft))
        drafts.remember_message(draft["id"], tail.chat_id, tail.message_id)
    elif action == "e":
        await query.answer()
        STATE.edit_target[key] = draft["id"]
        sent = await message.reply_text(
            "Mode revisi aktif untuk draf <b>%s</b>.\nTulis apa yang mau diubah. Kirim foto untuk menambah gambar. Ketik /selesai kalau sudah." % esc(draft["article"]["title"]),
            parse_mode=ParseMode.HTML,
            reply_markup=ForceReply(selective=True, input_field_placeholder="contoh: ringkas bagian 2"),
        )
        drafts.remember_message(draft["id"], sent.chat_id, sent.message_id)
    elif action == "g":
        await query.answer()
        await show_featured_picker(message, draft)
    elif action == "gf":
        target = next((img for img in draft["images"] if img["key"] == arg), None)
        if not target:
            await query.answer("Gambar itu sudah tidak ada.", show_alert=True)
            return
        if target["role"] == "featured":
            await query.answer("Gambar itu sudah jadi gambar utama.")
            return
        await query.answer("Mengganti gambar utama...")
        pipeline.set_featured(draft, arg)
        result = await sync_wordpress(draft, settings)
        await safe_edit(message, "<b>Gambar utama diganti.</b>" + sync_note(result), reply_markup=view.featured_keyboard(draft, pipeline.featured_candidates(draft)))
        await send_card(message, draft, "Gambar utama baru")
    elif action == "u":
        label = pipeline.undo(draft)
        if label is None:
            await query.answer("Tidak ada perubahan yang bisa dibatalkan.", show_alert=True)
            return
        await query.answer("Dibatalkan.")
        result = await sync_wordpress(draft, settings)
        await reply(message, "Perubahan <i>%s</i> dibatalkan.%s" % (esc(label), sync_note(result)), reply_markup=view.after_edit_keyboard(draft, conflict=result == "conflict"))
    elif action == "ws":
        await query.answer("Menimpa versi WordPress...")
        result = await sync_wordpress(draft, settings, force=True)
        await reply(message, "Versi bot sudah dikirim ke WordPress." if result == "ok" else sync_note(result) or "WordPress belum tersambung.")
    elif action == "p":
        await query.answer()
        await reply(message, "Tayangkan <b>%s</b> sekarang?" % esc(draft["article"]["title"]), reply_markup=view.confirm_keyboard(draft["id"], "pc", "Ya, tayangkan"))
    elif action == "pc":
        await query.answer("Menayangkan...")
        wp = await asyncio.to_thread(wordpress_push.set_status, draft, settings, "publish")
        drafts.save(draft)
        await safe_edit(
            message,
            "<b>Sudah tayang.</b>\n%s" % esc(draft["article"]["title"]),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Buka artikel", url=wp["link"])]]),
        )
    elif action == "dr":
        await query.answer("Menarik jadi draf...")
        await asyncio.to_thread(wordpress_push.set_status, draft, settings, "draft")
        drafts.save(draft)
        await send_card(message, draft, "Artikel ditarik jadi draf")
    elif action == "w":
        if not wordpress_push.ready(settings):
            await query.answer("WordPress belum tersambung. Pakai /wp dulu.", show_alert=True)
            return
        await query.answer("Mengirim ke WordPress...")
        await asyncio.to_thread(wordpress_push.push, draft, settings)
        drafts.save(draft)
        await send_card(message, draft, "Draf masuk WordPress")
    elif action == "x":
        await query.answer("Menyiapkan file...")
        await send_files(message, draft)
    else:
        await query.answer()


async def cmd_start(update, context):
    await cmd_help(update, context)


async def cmd_help(update, context):
    await reply(update.effective_message, HELP_TEXT)


async def cmd_status(update, context):
    values = settings_store.all_values()
    port = media_server.start()
    base = public_base() or "(belum diset, mode zip offline)"
    task = STATE.busy.get(STATE.key(update))
    text = (
        "<b>Status bot</b>\n"
        "Proses berjalan: <code>%s</code>\n"
        "Preferensi bahasa: <code>%s</code>\n"
        "Proxy: <code>%s</code>\n"
        "Frame pilihan: <code>%s</code>\n"
        "Brief aktif: <code>%s</code>\n"
        "WordPress: <code>%s</code> (mode %s, status awal %s)\n"
        "URL publik: <code>%s</code>\n"
        "Server gambar: port <code>%d</code>\n"
        "Akses: <code>%s</code>"
    ) % (
        "ya" if task and not task.done() else "tidak",
        esc(", ".join(settings_store.languages())),
        esc(values.get("proxy") or "(tanpa proxy)"),
        esc("otomatis" if values.get("frame") in (None, "") else str(values.get("frame"))),
        esc((values.get("brief") or "(kosong)")[:200]),
        esc(values.get("wp_url") or "belum tersambung"),
        esc(values.get("publish_mode") or "push"),
        esc(values.get("wp_status") or "draft"),
        esc(str(base)),
        port,
        "terbuka untuk semua" if values.get("allow_all") else "dikunci, %d user sudah masuk" % len(settings_store.unlocked_users()),
    )
    await reply(update.effective_message, text)


async def cmd_language(update, context):
    langs = settings_store.normalize_langs(" ".join(context.args or []))
    if not langs:
        await reply(update.effective_message, "Prioritas sekarang: <code>%s</code>.\nPakai: <code>/bahasa id en</code>" % esc(", ".join(settings_store.languages())))
        return
    settings_store.set_value("languages", langs)
    await reply(update.effective_message, "Oke, prioritas subtitle jadi <code>%s</code>." % esc(", ".join(langs)))


async def cmd_proxy(update, context):
    value = " ".join(context.args or []).strip()
    if not value or value.lower() in ("off", "hapus", "kosong"):
        settings_store.set_value("proxy", "")
        await reply(update.effective_message, "Proxy dimatikan. Transkrip diminta langsung ke YouTube.")
        return
    settings_store.set_value("proxy", value)
    await reply(update.effective_message, "Proxy disimpan. Kirim lagi link YouTubenya.")


async def cmd_brief(update, context):
    value = " ".join(context.args or []).strip()
    if not value:
        await reply(update.effective_message, "Brief aktif: <code>%s</code>\nHapus dengan <code>/brief off</code>." % esc(settings_store.get("brief", "") or "(kosong)"))
        return
    if value.lower() in ("off", "hapus", "kosong"):
        settings_store.set_value("brief", "")
        await reply(update.effective_message, "Brief dihapus.")
        return
    settings_store.set_value("brief", value)
    await reply(update.effective_message, "Brief disimpan. Artikel berikutnya pakai arahan ini.")


async def cmd_frame(update, context):
    seconds = video_source.parse_timestamp(" ".join(context.args or []))
    if seconds is None:
        await reply(update.effective_message, "Format: <code>/frame 3:20</code>. Kirim <code>/frame 0</code> untuk balik ke otomatis.")
        return
    if seconds == 0:
        settings_store.set_value("frame", None)
        await reply(update.effective_message, "Frame pilihan dihapus, bot memilih sendiri.")
        return
    settings_store.set_value("frame", seconds)
    await reply(update.effective_message, "Cuplikan di <code>%02d:%02d</code> akan ikut ditawarkan untuk isi artikel." % (seconds // 60, seconds % 60))


async def cmd_base(update, context):
    value = " ".join(context.args or []).strip().rstrip("/")
    if not value:
        await reply(update.effective_message, "URL publik sekarang: <code>%s</code>" % esc(public_base() or "(belum diset)"))
        return
    if not value.startswith("http"):
        value = "http://" + value
    settings_store.set_value("public_base", value)
    await reply(update.effective_message, "Oke. Gambar disajikan dari <code>%s</code> supaya ikut terunduh saat import." % esc(value))


async def cmd_allow(update, context):
    current = bool(settings_store.get("allow_all", False))
    settings_store.set_value("allow_all", not current)
    await reply(update.effective_message, "Akses terbuka untuk semua user: <code>%s</code>." % str(not current))


async def cmd_key(update, context):
    args = [item.lower() for item in (context.args or [])]
    message = update.effective_message
    if args and args[0] in ("baru", "ganti", "reset"):
        value = settings_store.rotate_app_key()
        await reply(
            message,
            "Kunci baru: <code>%s</code>\nSemua yang tadi sudah terbuka harus kirim kunci ini lagi." % esc(value),
        )
        return
    if args and args[0] in ("siapa", "daftar", "user"):
        people = settings_store.unlocked_users()
        await reply(
            message,
            "User yang sudah terbuka: <code>%s</code>" % esc(", ".join(str(item) for item in people) or "belum ada"),
        )
        return
    await reply(
        message,
        "Kunci akses: <code>%s</code>\nBagikan ke tim. Ganti kapan saja dengan <code>/kunci baru</code>." % esc(settings_store.app_key()),
    )


async def cmd_wp(update, context):
    args = context.args or []
    message = update.effective_message
    if not args:
        values = settings_store.all_values()
        if not values.get("wp_url"):
            await reply(message, "Belum tersambung ke WordPress.\nPakai: <code>/wp https://site.com user password</code>")
            return
        await reply(
            message,
            "WordPress: <code>%s</code>\nUser: <code>%s</code>\nPassword: <code>%s</code>\nStatus awal artikel: <code>%s</code>\nMode kirim: <code>%s</code>"
            % (
                esc(values["wp_url"]),
                esc(values.get("wp_user") or "(kosong)"),
                esc("*" * 24 if values.get("wp_app_password") else "(kosong)"),
                esc(values.get("wp_status") or "draft"),
                esc(values.get("publish_mode") or "push"),
            ),
        )
        return
    if args[0].lower() in ("off", "hapus", "reset"):
        for name in ("wp_url", "wp_user", "wp_app_password"):
            settings_store.set_value(name, "")
        await reply(message, "Koneksi WordPress dilepas.")
        return
    if len(args) < 3:
        await reply(message, "Argumennya kurang.\nFormat: <code>/wp https://site.com namauser password</code>")
        return
    url = args[0].rstrip("/")
    if not url.startswith("http"):
        url = "https://" + url
    settings_store.set_value("wp_url", url)
    settings_store.set_value("wp_user", args[1])
    settings_store.set_value("wp_app_password", "".join(args[2:]))
    await message.chat.send_action(ChatAction.TYPING)
    try:
        info = await asyncio.to_thread(wordpress_push.test_connection, settings_store.all_values())
        settings_store.set_value("publish_mode", "push")
        text = "Tersambung ke <code>%s</code> sebagai <b>%s</b> (role: %s).\nMode kirim diset ke <code>push</code>." % (
            esc(url),
            esc(info["name"]),
            esc(", ".join(info["roles"]) or "?"),
        )
    except Exception as exc:
        text = "Tersimpan, tapi koneksi <b>gagal</b>:\n<code>%s</code>" % esc(str(exc)[:400])
    try:
        await message.delete()
        text += "\nPesan berisi password sudah dihapus dari chat."
    except Exception:
        pass
    await message.chat.send_message(text, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW)


async def cmd_mode(update, context):
    value = " ".join(context.args or []).strip().lower()
    if value not in ("push", "xml", "both"):
        await reply(update.effective_message, "Pilih: <code>/mode push</code>, <code>/mode xml</code>, atau <code>/mode both</code>.")
        return
    settings_store.set_value("publish_mode", value)
    label = {
        "push": "bot upload gambar dan bikin draf langsung di WordPress",
        "xml": "bot kirim file XML dan zip untuk kamu import manual",
        "both": "push ke WordPress sekaligus kirim file XML",
    }[value]
    await reply(update.effective_message, "Mode kirim: <code>%s</code> (%s)." % (value, label))


async def cmd_wppost(update, context):
    value = " ".join(context.args or []).strip().lower()
    if value not in ("draft", "publish", "pending", "private"):
        await reply(update.effective_message, "Status valid: <code>draft</code>, <code>publish</code>, <code>pending</code>, <code>private</code>.")
        return
    settings_store.set_value("wp_status", value)
    warning = "\n\nAwas: artikel baru akan LANGSUNG tayang." if value == "publish" else ""
    await reply(update.effective_message, "Status awal artikel di WordPress: <code>%s</code>.%s" % (value, warning))


async def cmd_cancel(update, context):
    key = STATE.key(update)
    STATE.edit_target.pop(key, None)
    task = STATE.busy.get(key)
    if task and not task.done():
        task.cancel()
        STATE.busy.pop(key, None)
        await reply(update.effective_message, "Dibatalkan.")
    else:
        await reply(update.effective_message, "Tidak ada proses yang sedang jalan.")


async def cmd_artikel(update, context):
    video_id = utils_text.extract_video_id(" ".join(context.args or []))
    if not video_id:
        await reply(update.effective_message, "Tempel link YouTube setelah perintah.\nContoh: <code>/artikel https://youtu.be/dQw4w9WgXcQ</code>")
        return
    STATE.last_video[STATE.key(update)] = video_id
    rest = utils_text.URL_PATTERN.sub("", " ".join(context.args or [])).strip()
    if not start_task(update, create_article(update, "Menulis artikel dari video", video_id=video_id, caption=rest)):
        await busy_notice(update.effective_message)


async def cmd_transkrip(update, context):
    video_id = utils_text.extract_video_id(" ".join(context.args or []))
    if not video_id:
        await reply(update.effective_message, "Tempel link YouTube setelah perintah.")
        return
    STATE.last_video[STATE.key(update)] = video_id
    if not start_task(update, raw_job(update, video_id)):
        await busy_notice(update.effective_message)


async def cmd_draft(update, context):
    draft_id = current_draft_id(STATE.key(update))
    draft = drafts.load(draft_id) if draft_id else None
    if not draft:
        await reply(update.effective_message, "Belum ada draf. Kirim link YouTube, foto, atau catatan dulu.")
        return
    await send_card(update.effective_message, draft, "Draf terakhir")


async def cmd_revise(update, context):
    key = STATE.key(update)
    draft_id = current_draft_id(key)
    if not draft_id:
        await reply(update.effective_message, "Belum ada draf untuk direvisi.")
        return
    instruction = " ".join(context.args or []).strip()
    if not instruction:
        STATE.edit_target[key] = draft_id
        sent = await update.effective_message.reply_text(
            "Mode revisi aktif. Tulis apa yang mau diubah, atau kirim foto untuk ditambahkan. Ketik /selesai kalau sudah.",
            reply_markup=ForceReply(selective=True, input_field_placeholder="contoh: judulnya lebih santai"),
        )
        drafts.remember_message(draft_id, sent.chat_id, sent.message_id)
        return
    await start_revision(update, draft_id, instruction)


async def cmd_titles(update, context):
    await show_titles(update.effective_message, current_draft_id(STATE.key(update)))


async def cmd_done(update, context):
    had = STATE.edit_target.pop(STATE.key(update), None)
    await reply(update.effective_message, "Mode revisi ditutup." if had else "Mode revisi memang tidak aktif. Balas kartu draf kapan saja untuk revisi.")


async def cmd_search(update, context):
    keyword = " ".join(context.args or []).strip()
    video_id = STATE.last_video.get(STATE.key(update))
    if not keyword or not video_id:
        await reply(update.effective_message, "Pakai <code>/cari kata kunci</code> setelah bot memproses satu video.")
        return
    await update.effective_message.chat.send_action(ChatAction.TYPING)
    try:
        hits = await asyncio.to_thread(pipeline.lookup_timestamps, video_id, keyword)
    except Exception as exc:
        log.error("cari gagal: %s", exc)
        await reply(update.effective_message, "Pencarian gagal. %s" % public_error(str(exc)))
        return
    if not hits:
        await reply(update.effective_message, "Kata <b>%s</b> tidak ketemu di transkrip." % esc(keyword))
        return
    lines = ["<b>%s</b> muncul di:" % esc(keyword)]
    for start, text in hits[:12]:
        lines.append("• <code>%02d:%02d</code> %s" % (int(start) // 60, int(start) % 60, esc(text[:120])))
    await reply(update.effective_message, "\n".join(lines))


def guarded(handler):
    async def wrapper(update, context):
        if not await key_gate(update):
            return
        await react_user(update.effective_message)
        await handler(update, context)

    return wrapper


async def on_error(update, context):
    log.error("error: %s\n%s", context.error, "".join(traceback.format_exception(context.error)))
    try:
        if isinstance(update, Update) and update.effective_message:
            await reply(update.effective_message, public_error(str(context.error)))
    except Exception:
        pass


def build_application():
    app = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .concurrent_updates(True)
        .connect_timeout(20)
        .read_timeout(60)
        .write_timeout(60)
        .media_write_timeout(180)
        .build()
    )
    app.add_handler(CommandHandler(["start", "halo"], guarded(cmd_start)))
    app.add_handler(CommandHandler(["help", "bantuan"], guarded(cmd_help)))
    app.add_handler(CommandHandler("artikel", guarded(cmd_artikel)))
    app.add_handler(CommandHandler("transkrip", guarded(cmd_transkrip)))
    app.add_handler(CommandHandler(["draf", "draft"], guarded(cmd_draft)))
    app.add_handler(CommandHandler("revisi", guarded(cmd_revise)))
    app.add_handler(CommandHandler("judul", guarded(cmd_titles)))
    app.add_handler(CommandHandler("selesai", guarded(cmd_done)))
    app.add_handler(CommandHandler(["bahasa", "lang"], guarded(cmd_language)))
    app.add_handler(CommandHandler("proxy", guarded(cmd_proxy)))
    app.add_handler(CommandHandler("brief", guarded(cmd_brief)))
    app.add_handler(CommandHandler("frame", guarded(cmd_frame)))
    app.add_handler(CommandHandler(["base", "url"], guarded(cmd_base)))
    app.add_handler(CommandHandler("wp", guarded(cmd_wp)))
    app.add_handler(CommandHandler("mode", guarded(cmd_mode)))
    app.add_handler(CommandHandler(["wppost", "statusartikel"], guarded(cmd_wppost)))
    app.add_handler(CommandHandler("allow", guarded(cmd_allow)))
    app.add_handler(CommandHandler("kunci", guarded(cmd_key)))
    app.add_handler(CommandHandler("status", guarded(cmd_status)))
    app.add_handler(CommandHandler(["batal", "cancel"], guarded(cmd_cancel)))
    app.add_handler(CommandHandler("cari", guarded(cmd_search)))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^d:"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_error_handler(on_error)
    return app


def main():
    port = media_server.start()
    log.info("media server mendengarkan di port %d", port)
    log.info("kunci akses: %s", settings_store.app_key())
    app = build_application()
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
