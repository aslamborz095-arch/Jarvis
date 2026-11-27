package fr.jarvis.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/** Notifications natives : toutes les 60 s, lit /api/events du PC (via Tailscale) et affiche missions, bilan, idées.
 *  Sans ADB, sans compte. Tourne tant que l'appli ou l'écoute « Hey Jarvis » est active. */
object Notifier {
    @Volatile private var started = false
    private const val DEFAULT_URL = "https://desktop-u3cjv20.tail877ffc.ts.net/"
    private val TITLES = mapOf("mission" to "JARVIS 🎯 Mission", "bilan" to "JARVIS 📋 Bilan du jour",
        "suggest" to "JARVIS 💡 Anticipation", "idea" to "JARVIS 💡 Idée", "evolve" to "JARVIS 🧬 Amélioration",
        "health" to "JARVIS 🩺 Santé", "reminder" to "JARVIS ⏰ Rappel", "confirm" to "JARVIS ⚠️ Validation demandée")

    fun start(c: Context) {
        if (started) return
        started = true
        val ctx = c.applicationContext
        thread(name = "notifier", isDaemon = true) {
            while (true) {
                try { poll(ctx) } catch (_: Exception) {}
                Thread.sleep(60_000)
            }
        }
    }

    private fun poll(c: Context) {
        val prefs = c.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        val token = c.getSharedPreferences("kv", Context.MODE_PRIVATE).getString("jarvis_token", "") ?: ""
        val base = (prefs.getString("url", DEFAULT_URL) ?: DEFAULT_URL).trimEnd('/')
        var cursor = prefs.getInt("notif_after", -1)
        val con = URL("$base/api/events?after=${maxOf(cursor, 0)}").openConnection() as HttpURLConnection
        con.connectTimeout = 8000; con.readTimeout = 10000
        con.setRequestProperty("X-Jarvis-Token", token)
        con.setRequestProperty("X-Jarvis-Client", "android-native")
        if (con.responseCode != 200) return
        val j = JSONObject(con.inputStream.bufferedReader().readText())
        val last = j.optInt("last", 0)
        if (cursor < 0 || last < cursor) {   // 1er lancement ou PC redémarré : on part du présent, sans rejouer l'ancien
            prefs.edit().putInt("notif_after", last).apply(); return
        }
        val evs = j.optJSONArray("events") ?: return
        val nm = c.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("jarvis", "Messages de Jarvis", NotificationManager.IMPORTANCE_DEFAULT))
        val open = PendingIntent.getActivity(c, 2, Intent(c, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        for (i in 0 until evs.length()) {
            val e = evs.getJSONObject(i)
            cursor = maxOf(cursor, e.optInt("id", cursor))
            val title = TITLES[e.optString("type")] ?: continue
            var text = e.optString("text", "")
            if (text.isBlank()) text = e.optString("goal", "")
            if (text.isBlank()) text = e.optString("tool", "")
            if (text.isBlank()) continue
            if (e.optString("type") == "mission" && text.startsWith("Étape")) continue   // pas une notif par étape
            val n = Notification.Builder(c, "jarvis").setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(title).setContentText(text).setStyle(Notification.BigTextStyle().bigText(text))
                .setContentIntent(open).setAutoCancel(true).build()
            try { nm.notify(1000 + (e.optInt("id") % 500), n) } catch (_: SecurityException) {}
        }
        prefs.edit().putInt("notif_after", maxOf(cursor, last)).apply()
    }
}
