import {
  waitForEvenAppBridge,
  TextContainerProperty,
} from "@evenrealities/even_hub_sdk";

import "./style.css";

let bridge: any = null;
let ws: WebSocket | null = null;

let micStarted = false;
let stoppedByUser = false;

let reconnectTimer: number | null = null;
let pingTimer: number | null = null;

const RECONNECT_DELAY_MS = 2000;
const PING_INTERVAL_MS = 10000;

let answerText = "";
let displayVersion = 0;


// ============================================================
// CONFIG
// ============================================================

function getBackendUrl(): string {
  const saved = localStorage.getItem("serviceUrl");

  if (saved) {
    return saved;
  }

  return "https://phone-only-g2-interview-coach-fawf.onrender.com";
}


function getToken(): string {
  return localStorage.getItem("accessToken") || "";
}


function websocketUrl(): string {
  const base = getBackendUrl()
    .replace(/^https:/, "wss:")
    .replace(/^http:/, "ws:")
    .replace(/\/$/, "");

  const token = encodeURIComponent(
    getToken()
  );

  return `${base}/ws/glasses?token=${token}`;
}


// ============================================================
// DISPLAY
// ============================================================

async function showText(
  text: string
): Promise<void> {
  answerText = text;

  displayVersion += 1;
  const version = displayVersion;

  try {
    if (!bridge) {
      return;
    }

    const container =
      new TextContainerProperty({
        x: 0,
        y: 0,
        width: 576,
        height: 288,
        text: text || "Listening...",
      });

    await bridge.updatePage({
      containers: [
        container,
      ],
    });

    if (version !== displayVersion) {
      return;
    }

    if (
      ws &&
      ws.readyState === WebSocket.OPEN
    ) {
      ws.send(
        JSON.stringify({
          type: "display_ack",
          text_length: text.length,
          ts: Date.now(),
        })
      );
    }
  } catch (error) {
    console.error(
      "DISPLAY ERROR",
      error
    );
  }
}


// ============================================================
// MICROPHONE
// ============================================================

async function ensureMicrophoneStarted():
Promise<void> {
  if (micStarted) {
    return;
  }

  if (!bridge) {
    return;
  }

  try {
    const result =
      await bridge.audioControl(
        true
      );

    console.log(
      "MIC START RESULT",
      result
    );

    if (result) {
      micStarted = true;
    }
  } catch (error) {
    console.error(
      "MIC START ERROR",
      error
    );
  }
}


async function stopMicrophone():
Promise<void> {
  if (!bridge) {
    return;
  }

  if (!micStarted) {
    return;
  }

  try {
    await bridge.audioControl(
      false
    );
  } catch (error) {
    console.error(
      "MIC STOP ERROR",
      error
    );
  }

  micStarted = false;
}


// ============================================================
// AUDIO FORWARDING
// ============================================================

function handleAudio(
  audio: ArrayBuffer
): void {
  if (
    ws &&
    ws.readyState === WebSocket.OPEN
  ) {
    ws.send(audio);
  }
}


// ============================================================
// SERVER MESSAGE HANDLING
// ============================================================

function handleServerMessage(
  raw: string
): void {
  try {
    const message =
      JSON.parse(raw);

    const type =
      message.type;

    if (
      type === "ready" ||
      type === "listening"
    ) {
      showText(
        message.text ||
        "Listening..."
      );

      return;
    }

    if (
      type === "answer_delta"
    ) {
      answerText +=
        message.delta || "";

      showText(
        answerText
      );

      return;
    }

    if (
      type === "answer_start"
    ) {
      answerText = "";

      showText(
        "Thinking..."
      );

      return;
    }

    if (
      type === "answer_done"
    ) {
      if (message.text) {
        answerText =
          message.text;
      }

      showText(
        answerText
      );

      return;
    }

    if (
      type === "error"
    ) {
      showText(
        message.message ||
        "Connection error"
      );

      return;
    }
  } catch (error) {
    console.error(
      "MESSAGE PARSE ERROR",
      error,
      raw
    );
  }
}


// ============================================================
// PING
// ============================================================

function stopPing(): void {
  if (
    pingTimer !== null
  ) {
    clearInterval(
      pingTimer
    );

    pingTimer = null;
  }
}


function startPing(): void {
  stopPing();

  pingTimer =
    window.setInterval(
      () => {
        if (
          ws &&
          ws.readyState
            === WebSocket.OPEN
        ) {
          ws.send(
            JSON.stringify({
              type: "ping",
              ts: Date.now(),
            })
          );
        }
      },
      PING_INTERVAL_MS
    );
}


// ============================================================
// RECONNECT
// ============================================================

function scheduleReconnect():
void {
  if (stoppedByUser) {
    return;
  }

  if (
    reconnectTimer !== null
  ) {
    return;
  }

  reconnectTimer =
    window.setTimeout(
      () => {
        reconnectTimer = null;

        connectWebSocket();
      },
      RECONNECT_DELAY_MS
    );
}


// ============================================================
// WEBSOCKET
// ============================================================

function connectWebSocket():
void {
  if (stoppedByUser) {
    return;
  }

  if (
    ws &&
    (
      ws.readyState
        === WebSocket.OPEN ||
      ws.readyState
        === WebSocket.CONNECTING
    )
  ) {
    return;
  }

  const socket =
    new WebSocket(
      websocketUrl()
    );

  socket.binaryType =
    "arraybuffer";

  ws = socket;

  socket.onopen =
    async () => {
      if (ws !== socket) {
        return;
      }

      console.log(
        "WS OPEN"
      );

      answerText = "";

      startPing();

      await showText(
        "Listening..."
      );

      await ensureMicrophoneStarted();
    };


  socket.onmessage =
    (event) => {
      if (ws !== socket) {
        return;
      }

      if (
        typeof event.data
        === "string"
      ) {
        handleServerMessage(
          event.data
        );
      }
    };


  socket.onerror =
    (event) => {
      console.error(
        "WS ERROR",
        event
      );
    };


  socket.onclose =
    (event) => {
      if (ws !== socket) {
        return;
      }

      console.log(
        "WS CLOSED",
        {
          code:
            event.code,
          reason:
            event.reason,
          clean:
            event.wasClean,
        }
      );

      stopPing();

      ws = null;

      /*
       * IMPORTANT:
       *
       * Do NOT stop the G2 microphone here.
       *
       * Code 1006 is an unexpected
       * connection loss. The app should
       * simply reconnect.
       *
       * Starting/stopping the microphone
       * on every reconnect can itself
       * destabilize the Even app.
       */
      scheduleReconnect();
    };
}


// ============================================================
// MANUAL STOP
// ============================================================

async function stopEverything():
Promise<void> {
  stoppedByUser = true;

  if (
    reconnectTimer !== null
  ) {
    clearTimeout(
      reconnectTimer
    );

    reconnectTimer = null;
  }

  stopPing();

  const current =
    ws;

  ws = null;

  if (
    current &&
    (
      current.readyState
        === WebSocket.OPEN ||
      current.readyState
        === WebSocket.CONNECTING
    )
  ) {
    current.close(
      1000,
      "User stopped"
    );
  }

  await stopMicrophone();

  await showText(
    "Stopped"
  );
}


// ============================================================
// STARTUP
// ============================================================

async function main():
Promise<void> {
  console.log(
    "BOOT: Interview Lens"
  );

  bridge =
    await waitForEvenAppBridge();

  console.log(
    "EVEN BRIDGE READY"
  );

  await bridge.createStartUpPageContainer({
    containers: [
      new TextContainerProperty({
        x: 0,
        y: 0,
        width: 576,
        height: 288,
        text: "Starting...",
      }),
    ],
  });

  console.log(
    "GLASSES UI CREATED"
  );


  /*
   * G2 audio packets.
   */
  bridge.onAudioEvent(
    (event: any) => {
      const payload =
        event?.data ??
        event;

      if (
        payload instanceof ArrayBuffer
      ) {
        handleAudio(
          payload
        );

        return;
      }

      if (
        ArrayBuffer.isView(
          payload
        )
      ) {
        const view =
          payload as ArrayBufferView;

        const copy =
          view.buffer.slice(
            view.byteOffset,
            view.byteOffset +
            view.byteLength
          );

        handleAudio(
          copy
        );
      }
    }
  );


  /*
   * Log Even events only.
   *
   * Do NOT close the WebSocket
   * when system events occur.
   */
  if (
    typeof bridge.onEvenHubEvent
    === "function"
  ) {
    bridge.onEvenHubEvent(
      (event: any) => {
        console.log(
          "EVEN SYSTEM EVENT",
          event
        );
      }
    );
  }


  stoppedByUser =
    false;

  connectWebSocket();

  await ensureMicrophoneStarted();


  /*
   * Optional browser button.
   */
  const stopButton =
    document.getElementById(
      "stop"
    );

  if (stopButton) {
    stopButton.addEventListener(
      "click",
      () => {
        stopEverything();
      }
    );
  }
}


main().catch(
  (error) => {
    console.error(
      "BOOT ERROR",
      error
    );
  }
);  let reconnectTimer:
    ReturnType<typeof setTimeout> | undefined;

  let pingTimer:
    ReturnType<typeof setInterval> | undefined;

  let manuallyStopped = false;
  let microphoneStarted = false;

  let body =
    "Open Interview Lens on your phone\nto connect your service.";

  let status =
    "NOT CONNECTED";

  let answer = "";

  // ------------------------------------------------------
  // Create glasses UI
  // ------------------------------------------------------

  await bridge.createStartUpPageContainer(
    new CreateStartUpPageContainer({
      containerTotalNum: 2,

      textObject: [
        new TextContainerProperty({
          containerID: 1,
          containerName: "answer",
          xPosition: 0,
          yPosition: 0,
          width: 576,
          height: 246,
          paddingLength: 10,
          content: body,
          isEventCapture: 1,
        }),

        new TextContainerProperty({
          containerID: 2,
          containerName: "status",
          xPosition: 0,
          yPosition: 250,
          width: 576,
          height: 38,
          paddingLength: 6,
          content: status,
        }),
      ],
    })
  );

  console.log("GLASSES UI CREATED");

  // ------------------------------------------------------
  // Glasses text helpers
  // ------------------------------------------------------

  async function setText(
    id: number,
    name: string,
    content: string
  ) {
    try {
      await bridge.textContainerUpgrade(
        new TextContainerUpgrade({
          containerID: id,
          containerName: name,
          contentOffset: 0,
          contentLength: 0,
          content,
        })
      );
    } catch (e) {
      console.error(
        "TEXT UPDATE ERROR:",
        e
      );
    }
  }

  async function show() {
    await setText(
      1,
      "answer",
      glassesText(body)
    );

    await setText(
      2,
      "status",
      status
    );
  }

  // ------------------------------------------------------
  // Phone UI
  // ------------------------------------------------------

  function renderPhone(
    message = ""
  ) {
    root.innerHTML = `
      <div class="shell">
        <div class="card">

          <h1>Interview Lens</h1>

          <div class="muted">
            Phone + Even G2
          </div>

          <div class="status">
            <b>${escapeHtml(status)}</b>
            <br>
            ${escapeHtml(message)}
          </div>

          <form id="setup">

            <label>
              Hosted service URL
            </label>

            <input
              id="url"
              type="url"
              inputmode="url"
              placeholder="https://your-service.onrender.com"
              value="${escapeHtml(
                profile?.serviceUrl ?? ""
              )}"
              required
            >

            <label>
              Access token
            </label>

            <input
              id="token"
              type="password"
              autocomplete="current-password"
              value="${escapeHtml(
                profile?.token ?? ""
              )}"
              required
            >

            <button>
              Save & connect
            </button>

          </form>

          <button
            id="stop"
            class="danger"
          >
            Stop listening
          </button>

          <small>
            Keep Interview Lens open during
            the interview.
          </small>

        </div>
      </div>
    `;

    root
      .querySelector<HTMLFormElement>(
        "#setup"
      )!
      .onsubmit = e => {
        e.preventDefault();
        void save();
      };

    root
      .querySelector<HTMLButtonElement>(
        "#stop"
      )!
      .onclick = () => {
        void stopEverything();
      };
  }

  // ------------------------------------------------------
  // Save configuration
  // ------------------------------------------------------

  async function save() {
    try {
      const serviceUrl =
        root
          .querySelector<HTMLInputElement>(
            "#url"
          )!
          .value
          .trim()
          .replace(/\/$/, "");

      const token =
        root
          .querySelector<HTMLInputElement>(
            "#token"
          )!
          .value
          .trim();

      connectionUrl(serviceUrl);

      profile = {
        serviceUrl,
        token,
      };

      await bridge.setLocalStorage(
        STORAGE,
        JSON.stringify(profile)
      );

      manuallyStopped = false;

      // Close old connection only when user
      // explicitly saves new configuration.
      if (
        ws &&
        (
          ws.readyState === WebSocket.OPEN ||
          ws.readyState === WebSocket.CONNECTING
        )
      ) {
        ws.close(
          1000,
          "Configuration changed"
        );

        ws = undefined;

        await new Promise(
          resolve =>
            setTimeout(
              resolve,
              300
            )
        );
      }

      connect();

    } catch (e) {
      renderPhone(
        e instanceof Error
          ? e.message
          : "Invalid setup"
      );
    }
  }

  // ------------------------------------------------------
  // Start glasses microphone ONCE
  // ------------------------------------------------------

  async function ensureMicrophoneStarted() {
    if (microphoneStarted) {
      return;
    }

    try {
      console.log(
        "MIC: starting glasses microphone"
      );

      const result =
        await bridge.audioControl(
          true,
          AudioInputSource.Glasses
        );

      console.log(
        "MIC START RESULT:",
        result
      );

      microphoneStarted = true;

    } catch (e) {
      console.error(
        "MIC START ERROR:",
        e
      );

      status =
        "MIC ERROR";

      body =
        "Unable to start G2 microphone.";

      await show();

      renderPhone(
        "Microphone start failed"
      );
    }
  }

  // ------------------------------------------------------
  // Stop microphone ONLY when user presses Stop
  // ------------------------------------------------------

  async function stopMicrophone() {
    if (!microphoneStarted) {
      return;
    }

    try {
      console.log(
        "MIC: stopping"
      );

      const result =
        await bridge.audioControl(
          false,
          AudioInputSource.Glasses
        );

      console.log(
        "MIC STOP RESULT:",
        result
      );

    } catch (e) {
      console.error(
        "MIC STOP ERROR:",
        e
      );

    } finally {
      microphoneStarted = false;
    }
  }

  // ------------------------------------------------------
  // Manual stop
  // ------------------------------------------------------

  async function stopEverything() {
    manuallyStopped = true;

    if (reconnectTimer) {
      clearTimeout(
        reconnectTimer
      );

      reconnectTimer =
        undefined;
    }

    if (pingTimer) {
      clearInterval(
        pingTimer
      );

      pingTimer =
        undefined;
    }

    if (
      ws &&
      (
        ws.readyState === WebSocket.OPEN ||
        ws.readyState === WebSocket.CONNECTING
      )
    ) {
      ws.close(
        1000,
        "User stopped"
      );
    }

    ws = undefined;

    await stopMicrophone();

    status =
      "STOPPED";

    body =
      "Interview Lens stopped.";

    await show();

    renderPhone(
      "Microphone off"
    );
  }

  // ------------------------------------------------------
  // Schedule reconnect
  // ------------------------------------------------------

  function scheduleReconnect() {
    if (
      manuallyStopped ||
      !profile
    ) {
      return;
    }

    if (reconnectTimer) {
      return;
    }

    status =
      "RECONNECTING";

    void show();

    renderPhone(
      "Restoring connection..."
    );

    reconnectTimer =
      setTimeout(
        () => {
          reconnectTimer =
            undefined;

          ws =
            undefined;

          connect();
        },
        2000
      );
  }

  // ------------------------------------------------------
  // Connect to Render backend
  // ------------------------------------------------------

  function connect() {
    if (
      !profile ||
      manuallyStopped
    ) {
      return;
    }

    // IMPORTANT:
    // Never close a healthy connection here.
    if (
      ws &&
      (
        ws.readyState === WebSocket.OPEN ||
        ws.readyState === WebSocket.CONNECTING
      )
    ) {
      console.log(
        "WS: already connected/connecting"
      );

      return;
    }

    status =
      "CONNECTING";

    body =
      "Connecting to Interview Lens…";

    void show();

    renderPhone(
      "Connecting..."
    );

    const websocketUrl =
      `${
        connectionUrl(
          profile.serviceUrl
        )
      }?token=${
        encodeURIComponent(
          profile.token
        )
      }`;

    console.log(
      "WS: opening"
    );

    const socket =
      new WebSocket(
        websocketUrl
      );

    ws = socket;

    socket.binaryType =
      "arraybuffer";

    // ----------------------------------------------------
    // Connected
    // ----------------------------------------------------

    socket.onopen =
      async () => {

        // Ignore stale socket callbacks.
        if (
          ws !== socket
        ) {
          return;
        }

        console.log(
          "WS OPEN"
        );

        status =
          "LISTENING";

        body =
          "Listening for the interviewer’s question…";

        await show();

        renderPhone(
          "Connected securely"
        );

        // Start microphone only once.
        await ensureMicrophoneStarted();

        if (pingTimer) {
          clearInterval(
            pingTimer
          );
        }

        pingTimer =
          setInterval(
            () => {
              if (
                ws === socket &&
                socket.readyState ===
                  WebSocket.OPEN
              ) {
                try {
                  socket.send(
                    JSON.stringify({
                      type: "ping",
                      time: Date.now(),
                    })
                  );
                } catch (e) {
                  console.error(
                    "PING ERROR:",
                    e
                  );
                }
              }
            },
            10000
          );
      };

    // ----------------------------------------------------
    // Backend message
    // ----------------------------------------------------

    socket.onmessage =
      async e => {

        if (
          ws !== socket
        ) {
          return;
        }

        const m =
          parseMessage(
            String(e.data)
          );

        if (
          m.type === "state"
        ) {
          status =
            m.state.toUpperCase();

          if (
            m.transcript
          ) {
            body =
              `Q · ${m.transcript}`;
          }
        }

        else if (
          m.type ===
          "answer.delta"
        ) {
          if (
            m.first
          ) {
            answer = "";
          }

          answer +=
            m.text;

          body =
            answer;

          status =
            "ANSWERING";

          const displayStart =
            performance.now();

          await show();

          if (
            ws === socket &&
            socket.readyState ===
              WebSocket.OPEN
          ) {
            try {
              socket.send(
                JSON.stringify({
                  type:
                    "display.ack",

                  answer_id:
                    m.answer_id,

                  seq:
                    m.seq,

                  display_call_ms:
                    performance.now()
                    -
                    displayStart,
                })
              );
            } catch (e) {
              console.error(
                "ACK SEND ERROR:",
                e
              );
            }
          }

          renderPhone();

          return;
        }

        else if (
          m.type ===
          "answer.done"
        ) {
          body =
            m.text;

          status =
            `READY · ${
              Math.round(
                m.metrics?.total_ms
                ?? 0
              )
            }ms`;
        }

        else if (
          m.type === "error"
        ) {
          status =
            "ERROR";

          body =
            m.message;
        }

        await show();

        renderPhone();
      };

    // ----------------------------------------------------
    // Error
    // ----------------------------------------------------

    socket.onerror =
      e => {

        console.error(
          "WS ERROR:",
          e
        );
      };

    // ----------------------------------------------------
    // Closed
    // ----------------------------------------------------

    socket.onclose =
      e => {

        console.log(
          "WS CLOSED",
          {
            code:
              e.code,

            reason:
              e.reason,

            clean:
              e.wasClean,
          }
        );

        // Ignore stale sockets.
        if (
          ws !== socket
        ) {
          return;
        }

        if (pingTimer) {
          clearInterval(
            pingTimer
          );

          pingTimer =
            undefined;
        }

        ws =
          undefined;

        // IMPORTANT:
        // Do NOT stop the glasses microphone here.
        // Keep it alive while WebSocket reconnects.

        if (
          manuallyStopped
        ) {
          return;
        }

        scheduleReconnect();
      };
  }

  // ------------------------------------------------------
  // Even G2 audio
  // ------------------------------------------------------

  bridge.onEvenHubEvent(
    e => {
      const pcm =
        e.audioEvent?.audioPcm;

      if (
        pcm &&
        pcm.length &&
        ws?.readyState ===
          WebSocket.OPEN
      ) {
        try {
          ws.send(
            pcm
          );
        } catch (err) {
          console.error(
            "AUDIO SEND ERROR:",
            err
          );
        }
      }

      // IMPORTANT:
      // Do not automatically close the WebSocket when
      // an Even system event occurs.
      if (
        e.sysEvent
      ) {
        console.log(
          "EVEN SYSTEM EVENT:",
          e.sysEvent
        );
      }
    }
  );

  renderPhone();

  if (
    profile
  ) {
    connect();
  }
}


async function loadProfile(
  bridge: Awaited<
    ReturnType<
      typeof waitForEvenAppBridge
    >
  >
): Promise<Profile | null> {
  try {
    const raw =
      await bridge.getLocalStorage(
        STORAGE
      );

    return raw
      ? JSON.parse(raw)
      : null;

  } catch {
    return null;
  }
}


function escapeHtml(
  v: string
) {
  return v.replace(
    /[&<>"']/g,
    c =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[c]!)
  );
}


void boot();
