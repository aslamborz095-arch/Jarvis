package fr.jarvis.app

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import com.google.mediapipe.tasks.genai.llminference.LlmInference
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/** Cerveau 100 % hors ligne sur le téléphone (Qwen 2.5 1,5 B via MediaPipe). Téléchargé une fois en Wi-Fi (~1,6 Go). */
object LocalBrain {
    private const val URL_MODEL = "https://huggingface.co/litert-community/Qwen2.5-1.5B-Instruct/resolve/main/Qwen2.5-1.5B-Instruct_multi-prefill-seq_q8_ekv1280.task"
    @Volatile var progress = -1          // -1 rien, 0..99 téléchargement, 100 prêt
    @Volatile var error = ""
    private var llm: LlmInference? = null
    private var downloading = false

    private fun file(c: Context) = File(c.filesDir, "brain.task")
    fun ready(c: Context) = file(c).exists()

    fun status(c: Context): String = when {
        ready(c) -> "ready"
        downloading -> "download:$progress"
        error.isNotEmpty() -> "error:$error"
        else -> "absent"
    }

    private fun wifi(c: Context): Boolean {
        val cm = c.getSystemService(ConnectivityManager::class.java)
        val caps = cm.getNetworkCapabilities(cm.activeNetwork) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED) && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    /** Télécharge le cerveau en arrière-plan (Wi-Fi seulement sauf si force). */
    fun ensure(c: Context, force: Boolean = false) {
        if (ready(c) || downloading || (!force && !wifi(c))) return
        downloading = true; error = ""
        thread(isDaemon = true) {
            val tmp = File(c.filesDir, "brain.part")
            try {
                var url = URL(URL_MODEL)
                var con: HttpURLConnection
                while (true) {      // suit les redirections (Hugging Face → CDN)
                    con = url.openConnection() as HttpURLConnection
                    con.instanceFollowRedirects = false
                    if (tmp.exists()) con.setRequestProperty("Range", "bytes=${tmp.length()}-")
                    val code = con.responseCode
                    if (code in 300..399) { url = URL(url, con.getHeaderField("Location")); continue }
                    break
                }
                val append = con.responseCode == 206
                val total = (if (append) tmp.length() else 0L) + con.contentLengthLong
                con.inputStream.use { inp ->
                    java.io.FileOutputStream(tmp, append).use { out ->
                        val buf = ByteArray(1 shl 16); var done = if (append) tmp.length() else 0L
                        while (true) {
                            val n = inp.read(buf); if (n < 0) break
                            out.write(buf, 0, n); done += n
                            if (total > 0) progress = (done * 99 / total).toInt()
                        }
                    }
                }
                tmp.renameTo(file(c)); progress = 100
            } catch (e: Exception) { error = e.message ?: "échec" } finally { downloading = false }
        }
    }

    @Synchronized
    fun ask(c: Context, system: String, history: List<Pair<String, String>>, user: String): String {
        if (!ready(c)) return "Mon cerveau hors ligne n'est pas encore installé, monsieur. Il se télécharge au prochain passage en Wi-Fi."
        if (llm == null) llm = LlmInference.createFromOptions(c,
            LlmInference.LlmInferenceOptions.builder().setModelPath(file(c).path).setMaxTokens(1280).build())
        val p = StringBuilder("<|im_start|>system\n$system<|im_end|>\n")
        for ((u, a) in history.takeLast(4)) p.append("<|im_start|>user\n$u<|im_end|>\n<|im_start|>assistant\n$a<|im_end|>\n")
        p.append("<|im_start|>user\n$user<|im_end|>\n<|im_start|>assistant\n")
        return llm!!.generateResponse(p.toString()).substringBefore("<|im_end|>").trim()
    }
}
