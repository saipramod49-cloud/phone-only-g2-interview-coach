# Live practice beta

This replaces sample content with G2 PCM audio, server-side transcription, and streamed OpenAI answers. It is a first live test, not a completed continuous interview assistant.

## Deploy backend first

Use the existing Render service `phone-only-g2-interview-coach-fawf`. Deploy this source revision with the existing Docker service rooted at `backend` (Python 3.12). Keep its existing APP_TOKEN, OPENAI_API_KEY, OPENAI_MODEL, and persistent /data disk. Do not paste credentials into GitHub or the app package. If automatic deployments are disabled, use Render's manual deploy for the updated branch. `/health` must return `live_protocol: 1` before testing the new package. Existing `/v1/chat/completions` and `/ws/glasses` routes remain available.

## Install in the existing developer app

Upload `outputs/practice-live-0.2.0.ehpk` to the existing Practice Preview project. It retains package ID `com.practice.g2preview` and upgrades 0.1.1 to 0.2.0. Required Even app version: 2.2.10. Grant the G2 microphone and network permissions. Keep this build in private/beta testing.

Open the installed app. Enter Render's APP_TOKEN (not the OpenAI API key); it remains in memory only. Press Start practice. The backend authenticates via the first encrypted WebSocket message, not a URL token. Audio starts only after OpenAI acknowledges session setup. Ask one question, then pause. The microphone turns off and the generated answer streams to G2. Swipe to read additional pages. Tap the glasses or Next question on the phone to capture a follow-up. Pause and Stop retain the last answer. Stop closes the conversation; a new Start begins fresh context.

Use the existing Render home page to upload candidate documents. Claims about personal experience remain grounded in those materials. The preview's former fixed samples are not included in this live build.

## Validation

Automated tests cover streaming before provider completion, mocked G2 audio-to-answer protocol, authentication rejection, follow-up history, ignored audio after question capture, upstream setup failure, stale answer rejection, pagination, and display retention. These use fake provider responses; they do not prove real API or hardware behavior.

On G2 test: (1) ask a technical question; (2) verify a real transcript and answer; (3) read it aloud while mic is off; (4) wait and confirm answer remains; (5) tap and ask “Why?” to test context; (6) test Pause, Stop, double-tap exit, bad token, and network loss. Record observed latency. Check phone background/lock behavior separately; continuous locked-phone capture is not certified.

Not implemented here: automatic speaker recognition, continuous hands-free question detection, semantic speech-follow scrolling, reconnection with preserved history, or a production latency guarantee. Each explicit capture ends at the first nonempty finalized utterance; a long pause inside a question may end it early. This limitation must be tested with natural questions before release.
