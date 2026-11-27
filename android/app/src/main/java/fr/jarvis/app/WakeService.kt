package fr.jarvis.app

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.annotation.SuppressLint
import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import java.nio.FloatBuffer
import kotlin.concurrent.thread

/** Écoute permanente de « Hey Jarvis » sur le téléphone : openWakeWord (même moteur que le PC), 100 % local, sans compte. */
class WakeService : Service() {
    @Volatile private var running = false

    companion object {
        private fun p(c: Context) = c.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        fun enabled(c: Context) = p(c).getBoolean("wake_on", true)
        fun threshold(c: Context) = p(c).getFloat("wake_thr", 0.4f)
        fun start(c: Context) { if (enabled(c)) try { c.startForegroundService(Intent(c, WakeService::class.java)) } catch (_: Exception) {} }
        fun stop(c: Context) { c.stopService(Intent(c, WakeService::class.java)) }
    }

    override fun onBind(i: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("wake", "Écoute « Hey Jarvis »", NotificationManager.IMPORTANCE_MIN))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, "wake").setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("Jarvis vous écoute").setContentText("Dites « Hey Jarvis »").setContentIntent(open).setOngoing(true).build()
        if (Build.VERSION.SDK_INT >= 29) startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE) else startForeground(1, n)
        Notifier.start(this)
        if (!running) { running = true; thread(name = "wake") { loop() } }
        return START_STICKY
    }

    private fun session(env: OrtEnvironment, name: String): OrtSession =
        env.createSession(assets.open(name).readBytes(), OrtSession.SessionOptions())

    @SuppressLint("MissingPermission")
    private fun loop() {
        val prefs = getSharedPreferences("jarvis", MODE_PRIVATE)
        try {
            val env = OrtEnvironment.getEnvironment()
            val mel = session(env, "melspectrogram.onnx")
            val emb = session(env, "embedding_model.onnx")
            val ww = session(env, "hey_jarvis_v0.1.onnx")
            val chunk = 1280
            val rec = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, 16000, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, maxOf(AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT), chunk * 4))
            rec.startRecording()
            val buf = ShortArray(chunk)
            var raw = FloatArray(0)
            val melBuf = ArrayList<FloatArray>(); repeat(76) { melBuf.add(FloatArray(32) { 1f }) }
            val feats = ArrayList<FloatArray>()
            val thr = threshold(this)
            var hits = 0
            while (running) {
                var got = 0
                while (got < chunk && running) { val r = rec.read(buf, got, chunk - got); if (r <= 0) break; got += r }
                if (got < chunk) continue
                // audio brut (480 échantillons de contexte), comme openWakeWord
                val joined = FloatArray(raw.size + chunk); System.arraycopy(raw, 0, joined, 0, raw.size)
                for (i in 0 until chunk) joined[raw.size + i] = buf[i].toFloat()
                raw = if (joined.size > chunk + 480) joined.copyOfRange(joined.size - chunk - 480, joined.size) else joined
                // spectrogramme mel
                OnnxTensor.createTensor(env, FloatBuffer.wrap(raw), longArrayOf(1, raw.size.toLong())).use { t ->
                    mel.run(mapOf("input" to t)).use { out ->
                        val fb = (out[0] as OnnxTensor).floatBuffer
                        val frames = fb.remaining() / 32
                        for (f in 0 until frames) melBuf.add(FloatArray(32) { fb.get() / 10f + 2f })
                    }
                }
                while (melBuf.size > 970) melBuf.removeAt(0)
                // embedding des 76 dernières trames
                val win = FloatArray(76 * 32); for (i in 0 until 76) System.arraycopy(melBuf[melBuf.size - 76 + i], 0, win, i * 32, 32)
                OnnxTensor.createTensor(env, FloatBuffer.wrap(win), longArrayOf(1, 76, 32, 1)).use { t ->
                    emb.run(mapOf("input_1" to t)).use { out -> val fb = (out[0] as OnnxTensor).floatBuffer; feats.add(FloatArray(96) { fb.get() }) }
                }
                while (feats.size > 120) feats.removeAt(0)
                if (feats.size < 16) continue
                // détection
                val x = FloatArray(16 * 96); for (i in 0 until 16) System.arraycopy(feats[feats.size - 16 + i], 0, x, i * 96, 96)
                val score = OnnxTensor.createTensor(env, FloatBuffer.wrap(x), longArrayOf(1, 16, 96)).use { t ->
                    ww.run(mapOf("x.1" to t)).use { out -> (out[0] as OnnxTensor).floatBuffer.get() }
                }
                hits = if (score >= thr) hits + 1 else 0
                if (hits >= 1) { rec.stop(); rec.release(); running = false; onWake(); return }
            }
            rec.stop(); rec.release()
        } catch (e: Exception) {
            prefs.edit().putString("wake_error", e.toString()).apply()
            running = false; stopSelf()
        }
    }

    private fun onWake() {
        val svc = JarvisInteractionService.instance
        if (svc != null) svc.showSession(Bundle(), 0)
        else startActivity(Intent(this, MainActivity::class.java).putExtra("listen", true).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        stopSelf()
    }

    override fun onDestroy() { running = false; super.onDestroy() }
}
