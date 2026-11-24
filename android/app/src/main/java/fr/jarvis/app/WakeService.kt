package fr.jarvis.app

import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import ai.picovoice.porcupine.Porcupine
import ai.picovoice.porcupine.PorcupineManager

/** Écoute permanente du mot « Jarvis » (Porcupine, traitement 100 % sur le téléphone). */
class WakeService : Service() {
    private var porcupine: PorcupineManager? = null

    companion object {
        fun key(c: Context) = c.getSharedPreferences("jarvis", Context.MODE_PRIVATE).getString("pv_key", "") ?: ""
        fun enabled(c: Context) = c.getSharedPreferences("jarvis", Context.MODE_PRIVATE).getBoolean("wake_on", true)
        fun start(c: Context) { if (key(c).isNotBlank() && enabled(c)) try { c.startForegroundService(Intent(c, WakeService::class.java)) } catch (_: Exception) {} }
        fun stop(c: Context) { c.stopService(Intent(c, WakeService::class.java)) }
    }

    override fun onBind(i: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("wake", "Écoute « Jarvis »", NotificationManager.IMPORTANCE_MIN))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, "wake").setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("Jarvis vous écoute").setContentText("Dites « Jarvis »").setContentIntent(open).setOngoing(true).build()
        if (Build.VERSION.SDK_INT >= 29) startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE) else startForeground(1, n)
        if (porcupine == null) try {
            porcupine = PorcupineManager.Builder()
                .setAccessKey(key(this))
                .setKeyword(Porcupine.BuiltInKeyword.JARVIS)
                .setSensitivity(0.75f)
                .build(applicationContext) { onWake() }
            porcupine?.start()
        } catch (e: Exception) {
            getSharedPreferences("jarvis", MODE_PRIVATE).edit().putString("wake_error", e.message ?: "erreur").apply()
            stopSelf()
        }
        return START_STICKY
    }

    private fun onWake() {
        // libère le micro pour l'écoute de la demande, puis ouvre Jarvis (même écran verrouillé)
        porcupine?.stop()
        val svc = JarvisInteractionService.instance
        if (svc != null) svc.showSession(Bundle(), 0)
        else startActivity(Intent(this, MainActivity::class.java).putExtra("listen", true).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        stopSelf()
    }

    override fun onDestroy() { try { porcupine?.stop(); porcupine?.delete() } catch (_: Exception) {}; porcupine = null; super.onDestroy() }
}
