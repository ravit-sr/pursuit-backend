# Known Issues

## Gemini API — 401 `ACCESS_TOKEN_TYPE_UNSUPPORTED`

**Status:** Blocked on Google's side, not a bug in this codebase.
**Affected features:** Resume analysis (`POST /resumes/{id}/analyze`), Resume Coach chat (`POST /resumes/{id}/chats/{chat_id}/messages`), Dashboard AI insights (`POST /applications/insights/generate`).

### Symptom
All three features return a clean `502 "...temporarily unavailable"` to the user. The server log shows the real cause underneath:

```
ClientError("401 UNAUTHENTICATED. {'error': {'code': 401, 'message': 'Request had invalid
authentication credentials. Expected OAuth 2 access token, login cookie or other valid
authentication credential...', 'status': 'UNAUTHENTICATED', 'details': [{'reason':
'ACCESS_TOKEN_TYPE_UNSUPPORTED', ...}]}")
```

### Root cause
Since mid-June 2026, Google AI Studio has stopped issuing the legacy `AIzaSy...`-format API keys and now issues `AQ.`-prefixed "Auth keys" instead, even for brand-new keys in brand-new projects. These `AQ.` keys are rejected by the `generativelanguage.googleapis.com` REST endpoint with the error above — this happens via the official `google-genai` Python SDK (which this project uses) just as it does via raw `curl`. It is not caused by an expired key, a bad rotation, missing billing, or a code issue on our end.

This is a widely-reported, currently open issue on Google's own developer forum (dozens of near-identical threads as of July 2026), with no fix shipped yet. Google has additionally stated old `AIza` keys will stop working entirely by September 2026, so reverting to an old-format key is not a viable workaround either.

Reference: [Google AI Developers Forum — search "ACCESS_TOKEN_TYPE_UNSUPPORTED"](https://discuss.ai.google.dev/)

### What was tried
- Rotated the Gemini API key — new key is also `AQ.`-prefixed; same failure.
- Confirmed the error occurs through the official SDK (`genai.Client(api_key=...)`), not just raw REST calls.
- Confirmed `main.py`'s error handling itself works correctly — it catches the SDK exception and returns a clean 502 rather than crashing, so the app degrades gracefully.

### Path to a real fix (not yet implemented)
Switch these three call sites from AI Studio API-key auth to **Vertex AI**, which uses OAuth2/service-account auth and is not affected by this bug. Requires:
- A GCP project with billing enabled
- A service account with Vertex AI access
- Replacing `genai.Client(api_key=GEMINI_API_KEY)` with Vertex-mode client initialization in `call_gemini_resume_analysis`, `call_gemini_chat`, and `call_gemini_insights` (`main.py`)

This is a real chunk of new work, not a config tweak, and has been deferred for now.