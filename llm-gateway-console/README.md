# LLM Gateway Console

LLM Gateway Console is a small admin panel for managing one public LLM gateway.

Client applications call one stable API domain:

```text
https://ai.gettingstarted.app
```

The gateway then decides which LLM provider should handle the request.

```text
Client App
  -> LLM Gateway
  -> Selected Provider
  -> LLM Backend
  -> Response back to Client App
```

The gateway does not run models. It only receives requests, checks access, selects a provider, forwards the request, and logs the result.

## Main Idea

Instead of every app calling different LLM backends directly, all apps call the gateway.

Example provider backends:

```text
olares      -> https://ai-1.gettingstarted.app
mac-studio  -> https://ai-2.gettingstarted.app
```

Client apps only need to know:

```text
https://ai.gettingstarted.app/v1/chat/completions
```

## Request Flow

When a client sends a chat request:

1. The gateway receives the request.
2. The gateway checks the client API key.
3. The gateway checks which providers and models that key can use.
4. The gateway reads the requested model.
5. If the request includes a provider name, that provider is used.
6. If no provider is sent, the gateway chooses one automatically.
7. The request is forwarded to the selected provider.
8. The provider response is returned to the client.
9. A request log is saved.

## Automatic Routing

If the client does not send `provider`, the gateway chooses the provider.

Example:

```json
{
  "model": "qwen2.5-coder:32b-instruct-q8_0",
  "messages": [
    {
      "role": "user",
      "content": "Write a short welcome message."
    }
  ],
  "temperature": 0.7
}
```

Automatic routing uses:

- active/passive provider status
- API key permissions
- requested model
- provider priority
- provider timeout/failure handling

Lower priority numbers run first. Priority `1` is tried before priority `2`.

If the first provider fails or times out, the gateway can try the next valid provider.

## Token Streaming

Clients can request streaming responses with:

```json
{
  "model": "qwen2.5-coder:32b-instruct-q8_0",
  "messages": [
    {
      "role": "user",
      "content": "Write a short welcome message."
    }
  ],
  "stream": true
}
```

When `stream` is `true`, the gateway forwards the request as a stream and passes token chunks back to the client.

Failover can happen before the stream starts. Once a provider starts streaming tokens, the gateway keeps that stream connected to the same provider.

## Targeted Provider Routing

If the client sends `provider`, the gateway targets that provider by name.

Example:

```json
{
  "provider": "olares",
  "model": "qwen2.5-coder:32b-instruct-q8_0",
  "messages": [
    {
      "role": "user",
      "content": "Write a short welcome message."
    }
  ],
  "temperature": 0.7
}
```

In this mode, the gateway does not fail over to another provider. It validates the selected provider and forwards the request only there.

The `provider` field is removed before forwarding, so the backend receives a normal OpenAI-compatible request.

## Admin Panel Pages

### Dashboard

Shows a quick overview of the gateway:

- number of providers
- active providers
- available models
- logged requests
- recent request activity

Use it to quickly see whether the system is healthy.

### Providers

Used to manage LLM backends.

Each provider has:

- name
- endpoint URL
- optional API key
- active/passive status
- priority
- timeout

Providers are the real backends behind the gateway.

### Models

Shows models imported from providers.

Example:

```text
qwen2.5-coder:32b-instruct-q8_0 -> olares
qwen3.6:35b                     -> olares
```

Clients request models by name. The gateway uses this model name to find a compatible provider.

### API Keys

Used to create client keys for apps and services.

Each API key can allow:

- all providers and all models
- selected providers
- selected models under selected providers

This makes it possible to give different apps different access levels.

### API Docs

Shows developers how to call the gateway.

It includes:

- public endpoint
- authentication format
- request examples
- provider/model usage
- routing behavior
- error examples

Client apps should use the public gateway domain shown here.

### Logs

Shows recent request attempts.

Useful for checking:

- requested model
- selected provider
- success or failure
- latency
- provider errors

## Public Endpoint

Chat completions:

```text
POST https://ai.gettingstarted.app/v1/chat/completions
```

Authentication:

```text
Authorization: Bearer <API_KEY>
```

## Example Request

```bash
curl https://ai.gettingstarted.app/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <API_KEY>" \
  -d '{
    "provider": "olares",
    "model": "qwen2.5-coder:32b-instruct-q8_0",
    "messages": [
      {
        "role": "user",
        "content": "Write a short welcome message."
      }
    ],
    "temperature": 0.7
  }'
```

## Summary

The gateway gives all client apps one stable API endpoint.

Providers can change behind the scenes without changing client apps.

API keys control who can use which providers and models.

Logs show what happened for each request.

The admin panel is only for managing the gateway; client apps should call the public API endpoint.
  
