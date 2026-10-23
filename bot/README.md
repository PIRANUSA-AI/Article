# Piranusa Bot: Generator Artikel WordPress dari Telegram

Bot Telegram untuk tim internal. Bahan yang bisa dikirim:

| Kirim ini | Hasilnya |
|---|---|
| Link YouTube | Artikel dari transkrip, cuplikan video terbaik ditaruh di isi, thumbnail jadi gambar utama |
| Link artikel dalam bahasa apa pun | Isi halaman diekstrak, ditulis ulang dalam bahasa Indonesia sesuai konteks Piranusa, sumber tetap dicantumkan |
| Link Instagram | Post foto, carousel, reel, atau story spesifik yang masih dapat diakses dibaca sebagai bahan artikel |
| Satu foto atau album | Qwen membaca isi foto lalu menulis artikel, foto terbaik jadi gambar utama |
| Foto dengan link YouTube di caption | Artikel dari video, fotomu jadi gambar utama |
| Teks panjang (catatan, poin rapat, rilis) | Artikel dari teks itu |
| Foto sebagai balasan kartu draf | Foto ditambahkan ke bagian artikel yang paling cocok |
| Link YouTube video testimoni | Masuk modul Testimoni WordPress (bukan artikel) sebagai draf, homepage mati |
| `/testimoni link atau teks` | Membuat draf testimoni dari ucapan, tulisan yang terbaca, atau pengalaman pelanggan yang dikirim user |

### Video dengan transkrip minim

Transkrip dinilai dari jumlah kata, keragaman kata, cakupan waktu, dan durasi video. Subtitle `[musik]`, repetisi, atau satu kata seperti `halo` untuk video 10 menit belum dianggap memadai. Bot tetap mencoba backend subtitle dan Deepgram sebelum memakai visual. Jika semua transkrip tidak tersedia, visual dipakai sebagai pengamatan, bukan dianggap bukti bahwa videonya bisu.

Saat transkrip tidak memadai, video diunduh satu kali dan ffmpeg mengambil frame dalam satu lintasan. Video hingga 90 detik diambil tiap 1 detik; video lebih panjang tiap 10 detik. Interval diperbesar untuk menjaga batas `VISION_MAX_FRAMES` (default 120). Frame disusun berurutan dalam contact sheet berisi maksimal 12 sel dengan waktu. Setiap chunk dibaca dengan konteks catatan sebelumnya. Semua catatan digunakan untuk menulis, sedangkan maksimal 6 frame penting dipilih sebagai kandidat gambar. Video dengan percakapan memadai tetap memakai alur transkrip biasa.

Testimoni visual hanya menggunakan pengalaman pelanggan yang terbaca dari tulisan atau diberikan eksplisit oleh user. Demo, ekspresi wajah, dan aktivitas bukan bukti kepuasan atau hasil bisnis. Jika bukti tidak cukup, bot meminta bahan tambahan.

### Instagram dan teks

Kirim link `instagram.com/p/...`, `/reel/...`, atau `/stories/username/id/...`. Cookie `YTDLP_COOKIES` digunakan untuk akses story atau media yang memerlukan akun berizin. Story kedaluwarsa dan media tanpa akses menghasilkan pesan kegagalan yang jelas. Dukungan ekstraksi mengikuti kemampuan yt-dlp dan dapat dipengaruhi perubahan Instagram. Audio reel menggunakan Deepgram jika `DEEPGRAM_API_KEY` tersedia; jika transkrip tidak memadai, bot membaca urutan visual. Foto dan carousel dibaca oleh Qwen vision. Batas satu kiriman adalah 12 media; anggaran frame dibagi di antara video dalam kiriman.

Teks panjang dapat langsung dikirim. Untuk teks singkat atau agar pasti membuat artikel baru, gunakan `/artikel teks kamu`. Untuk testimoni dari teks gunakan `/testimoni pengalaman pelanggan beserta nama perusahaan`.

### Thumbnail Qwen acak

Artikel baru tanpa foto kiriman mendapat satu thumbnail dari API Qwen dengan gaya acak dari delapan arah visual yang disetujui: thumbnail YouTube heboh, editorial surealis, fotografi dokumenter, sketsa arsitektur liar, poster tipografi brutalist, pabrik mini 3D, origami sinematik, dan papercut. Komik, anime, dan cyberpunk tidak dipakai. Konsep dan komposisi disusun sesuai isi artikel, bukan hanya mengganti filter pada adegan yang sama.

Tekan **Regenerate thumbnail** bila hasil kurang cocok. Setiap klik membuat satu gambar baru, memakai gaya yang berbeda dari hasil terakhir, dan memasangnya sebagai gambar utama. Gambar lama tetap tersedia di **Gambar utama** dan dapat dikembalikan lewat **Batalkan perubahan terakhir**. Jika API gagal, thumbnail lama tetap dipakai. Foto kiriman user tetap diprioritaskan saat artikel pertama dibuat. Regenerasi ikut memperbarui WordPress melalui pemeriksaan konflik yang sama seperti perubahan draf lain.

Konfigurasi `QWEN_IMAGE_MODEL`, `QWEN_IMAGE_URL`, dan `QWEN_IMAGE_SIZE` ada di `.env.example`. Endpoint gambar harus cocok dengan region/workspace dan izin key. Format request mengikuti [dokumentasi resmi Qwen Image](https://www.alibabacloud.com/help/en/model-studio/qwen-image-api). Model chat/vision tidak menghasilkan file gambar lewat chat completion.

## Susunan artikel

1. Judul, dipilih dari lima nada: Edukatif, Penasaran, Waspada, Kontras, Emosi terbalik. Judul yang terlalu mirip judul YouTube otomatis dibuang.
2. Subjudul, satu per opsi judul.
3. Ringkasan (paragraf plus poin kunci), lalu embed video kalau sumbernya YouTube.
4. Isi dengan bentuk bebas: paragraf, langkah bernomor, daftar, kutipan, catatan tips. Paling banyak 2 gambar di isi, ditaruh di bagian yang cocok.
5. Kesimpulan.
6. Kartu CTA WhatsApp: judul pendek dan teks tombol diacak per artikel, kalimat ajakan ditulis AI maksimal 18 kata, link pendek SIPIRA dengan kode acak 7 karakter.
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
../.venv/Scripts/python.exe test_sources.py
../.venv/Scripts/python.exe bot_app.py
```

Butuh `ffmpeg` di PATH.

## Deploy ke VPS (Docker)

Repo ini memakai runner khusus `artikel-vps` untuk deployment `/var/www/artikel`. Workflow `.github/workflows/deploy.yml` berjalan pada push ke `main` yang mengubah kode bot/deployment, atau lewat `workflow_dispatch`. Runner berjalan sebagai user `artikel-runner`; perintah deployment terbatas pada `/usr/local/sbin/deploy-article`.

Deployment hanya melakukan fast forward dari `origin/main`, menjaga `.env` dan folder data, membangun image Docker, lalu menjalankan dua suite tes offline sebelum container diperbarui. Suite tes memakai direktori data sementara. Tidak ada sinkronisasi balik draf atau credential ke GitHub. Jika build atau tes gagal, container lama tetap berjalan. Perubahan manual pada file kode yang dilacak Git akan menghentikan deployment agar tidak tertimpa.

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
| `/artikel link atau teks` | Artikel dari YouTube, artikel web, Instagram, atau teks |
| `/testimoni link atau teks` | Testimoni dari pengalaman pelanggan yang tersedia di sumber |
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
| `/youtube` | Cek video channel yang belum jadi artikel atau testimoni |
| `/models`, `/status`, `/batal`, `/help` | Info dan kontrol |

## Catatan

1. `piranusa.com` ada di belakang Cloudflare yang membuang header Authorization, jadi bot login lewat cookie plus nonce REST.
2. SEO Yoast (focus keyphrase, meta description, SEO title, kategori utama) diisi lewat form metabox editor memakai sesi login bot, karena Yoast tidak membuka field itu di REST. Setelah artikel ditulis, ada langkah SEO yang memastikan kata kunci ada di subjudul, judul bagian, dan isi, plus 2 link internal dari artikel yang sudah tayang dan 1 link keluar.
3. Kelas CSS `pipSubtitle`, `pipSummary`, dan `pipCallout` sudah terpasang di blok. Kartu CTA (`pipCtaCard`) membawa gayanya sendiri di blok HTML.
4. Testimoni: AI mengecek tiap video. Kalau testimoni, bot menyusun perusahaan, pembicara, jabatan, kutipan, dan produk, lalu membuat post `testimoni` berstatus draf. Field ACF diisi lewat form editor klasik. Kalau nama perusahaan tidak disebut di video, tulis namanya bersama link. Tombol Bukan testimoni menulis ulang sebagai artikel.
5. Pengingat YouTube: bot membandingkan channel `YOUTUBE_CHANNEL_URL` dengan artikel dan testimoni di WordPress. Video lama diingatkan Senin, Rabu, Jumat (3 video per pesan), video baru tiap 2 hari, jam 09.00 WIB, ke semua user bot. Tombol Buat langsung memproses linknya, Lewati menghentikan pengingat untuk video itu.
