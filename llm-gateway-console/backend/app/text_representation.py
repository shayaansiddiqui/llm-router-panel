"""Bounded whole-text encoding without silently dropping the request tail."""
from collections import deque
import math


def encode_text(model, text: str) -> list[float]:
    pending = deque([text])
    windows = []
    weights = []
    while pending:
        part = pending.popleft()
        count = len(model.tokenizer(part, truncation=False, add_special_tokens=True)['input_ids'])
        if count > model.max_seq_length:
            if len(part) < 2 or len(windows) + len(pending) + 2 > 64:
                raise ValueError('Request exceeds bounded encoder window capacity.')
            midpoint = len(part) // 2
            pending.appendleft(part[midpoint:])
            pending.appendleft(part[:midpoint])
        else:
            windows.append(part)
            weights.append(max(1, count - 2))
    vectors = model.encode(windows, normalize_embeddings=True, show_progress_bar=False).tolist()
    vector = [sum(weight * values[index] for weight, values in zip(weights, vectors)) / sum(weights)
              for index in range(len(vectors[0]))]
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm or not math.isfinite(norm):
        raise ValueError('Encoder returned an invalid representation.')
    return [value / norm for value in vector]
