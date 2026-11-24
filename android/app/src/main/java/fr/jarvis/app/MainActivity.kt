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
import org.json.JSONObject

/** Jarvis en plein écran : l'interface 3D (via Tailscale) + micro natif + accès écran verrouillé. */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private var recognizer: SpeechRecognizer? = null
    private val prefs by lazy { getSharedPreferences("jarvis", MODE_PRIVATE) }
    private val defaultUrl = "https://desktop-u3cjv20.tail877ffc.ts.net/"

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
        web.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView, url: String) { if (pendingListen) { pendingListen = false; startConversation() } }
            override fun onReceivedError(view: WebView, req: WebResourceRequest, err: WebResourceError) {
                if (req.isForMainFrame) view.loadData(
                    "<body style='background:#010409;color:#35e0ff;font-family:sans-serif;text-align:center;padding-top:35vh'>" +
                    "<h2>Jarvis injoignable</h2><p>Active Tailscale puis touche l'écran.</p>" +
                    "<script>document.body.onclick=()=>location.href='${url()}'</script></body>", "text/html", "utf-8")
            }
        }
        web.setOnLongClickListener { askUrl(); true }
        handle(intent)
        web.loadUrl(url())
    }

    private fun url() = prefs.getString("url", defaultUrl)!!

    private fun askUrl() {
        val box = android.widget.LinearLayout(this).apply { orientation = android.widget.LinearLayout.VERTICAL; setPadding(40, 20, 40, 0) }
        val input = EditText(this).apply { setText(url()); hint = "Adresse de Jarvis" }
        val key = EditText(this).apply { setText(WakeService.key(this@MainActivity)); hint = "Clé Picovoice (mot « Jarvis »)" }
        val err = prefs.getString("wake_error", "")
        box.addView(input); box.addView(key)
        AlertDialog.Builder(this).setTitle("Réglages Jarvis").setView(box)
            .setMessage(if (err.isNullOrBlank()) "Clé gratuite : console.picovoice.ai" else "Dernière erreur d'écoute : $err")
            .setPositiveButton("OK") { _, _ ->
                prefs.edit().putString("url", input.text.toString().trim()).putString("pv_key", key.text.toString().trim())
                    .putString("wake_error", "").apply()
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
    override fun onDestroy() { recognizer?.destroy(); super.onDestroy() }

    /** Reconnaissance vocale native d'Android (utilisée quand le PC est éteint). */
    inner class Bridge {
        @JavascriptInterface fun listen() = runOnUiThread { listenNative() }
        @JavascriptInterface fun available() = SpeechRecognizer.isRecognitionAvailable(this@MainActivity)
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
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "fr-FR"))
        }
    }
}
