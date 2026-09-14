# Ring Ask v0.4.2

Tap starts listening; hold continues; release submits. Swipe between answer pages. Controls are unchanged from v0.3.2.

Native mode uses Even's @evenrealities/pretext 0.1.4 font metrics rather than estimated character widths. Its full 576×288 canvas has a 1px green border and 3px padding: inner text area 568×280. Ten native lines occupy 270px. Existing native settings migrate once to 10 lines and Auto words to fill available width. Optional 1–10 word limits remain; these intentionally shorten lines.

Font options: Native or image-rendered 18/22/26/30px. Larger image fonts may fit fewer rows and update more slowly. Paragraph dividers are retained. This uses published G2 metrics; the private built-in Even AI UI configuration is not exposed by the saved agent settings.

Validation: build, 25 tests, SDK container validation, and measured 10-line page fit. Physical glasses still require wearer verification.

Version 0.4.3: answers now target 2–4 concise bullets and 35–65 words, with one emphasized key phrase per bullet. Uppercase phrases render bold in the phone and image-font views; native text preserves capitals because it has no bold API. Three real profile questions were evaluated in outputs/natural-answer-evaluation.json.

Adaptive answer update: the agent chooses compact text flows for processes, plain-language definitions with small examples for concepts, and grounded bullets for experience and comparisons. Backend health identifies answer_style adaptive-clear-v1. Frontend remains v0.4.3; no new QR is required. Four real model questions and 15 backend tests passed.

Version 0.4.4: glasses recovery continues while Ring Ask remains active, using a capped 15-second retry delay. A ring tap received during recovery is remembered and starts listening after reconnection; releasing before recovery cancels the pending microphone start. The phone checks Render health every four minutes while online.
