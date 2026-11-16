package com.example.fokusbelajar

import android.app.Activity
import android.graphics.Typeface
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Live Screen untuk orang tua: menampilkan aplikasi yang SEDANG dibuka
 * anak di HP lain, plus riwayat 30 aplikasi terakhir. Diperbarui otomatis
 * tiap 3 detik dari server.
 */
class MonitorActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private val timeFmt = SimpleDateFormat("HH:mm:ss", Locale.getDefault())

    private lateinit var liveTv: TextView
    private lateinit var recentTv: TextView
    private lateinit var statusTv: TextView

    private val refresh = object : Runnable {
        override fun run() {
            loadLive()
            handler.postDelayed(this, 3000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val titleTv = TextView(this).apply {
            text = "Live Screen - Pantauan Anak"
            textSize = 20f
            setTypeface(typeface, Typeface.BOLD)
            setPadding(0, 0, 0, 16)
        }

        liveTv = TextView(this).apply {
            textSize = 18f
            setTypeface(typeface, Typeface.BOLD)
            gravity = Gravity.CENTER
            setPadding(24, 24, 24, 24)
            text = "Memuat..."
        }

        statusTv = TextView(this).apply {
            textSize = 13f
            setPadding(0, 0, 0, 12)
        }

        recentTv = TextView(this).apply {
            textSize = 15f
            setPadding(0, 12, 0, 12)
        }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(40, 40, 40, 40)
            addView(titleTv)
            addView(liveTv)
            addView(statusTv)
            addView(recentTv)
        }
        setContentView(ScrollView(this).apply { addView(root) })
    }

    override fun onResume() {
        super.onResume()
        handler.post(refresh)
    }

    override fun onPause() {
        handler.removeCallbacks(refresh)
        super.onPause()
    }

    private fun loadLive() {
        Thread {
            try {
                val j = ApiClient.live()
                runOnUiThread { render(j) }
            } catch (e: Exception) {
                runOnUiThread {
                    liveTv.text = "Gagal terhubung server"
                    statusTv.text = "Cek URL server & token, lalu coba lagi.\nDetail: ${e.message}"
                }
            }
        }.start()
    }

    private fun render(j: JSONObject) {
        val devices = j.optJSONArray("devices")
        if (devices == null || devices.length() == 0) {
            liveTv.text = "Belum ada data.\n\nPastikan sesi belajar sedang berjalan di HP anak."
            statusTv.text = ""
            recentTv.text = ""
            return
        }

        val d = devices.getJSONObject(0)
        val currentApp = d.optString("current_app", "")
        val live = d.optBoolean("live", false)
        val secondsAgo = d.optInt("seconds_ago", 0)
        val lastApp = d.optString("last_app", "")

        if (live && currentApp.isNotEmpty()) {
            liveTv.text = "Sekarang: ${appLabel(currentApp)}"
            statusTv.text = "Update $secondsAgo detik lalu. Menyegarkan tiap 3 detik."
        } else {
            liveTv.text = "Tidak ada laporan baru"
            statusTv.text = "Laporan terakhir ${secondsAgo / 60} menit lalu: ${appLabel(lastApp)}"
        }

        val recent = j.optJSONArray("recent")
        if (recent != null && recent.length() > 0) {
            val sb = StringBuilder("Riwayat aplikasi yang dibuka:\n\n")
            for (i in 0 until recent.length()) {
                val e = recent.getJSONObject(i)
                val time = timeFmt.format(Date(e.optLong("ts") * 1000))
                sb.append(time)
                    .append("  ")
                    .append(appLabel(e.optString("package")))
                    .append('\n')
            }
            recentTv.text = sb.toString()
        } else {
            recentTv.text = "Belum ada riwayat."
        }
    }

    /** Ubah nama paket jadi nama aplikasi yang terbaca manusia. */
    private fun appLabel(pkg: String): String {
        if (pkg.isBlank()) return "(tidak diketahui)"
        return try {
            val pm = packageManager
            pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString()
        } catch (_: Exception) {
            pkg
        }
    }
}
