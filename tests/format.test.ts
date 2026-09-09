import { describe, expect, it } from "vitest";
import { connectionUrl, glassesText } from "../src/format";
describe("G2 formatting",()=>{
  it("uses supported plain-text emphasis",()=>expect(glassesText("**Impact**\n- cut latency")).toBe("IMPACT\n› cut latency"));
  it("maps hosted HTTPS to secure websocket",()=>expect(connectionUrl("https://x.onrender.com")).toBe("wss://x.onrender.com/ws/glasses"));
  it("rejects insecure remote services",()=>expect(()=>connectionUrl("http://example.com")).toThrow());
});
