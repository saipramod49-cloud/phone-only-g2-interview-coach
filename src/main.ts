import {
  waitForEvenAppBridge,
  CreateStartUpPageContainer,
  TextContainerProperty,
  TextContainerUpgrade,
  AudioInputSource,
} from "@evenrealities/even_hub_sdk";

import "./style.css";
import { connectionUrl, glassesText } from "./format";
import { parseMessage } from "./protocol";

const STORAGE = "interviewlens.profile.v1";

type Profile = {
  serviceUrl: string;
  token: string;
  selectedProfile?: string;
};

async function boot() {
  const root =
    document.querySelector<HTMLElement>("#app")!;

  console.log("BOOT: waiting for Even bridge");

  const bridge =
    await waitForEvenAppBridge();

  console.log("BOOT: bridge ready");

  let profile =
    await loadProfile(bridge);

  let ws: WebSocket | undefined;

  let reconnectTimer:
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
