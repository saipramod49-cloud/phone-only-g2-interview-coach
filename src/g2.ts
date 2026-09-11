import {
  waitForEvenAppBridge,
  AudioInputSource,
  TextContainerProperty,
  CreateStartUpPageContainer,
  TextContainerUpgrade,
  RebuildPageContainer,
  OsEventTypeList,
  type EvenAppBridge,
} from "@evenrealities/even_hub_sdk";
export class DisplayWriter {
  private desired = "";
  private rendered = "";
  private running = false;
  private closed = false;
  constructor(
    private write: (text: string) => Promise<boolean>,
    private onAck: (ms: number) => void,
    private onError: () => void,
  ) {}
  show(text: string) {
    this.desired = text;
    if (!this.running && !this.closed) void this.flush();
  }
  invalidate() {
    this.rendered = "";
    if (!this.running && !this.closed) void this.flush();
  }
  close() {
    this.closed = true;
  }
  private async flush() {
    this.running = true;
    while (!this.closed && this.desired !== this.rendered) {
      const target = this.desired,
        start = performance.now();
      try {
        const ok = await this.write(target);
        if (!ok) throw new Error("Render rejected");
        this.rendered = target;
        this.onAck(performance.now() - start);
      } catch {
        this.onError();
        await new Promise((r) => setTimeout(r, 800));
      }
      await new Promise((r) => setTimeout(r, 100));
    }
    this.running = false;
  }
}
export async function connectG2(callbacks: {
  audio: (pcm: Uint8Array, role: string) => void;
  action: (type: string, direction?: number) => boolean | void;
  status: (s: string) => void;
  ack: (ms: number) => void;
}) {
  const bridge = await waitForEvenAppBridge();
  const create = async () => {
    const code = await bridge.createStartUpPageContainer(
      new CreateStartUpPageContainer({
        containerTotalNum: 1,
        textObject: [
          new TextContainerProperty({
            containerID: 1,
            containerName: "coach",
            xPosition: 0,
            yPosition: 0,
            width: 576,
            height: 288,
            paddingLength: 4,
            isEventCapture: 1,
            textColor: 4,
            content: "Practice coach",
          }),
        ],
      }),
    );
    if (code !== 0) throw new Error("G2 startup failed: " + code);
  };
  await create();
  let layout = {x:0,y:0,width:576,height:288};
  let renderedLayout = JSON.stringify(layout);
  const writer = new DisplayWriter(
    async (text) => {
      const key = JSON.stringify(layout);
      if (key !== renderedLayout) {
        const ok = await bridge.rebuildPageContainer(new RebuildPageContainer({
          containerTotalNum:1, textObject:[new TextContainerProperty({
            containerID:1, containerName:'coach', xPosition:layout.x, yPosition:layout.y,
            width:layout.width, height:layout.height, paddingLength:4,
            isEventCapture:1, textColor:4, content:text,
          })],
        }));
        if (!ok) return false;
        renderedLayout = key;
      }
      return bridge.textContainerUpgrade(
        new TextContainerUpgrade({
          containerID: 1,
          containerName: "coach",
          content: text,
          textColor: 4,
        }),
      );
    },
    callbacks.ack,
    () => callbacks.status("G2 update retry; last successful frame retained"),
  );
  const unsub = bridge.onEvenHubEvent((e) => {
    if (e.audioEvent)
      callbacks.audio(
        e.audioEvent.audioPcm,
        e.audioEvent.speakerRole ?? "unknown",
      );
    // Zero-valued click is implicit ONLY inside an existing input envelope.
    const envelope = e.sysEvent ?? e.textEvent ?? e.listEvent;
    if (!envelope) return;
    const type = envelope.eventType ?? OsEventTypeList.CLICK_EVENT;
    if (type === OsEventTypeList.SCROLL_TOP_EVENT)
      callbacks.action("navigate", -1);
    else if (type === OsEventTypeList.SCROLL_BOTTOM_EVENT)
      callbacks.action("navigate", 1);
    else if (type === OsEventTypeList.CLICK_EVENT) callbacks.action("resume");
    else if (type === OsEventTypeList.DOUBLE_CLICK_EVENT) {
      if (!callbacks.action("back")) void bridge.shutDownPageContainer(1);
    } else if (type === OsEventTypeList.LONG_PRESS_EVENT) callbacks.action("menu");
    else if (
      type === OsEventTypeList.SYSTEM_EXIT_EVENT ||
      type === OsEventTypeList.ABNORMAL_EXIT_EVENT
    ) {
      callbacks.action("end");
      void bridge.audioControl(false);
      writer.close();
      unsub();
    } else if (type === OsEventTypeList.FOREGROUND_ENTER_EVENT)
      writer.invalidate();
    else if (type === OsEventTypeList.FOREGROUND_EXIT_EVENT)
      callbacks.status(
        "Host backgrounded; capture continuity must be verified on this phone",
      );
  });
  return {
    show: (s: string) => writer.show(s),
    layout: (value: typeof layout) => {if(JSON.stringify(layout)!==JSON.stringify(value)){layout=value;writer.invalidate();}},
    mic: (on: boolean) => bridge.audioControl(on, AudioInputSource.Glasses),
    close: async () => {
      unsub();
      writer.close();
      await bridge.audioControl(false);
    },
  };
}
