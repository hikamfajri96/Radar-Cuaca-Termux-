# README singkat

## Deskripsi
Radar Cuaca Ojol adalah script Python Termux-ready untuk membuat prakiraan cuaca per-jam (24 jam) khusus untuk driver ojol. Output rapi di terminal dan dapat dikirim ke Telegram.

## Disclaimer
"Data cuaca tidak menjamin keselamatan. Pengguna bertanggung jawab atas keputusan operasional."

## Waktu ideal buat update radar cuaca (default Jabodetabek)

1. **Malam (21.00–23.00 WIB)**  
   Cek sekilas apakah ada sistem besar dari barat (Sumatera), selatan (Samudera Hindia), atau timur (Jawa Timur). Ini cuma early warning.

2. **Pagi (06.00–07.00 WIB)**  
   Wajib. Model cuaca segar keluar dan atmosfer mulai kelihatan arahnya.

3. **Menjelang siang (11.00–12.00 WIB)**  
   Final check sebelum jam rawan (13.00–17.00).

**Catatan:** Cek malam hanya gambaran awal. Keputusan tetap di update pagi + cek ulang menjelang siang.

## Fitur Utama
- Data per-jam (24 jam) dari Open-Meteo  
- Integrasi nowcast BMKG (XML)  
- Status per jam: ✅ Aman / ⚠️ Waspada / ❌ Rawan  
- Ringkasan 6/12/24 jam  
- Ringkasan AI (jika OPENAI_API_KEY ada)  
- Kirim hasil ke Telegram  
- Opsi CLI: `--daemon`, `--once`, `--interval`, `--compact`, `--names`, `--koordinat`, dll.

## Persyaratan
- Termux (Android)  
- pkg: python, curl, jq, git  
- Python packages: requests, beautifulsoup4  

## Instalasi (cepat) paket dasar
Jalankan ini langsung di Termux (blok utuh, bisa di-copy sekaligus):

```sh
pkg update -y && pkg upgrade -y
pkg install -y python curl jq git
pip install requests beautifulsoup4
```

```sh
git clone https://github.com/hikamfajri96/Radar-Cuaca-Termux-
```
## Masuk ke directory 

```sh
cd Radar-Cuaca-Termux-
```

## Clone database Indonesia 

```sh
git clone https://github.com/hikamfajri96/data-indonesia
```
## Instal dependensi tambahan

```sh
pkg install -y xmlstarlet
pkg install -y bc
pkg install -y perl
pkg install -y ncurses-utils
```

## Selesai.

cara menjalankan bisa di lihat di file "Cara Instalasi".
