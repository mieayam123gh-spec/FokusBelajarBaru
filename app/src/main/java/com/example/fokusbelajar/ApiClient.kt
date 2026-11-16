package com.example.fokusbelajar

import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

object ApiClient {
    var baseUrl = ""
    var token = ""

    private fun request(method: String, path: String, body: JSONObject? = null): JSONObject {
        if (baseUrl.isBlank()) throw IOException("URL server belum diisi")
        val conn = URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection
        conn.requestMethod = method
        conn.connectTimeout = 5000
        conn.readTimeout = 8000
        conn.setRequestProperty("X-Token", token)
        conn.setRequestProperty("Content-Type", "application/json")
        if (method == "POST") {
            conn.doOutput = true
            conn.outputStream.use { it.write((body ?: JSONObject()).toString().toByteArray()) }
        }
        val code = conn.responseCode
        val stream = if (code in 200..299) conn.inputStream else conn.errorStream
        val text = stream?.bufferedReader()?.readText() ?: "{}"
        conn.disconnect()
        if (code !in 200..299) throw IOException("HTTP $code: $text")
        return JSONObject(text)
    }

    fun setBlocked(list: List<String>) {
        request("POST", "/api/rules", JSONObject().put("blocked", JSONArray(list)))
    }

    fun startSession(): JSONObject = request("POST", "/api/session/start")

    fun stopSession(): JSONObject = request("POST", "/api/session/stop")

    fun stats(): JSONObject = request("GET", "/api/sessions")

    /** Lapor ke server: aplikasi [pkg] sedang dibuka di device ini. */
    fun reportActivity(pkg: String) {
        val body = JSONObject()
            .put("device", deviceName())
            .put("package", pkg)
            .put("ts", System.currentTimeMillis() / 1000)
        request("POST", "/api/activity", body)
    }

    /** Ambil status live dari server (untuk HP orang tua). */
    fun live(): JSONObject = request("GET", "/api/live")

    private fun deviceName(): String =
        android.os.Build.MODEL.takeIf { it.isNotBlank() } ?: "HP Anak"
}
