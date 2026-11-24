"""IA connues (API compatible OpenAI). rank : ordre d'essai, du plus puissant au plus modeste.
Données vérifiées sur la documentation des fournisseurs (novembre 2026) ; modèles modifiables."""
PRESETS = {
    # --- payants (essayés en premier s'ils sont ajoutés) ---
    "openai":   {"name": "OpenAI", "tier": "top", "rank": 10, "free": False, "base": "https://api.openai.com/v1", "model": "gpt-6.1-terra",
                 "signup": "https://platform.openai.com/api-keys", "note": "Payant à l'usage."},
    "xai":      {"name": "Grok (xAI)", "tier": "top", "rank": 12, "free": False, "base": "https://api.x.ai/v1", "model": "grok-4.7",
                 "signup": "https://console.x.ai", "note": "Payant à l'usage."},
    "deepseek": {"name": "DeepSeek", "tier": "top", "rank": 14, "free": False, "base": "https://api.deepseek.com", "model": "deepseek-v4-pro",
                 "signup": "https://platform.deepseek.com/api_keys", "note": "Payant, très bon marché."},
    "together": {"name": "Together AI", "tier": "mid", "rank": 16, "free": False, "base": "https://api.together.ai/v1", "model": "openai/gpt-oss-120b",
                 "signup": "https://api.together.ai/settings/api-keys", "note": "Payant à l'usage."},
    # --- gratuits ---
    "gemini":   {"name": "Google Gemini", "tier": "mid", "rank": 20, "free": True, "base": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-3.5-flash",
                 "signup": "https://aistudio.google.com/apikey", "note": "Gratuit avec ton compte Google, sans carte. Très bon."},
    "groq":     {"name": "Groq", "tier": "fast", "rank": 22, "free": True, "base": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b",
                 "signup": "https://console.groq.com/keys", "note": "Gratuit, sans carte, ultra rapide."},
    "cerebras": {"name": "Cerebras", "tier": "fast", "rank": 24, "free": True, "base": "https://api.cerebras.ai/v1", "model": "gpt-oss-120b",
                 "signup": "https://cloud.cerebras.ai", "note": "Essai gratuit (crédits offerts), très rapide."},
    "mistral":  {"name": "Mistral", "tier": "mid", "rank": 26, "free": True, "base": "https://api.mistral.ai/v1", "model": "mistral-large-latest",
                 "signup": "https://console.mistral.ai/api-keys", "note": "Gratuit (plan Experiment, numéro de téléphone demandé). IA française."},
    "sambanova": {"name": "SambaNova", "tier": "fast", "rank": 28, "free": True, "base": "https://api.sambanova.ai/v1", "model": "gpt-oss-120b",
                  "signup": "https://cloud.sambanova.ai/apis", "note": "Gratuit avec limites."},
    "openrouter": {"name": "OpenRouter", "tier": "fast", "rank": 30, "free": True, "base": "https://openrouter.ai/api/v1", "model": "openai/gpt-oss-120b:free",
                   "signup": "https://openrouter.ai/keys", "note": "Modèles « :free » : 50 requêtes/jour gratuites."},
}
