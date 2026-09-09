# Interview Lens for Even G2

Interview Lens is a phone-only runtime for live interviews. After installation and deployment, it needs only the user's iPhone, the Even Realities phone app, Even G2 glasses, and mobile internet. No laptop, home server, Hermes gateway, Tailscale node, or MacBook remains in the runtime path.

## What is delivered

- `outputs/g2-interview-coach.ehpk`: installable Even Hub package.
- `src/`: the glasses + phone companion app. The G2 four-microphone PCM stream goes directly from the phone-hosted Even WebView to the backend over WSS.
- `backend/`: deployable FastAPI service with an iPhone-friendly profile manager, document extraction, local indexed retrieval, streaming Deepgram speech-to-text, question gating, streamed OpenAI answers, and latency records.
- `backend/render.yaml`: a one-service Render deployment blueprint with persistent encrypted-at-rest disk support (subject to the host plan).

## Architecture

```text
G2 mic/display
   │ BLE (managed by Even app)
   ▼
iPhone · Even app · Interview Lens plugin
   │ 16 kHz PCM over WSS          ▲ streamed answer deltas
   ▼                              │
Hosted Interview Lens service ────┘
   ├─ OpenAI Realtime streaming STT + server VAD endpointing
   ├─ conservative question gate
   ├─ SQLite profile/document store + in-process BM25-like retrieval
   └─ OpenAI Responses streaming generation
```

Documents and provider credentials never ship in the `.ehpk`. The app stores only the service URL and an app access token using the Even SDK's phone-side local storage. Provider keys are server environment variables. Uploaded text is stored on the service's persistent volume; choose a region/provider appropriate for the user's privacy obligations.

## Deploy once (no laptop needed afterward)

### Simplest: Render

1. Put this repository in a private GitHub repository.
2. In Render, create a Blueprint using `backend/render.yaml` with root directory `backend`.
3. Add the secret value for `OPENAI_API_KEY`. Render generates `APP_TOKEN`; reveal/copy it once for setup.
4. Use a paid always-on instance in a region near the interview. Free instances may sleep and cannot meet latency targets. Confirm `/health` returns `{"ok":true}`.
5. Open the public service URL on the iPhone. Enter `APP_TOKEN`, create/select an interview profile, paste the target job description, and upload candidate materials.
6. Open Interview Lens inside the Even app. On its phone surface enter the HTTPS service URL and `APP_TOKEN`, then tap **Save & connect**.

The included whitelist accepts `*.onrender.com`. For another host or a custom domain, add that exact HTTPS/WSS origin to `app.json`, rebuild, and repackage; Even Hub network permissions are deliberately restrictive.

### Self-hosted cloud

Copy `backend/.env.example` to `backend/.env`, populate secrets, and deploy `backend/docker-compose.yml` on an always-on HTTPS host. Put a TLS reverse proxy/load balancer in front of port 8080 and preserve WebSocket upgrades. Back up the `interview-data` volume. A single process is intentional because SQLite and the in-memory retrieval index are single-user oriented.

## Install the Even Hub package

The `.ehpk` can be uploaded as a private build in the Even Hub developer portal, then installed from the Even app. Initial developer sideloading may still require the Even developer workflow and a computer; the production interview runtime does not. Even's current QR development path serves a local build, so it is not a phone-only installation mechanism.

## Profile materials

The mobile manager supports PDF, DOCX, TXT, Markdown, and CSV up to 8 MB each. Use separate materials for resume, professional profile, responsibilities, and project details. Scanned/image-only PDFs require OCR before upload. Each interview profile owns its job description and files; activating one changes grounding for the next glasses connection.

Grounding is lexical and local, avoiding a second model/embedding round trip. Retrieved excerpts and the selected job description are passed to the answer model with an explicit no-fabrication policy. This reduces invention risk but cannot guarantee factual output; the wearer must review and speak only truthful content.

## Interview operation

1. Select the correct profile in the phone manager before connecting the glasses.
2. Open Interview Lens on the G2 and leave it open. It begins listening automatically.
3. The server ignores short/background statements and generates only after a final utterance matches an interrogative or interview-question pattern.
4. The first useful answer text streams to the display immediately. Close the app or tap **Stop listening** on the phone surface to stop audio.

The display uses supported native text only. Even Hub currently provides no bold, italic, font-size, or per-span styling in text containers. `**keywords**` produced by the model are converted to uppercase; `ACTION`, `RESULT`, and similar labels plus `›` bullets provide reliable supported emphasis. Updates use `textContainerUpgrade` to avoid rebuild flicker.

## Latency measurement and claim boundary

The manager records, for live questions:

- `stt_ms`: capture segment start through the STT final/question endpoint event. This includes speech duration and endpointing, so compare like-for-like questions.
- `retrieval_ms`: local evidence selection.
- `model_first_token_ms`: question detection through the first model delta; currently includes retrieval and model request.
- `total_ms`: question detection through complete generated answer.
- `transport_ms`: half of the server-to-phone display acknowledgement round trip (an estimate, reported `n/a` when no acknowledgement arrives).
- `display_estimate_ms`: elapsed time for the phone to complete the Even SDK `textContainerUpgrade` call (reported `n/a` when absent). This is separate instrumentation, not a photons-on-lens guarantee because the SDK has no display-presented event.

This deliverable does **not** claim sub-2-second end-to-end performance: hardware credentials and an actual G2/iPhone session were unavailable here, and the platform cannot acknowledge display presentation. The architecture removes the former laptop hop and streams immediately, but the first-content target must be validated on the user's hardware. For defensible end-to-end measurement, video the interviewer/audio waveform and the lens through an optical fixture using a shared high-frame-rate clock; report median, p95, mobile carrier, phone model, firmware, region, and provider models.

## Cost and production notes

Ongoing cost has two providers: an always-on web service/persistent disk, plus OpenAI transcription and answer-generation usage. Exact prices change; consult the selected host and OpenAI pricing pages before deployment. Set API spend limits and alerts.

Before production use, replace the shared token with an identity provider if multiple users are added, encrypt especially sensitive fields at the application layer, define retention/deletion policy, add rate limiting at the edge, and obtain all legally required consent for recording/transcription. Laws and interview policies vary. Do not use the system where assistance or recording is prohibited.

## Verification

```bash
npm test
npm run build
npm run pack
PYTHONPATH=backend python -m pytest backend/tests -q
docker compose -f backend/docker-compose.yml config
```

Provider integration tests require real credentials and incur usage. A live G2 verification requires the device, current Even app, mobile network, and deployed HTTPS service.
