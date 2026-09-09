export type ServerMessage =
  | { type: "ready"; profile: string | null }
  | { type: "state"; state: string; transcript?: string }
  | { type: "answer.delta"; text: string; first?: boolean; answer_id: string; seq: number }
  | { type: "answer.done"; text: string; metrics: Record<string, number> }
  | { type: "error"; message: string };

export function parseMessage(raw: string): ServerMessage {
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object" || !("type" in value)) throw new Error("Invalid server message");
  return value as ServerMessage;
}
