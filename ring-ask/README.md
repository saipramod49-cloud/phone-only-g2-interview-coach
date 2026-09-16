# Ring Ask v0.7.10

Open [Ring Ask in Even Hub](https://hub.evenrealities.com/landing?package_id=com.saipramod.ringask), the [live Render app](https://phone-only-g2-interview-coach-fawf.onrender.com/ring/), or the [GitHub source](https://github.com/saipramod49-cloud/phone-only-g2-interview-coach).

Choose one listening mode in Listening & answer settings:

- Tap mode: tap starts capture, the next deliberate tap stops and submits. Release does nothing.
- Hold mode: hold throughout the question, release to submit. Both modes support up to five minutes.
- Double tap opens the next answer page. Triple tap blanks or restores the lens without opening the firmware menu, so Ring Ask retains ring event capture. Neither gesture changes answer style or opens the microphone.
- Swipe up for older answers and down for newer/current answers. The last 30 completed answers are saved on this phone.

Starting or cancelling a recording preserves the previous completed answer. The ring handler disambiguates single, double, and triple taps and accepts SDK input envelopes with an omitted zero event enum. Accidental holds in tap mode do not start capture. Returning from a system menu rebuilds the app display when the firmware sends the foreground event. The app cannot override firmware-owned controls or receive ring events after it has been closed.

Every answer page has a question and page/history status. Choose question above/answer below or question left/answer right. Reading settings support width, position, 1–10 requested lines, 1–10 words or automatic wrapping, and Native/18/22/26/30px fonts. The physical 576×288 display limits the lines that fit; the UI reports the effective count. Long questions are abbreviated on the lens and remain complete on the phone. Native emphasis uses capitals; the phone and bitmap fonts also use bold. Code retains indentation and is paginated without dropping text.

There is one answer style, adapted to the request: readable conversational paragraphs, a matching flow for architecture where useful, and actual SQL/Python/PySpark code first when requested. Follow-ups retain conversation context. Resume and prep notes guide relevant answers without limiting help on unfamiliar stacks. Proposed experience uses conditional language rather than invented personal claims. The next-answer instruction box can refine answers without a deployment.

Ring Ask defaults to GPT-6 Astra with low reasoning effort, independently of the legacy agent model. Set RING_MODEL to override. The authenticated /api/health reports the deployed model, prompt style, version, and recording limit. Measured latency varies with transcription, model service, network, and glasses rendering.

Wake recovery in v0.7.8 is available inside the glasses menu. **Start listening** is the first plugin action, directly above **Resume Ring Ask**; it force-rebuilds ring capture and opens the glasses microphone. **Resume Ring Ask** force-rebuilds controls without recording, and returning from the system menu triggers that rebuild automatically.

Latency optimization sends a compact, question-relevant slice of the candidate profile and routes normal interview questions to GPT-5.6 Sol. GPT-6 Astra is reserved for leadership and HR-style behavioral questions. Independent questions do not inherit previous answers; explicit follow-ups retain the two recent exchanges needed for chained SQL corrections. Direct technical answers use 25–55 words, project examples 50–80 words, and requested scripts include only the essential technique, condition, and minimal code. The prompt treats supplied project facts as exact evidence and forbids embellishing, generic technology substitution, or project mixing.

Validation includes frontend unit and real-handler simulated-bridge tests, backend request/stream tests including five-minute audio, production build, live transcription-to-code smoke test, and phone-browser layout checks. Physical ring and glasses operation still requires wearer testing. v0.7.1 also excludes obsolete saved startup instructions from answer-history migration.
