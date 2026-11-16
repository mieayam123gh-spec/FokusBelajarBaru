# Fokus Belajar

Aplikasi Android sederhana untuk membantu adik fokus belajar.
Dibuat terbuka: adik tahu aturannya, dan izin diberikan secara manual di HP-nya.

## Fitur
- **Blokir aplikasi saat sesi belajar**: aplikasi yang masuk daftar akan ditutup
  dan diganti layar "Waktunya belajar!".
- **Live Screen**: pantau secara real-time aplikasi apa yang sedang dibuka anak,
  lengkap dengan riwayat 30 aplikasi terakhir. Tersedia di dua tempat:
  1. Tombol **"Live Screen: pantau aplikasi anak"** di aplikasi (HP orang tua).
  2. **Dashboard web**: buka `http://IP-SERVER:5000` di browser HP orang tua,
     masukkan token, dan pantauan tampil tiap 3 detik.
- **Rekap sesi**: jumlah sesi dan total menit belajar hari ini.

## Struktur
- `backend/`    server Python (Flask) yang dijalankan di Termux
- `app/`        aplikasi Android (Kotlin)
- `.github/`    workflow untuk build APK otomatis di GitHub

## Menjalankan backend di Termux
1. Pasang Termux dari F-Droid.
2. Di Termux jalankan:
   ```
   cd backend
   bash setup_termux.sh
   FOKUS_TOKEN=tokenrahasia python app.py
   ```
3. Cek IP HP server dengan perintah `ifconfig` atau `ip addr` (contoh: 192.168.1.10).
4. Server berjalan di `http://IP:5000`. Kedua HP harus terhubung ke WiFi yang sama.
5. Jalankan `termux-wake-lock` agar Termux tidak dimatikan sistem.
6. Dashboard pantauan live bisa dibuka di browser: `http://IP:5000`
   (masukkan token yang sama dengan FOKUS_TOKEN).

## Build APK
Push folder ini ke GitHub, lalu ambil file APK dari tab Actions (artifact
fokus-belajar-apk). Workflow sudah dikonfigurasi (`.github/workflows/build-apk.yml`)
dan akan otomatis membuild setiap kali ada push ke branch main/master.
Atau buka folder ini di Android Studio dan tekan Build > Build APK.

## Cara pakai
### HP anak
1. Install APK, buka aplikasi.
2. Isi URL server (`http://IP:5000`) dan token yang sama dengan FOKUS_TOKEN.
3. Isi daftar paket aplikasi yang diblokir, pisah dengan koma.
   Contoh: `com.google.android.youtube, com.mobile.legends`
4. Tekan **"Simpan pengaturan"**.
5. Beri izin: **"Izinkan akses penggunaan"** dan **"Izinkan tampil di atas aplikasi"**.
6. Tekan **"Mulai sesi belajar"**. Selama sesi berjalan, HP anak otomatis
   melapor ke server setiap kali membuka aplikasi (inilah sumber data Live Screen).
   Tekan **"Berhenti sesi"** untuk mengakhiri.

### HP orang tua
1. Install APK (atau cukup pakai browser), isi URL server dan token yang sama.
2. Tekan **"Live Screen: pantau aplikasi anak"** untuk melihat aplikasi yang
   sedang dan baru saja dibuka anak. Data menyegarkan otomatis tiap 3 detik.
3. Tekan **"Lihat rekap hari ini"** untuk statistik sesi belajar.

## Catatan teknis
- Live Screen memakai `UsageStatsManager` di HP anak (izinkan "akses penggunaan"
  harus aktif). Laporan dikirim saat anak pindah aplikasi, plus heartbeat tiap
  20 detik, jadi ortu selalu tahu aplikasi apa yang sedang dibuka.
- Riwayat aktivitas disimpan di server maksimal 7 hari.
- Semua endpoint (kecuali health & dashboard) dilindungi token lewat header `X-Token`.
