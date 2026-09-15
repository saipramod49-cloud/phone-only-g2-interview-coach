# Ring Ask v0.7.2

Open [Ring Ask in Even Hub](https://hub.evenrealities.com/landing?package_id=com.saipramod.ringask), the [live Render app](https://phone-only-g2-interview-coach-fawf.onrender.com/ring/), or the [GitHub source](https://github.com/saipramod49-cloud/phone-only-g2-interview-coach).

Choose one listening mode in Listening & answer settings:

- Tap mode: tap starts capture, the next deliberate tap stops and submits. Release does nothing.
- Hold mode: hold throughout the question, release to submit. Both modes support up to five minutes.
- Double tap changes the answer page, wrapping from the last page to the first. It does not change answer style or open the microphone.
- Swipe up for older answers and down for newer/current answers. The last 30 completed answers are saved on this phone.

Starting or cancelling a recording preserves the previous completed answer. The ring handler disambiguates single and double taps and accepts SDK input envelopes with an omitted zero event enum. Accidental holds in tap mode do not start capture. Returning from a system menu rebuilds the app display when the firmware sends the foreground event. The app cannot override firmware-owned controls or receive ring events after it has been closed.

Every answer page has a question and page/history status. Choose question above/answer below or question left/answer right. Reading settings support width, position, 1–10 requested lines, 1–10 words or automatic wrapping, and Native/18/22/26/30px fonts. The physical 576×288 display limits the lines that fit; the UI reports the effective count. Long questions are abbreviated on the lens and remain complete on the phone. Native emphasis uses capitals; the phone and bitmap fonts also use bold. Code retains indentation and is paginated without dropping text.

There is one answer style, adapted to the request: readable conversational paragraphs, a matching flow for architecture where useful, and actual SQL/Python/PySpark code first when requested. Follow-ups retain conversation context. Resume and prep notes guide relevant answers without limiting help on unfamiliar stacks. Proposed experience uses conditional language rather than invented personal claims. The next-answer instruction box can refine answers without a deployment.

Ring Ask defaults to GPT-6 Astra with low reasoning effort, independently of the legacy agent model. Set RING_MODEL to override. The authenticated /api/health reports the deployed model, prompt style, version, and recording limit. Measured latency varies with transcription, model service, network, and glasses rendering.

Latency optimization in v0.7.2 sends a compact, question-relevant slice of the candidate profile instead of the entire file, targets shorter complete answers, and routes explicit code requests to GPT-5.6 Sol while keeping GPT-6 Astra for architecture, scenarios, troubleshooting, and behavioral questions.

Validation includes frontend unit and real-handler simulated-bridge tests, backend request/stream tests including five-minute audio, production build, live transcription-to-code smoke test, and phone-browser layout checks. Physical ring and glasses operation still requires wearer testing. v0.7.1 also excludes obsolete saved startup instructions from answer-history migration.
