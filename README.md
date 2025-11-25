# README singkat

## Deskripsi
Radar Cuaca Ojol adalah script Python Termux-ready untuk membuat prakiraan cuaca per-jam (24 jam) khusus untuk driver ojol. Output rapi di terminal dan dapat dikirim ke Telegram.

## Disclaimer: "Data cuaca tidak menjamin keselamatan. Pengguna bertanggung jawab atas keputusan operasional."

## Waktu ideal buat update radar cuaca (default Jabodetabek)

1. Malam (sekitar 21.00–23.00 WIB): cek sekilas. Lihat apakah ada sistem besar dari barat (Sumatera), selatan (Samudera Hindia), atau timur (Jawa bagian timur) yang bakal jalan ke Jabodetabek. Ini cuma “early warning,” bukan keputusan.

2. Pagi besok (06.00–07.00 WIB): ini wajib. Model cuaca paling segar keluar, dan atmosfer mulai kelihatan arahnya.

3. Menjelang siang (11.00–12.00 WIB): ini pengecekan pamungkas sebelum masuk jam rawan (13.00–17.00).

“Cek cuaca malam cuma buat gambaran awal. Keputusan besok tetap harus lihat update pagi jam 06.00–07.00 dan cek ulang menjelang siang. Radar malam bukan ramalan besok.”

## Fitur Utama
- Data per-jam (24 jam) dari Open-Meteo
- Integrasi nowcast BMKG (XML) untuk peringatan lokal
- Penilaian status per jam: ✅ Aman / ⚠️ Waspada / ❌ Rawan
- Ringkasan 6/12/24 jam per lokasi
- Ringkasan AI (jika OPENAI_API_KEY diisi) — fallback lokal bila tidak ada
- Kirim hasil ke Telegram (via BOT token + chat id)
- CLI: --daemon, --once, --interval, --compact, --names, --koordinat, dll.

## Persyaratan
- Termux (Android)
- pkg: python, curl, jq, git
- Python packages: requests, beautifulsoup4

## Instalasi (cepat)
1. Buka Termux, jalankan:
   ```sh
   pkg update -y && pkg upgrade -y
   pkg install python curl jq git -y
   python -m pip install --upgrade pip
   python -m pip install requests beautifulsoup4
