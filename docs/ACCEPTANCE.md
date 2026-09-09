# Acceptance and limitations

## Implemented

- Installable Even Hub artifact and SDK-native G2 microphone/display path.
- iPhone companion setup embedded in the Even app; mobile web document/profile manager on the hosted service.
- Phone/cloud-only runtime with WSS, reconnect, persistent selected profile, and server-only provider keys.
- PDF, DOCX, text, Markdown, and CSV extraction; per-profile job description; local retrieval; grounded first-person response prompt.
- OpenAI Realtime streaming transcription and server VAD, conservative question gate, cancel-and-replace answer generation, and streaming display updates.
- Supported keyword emphasis without relying on unsupported rich text.
- Per-session STT, retrieval, model-first-token, and total generation records with explicit unmeasured transport/display fields.

## Unavoidable / unverified here

- Even Hub offers no rich text and no display-presented acknowledgement.
- Real hardware, mobile-carrier, provider, and end-to-end latency were not measurable without the user's G2, iPhone, deployed service, and credentials.
- Development sideloading/private distribution follows Even's developer portal flow; App Store-style public distribution remains controlled by Even.
- Background operation is not promised: the Even Hub plugin must remain open and iOS/Even app lifecycle rules apply.
- The heuristic question gate reduces but cannot eliminate room-speech false positives; speaker diarization/voice enrollment is not exposed by the glasses SDK and is not claimed.
- Scanned PDFs need OCR; legacy `.doc` is intentionally unsupported.
- Network loss prevents cloud transcription/generation; there is no useful offline model path in this production slice.
