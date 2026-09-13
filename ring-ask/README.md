# Ring Ask v0.3.1

Open Ring Ask in Even Hub. Single tap starts listening; wait for Listening before speaking. Double-tap stops and submits. Swipe down/up for next/previous pages. Hold/release are ignored. The app never starts recording on reconnect or resume. Only a tap while ready and connected can start the microphone.

Full-screen paged answers are retained. Old layout and gesture-mode preferences are ignored; server/token are preserved. Connection & recovery shows the latest received input; page swipes update the page hint. A single-page answer has nowhere further to scroll.

Build and 20 reader/control tests pass. Physical ring event delivery has not been verified remotely. The old tap flow is restored, but the reported device swipe problem still requires confirmation on hardware.
