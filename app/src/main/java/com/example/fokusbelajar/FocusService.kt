package com.example.fokusbelajar

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import java.util.concurrent.Executors

class FocusService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private var blocked: Set<String> = emptySet()
    private var lastCheck = System.currentTimeMillis()
    private var lastReported: String? = null
    private var ticksSinceHeartbeat = 0
    private var prefs: SharedPreferences? = null

    private val netExecutor = Executors.newSingleThreadExecutor()

    private val tick = object : Runnable {
        override fun run() {
            checkForeground()
            handler.postDelayed(this, 1000)
        }
    }

    override fun onCreate() {
        super.onCreate()
        prefs = getSharedPreferences("fokus", MODE_PRIVATE)
        ApiClient.baseUrl = prefs?.getString("url", "") ?: ""
        ApiClient.token = prefs?.getString("token", "") ?: ""

        val channel = NotificationChannel("focus", "Sesi belajar", NotificationManager.IMPORTANCE_LOW)
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)

        val notif = Notification.Builder(this, "focus")
            .setContentTitle("Sesi belajar aktif")
            .setContentText("Pembatasan aplikasi sedang berjalan")
            .setSmallIcon(android.R.drawable.ic_lock_idle_lock)
            .build()

        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(1, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(1, notif)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        blocked = intent?.getStringArrayListExtra("blocked")?.toSet() ?: blocked
        lastCheck = System.currentTimeMillis()
        handler.removeCallbacks(tick)
        handler.post(tick)
        return START_STICKY
    }

    private fun checkForeground() {
        val usm = getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val now = System.currentTimeMillis()
        val events = usm.queryEvents(lastCheck, now)
        lastCheck = now

        val event = UsageEvents.Event()
        var last: String? = null
        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            @Suppress("DEPRECATION")
            if (event.eventType == UsageEvents.Event.MOVE_TO_FOREGROUND) {
                last = event.packageName
            }
        }

        // Blokir aplikasi yang dilarang
        if (last != null && last in blocked && last != packageName) {
            startActivity(
                Intent(this, BlockActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            )
        }

        // Live screen: laporkan ke server saat anak pindah aplikasi,
        // plus heartbeat tiap 20 detik agar ortu tahu masih di app yang sama.
        val current = last ?: lastReported
        if (current != null && current != packageName) {
            val changed = current != lastReported
            ticksSinceHeartbeat++
            if (changed || ticksSinceHeartbeat >= 20) {
                ticksSinceHeartbeat = 0
                if (changed) lastReported = current
                reportToServer(current)
            }
        }
    }

    private fun reportToServer(pkg: String) {
        netExecutor.execute {
            try {
                ApiClient.reportActivity(pkg)
            } catch (_: Exception) {
                // Jaringan gagal: abaikan, akan dicoba lagi pada tick berikutnya.
            }
        }
    }

    override fun onDestroy() {
        handler.removeCallbacks(tick)
        netExecutor.shutdown()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        fun start(ctx: Context, blocked: ArrayList<String>) {
            val i = Intent(ctx, FocusService::class.java).putStringArrayListExtra("blocked", blocked)
            ctx.startForegroundService(i)
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, FocusService::class.java))
        }
    }
}
