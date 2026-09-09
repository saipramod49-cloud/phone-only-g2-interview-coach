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


// ============================================================
// CONFIG
// ============================================================

function getBackendUrl(): string {
  const saved =
    localStorage.getItem("serviceUrl");

  return (
    saved ||
    "https://phone-only-g2-interview-coach-fawf.onrender.com"
  );
}


function getToken(): string {
  return (
    localStorage.getItem("accessToken") ||
    ""
  );
}


function getWebSocketUrl(): string {
  const base = getBackendUrl()
    .replace(/^https:/, "wss:")
    .replace(/^http:/, "ws:")
    .replace(/\/$/, "");

  const token =
    encodeURIComponent(
      getToken()
    );

  return (
    `${base}/ws/glasses?token=${token}`
  );
}


// ============================================================
// GLASSES DISPLAY
// ============================================================

async function showText(
  text: string
): Promise<void> {

  if (!bridge) {
    return;
  }

  try {
    await bridge.updatePage({
      containers: [
        new TextContainerProperty({
          x: 0,
          y: 0,
          width: 576,
          height: 288,
          text:
            text ||
            "Listening...",
        }),
      ],
    });

    if (
      ws &&
      ws.readyState ===
        WebSocket.OPEN
    ) {
      ws.send(
        JSON.stringify({
          type: "display_ack",
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

async function startMicrophone():
Promise<void> {

  if (
    micStarted ||
    !bridge
  ) {
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

  if (
    !bridge ||
    !micStarted
  ) {
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
// AUDIO
// ============================================================

function sendAudio(
  audio: ArrayBuffer
): void {

  if (
    ws &&
    ws.readyState ===
      WebSocket.OPEN
  ) {
    ws.send(audio);
  }
}


// ============================================================
// SERVER MESSAGES
// ============================================================

function handleServerMessage(
  raw: string
): void {

  try {
    const message =
      JSON.parse(raw);

    switch (message.type) {

      case "ready":
      case "listening":

        showText(
          message.text ||
          "Listening..."
        );

        break;


      case "answer_start":

        answerText = "";

        showText(
          "Thinking..."
        );

        break;


      case "answer_delta":

        answerText +=
          message.delta || "";

        showText(
          answerText
        );

        break;


      case "answer_done":

        if (message.text) {
          answerText =
            message.text;
        }

        showText(
          answerText
        );

        break;


      case "error":

        showText(
          message.message ||
          "Error"
        );

        break;
    }

  } catch (error) {
    console.error(
      "MESSAGE ERROR",
      error,
      raw
    );
  }
}


// ============================================================
// KEEPALIVE
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
          ws.readyState ===
            WebSocket.OPEN
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

        connect();

      },
      RECONNECT_DELAY_MS
    );
}


// ============================================================
// WEBSOCKET
// ============================================================

function connect(): void {

  if (stoppedByUser) {
    return;
  }

  if (
    ws &&
    (
      ws.readyState ===
        WebSocket.OPEN ||
      ws.readyState ===
        WebSocket.CONNECTING
    )
  ) {
    return;
  }

  console.log(
    "WS CONNECTING"
  );

  const socket =
    new WebSocket(
      getWebSocketUrl()
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

      startPing();

      await showText(
        "Listening..."
      );

      await startMicrophone();
    };


  socket.onmessage =
    (event) => {

      if (ws !== socket) {
        return;
      }

      if (
        typeof event.data ===
        "string"
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
       * Do NOT stop the microphone
       * on an unexpected socket close.
       *
       * We reconnect automatically.
       */
      scheduleReconnect();
    };
}


// ============================================================
// STOP
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

  const socket =
    ws;

  ws = null;

  if (
    socket &&
    (
      socket.readyState ===
        WebSocket.OPEN ||
      socket.readyState ===
        WebSocket.CONNECTING
    )
  ) {
    socket.close(
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


  bridge.onAudioEvent(
    (event: any) => {

      const payload =
        event?.data ??
        event;

      if (
        payload instanceof
        ArrayBuffer
      ) {
        sendAudio(
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
          payload as
          ArrayBufferView;

        const copy =
          view.buffer.slice(
            view.byteOffset,
            view.byteOffset +
              view.byteLength
          ) as ArrayBuffer;

        sendAudio(
          copy
        );
      }
    }
  );


  if (
    typeof bridge.onEvenHubEvent ===
    "function"
  ) {
    bridge.onEvenHubEvent(
      (event: any) => {

        console.log(
          "EVEN SYSTEM EVENT",
          event
        );

        /*
         * Important:
         * do not close WebSocket here.
         */
      }
    );
  }


  stoppedByUser = false;

  connect();

  await startMicrophone();


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
);
