// Parse SSE by lines: chunks need not align with UTF-8 characters or events.
// Keep partial output in the caller if the connection fails mid-generation.
export async function readChatStream(response, onUpdate, byteLimit) {
  const reader = response.body?.getReader();
  if (!reader) throw new Error('The gateway returned an empty stream.');
  const decoder = new TextDecoder();
  let buffer = '';
  let dataLines = [];
  let bytes = 0;
  let done = false;
  let sawChoice = false;
  let lastUpdate = 0;
  let body = { object: 'chat.completion', choices: [{ index: 0, message: { role: 'assistant', content: '', reasoning: '' }, finish_reason: null }] };

  function dispatch() {
    if (!dataLines.length) return;
    const data = dataLines.join('\n');
    dataLines = [];
    if (data.trim() === '[DONE]') { done = true; return; }
    let chunk;
    try { chunk = JSON.parse(data); } catch { throw new Error('The gateway returned invalid streaming JSON. Partial output was preserved.'); }
    if (chunk?.gateway?.event === 'model_retry') {
      body = { object: 'chat.completion', gateway_recovery: chunk.gateway,
        choices: [{ index: 0, message: { role: 'assistant', content: '', reasoning: '' }, finish_reason: null }] };
      sawChoice = false;
      onUpdate(body);
      return;
    }
    if (chunk?.error) throw new Error(typeof chunk.error.message === 'string' ? chunk.error.message.slice(0, 1000) : 'The provider reported a streaming error.');
    if (!chunk || typeof chunk !== 'object' || Array.isArray(chunk)) throw new Error('Invalid chat stream event.');
    const choice = chunk.choices?.find((item) => item.index === 0) || (chunk.choices?.[0]?.index == null ? chunk.choices?.[0] : null);
    const current = body.choices[0];
    const delta = choice?.delta || {};
    if (choice) {
      sawChoice = true;
      if (delta.content != null && typeof delta.content !== 'string') throw new Error('Unsupported streamed content format.');
      const reasoning = delta.reasoning ?? delta.reasoning_content ?? '';
      if (typeof reasoning !== 'string') throw new Error('Unsupported streamed reasoning format.');
      body = { ...body, choices: [{ ...current,
        message: { ...current.message, content: current.message.content + (delta.content || ''), reasoning: current.message.reasoning + reasoning },
        finish_reason: choice.finish_reason ?? current.finish_reason,
      }] };
    }
    if (typeof chunk.model === 'string') body = { ...body, model: chunk.model };
    if (typeof chunk.id === 'string') body = { ...body, id: chunk.id };
    if (chunk.usage) body = { ...body, usage: chunk.usage };
    if (performance.now() - lastUpdate > 50) { onUpdate(body); lastUpdate = performance.now(); }
  }

  function line(value) {
    const text = value.endsWith('\r') ? value.slice(0, -1) : value;
    if (!text) dispatch();
    else if (text.startsWith('data:')) dataLines.push(text.slice(5).replace(/^ /, ''));
  }

  try {
    while (!done) {
      const next = await reader.read();
      if (next.done) { buffer += decoder.decode(); break; }
      bytes += next.value.byteLength;
      if (bytes > byteLimit) throw new Error('Stream exceeded the Playground 2 MiB limit. Partial output was preserved.');
      buffer += decoder.decode(next.value, { stream: true });
      let newline;
      while (!done && (newline = buffer.indexOf('\n')) !== -1) {
        line(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
      }
    }
    if (!done) { if (buffer) line(buffer); dispatch(); }
    if (!sawChoice || !body.choices[0].finish_reason) throw new Error('Stream ended without a completion finish reason. Partial output was preserved.');
    onUpdate(body);
    return body;
  } catch (error) {
    if (sawChoice) onUpdate(body);
    throw error;
  } finally {
    try { await reader.cancel(); } catch { /* The network may already be closed. */ }
    reader.releaseLock();
  }
}
