# Piranusa Bot: Generator Artikel WordPress dari Telegram

Bot Telegram untuk tim internal. Bahan yang bisa dikirim:

| Kirim ini | Hasilnya |
|---|---|
| Link YouTube | Artikel dari transkrip, cuplikan video terbaik ditaruh di isi, thumbnail jadi gambar utama |
| Satu foto atau album | Qwen membaca isi foto lalu menulis artikel, foto terbaik jadi gambar utama |
| Foto dengan link YouTube di caption | Artikel dari video, fotomu jadi gambar utama |
| Teks panjang (catatan, poin rapat, rilis) | Artikel dari teks itu |
| Foto sebagai balasan kartu draf | Foto ditambahkan ke bagian artikel yang paling cocok |

## Susunan artikel

1. Judul, dipilih dari lima nada: Edukatif, Penasaran, Waspada, Kontras, Emosi terbalik. Judul yang terlalu mirip judul YouTube otomatis dibuang.
2. Subjudul, satu per opsi judul.
3. Ringkasan (paragraf plus poin kunci), lalu embed video kalau sumbernya YouTube.
4. Isi dengan bentuk bebas: paragraf, langkah bernomor, daftar, kutipan, catatan tips. Paling banyak 2 gambar di isi, ditaruh di bagian yang cocok.
5. Kesimpulan.
6. CTA yang mengarahkan ke ikon WhatsApp (tombol menyusul).
7. Glosarium, hanya kalau videonya memuat istilah teknis.

Semua teks lewat `humanizer.py`: panduan `prompts/humanizer.md` dipakai sebagai aturan gaya penulis, lalu kode membuang em dash, en dash, tanda hubung, titik koma, emoji, kutip melengkung, dan timestamp. Kalau masih banyak frasa khas AI, bagian itu ditulis ulang otomatis.

## Di Telegram setelah draf jadi

Kartu draf punya tombol:

| Tombol | Guna |
|---|---|
| Edit di WordPress, Pratinjau | Link langsung ke wp admin dan preview |
| Pilih judul | Lima opsi judul, ganti dengan satu klik, WordPress ikut diperbarui |
| Lihat isi | Isi artikel dikirim ke chat, balas pesannya untuk revisi |
| Revisi lewat chat | Mode revisi, tiap pesan jadi permintaan revisi sampai `/selesai` |
| Gambar utama | Pilih sampul dari thumbnail, cuplikan, atau foto kiriman |
| Publish, Tarik jadi draf | Ubah status di WordPress (publish minta konfirmasi) |
| File XML | Paket WXR plus zip gambar dan Markdown |
| Batalkan perubahan terakhir | Undo sampai 6 langkah |

Kalau artikel sudah diedit manual di WordPress, bot tidak menimpa diam diam. Bot memberi tahu dan menyediakan tombol timpa.

## Model

| Tugas | Default |
|---|---|
| Menulis dan revisi | `qwen3.8-max`, cadangan `qwen3.8-flash`, `qwen3.7-max`, `qwen-plus` |
| Router niat dan perapian gaya | `qwen3.8-flash` |
| Membaca gambar | `qwen3.8-max`, cadangan `qwen3.8-flash`, `qwen3-vl-plus` |

Mode berpikir Qwen hanya dinyalakan untuk penulisan utama (`QWEN_WRITE_THINKING`, default 3000 token). Tugas lain mematikannya supaya cepat.

## Isi folder

| File | Fungsi |
|---|---|
| `bot_app.py` | Handler Telegram: pesan, foto, album, tombol, perintah |
| `telegram_view.py` | Teks kartu draf, keyboard, pratinjau isi |
| `pipeline.py` | Alur video, foto, teks, dan operasi draf (revisi, judul, gambar, undo) |
| `article_generator.py` | Prompt penulis, lima nada judul, revisi, perapian gaya |
| `image_picker.py` | Saring frame gelap dan kembar, penilaian gambar oleh Qwen, pemilihan sampul |
| `humanizer.py`, `prompts/humanizer.md` | Aturan gaya dan pembersih karakter |
| `drafts.py` | Penyimpanan draf di `data/drafts` dan peta pesan ke draf |
| `wxr_builder.py` | Render blok Gutenberg dan file WXR |
| `wordpress_push.py` | Login cookie, upload media, buat dan perbarui post, status |
| `qwen_client.py` | Klien Qwen teks dan gambar |
| `transcript_source.py`, `video_source.py` | Transkrip dan cuplikan YouTube |
| `selftest.py` | Tes offline tanpa API |

## Jalanin lokal (Windows)

```bash
cd bot
python -m venv ../.venv
../.venv/Scripts/python.exe -m pip install -r requirements.txt
../.venv/Scripts/python.exe selftest.py
../.venv/Scripts/python.exe bot_app.py
```

Butuh `ffmpeg` di PATH.

## Deploy ke VPS (Docker)

```bash
cd /opt/piranusa-bot/bot
cp .env.example .env
docker compose up -d --build
docker compose logs -f
```

## Deploy ke VPS (systemd)

```bash
sudo apt update && sudo apt install -y ffmpeg python3-venv
cd /opt/piranusa-bot/bot
python3 -m venv /opt/piranusa-bot/.venv
/opt/piranusa-bot/.venv/bin/pip install -r requirements.txt
sudo cp piranusa-bot.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now piranusa-bot
```

## Perintah

| Perintah | Guna |
|---|---|
| `/artikel link` | Artikel dari video |
| `/transkrip link` | Teks transkrip saja |
| `/draf` | Kartu draf terakhir |
| `/revisi permintaan` | Revisi draf terakhir |
| `/judul` | Pilihan judul draf terakhir |
| `/selesai` | Tutup mode revisi |
| `/cari kata` | Menit kemunculan kata di video terakhir |
| `/bahasa id en` | Prioritas bahasa subtitle |
| `/frame 3:20` | Cuplikan di menit itu ikut ditawarkan untuk isi |
| `/brief arahan` | Gaya untuk artikel berikutnya (`/brief off` untuk hapus) |
| `/proxy url` | Proxy kalau IP diblokir YouTube |
| `/base url` | URL publik bot untuk mode XML |
| `/wp url user password` | Sambungkan WordPress, pesan berisi password dihapus otomatis |
| `/mode push`, `xml`, `both` | Cara kirim hasil |
| `/wppost draft` atau `publish` | Status awal artikel |
| `/models`, `/status`, `/batal`, `/help` | Info dan kontrol |

## Catatan

1. `piranusa.com` ada di belakang Cloudflare yang membuang header Authorization, jadi bot login lewat cookie plus nonce REST.
2. SEO Yoast (focus keyphrase, meta description, SEO title, kategori utama) diisi lewat form metabox editor memakai sesi login bot, karena Yoast tidak membuka field itu di REST. Setelah artikel ditulis, ada langkah SEO yang memastikan kata kunci ada di subjudul, judul bagian, dan isi, plus 2 link internal dari artikel yang sudah tayang dan 1 link keluar.
3. Kelas CSS `pipSubtitle`, `pipSummary`, `pipCallout`, dan `pipCta` sudah terpasang di blok, tinggal diberi gaya di tema kalau mau tampil beda.
