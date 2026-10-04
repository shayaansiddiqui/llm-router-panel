const MAX_TURNS = 10;
const MAX_STORED_BYTES = 65536;
const byteLength = (text) => new TextEncoder().encode(text).byteLength;
const turnBytes = (turn) => byteLength(turn.user) + byteLength(turn.assistant);

export function retainHistory(turns) {
  const retained = turns.slice(-MAX_TURNS);
  while (retained.length && retained.reduce((sum, turn) => sum + turnBytes(turn), 0) > MAX_STORED_BYTES) retained.shift();
  return retained;
}

export function historyForRequest(turns, system, prompt, outputTokens, contextTokens = 16384) {
  // Byte-based screening, not an exact tokenizer count. The backend still
  // checks each candidate and verifies native Ollama's advertised limit.
  const available = Math.max(0, contextTokens - 1024 - outputTokens - byteLength(system) - byteLength(prompt));
  const selected = [];
  let bytes = 0;
  for (const turn of [...turns].reverse()) {
    if (bytes + turnBytes(turn) > available) break;
    selected.unshift(turn);
    bytes += turnBytes(turn);
  }
  return { turns: selected, dropped: turns.length - selected.length,
    messages: selected.flatMap((turn) => [{ role: 'user', content: turn.user }, { role: 'assistant', content: turn.assistant }]) };
}
