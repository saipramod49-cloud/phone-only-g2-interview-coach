export function answerVariants(text) {
  const clean = String(text || '').trim();
  const flow = clean.match(/(?:^|\n)FLOW:\s*([\s\S]*)$/i);
  const spoken = clean.match(/(?:^|\n)SPOKEN:\s*([\s\S]*?)(?=\nFLOW:|$)/i);
  return {
    spoken: (spoken?.[1] ?? clean.replace(/^SPOKEN:\s*/i, '').split(/\nFLOW:/i)[0]).trim(),
    flow: (flow?.[1] ?? '').trim(),
  };
}
