# Ring Ask — first version

A G2 / R1 plugin that uses your existing Render-hosted Even AI Sol agent and saved profile.

## Status

Built and packaged locally. The live Render service has NOT yet been updated. The new audio endpoint must be deployed before real questions work. Hardware timing and locked-phone operation have not yet been verified on your G2/R1.

- Single tap: start a new recording when ready.
- Double tap while recording: stop and submit the question.
- Scroll up/down: previous/next answer page.
- Double tap when idle: system exit confirmation.
- Optional Hold mode: sustained press starts, release submits. Wait for Listening before speaking. Tap then long press belongs to the system menu; use a sustained press alone.
- Phone Cancel: discard a recording or stop waiting for an answer. A request already received by the server may finish and incur API usage.
- Recording ends automatically at 90 seconds. Background/exit events discard an active recording.

Requires Even Realities app 2.2.10+ for the bundled SDK 0.0.15. Update G2/R1 firmware to a compatible version through the Even app.

## Your existing service

Server: https://phone-only-g2-interview-coach-fawf.onrender.com

The plugin calls the added /api/ask route. Your original /v1/chat/completions agent remains available, using the existing OPENAI_MODEL, BRIDGE_TOKEN, OPENAI_API_KEY, and profile configuration. No second Render service or new OpenAI key is needed.

In the plugin's phone screen, enter the SAME bridge token already used for the native Even AI custom agent, then Save & check connection. Do not enter the OpenAI API key on the phone. The bridge token is stored locally by the plugin so you only enter it once. Server and token must be configured before asking questions.

Audio goes to OpenAI for transcription after submission. The transcript goes through the existing personalized Sol conversation. V1 returns the transcript followed by the completed answer, rather than token-by-token Sol output. It does not continuously detect speakers/questions. There is no live web search. Raw recordings are held in memory, not saved by this code.

## Install / test after deployment

1. Open the Even Hub developer portal using the same account as the Even phone app. Enable the available prototype/private testing flow.
2. Import `ring-ask.ehpk` as a private test build using Even Hub. The package itself contains no API key or bridge token.
3. Launch Ring Ask, open its phone settings, enter your existing bridge token, and check the connection.
4. Tap the ring, wait for Listening, ask a short question, double-tap, then scroll the answer.
5. Test Hold mode only after the tap flow works. Test the phone locked and after switching apps; restart the plugin if the phone suspends it.

For QR local testing: `npm ci`, `npm run dev`, then `npx evenhub qr --url "http://YOUR-LAPTOP-IP:5173/"`. Phone and laptop must share a network. Local testing requires the laptop to stay on; installed private builds use Render directly.

## Build / verification

```
npm ci
npm test
python3 -m unittest discover -s tests -p 'test_*.py'
npm run pack
```

17 focused tests cover gesture/audio state, fast release during microphone startup, duplicate taps, cancellation, duration cap, pagination, authorization, WAV encoding, route isolation, and error recovery. TypeScript and Vite builds pass; browser sample pagination was checked. No paid live transcription has been performed for this build.

## Deploy to the existing repository

Apply the adjacent `render-ring-update.patch` at the root of `phone-only-g2-interview-coach`. The patch updates `sol-bridge/cloud_app.py` and its Dockerfile, adds `ring_api.py` and prebuilt `ring-ui` assets, and includes Ring Ask source under `ring-ask/`. Keep Render's existing Docker context `sol-bridge` and existing environment variables. No credential changes are required.

After deployment, verify /health, authenticated /api/health, a short audio request, and the original native agent. Open /ring/ to configure the companion UI. Roll back the deployment to the preceding Render commit if needed.

References:
- https://hub.evenrealities.com/docs/build/device-apis
- https://hub.evenrealities.com/docs/ship/packaging
- https://developers.openai.com/api/docs/guides/speech-to-text
