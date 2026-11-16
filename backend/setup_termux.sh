#!/data/data/com.termux/files/usr/bin/bash
set -e
pkg update -y && pkg install -y python
pip install -r requirements.txt
echo "Selesai. Jalankan: FOKUS_TOKEN=tokenrahasia python app.py"
