## Instal Termux dan repo yang bener

- Hapus Termux lama (kalau dari Play Store).


- Install Termux dari F-Droid biar repo-nya gak rusak:
👉 https://f-droid.org/en/packages/com.termux/


- Buka Termux, lalu update repo:

```sh
pkg update && pkg upgrade -y
pkg install which jq xmlstarlet bc perl ncurses-utils -y
```

- Pasang Python + dependensi

```sh
pkg install -y python git wget curl
pip install requests beautifulsoup4
```

**Cek Python-nya jalan:**

python3 -V

Harus muncul semacam Python 3.x.x.

```sh
git clone https://github.com/ibnux/data-indonesia.git
```

# Buat folder dan file script

**Biar rapi:**
```sh
mkdir -p ~/cuaca_logs
cd ~
```
Buat file-nya: nama file bebas yang penting ujungnya kasih .py

```sh
nano cuaca_jabodetabek.py
```
Paste isi script Python lengkap yang gue kasih di file terpisah (V3.py atau yang paling terbaru jika ada update).
Setelah paste, tekan:

**CTRL + O  →  Enter  →  CTRL + X**

Kasih izin eksekusi:
```sh
chmod +x cuaca_jabodetabek.py
```

---

- Jalankan pertama kali

Cukup ketik:

```
python3 cuaca_jabodetabek.py
```
Atau
```
./cuaca_jabodetabek.py
```

Kalau semua benar, bakal muncul tabel datanya
Kalau outputnya cuma teks tanpa warna, bisa jalankan:

```sh
python3 cuaca_jabodetabek.py --no-color --no-unicode
```

kalo mau jalankan fitur lainnya ketikan perintah ini

paling simpel cari lokasi

```
./cuaca_jabodetabek.py --names nama_lokasi #kalo dua kata atau ada spasinya tambahkan tanda kutip di awal dan diakhirnya contoh "Bekasi Barat"
```

atau seperti ini:

**Tunggal:**
```
./cuaca_jabodetabek.py --level kelurahan --names "Cengkareng barat"
```
**Catatan:** ganti kelurahan dengan kecamatan, kabupaten, atau provinsi

**Multi:**
```
./cuaca_jabodetabek.py --level kelurahan --names "Cengkareng barat,cipulir,grogol"
```

Kalo mau data presisi untuk daerah tertentu tentukan dengan koordinat GPS, contoh
Tunggal: perhatikan spasinya.
```
./cuaca_jabodetabek.py --koordinat=-6.23579,106.76893
```

Multi: Kasih labelnya terserah bisa kantor, rumah, nama daerah, dll. contoh:
```
./cuaca_jabodetabek.py --koordinat "Cipulir:-6.23579, 106.76893;RW. Buaya:-6.16988, 106.73309"
```

# Perintah dibawah ini semuanya opsional, perintah diatas udah cukup untuk jalankan script

- Mode otomatis (daemon 30 menit sekali)

Biar Termux narik data terus:
```
python3 cuaca_jabodetabek.py --daemon --interval=1800
```
Atau kalau mau lebih ringan, tiap 1 jam:

```
python3 cuaca_jabodetabek.py --daemon --interval=3600
```
Jangan keluar dari Termux.
Kalau mau biar gak mati saat layar mati, pasang:

```
pkg install termux-api
termux-wake-lock
```


# (Opsional) Kirim hasil ke Telegram

Kalau lo mau hasilnya dikirim otomatis ke bot Telegram:

1. Buat bot Telegram di @BotFather, ambil TOKEN.


2. Chat dulu ke bot lo supaya dia tahu akun lo.


3. Ambil CHAT_ID (dari https://api.telegram.org/bot<TOKEN>/getUpdates).


4. Export variabel:
```sh
export TG_BOT_TOKEN="123456:ABCDEF..."
export TG_CHAT_ID="-1001234567890"
export OPENAI_API_KEY="sk-..."
```
5. Jalankan script seperti biasa:
```
python3 cuaca_jabodetabek.py
```
Hasil ringkasan bakal nongol di chat Telegram lo.




---

# (Opsional) Jalankan otomatis saat boot

Kalau mau jalan otomatis tiap buka Termux:
```
echo "python3 ~/cuaca_jabodetabek.py --daemon --interval=3600" >> ~/.bashrc
```
Nanti setiap buka Termux, dia langsung jalan mode daemon.

++++++++++++++++++++++++++++++++++++++++++++++

Kalo lu mau simpen token Bot Telegram dll bisa menggunakan cara ini:
```
nano ~/.env_cuaca
```
Isi dengan ini
```sh
export TG_BOT_TOKEN="isi_bot_token"
export TG_CHAT_ID="isi_id_chat"
export OPENAI_API_KEY="isi_api_key_open_ai"
export OPENAI_MODEL="gpt-5.1"
```
**Catatan:** Ganti sesuai yang mau lu pake model Ai nya
**Support model Ai:** gpt-4.1, gpt-4.1-mini, gpt-4o-mini, gpt-5.1

**Simpan CTRL+O ENTER CTRL+X**

Isi juga di 
```
nano ~/.profile
```
Isi lagi tokennya kayak diatas

Kemudian simpan lagi bot token, OpenAi, dan chat id nya, terus jalankan ini
```sh
chmod 600 ~/.env_cuaca
source ~/.profile
```
Tes token
```sh
echo $TG_BOT_TOKEN
echo $TG_CHAT_ID
echo $OPENAI_API_KEY
echo $OPENAI_MODEL
```
**Catatan:** Jadi kalo mau jalanin script gak usah masukin bot token, chat id, dan api key open Ai lagi.

ganti model open ai manual seperti ini contohnya:
```sh
./nama_file.py --openai-model gpt-4.1-mini
```

- Cek log

Log otomatis disimpan di:

~/cuaca_logs/run.log
~/cuaca_logs/tg_resp.log

Kalau script gak kirim ke Telegram, cek tg_resp.log.

# Custom Prompt Ai cari ``system_msg`` seperti di bawah ini:

```sh
system_msg = (
    "Kamu bikin ringkasan tegas untuk driver ojol. "
    "Nada abang ojol senior: santai, ceplas-ceplos, tapi sopan. "
    "Baca semua datanya dari awal sampai akhir dan analisa secara mendalam dan akurat. "
    "Buat 1 paragraf saja, dimulai dengan 'Kesimpulan tegasnya:'. "
    "Tidak pakai emoji. "
    "Gak usah bertele-tele, berikan kepastian apakah sekarang dan untuk 3 dan 6 jam kedepan aman atau turun hujan, singkat padat dan jelas untuk pesan singkat status WhatsApp. "
)
```


**Ringkasan singkat buat lo yang males baca:**
```
pkg update -y && pkg upgrade -y
pkg install -y python git wget curl termux-api
pip install requests beautifulsoup4
mkdir -p ~/cuaca_logs
cd ~
nano cuaca_jabodetabek.py   # paste script
chmod +x cuaca_jabodetabek.py
python3 cuaca_jabodetabek.py
```
