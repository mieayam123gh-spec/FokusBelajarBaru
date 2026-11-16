package com.example.fokusbelajar

import android.app.Activity
import android.content.Intent
import android.content.SharedPreferences
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

class MainActivity : Activity() {
    private lateinit var prefs: SharedPreferences
    private lateinit var urlEt: EditText
    private lateinit var tokenEt: EditText
    private lateinit var blockedEt: EditText
    private lateinit var statusTv: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = getSharedPreferences("fokus", MODE_PRIVATE)

        urlEt = EditText(this).apply {
            hint = "URL server, contoh http://192.168.1.10:5000"
            setText(prefs.getString("url", ""))
        }
        tokenEt = EditText(this).apply {
            hint = "Token (sama dengan FOKUS_TOKEN)"
            setText(prefs.getString("token", ""))
        }
        blockedEt = EditText(this).apply {
            hint = "Paket aplikasi diblokir, pisah koma"
            setText(prefs.getString("blocked", ""))
        }
        statusTv = TextView(this).apply { text = "Siap." }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(40, 40, 40, 40)
        }

        listOf<View>(
            urlEt,
            tokenEt,
            blockedEt,
            button("Simpan pengaturan") { saveSettings() },
            button("Mulai sesi belajar") { startSession() },
            button("Berhenti sesi") { stopSession() },
            button("Live Screen: pantau aplikasi anak") { openMonitor() },
            button("Lihat rekap hari ini") { showStats() },
            button("Izinkan akses penggunaan") {
                startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS))
            },
            button("Izinkan tampil di atas aplikasi") {
                startActivity(
                    Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))
                )
            },
            statusTv
        ).forEach { root.addView(it) }

        setContentView(ScrollView(this).apply { addView(root) })
    }

    private fun button(label: String, onClick: () -> Unit): Button =
        Button(this).apply {
            text = label
            setOnClickListener { onClick() }
        }

    private fun applyConfig(): Boolean {
        val url = urlEt.text.toString().trim()
        val token = tokenEt.text.toString().trim()
        if (url.isEmpty() || token.isEmpty()) {
            statusTv.text = "URL dan token wajib diisi."
            return false
        }
        ApiClient.baseUrl = url
        ApiClient.token = token
        return true
    }

    private fun blockedList(): ArrayList<String> =
        ArrayList(blockedEt.text.toString().split(",").map { it.trim() }.filter { it.isNotEmpty() })

    private fun background(busy: String, work: () -> Unit, done: String, after: (() -> Unit)? = null) {
        statusTv.text = busy
        Thread {
            try {
                work()
                runOnUiThread {
                    statusTv.text = done
                    after?.invoke()
                }
            } catch (e: Exception) {
                runOnUiThread { statusTv.text = "Gagal: ${e.message}" }
            }
        }.start()
    }

    private fun saveSettings() {
        prefs.edit()
            .putString("url", urlEt.text.toString().trim())
            .putString("token", tokenEt.text.toString().trim())
            .putString("blocked", blockedEt.text.toString())
            .apply()
        if (!applyConfig()) return
        val list = blockedList()
        background("Menyimpan...", { ApiClient.setBlocked(list) }, "Pengaturan tersimpan di server.")
    }

    private fun startSession() {
        if (!applyConfig()) return
        if (!Settings.canDrawOverlays(this)) {
            statusTv.text = "Izinkan tampil di atas aplikasi dulu."
            return
        }
        val list = blockedList()
        background(
            "Memulai...",
            { ApiClient.startSession() },
            "Sesi dimulai.",
            { FocusService.start(this, list) }
        )
    }

    private fun stopSession() {
        if (!applyConfig()) return
        FocusService.stop(this)
        background("Menghentikan...", { ApiClient.stopSession() }, "Sesi dihentikan.")
    }

    private fun openMonitor() {
        if (!applyConfig()) return
        startActivity(Intent(this, MonitorActivity::class.java))
    }

    private fun showStats() {
        if (!applyConfig()) return
        statusTv.text = "Mengambil rekap..."
        Thread {
            try {
                val j = ApiClient.stats()
                val count = j.getInt("today_sessions")
                val minutes = j.getInt("today_minutes")
                runOnUiThread { statusTv.text = "Hari ini: $count sesi, total $minutes menit." }
            } catch (e: Exception) {
                runOnUiThread { statusTv.text = "Gagal: ${e.message}" }
            }
        }.start()
    }
}
