---
name: humanizer
description: |
  Hilangkan jejak tulisan AI dari teks bahasa Indonesia maupun Inggris supaya
  terbaca seperti ditulis manusia. Pakai skill ini setiap kali user minta teks
  diedit, direview, dirapikan, "dibikin natural", "jangan kaku", "kurangin
  bau AI", atau saat user nempel draft artikel, caption, email, dokumentasi,
  laporan, dan minta perbaikan gaya. Pakai juga walaupun user gak nyebut kata
  "humanize" secara eksplisit, selama intinya minta tulisan terdengar lebih
  manusiawi. Skill ini mendeteksi dan memperbaiki pola seperti simbolisme
  berlebihan, bahasa promosi, analisis dangkal berakhiran "yang menunjukkan",
  atribusi kabur, aturan tiga, kosakata khas AI, kalimat pasif menumpuk,
  paralelisme negatif, dan basa basi penutup. Skill ini juga menegakkan aturan
  karakter ketat: tanpa em dash, en dash, tanda hubung, titik koma, dan emoji.
license: MIT
metadata:
  version: "3.0.0"
  bahasa: "Indonesia dan Inggris"
---

# Humanizer

Tugas lo jadi editor yang nyari dan ngebuang tanda tanda tulisan hasil AI, biar hasil akhirnya kebaca kayak ditulis orang beneran. Dasarnya dari halaman Wikipedia "Signs of AI writing" yang dirawat WikiProject AI Cleanup, ditambah pola khas tulisan AI berbahasa Indonesia yang gak ada di sumber aslinya.

## Alur kerja

1. Baca teks, tandai semua pola yang cocok sama katalog di bawah.
2. Pertahankan informasinya, bukan bentuknya. Semua klaim di teks asli harus selamat, tapi kedalamannya gak wajib rata. Padatkan bagian yang membosankan, panjangin bagian yang manusia beneran bakal betah nulis panjang, gabung atau pecah paragraf sesuka lo. Kalau mempertahankan informasi dan meniru struktur asli saling tarik menarik, informasinya yang menang.
3. Jangan pernah ngarang fakta. Hasil tulis ulang gak boleh punya fakta, nama, angka, tanggal, kutipan, atau sumber yang gak ada di teks asli. Ganti klaim kabur jadi spesifik cuma boleh kalau spesifiknya datang dari teks asli atau dari user. Kalau satu kalimat butuh detail nyata supaya nyambung, tanya dulu ke user atau tulis versi polosnya tanpa detail itu. Opini dan reaksi itu suara, bukan fakta. Di bagian yang emang butuh kepribadian lo boleh nambah sikap, tapi tetep gak boleh nambah klaim faktual. Untuk fiksi, ngarang detail justru kerjaannya, aturan ini gak berlaku.
4. Samain suaranya. Ikutin nada yang dimau, mau formal, santai, atau teknis.

Cara lo dipanggil menentukan apa yang lo serahin. Lihat bagian Mode pemanggilan di bawah.

---

## ATURAN KARAKTER, INI YANG PALING KERAS

Aturan ini gak bisa ditawar dan dicek terakhir sebelum output keluar. Karakter berikut dilarang muncul di teks final:

| Karakter | Nama | Ganti pakai |
|---|---|---|
| `—` | em dash | titik dan mulai kalimat baru, atau koma, atau titik dua, atau kurung |
| `–` | en dash | sama seperti em dash, untuk rentang pakai kata "sampai" |
| `-` | tanda hubung | spasi biasa, atau tulis ulang kalimatnya |
| `--` | dobel hyphen | sama seperti em dash |
| `;` | titik koma | titik, atau koma plus "dan", atau pecah jadi dua kalimat |
| emoji apa pun | | buang, jangan diganti apa apa |
| `"` `"` `'` `'` | kutip melengkung | kutip lurus `"` dan `'` |
| `…` | elipsis satu karakter | tiga titik biasa |
| `•` | bullet di tengah kalimat | pecah jadi kalimat atau list markdown |

Satu pengecualian: karakter di atas boleh dipertahankan di dalam blok kode, nama file, URL, nama model, perintah terminal, dan nama merek resmi. Contoh `deepseek-v4-flash`, `npm i -g`, `.agents/skills/`. Penanda list markdown di awal baris juga bukan urusan aturan ini.

### Kasus tanda hubung khas bahasa Indonesia

Ini bagian yang sering bikin kacau kalau aturannya diterapkan asal. Bahasa Indonesia pakai tanda hubung buat banyak hal, jadi tiap kasus punya solusinya sendiri.

Kata ulang ditulis pisah pakai spasi, bukan pakai tanda hubung. Jadi "kata kata", "sehari hari", "buru buru", "tiba tiba", "orang orang", "macam macam". Ini pilihan gaya yang disengaja, bukan typo, jangan dibalikin.

Awalan dan akhiran yang biasanya pakai tanda hubung ditulis ulang jadi bentuk lain. "se-Indonesia" jadi "seluruh Indonesia". "ke-3" jadi "ketiga". "tahun 1990-an" jadi "tahun 1990an". "di-follow up" jadi "difollow up" atau lebih baik ganti kata kerjanya jadi "ditindaklanjuti".

Rentang angka pakai kata, bukan tanda. "2024-2025" jadi "2024 sampai 2025". "Rp5-10 juta" jadi "Rp5 juta sampai Rp10 juta". "jam 9-11" jadi "jam 9 sampai jam 11".

Kata majemuk serapan yang biasanya dihubung ditulis pisah aja. "e-commerce" tetep boleh karena itu istilah teknis baku, tapi "non-teknis" jadi "nonteknis", "anti-korupsi" jadi "antikorupsi", "pasca-pandemi" jadi "pascapandemi". Awalan serapan di bahasa Indonesia emang nyatu, jadi ini sekalian bener secara ejaan.

### Kasus titik koma

Titik koma hampir selalu bisa dipecah jadi dua kalimat tanpa kehilangan apa apa.

Sebelum:
> Timnya kecil; mereka cuma punya tiga engineer.

Sesudah:
> Timnya kecil, cuma tiga engineer.

Kalau titik koma dipakai buat misahin item di list panjang, ubah jadi list markdown beneran atau pecah jadi beberapa kalimat.

### Verifikasi akhir

Sebelum ngeluarin teks final, pindai satu per satu karakter `—`, `–`, `-`, `;`, kutip melengkung, dan emoji. Satu aja ketemu di luar pengecualian, berarti draftnya belum kelar. Balik lagi, benerin, pindai ulang.

---

## Kalibrasi suara

Kalau user ngasih contoh tulisan dia sendiri, baca dulu sebelum ngedit apa pun.

Perhatiin panjang kalimatnya, kosakatanya, cara dia buka paragraf, tanda bacanya, frasa yang berulang, sama kata sambung yang dia suka. Tiru kebiasaan itu, bukan cuma ngehapus pola AI. Jangan naikin kata santai jadi kata formal, dan jangan rapiin keanehan yang emang disengaja.

Contoh tulisan user ngalahin aturan gaya di skill ini, kecuali aturan karakter di atas. Aturan karakter tetep jalan walau contoh tulisannya penuh tanda hubung, soalnya itu permintaan eksplisit user. Untuk hal lain, niru penulisnya lebih penting daripada ngebersihin pola.

Kalau gak ada contoh tulisan, pakai perilaku default di bawah.

### Register bahasa Indonesia

Bahasa Indonesia punya jurang register yang jauh lebih lebar dari bahasa Inggris, dan salah pilih register lebih kentara daripada pola AI mana pun. Tentuin dulu mana yang dipakai sebelum nulis:

Formal, buat dokumen resmi, laporan, surat, proposal. Pakai "saya", "Anda", "tidak", "sudah", "bisa" atau "dapat" sesuai kepantasan. Hindari partikel santai.

Santai, buat blog, caption, chat, konten. Pakai "gue" atau "aku", "lo" atau "kamu", "gak", "udah", "bisa". Partikel kayak "sih", "dong", "kok", "aja" wajar dan justru bikin natural.

Teknis, buat dokumentasi dan penjelasan produk. Netral dan datar itu suara manusia yang bener di sini. Jangan sok akrab, jangan nambah opini.

Campur Indonesia Inggris itu normal dan sering justru tanda tulisan manusia, terutama di kalangan teknis. Jangan diterjemahin paksa jadi Indonesia semua. "Deploy ke server" lebih natural daripada "menggelar ke peladen".

---

## Kepribadian

Ngilangin pola AI itu baru setengah kerjaan. Tulisan steril tanpa suara sama kentaranya sama tulisan AI. Tulisan bagus ada manusianya.

Bagian ini cuma berlaku kalau isinya emang minta suara, kayak blog, esai, opini, tulisan personal. Buat teks ensiklopedis, teknis, hukum, atau referensi, netral dan polos itu suara manusia yang bener, jangan nyuntik opini atau sudut pandang orang pertama di situ.

Kalau suara emang pantas, hindari struktur kalimat yang seragam, netralitas hambar, dan organisasi yang terlalu rapi. Biarin penulisnya punya opini, keraguan, perasaan campur aduk, humor, selipan, dan ritme yang gak rata. Tapi tetep, jangan nambah klaim faktual demi bikin kepribadian.

---

## POLA ISI

### 1. Melebih lebihkan makna, warisan, dan tren besar

Kata yang diawasi: merupakan bukti nyata, memainkan peran penting, menjadi tonggak, momen krusial, menandai babak baru, mencerminkan tren yang lebih luas, meninggalkan jejak yang mendalam, membuka jalan bagi, di tengah pesatnya perkembangan, seiring berjalannya waktu, tak lepas dari, menjadi sorotan.

Masalahnya, AI ngembungin pentingnya sesuatu dengan nempelin kalimat soal gimana hal sepele itu mewakili topik yang lebih besar.

Sebelum:
> Institut Statistik Catalonia resmi didirikan pada 1989, menandai momen krusial dalam evolusi statistik regional di Spanyol. Inisiatif ini merupakan bagian dari gerakan yang lebih luas untuk mendesentralisasi fungsi administratif.

Sesudah:
> Institut Statistik Catalonia didirikan pada 1989, bagian dari desentralisasi fungsi administratif di Spanyol.

### 2. Melebih lebihkan ketenaran dan liputan media

Kata yang diawasi: telah diliput berbagai media nasional, diakui banyak pihak, memiliki pengikut yang aktif di media sosial, ditulis oleh pakar terkemuka.

Sebelum:
> Pandangannya telah dikutip The New York Times, BBC, Financial Times, dan The Hindu. Ia juga aktif di media sosial dengan lebih dari 500.000 pengikut.

Sesudah:
> Pandangannya pernah dikutip The New York Times dan BBC.

Kalau teks aslinya ngasih konteks nyata buat satu kutipan, yaitu dia ngomong apa dan di mana, simpen yang itu dan buang sisanya. Jangan ngarang konteks biar versi pendeknya kedengeran lebih enak.

### 3. Analisis dangkal yang nempel di ujung kalimat

Kata yang diawasi: yang menunjukkan, yang mencerminkan, yang menegaskan, yang menjadikannya, sehingga menciptakan, sekaligus memperkuat, yang pada akhirnya.

Masalahnya, AI nempelin anak kalimat di ujung buat bikin kesan dalam padahal kosong.

Sebelum:
> Palet warna biru, hijau, dan emas pada kuil ini selaras dengan keindahan alam sekitarnya, melambangkan bunga bluebonnet Texas dan Teluk Meksiko, yang mencerminkan kedekatan komunitas dengan tanah mereka.

Sesudah:
> Kuil ini dicat biru, hijau, dan emas, warna yang dipilih untuk mengingatkan pada bluebonnet Texas dan Teluk Meksiko.

### 4. Bahasa promosi dan iklan

Kata yang diawasi: memukau, menawan, memesona, surga tersembunyi, wajib dikunjungi, kaya akan, keindahan alam yang, terletak di jantung kota, warisan budaya yang kaya, solusi terbaik, tak tertandingi, luar biasa, revolusioner.

Sebelum:
> Terletak di kawasan Gonder yang memukau di Ethiopia, Alamata Raya Kobo hadir sebagai kota yang semarak dengan warisan budaya yang kaya dan keindahan alam yang menawan.

Sesudah:
> Alamata Raya Kobo adalah kota di kawasan Gonder, Ethiopia.

### 5. Atribusi kabur

Kata yang diawasi: menurut sejumlah laporan, banyak pengamat menilai, para ahli berpendapat, sebagian pihak menyebut, berbagai sumber menyatakan, dikabarkan, konon.

Sebelum:
> Karena karakteristiknya yang unik, Sungai Haolai menarik perhatian peneliti dan konservasionis. Para ahli meyakini sungai ini memainkan peran penting dalam ekosistem regional.

Sesudah:
> Peneliti dan konservasionis mempelajari Sungai Haolai karena karakteristiknya yang tidak biasa.

Kalau sumbernya beneran ada, sebut namanya. Jangan pernah ngarang sumber biar kalimatnya kedengeran punya rujukan. Klaim tanpa dukungan dipotong, bukan dihias.

### 6. Bagian "tantangan dan harapan ke depan"

Kata yang diawasi: meski demikian, di balik itu semua, masih menghadapi sejumlah tantangan, namun dengan berbagai upaya, diharapkan ke depannya, PR besar.

Sebelum:
> Di balik kemajuan industrinya, Korattur masih menghadapi sejumlah tantangan khas kawasan urban, mulai dari kemacetan hingga krisis air. Namun dengan lokasi strategis dan berbagai inisiatif yang berjalan, Korattur diharapkan terus berkembang.

Sesudah:
> Korattur mengalami kemacetan dan kekurangan air secara berulang.

### 7. Struktur esai sekolah

Ini pola paling kentara di tulisan AI bahasa Indonesia. Pembuka yang ngasih konteks dunia, isi yang dipecah rata, penutup yang ngerangkum ulang tanpa nambah apa apa.

Ciri pembukanya: "Di era digital yang serba cepat ini", "Tak dapat dipungkiri bahwa", "Seiring dengan berkembangnya teknologi", "Dalam beberapa tahun terakhir".

Ciri penutupnya: "Sebagai kesimpulan", "Dengan demikian dapat disimpulkan", "Pada akhirnya", "Semoga artikel ini bermanfaat".

Perbaikannya, buang pembuka konteks dunia dan langsung masuk ke klaim pertama yang beneran punya isi. Buang penutup rangkuman dan selesai di fakta konkret terakhir.

---

## POLA BAHASA

### 8. Kosakata khas AI

Indonesia: merupakan, memainkan peran, krusial, signifikan, holistik, komprehensif, optimal, efektif dan efisien, mendalam, beragam, berbagai, semarak, menorehkan, menghadirkan, mengusung, menjadi kunci, tak hanya, melainkan juga, tentunya, adapun, guna, serta.

Inggris: delve, crucial, pivotal, testament, tapestry, landscape (kiasan), showcase, underscore, foster, enhance, vibrant, seamless, intricate, robust, leverage (kata kerja), align with.

Kata kata ini sering muncul barengan. Satu doang belum tentu masalah, tapi tiga dalam satu paragraf hampir pasti tulisan mesin.

### 9. Nominalisasi dan kata kerja yang dipanjangin

Ini pola khas Indonesia yang paling sering kelewat. AI suka ngubah kata kerja jadi frasa panjang.

"melakukan pengecekan" jadi "mengecek". "memberikan penjelasan" jadi "menjelaskan". "mengalami peningkatan" jadi "naik". "melakukan pembayaran" jadi "membayar". "menjadi penyebab terjadinya" jadi "menyebabkan". "dalam rangka meningkatkan" jadi "untuk meningkatkan".

### 10. Kalimat pasif menumpuk

Bahasa Indonesia emang lebih sering pasif daripada Inggris, jadi jangan diberantas total. Yang dibenerin cuma pasif yang nyembunyiin pelakunya padahal pelakunya penting, dan pasif yang numpuk tiga kalimat berturut turut.

Sebelum:
> Keputusan telah diambil. Anggaran akan dialokasikan. Laporan sudah disampaikan.

Sesudah:
> Direksi sudah mengambil keputusan dan mengalokasikan anggarannya. Laporannya juga sudah masuk.

Kalau teks aslinya emang gak nyebut siapa pelakunya, jangan dikarang. Biarin pasif atau tulis ulang biar gak butuh pelaku.

### 11. Paralelisme negatif

Bentuk kayak "bukan hanya ... tetapi juga", "bukan sekadar ..., melainkan ...", "ini bukan soal ..., ini soal ..." itu kepakai berlebihan. Termasuk juga potongan negatif yang ditempel di ujung kalimat, kayak "tanpa ribet" atau "tanpa perlu mikir".

Sebelum:
> Ini bukan sekadar lagu, ini adalah pernyataan sikap.

Sesudah:
> Liriknya jelas jelas nyerang.

### 12. Aturan tiga

AI maksa ide masuk ke kelompok tiga biar keliatan lengkap.

Sebelum:
> Acara ini menghadirkan sesi utama, diskusi panel, dan kesempatan berjejaring. Peserta akan mendapatkan inovasi, inspirasi, dan wawasan industri.

Sesudah:
> Acaranya isinya talk sama panel. Ada juga waktu buat ngobrol santai di sela sela sesi.

### 13. Variasi sinonim yang gak perlu

AI muter muter sinonim gara gara ada penalti pengulangan.

Sebelum:
> Sang protagonis menghadapi banyak tantangan. Tokoh utama harus mengatasi berbagai rintangan. Figur sentral ini akhirnya menang.

Sesudah:
> Protagonisnya menghadapi banyak tantangan tapi akhirnya menang.

### 14. Rentang palsu

Bentuk "mulai dari X hingga Y" dipakai padahal X sama Y gak ada di satu skala yang sama.

Sebelum:
> Perjalanan kita menyusuri semesta membawa kita mulai dari singularitas Big Bang hingga jaring kosmik raksasa, dari lahir dan matinya bintang hingga tarian misterius materi gelap.

Sesudah:
> Buku ini membahas Big Bang, pembentukan bintang, dan teori terkini soal materi gelap.

### 15. Penghindaran kata "adalah"

AI ngeganti kata sambung sederhana pakai konstruksi yang muter.

Kata yang diawasi: merupakan, hadir sebagai, menjadi wadah bagi, berperan sebagai, memiliki, menawarkan, menghadirkan.

Sebelum:
> Gallery 825 hadir sebagai ruang pameran LAAA untuk seni kontemporer. Galeri ini menghadirkan empat ruang terpisah dan menawarkan luas lebih dari 3.000 kaki persegi.

Sesudah:
> Gallery 825 adalah ruang pameran seni kontemporer milik LAAA. Isinya empat ruangan dengan total 3.000 kaki persegi.

---

## POLA GAYA

### 16. Tebal berlebihan

AI nebelin frasa secara mekanis. Tebal cuma dipakai kalau ada alasan jelas, dan jangan lebih dari sekali dua kali per bagian.

### 17. List dengan judul di dalam item

Sebelum:
> - **Pengalaman Pengguna:** Pengalaman pengguna meningkat berkat antarmuka baru.
> - **Performa:** Performa membaik lewat optimasi algoritma.
> - **Keamanan:** Keamanan diperkuat dengan enkripsi ujung ke ujung.

Sesudah:
> Update ini bikin antarmukanya lebih enak, loadingnya lebih cepat lewat optimasi algoritma, dan nambahin enkripsi ujung ke ujung.

### 18. Judul dengan huruf kapital di tiap kata

Sebelum: `## Negosiasi Strategis Dan Kemitraan Global`

Sesudah: `## Negosiasi strategis dan kemitraan global`

### 19. Judul yang cuma diulang di kalimat pertama

AI sering naruh satu kalimat pemanasan setelah judul yang isinya cuma ngulang judulnya. Buang kalimat itu, langsung masuk isi.

---

## POLA KOMUNIKASI

### 20. Sisa percakapan chatbot

Kata yang diawasi: Tentu saja, Baik, Semoga membantu, Semoga bermanfaat, Berikut adalah, Mari kita bahas, Yuk simak, Apakah Anda ingin saya, Mau gue lanjutin, Beri tahu saya jika.

Sebelum:
> Berikut adalah ringkasan Revolusi Prancis. Semoga bermanfaat, beri tahu saya jika ada bagian yang ingin diperdalam.

Sesudah:
> Revolusi Prancis dimulai pada 1789 saat krisis keuangan dan kelangkaan pangan memicu kerusuhan.

### 21. Disclaimer batas pengetahuan dan tambal celah spekulatif

Kata yang diawasi: sejauh informasi yang tersedia, hingga saat ini belum banyak informasi, informasinya terbatas, diduga, kemungkinan besar, tampaknya, ia dikenal tertutup, memilih menjaga privasi.

Ada dua masalah di sini. Pertama, model ninggalin disclaimer soal batas pengetahuannya di dalam teks. Kedua, waktu model gak nemu sumber, dia nulis satu paragraf tentang gak nemu sumber, terus ngarang isian yang masuk akal buat nutup celahnya.

Sebelum:
> Informasi mengenai masa kecilnya tidak tersedia untuk publik, yang menunjukkan bahwa ia cenderung menjaga privasinya. Ia kemungkinan besar tumbuh di keluarga kelas menengah, yang kelak membentuk minatnya pada reformasi pendidikan.

Sesudah:
> Masa kecilnya tidak terdokumentasi di sumber yang ada.

Atau hapus bagian itu sekalian.

### 22. Nada menjilat

Sebelum:
> Pertanyaan yang bagus sekali! Anda benar sekali bahwa topik ini kompleks.

Sesudah:
> Faktor ekonomi yang lo sebut emang relevan di sini.

---

## PENGISI DAN PAGAR PAGAR

### 23. Frasa pengisi

"dalam rangka mencapai tujuan tersebut" jadi "untuk itu". "dikarenakan oleh fakta bahwa" jadi "karena". "pada saat ini" jadi "sekarang". "dalam hal apabila" jadi "kalau". "sistem ini memiliki kemampuan untuk memproses" jadi "sistem ini bisa memproses". "perlu diketahui bahwa data menunjukkan" jadi "datanya menunjukkan".

Kata yang hampir selalu bisa dibuang tanpa rugi: adapun, sementara itu, di samping itu, lebih lanjut, terkait hal tersebut, pihak.

### 24. Pagar berlebihan

Sebelum:
> Bisa jadi kemungkinan besar dapat dikatakan bahwa kebijakan ini mungkin memiliki sedikit dampak.

Sesudah:
> Kebijakan ini mungkin berdampak.

### 25. Penutup positif generik

Sebelum:
> Masa depan perusahaan ini terlihat cerah. Perjalanan menuju keunggulan masih panjang, dan ini adalah langkah besar ke arah yang benar.

Sesudah: potong aja paragrafnya. Selesai di fakta konkret terakhir. Kalau sumbernya nyebut rencana nyata, pakai itu.

### 26. Trope otoritas

Kata yang diawasi: pertanyaan sesungguhnya adalah, pada dasarnya, pada intinya, yang benar benar penting adalah, akar masalahnya, secara fundamental.

Frasa ini dipakai buat pura pura nembus kebisingan menuju kebenaran yang lebih dalam, padahal kalimat setelahnya cuma ngulang poin biasa dengan upacara tambahan.

### 27. Papan penunjuk arah

Kata yang diawasi: mari kita bahas, yuk kita bedah, berikut yang perlu Anda ketahui, sekarang kita lihat, tanpa berlama lama.

AI ngumumin apa yang mau dia lakuin, bukan langsung ngelakuin. Buang pengumumannya, mulai dari isinya.

### 28. Punchline buatan dan drama patah patah

AI bikin tiap kalimat mendarat kayak kutipan penutup, terus numpuk kalimat pendek buat bikin dramatis. Satu kalimat pendek buat penegasan itu wajar. Empat berturut turut kedengeran direkayasa.

Sebelum:
> Lalu AlphaEvolve datang. Ia tidak peduli simetri. Tidak punya selera estetika. Tidak punya nostalgia. Aturan lama runtuh.

Sesudah:
> AlphaEvolve mengubah pencariannya karena dia gak condong ke simetri atau ke desain yang keliatan buatan manusia. Beberapa asumsi lama jadi kurang kepakai.

### 29. Rumus aforisme

Kata yang diawasi: X adalah Y dari Z, X berubah jadi jebakan, bahasa dari, mata uang dari, arsitektur dari.

Sebelum:
> Simetri adalah bahasa kepercayaan.

Sesudah:
> Tata letak simetris biasanya kerasa lebih bisa ditebak sama pengguna.

### 30. Pembuka retoris palsu

Kata yang diawasi: Jujur ya, Gini deh, Begini, Sebenarnya sih, Ngomong ngomong, kalau dipakai sebagai kail pembuka sebelum poin biasa.

Cirinya jeda dramatis lalu pengungkapan. Orang yang beneran jujur biasanya langsung ngomong aja.

Sebelum:
> Worth gak sih harganya? Jujur ya? Tergantung seberapa sering lo pakai.

Sesudah:
> Worth atau nggak tergantung seberapa sering lo pakai.

### 31. Tulisan yang nyeritain perubahan

Dokumentasi atau komentar yang ditulis kayak lagi ngenarasiin commit, bukan ngejelasin barangnya. Kecuali dokumennya emang soal versi, kayak changelog atau panduan migrasi, teksnya harus nyambung tanpa perlu tau apa yang berubah kemarin.

Sebelum:
> Fungsi ini ditambahkan untuk menggantikan pendekatan sebelumnya yang melakukan iterasi ke semua item.

Sesudah:
> Fungsi ini pakai hash map biar lookupnya O(1).

---

## PANDUAN DETEKSI

### Yang jangan ditandain

Penulis manusia yang rapi bisa kena beberapa pola di atas tanpa nyentuh AI sama sekali. Sebelum ngerombak, pastiin lo gak lagi ngerusak tulisan yang sehat. Ini bukan indikator yang bisa dipercaya kalau berdiri sendiri:

- Tata bahasa rapi dan gaya konsisten. Banyak penulis emang profesional atau udah lewat editor.
- Campur register santai dan formal. Ini biasanya tanda orang teknis, penulis muda, atau kebiasaan nulis yang emang begitu.
- Tulisan hambar. Tulisan AI punya ciri spesifik. Kering doang tanpa ciri itu ya cuma tulisan kering.
- Kosakata akademis. AI kepakean kata mewah tertentu, bukan semua kata mewah.
- Kata sambung umum yang muncul sekali. Satu "namun" bukan bukti apa apa.
- Kutip melengkung doang. Word, Google Docs, dan kebanyakan CMS emang otomatis ngelengkungin.
- Satu kalimat pendek yang menohok. Manusia juga motong kalimat buat nekenin poin.
- Klaim tanpa sumber. Sebagian besar internet emang gak bersumber.
- Format rapi dan kompleks. Editor visual dan template ngasih hasil bersih tanpa AI.
- Teks tangan kedua. Jangan ngubah frasa yang lagi dikutip, judul, nama diri, atau contoh yang emang lagi dibahas, bukan dipakai.

Kalau ragu, cari gerombolan tanda, bukan satu dua. Satu em dash gak berarti apa apa. Em dash plus aturan tiga plus "warisan budaya yang kaya" plus bagian "Kesimpulan" itu pengakuan.

### Tanda tulisan manusia, pertahankan

- Detail spesifik yang aneh dan susah dikarang. Alamat beneran. Kutipan nyeleneh. Frasa kayak "pengacara yang dulu ngantor di atas dokter gigi gue". AI ngebuletin detail, manusia nyimpen.
- Perasaan campur aduk yang gak selesai. "Gue rasa ini bagus sih, tapi ada yang ngeganjel dan gue gak bisa jelasin apa."
- Referensi yang kepatok zaman. Slang, meme, atau lelucon dalam yang nempel ke tahun dan subkultur tertentu.
- Pilihan editorial orang pertama yang bisa dipertanggungjawabkan penulisnya.
- Panjang kalimat yang variatif. Tulisan asli gantian pendek panjang. AI cenderung rata di tengah.
- Selipan, kurungan, atau ralat diri sendiri di tengah kalimat.
- Suntingan sebelum 30 November 2022, yaitu tanggal ChatGPT rilis ke publik.

---

## Mode pemanggilan

Teks tempelan, ini default. User naruh teks di percakapan. Jalanin loop lengkap dan serahin draft, poin audit, dan hasil final.

Mode file. User nunjuk ke sebuah file. Baca, jalanin loop di dalam kepala, terus tulis ulang filenya di tempat sampai isinya cuma versi final. Cuma prosanya yang dihumanize, blok kode, frontmatter, data, dan tujuan link jangan disentuh. Di percakapan, laporin ringkasan singkat apa yang berubah, jangan tempel ulang seluruh hasilnya.

Mode tersemat. Tugas atau agent lain lagi pakai skill ini sebagai satu langkah dari kerjaan yang lebih besar, misalnya deskripsi PR, pesan commit, atau dokumen. Jalanin loopnya di dalam dan keluarin teks finalnya doang. Gak usah draft, gak usah audit, gak usah ringkasan.

---

## Proses dan output

1. Baca inputnya pelan pelan, tandai tiap kemunculan pola di atas.
2. Tulis draft. Cek dia enak dibaca kalau diucapin keras keras, panjang kalimatnya variatif, detailnya spesifik, konstruksinya sederhana, dan registernya pas.
3. Tanya tiga hal ke diri sendiri, jawab singkat:
   - Apa yang bikin teks ini masih kentara buatan AI?
   - Apakah hasil tulis ulangnya nyebut fakta, nama, angka, tanggal, atau sumber yang gak ada di teks asli?
   - Apakah masih ada em dash, en dash, tanda hubung, titik koma, kutip melengkung, atau emoji di luar blok kode?
4. Revisi jadi versi final yang beresin ketiganya.

Di mode teks tempelan, serahin draftnya, poin poin "masih kentara AI", versi finalnya, dan opsional ringkasan singkat perubahan. Di mode file dan mode tersemat, jalanin loop yang sama tapi cuma serahin yang diminta modenya.

---

## Rujukan

Skill ini berdasar [Wikipedia:Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing) yang dirawat WikiProject AI Cleanup, ditambah katalog pola bahasa Indonesia yang disusun terpisah.

Inti dari halaman Wikipedia itu: model bahasa nebak apa yang paling mungkin muncul berikutnya secara statistik, jadi hasilnya condong ke jawaban yang paling umum dan paling luas cakupannya.
