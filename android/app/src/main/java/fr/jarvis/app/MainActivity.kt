package fr.jarvis.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.view.WindowManager
import android.webkit.*
import android.widget.EditText
import org.json.JSONArray
import org.json.JSONObject
import android.speech.tts.TextToSpeech
import java.util.Locale
import kotlin.concurrent.thread

/** Jarvis en plein écran : l'interface 3D (via Tailscale) + micro natif + accès écran verrouillé. */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private var recognizer: SpeechRecognizer? = null
    private val prefs by lazy { getSharedPreferences("jarvis", MODE_PRIVATE) }
    private val defaultUrl = "https://desktop-u3cjv20.tail877ffc.ts.net/"
    private val LOCAL = "https://appassets.androidplatform.net/index.html"   // interface embarquée (marche sans réseau)
    private var tts: TextToSpeech? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setShowWhenLocked(true); setTurnScreenOn(true)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val need = mutableListOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.CAMERA)
        if (android.os.Build.VERSION.SDK_INT >= 33) need.add(Manifest.permission.POST_NOTIFICATIONS)
        val missing = need.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), 1)

        web = WebView(this)
        setContentView(web)
        with(web.settings) {
            javaScriptEnabled = true; domStorageEnabled = true; mediaPlaybackRequiresUserGesture = false
            cacheMode = WebSettings.LOAD_DEFAULT
        }
        web.addJavascriptInterface(Bridge(), "JarvisAndroid")
        web.webChromeClient = object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest) { runOnUiThread { request.grant(request.resources) } }
        }
        tts = TextToSpeech(this) { if (it == TextToSpeech.SUCCESS) tts?.language = Locale.FRANCE }
        try {
            LocalBrain.ensure(this)
            getSystemService(android.net.ConnectivityManager::class.java).registerDefaultNetworkCallback(object : android.net.ConnectivityManager.NetworkCallback() {
                override fun onAvailable(n: android.net.Network) {
                    try { LocalBrain.ensure(this@MainActivity) } catch (_: Exception) {}
                    runOnUiThread { if (web.url?.contains("appassets.androidplatform.net") == true) web.loadUrl(url()) }
                }
            })
        } catch (e: Exception) { prefs.edit().putString("wake_error", "réseau : ${e.message}").apply() }
        web.webViewClient = object : WebViewClient() {
            // sert l'interface embarquée dans l'appli (assets/www) : Jarvis s'ouvre même sans Wi-Fi ni données
            override fun shouldInterceptRequest(view: WebView, req: WebResourceRequest): WebResourceResponse? {
                if (req.url.host != "appassets.androidplatform.net") return null
                val path = "www" + (req.url.path ?: "/index.html").let { if (it == "/") "/index.html" else it }
                return try {
                    val mime = when (path.substringAfterLast('.')) { "html" -> "text/html"; "js" -> "text/javascript"; "css" -> "text/css"
                        "svg" -> "image/svg+xml"; "json" -> "application/json"; "woff2" -> "font/woff2"; "wasm" -> "application/wasm"; "png" -> "image/png"
                        else -> "application/octet-stream" }
                    WebResourceResponse(mime, "utf-8", assets.open(path))
                } catch (e: Exception) { WebResourceResponse("text/plain", "utf-8", 404, "absent", null, null) }
            }
            override fun onPageFinished(view: WebView, url: String) { if (pendingListen) { pendingListen = false; startConversation() } }
            override fun onReceivedError(view: WebView, req: WebResourceRequest, err: WebResourceError) {
                if (req.isForMainFrame && req.url.host != "appassets.androidplatform.net") view.loadUrl(LOCAL)   // PC injoignable : interface embarquée
            }
        }
        web.setOnLongClickListener { askUrl(); true }
        handle(intent)
        web.loadUrl(if (online()) url() else LOCAL)
    }

    private fun online(): Boolean = try {
        val cm = getSystemService(android.net.ConnectivityManager::class.java)
        cm.getNetworkCapabilities(cm.activeNetwork)?.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_INTERNET) == true
    } catch (e: Exception) { true }

    private fun url() = prefs.getString("url", defaultUrl)!!

    private fun askUrl() {
        val box = android.widget.LinearLayout(this).apply { orientation = android.widget.LinearLayout.VERTICAL; setPadding(40, 20, 40, 0) }
        val input = EditText(this).apply { setText(url()); hint = "Adresse de Jarvis" }
        val sw = android.widget.Switch(this).apply { text = "Écoute « Hey Jarvis » en arrière-plan"; isChecked = WakeService.enabled(this@MainActivity) }
        val sens = android.widget.SeekBar(this).apply { max = 80; progress = ((0.9f - WakeService.threshold(this@MainActivity)) * 100).toInt().coerceIn(0, 80) }
        val lbl = android.widget.TextView(this).apply { text = "Sensibilité (vers la droite = réagit plus facilement)" }
        val err = prefs.getString("wake_error", "")
        box.addView(input); box.addView(sw); box.addView(lbl); box.addView(sens)
        AlertDialog.Builder(this).setTitle("Réglages Jarvis").setView(box)
            .setMessage(if (err.isNullOrBlank()) "Quittez l'appli, puis dites « Hey Jarvis »." else "Dernière erreur d'écoute : $err")
            .setPositiveButton("OK") { _, _ ->
                prefs.edit().putString("url", input.text.toString().trim()).putBoolean("wake_on", sw.isChecked)
                    .putFloat("wake_thr", 0.9f - sens.progress / 100f).putString("wake_error", "").apply()
                web.loadUrl(url())
            }
            .setNegativeButton("Annuler", null).show()
    }

    // Micro libre pour l'appli quand elle est ouverte ; écoute du mot « Jarvis » quand elle est en arrière-plan
    override fun onResume() { super.onResume(); WakeService.stop(this) }
    override fun onPause() { super.onPause(); WakeService.start(this) }

    private var pendingListen = false
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); handle(intent); if (!pendingListen) return; pendingListen = false; startConversation() }
    private fun handle(i: Intent?) {
        if (i?.action == Intent.ACTION_ASSIST || i?.action == Intent.ACTION_VOICE_COMMAND || i?.getBooleanExtra("listen", false) == true)
            pendingListen = true
    }

    /** Lance la conversation vocale dans l'interface (bouton ∞). */
    private fun startConversation() {
        web.postDelayed({ web.evaluateJavascript("window.jarvisAssist && window.jarvisAssist()", null) }, 900)
    }

    override fun onBackPressed() { if (web.canGoBack()) web.goBack() else super.onBackPressed() }
    override fun onDestroy() { recognizer?.destroy(); tts?.shutdown(); super.onDestroy() }

    /** Reconnaissance vocale native d'Android (utilisée quand le PC est éteint). */
    inner class Bridge {
        @JavascriptInterface fun listen() = runOnUiThread { listenNative() }
        @JavascriptInterface fun available() = SpeechRecognizer.isRecognitionAvailable(this@MainActivity)
        @JavascriptInterface fun online() = this@MainActivity.online()
        @JavascriptInterface fun kvGet(k: String): String? = getSharedPreferences("kv", MODE_PRIVATE).getString(k, null)
        @JavascriptInterface fun kvSet(k: String, v: String) = getSharedPreferences("kv", MODE_PRIVATE).edit().putString(k, v).apply()
        /** Voix native du téléphone (hors ligne). */
        @JavascriptInterface fun speak(text: String) {
            tts?.setSpeechRate(1.12f); tts?.setPitch(0.95f)
            tts?.setOnUtteranceProgressListener(object : android.speech.tts.UtteranceProgressListener() {
                override fun onStart(id: String?) {}
                override fun onDone(id: String?) = runOnUiThread { web.evaluateJavascript("window.onAndroidSpoken && window.onAndroidSpoken()", null) }
                @Deprecated("") override fun onError(id: String?) = onDone(id)
            })
            tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "j")
        }
        @JavascriptInterface fun stopSpeak() { tts?.stop() }
        /** Cerveau hors ligne : état, téléchargement, question (réponse via window.onLocalReply(id, texte)). */
        @JavascriptInterface fun brainStatus() = LocalBrain.status(this@MainActivity)
        @JavascriptInterface fun brainDownload() = LocalBrain.ensure(this@MainActivity, true)
        @JavascriptInterface fun localAsk(id: String, system: String, historyJson: String, user: String) {
            thread {
                val r = try {
                    val h = JSONArray(historyJson); val pairs = mutableListOf<Pair<String, String>>()
                    var i = 0
                    while (i + 1 < h.length()) { pairs.add(h.getJSONObject(i).optString("content") to h.getJSONObject(i + 1).optString("content")); i += 2 }
                    LocalBrain.ask(this@MainActivity, system, pairs, user)
                } catch (e: Throwable) { "Erreur du cerveau hors ligne : ${e.message}" }
                runOnUiThread { web.evaluateJavascript("window.onLocalReply && window.onLocalReply(${JSONObject.quote(id)}, ${JSONObject.quote(r)})", null) }
            }
        }
    }

    private fun listenNative() {
        recognizer?.destroy()
        recognizer = SpeechRecognizer.createSpeechRecognizer(this).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onResults(b: Bundle) {
                    val t = b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull() ?: ""
                    web.evaluateJavascript("window.onAndroidSpeech && window.onAndroidSpeech(${JSONObject.quote(t)})", null)
                }
                override fun onError(e: Int) { web.evaluateJavascript("window.onAndroidSpeech && window.onAndroidSpeech('')", null) }
                override fun onReadyForSpeech(p: Bundle?) {}
                override fun onBeginningOfSpeech() {}
                override fun onRmsChanged(v: Float) { web.evaluateJavascript("window.FX && (FX.level=${(v.coerceIn(0f, 10f) / 10f)})", null) }
                override fun onBufferReceived(b: ByteArray?) {}
                override fun onEndOfSpeech() {}
                override fun onPartialResults(b: Bundle?) {}
                override fun onEvent(t: Int, b: Bundle?) {}
            })
            startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "fr-FR")
                .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, !online()))
        }
    }
}
