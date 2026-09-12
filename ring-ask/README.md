# Ring Ask 0.2.0

Personal G2/R1 assistant using your existing Render-hosted Sol agent, OpenAI key, bridge token, and candidate profile. Native Even AI is preserved separately.

## What changed

- Streams the entire answer as text arrives. The previous ring implementation incorrectly returned only the first native voice page and waited for completion.
- Natural connected first-person answers grounded in your saved background. Current QFC work uses Mizuho/Snowflake/TIDAL; Priceline experimentation and incidents stay correctly attributed. No invented experience to fill missing details.
- Choose Brief (40–65 words), Natural (80–120), or Detailed (140–190). These are model targets, not guaranteed exact lengths.
- Reading preferences: 2–7 visible lines; up to 2–12 words per line; width; horizontal/vertical position; 1–3 lines per swipe; 60–240 words/min auto-scroll. Text may wrap earlier to fit long words. Font size and perceived optical distance cannot be changed by this SDK.
- Scroll one line at a time instead of replacing a full page. Auto-scroll advances at your reading speed; the SDK does not expose pixel-smooth animation.
- Stores connection settings in the phone and, when available, Even's native plugin storage. Saves the last answer and reading position on the phone. Rechecks the server automatically on startup, online, and resume.
- Bounded reconnect attempts restore the glasses display after device reconnection, foreground events, and failed display writes. Missing microphone audio is detected. Interrupted recordings are discarded; tap again after recovery. No automatic resubmission of audio or duplicate AI charges.
- Retry last question explicitly resends the last submitted audio held only in memory. A cancelled server request may still finish and incur API usage.
- First-word and complete-answer timing is visible on the phone. Audio samples, API keys, and tokens are never printed in diagnostic output.

## Controls

Tap: start recording (when ready). Wait for Listening before speaking.
Double-tap while recording: stop and submit.
Swipe up/down: move through the answer by the chosen line count.
Double-tap while idle: pause/start auto-scroll.
Optional Hold mode: sustained press starts; release submits. Tap-then-hold opens the OS menu instead.
Close the plugin from the OS menu or the phone's Connection & recovery section.
A recording stops at 90 seconds. A new question does not erase the displayed answer until it is submitted.

## Setup and launch

Server: https://phone-only-g2-interview-coach-fawf.onrender.com
Phone page: https://phone-only-g2-interview-coach-fawf.onrender.com/ring/?v=0.2.0

Enter the SAME bridge token used by your native Even AI custom agent once, then Save & check connection. The OpenAI API key stays on Render. Settings save automatically after that.

Requires Even Realities app 2.2.10+ and compatible G2/R1 firmware.

QR: Scan the adjacent ring-ask-qr.png inside Even Hub's developer testing scanner. Close the previous prototype first; confirm v0.2.0 in the header. This remains a prototype session, not a persistent installed app.

For an app card and glasses-menu launch, sign into https://hub.evenrealities.com using the same Even account as the phone. Upload ring-ask.ehpk using the portal's private/beta testing flow, install the resulting build in the phone app, then select Ring Ask among the plugins shown in the glasses menu. The prototype cannot add itself to the system menu. No public store submission has been made.

The plugin recovers while its WebView remains alive and after it resumes. It cannot restart itself after the phone OS kills it or after you close it. Installed/beta builds must be tested on your actual phone with the screen locked. If the OS ends the session, reopen Ring Ask from its installed card/menu.

## Closest display distance

In the Even phone app, open Display Adjustment → Near. This is Even's closest supported preset, approximately 1 m for the foreground plane, varying with the wearer. Move Display Height there for the whole glasses UI, or use this plugin's x/y controls to place its text area. A software plugin cannot move the optical focal plane closer than the hardware presets.

## Verification

28 local tests pass: microphone gesture sequencing/cancellation, bounded capture, full-answer streaming beyond 360 characters, follow-up context, interrupted-stream lock release, authentication, WAV encoding, reader bounds, line/word counts and bridge-call deadlines. TypeScript/Vite build and Even packaging pass. SDK validates 2-, 4- and 7-line display layouts. Browser checks verified 3 lines, 5 words/line, overlapping one-line scrolling and automatic reading.

Three profile-grounded model tests returned first text in roughly 0.9–1.1 seconds in the final prompt evaluation; this excludes audio transcription, phone network and BLE/display latency. See natural-answer-evaluation.json beside the project. Hardware dropout recovery, comfort and locked-phone operation still require testing on your G2/R1.

```
npm ci
npm test
python3 -m unittest discover -s tests -p 'test_*.py'
npm run pack
```

Source changes live under ring-ask/ in the existing GitHub repo. Render serves the prebuilt sol-bridge/ring-ui assets. Copy rebuilt dist/ there for a frontend deploy; cloud/ring_api.py and cloud/ring_agent.py go into sol-bridge/. Keep the existing Docker context and environment variables.

Sources:
- https://support.evenrealities.com/hc/en-us/articles/15688149217167-Even-Hub
- https://support.evenrealities.com/hc/en-us/articles/13755064994831-Display-Adjustment
- https://hub.evenrealities.com/docs/build/device-apis
- https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
