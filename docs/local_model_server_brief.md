# Brief: set up a local model server for Parameter Extractor

You are helping set up a **local LLM server on this Windows machine**. A desktop app, Parameter Extractor, will send
requests to it **over the local network from a Mac**. Do **not** install Parameter Extractor here; only the model
server is needed. This file has everything the app expects from the server.

## What the app does with the model

Parameter Extractor reads scientific papers (prebiotic chemistry, exoplanets) and extracts experimental values into a
dataset. Each paper takes about 4–8 requests ("steps"). Each request sends:

- the whole paper text,
- often images of the paper's tables (PNG/JPEG crops), and
- a JSON Schema the answer must follow.

Each step asks for **one JSON object** that fits that schema. The answers are long, structured lists of values, each
with its unit, a short verbatim quote, where it was found and a confidence. Accuracy matters more than speed: this
replaces careful manual reading.

## What the server has to support

Either of two kinds works. The app has a setting for each.

### Option A: Ollama (preferred, simplest)

- The app calls `POST <url>/api/chat` with `"stream": true` and `"format": <JSON Schema>` (structured outputs). It
  sends `options.num_ctx` (context length), `options.num_predict` and `temperature: 0`.
- Images go in the message's `"images"` list as base64.
- The app lists models with `GET /api/tags`. For each one it calls `POST /api/show` and reads `capabilities` (whether
  it does vision) and `model_info.*.context_length`.
- The app sets `num_ctx` per request itself, so Ollama's small default context is not a problem.
- Default address: `http://localhost:11434`. Here it must listen on the network (see below).

### Option B: an OpenAI-compatible server (LM Studio, llama.cpp `llama-server`, vLLM)

- The app calls `POST <url>/v1/chat/completions` with `"stream": true`,
  `"stream_options": {"include_usage": true}`, `temperature: 0`, `max_tokens`, and
  `"response_format": {"type": "json_schema", "json_schema": {"name": ..., "schema": ..., "strict": true}}`.
  **The server must honour `json_schema` response formats.** Check that the chosen server and version do.
- Images are sent as `image_url` parts with `data:` URIs.
- The app lists models with `GET /v1/models`. An optional bearer API key is supported.
- The context length is the server's own setting (the app can't change it per request), so set it high when the
  model is loaded.

## Sizes to plan for

- **Prompt per request:**
  - typical prebiotic paper: about 15–45K tokens (paper text + instructions + schema + table images);
  - long exoplanet catalogue papers: 80–120K tokens.
- **Context:** the app refuses a request when the prompt won't fit in the context length configured for the model.
  - Minimum: **64K**.
  - Comfortable: **128K**.
  - Find the largest context the GPU memory can hold for the chosen model. The KV cache grows with context.
    Look at quantised KV cache and flash attention (for Ollama, the `OLLAMA_FLASH_ATTENTION` and
    `OLLAMA_KV_CACHE_TYPE` environment variables; check the current Ollama docs for the exact names and values).
- **Answer per request:** up to about 6–12K tokens for the largest step; a paper totals roughly 10–25K output tokens.
- **Images:** table crops, about 600 tokens each in the app's estimate. Without a vision-capable model, the app leaves
  the images out and relies on the text. That works, but it loses accuracy on tables whose text layout is scrambled
  (common in older scanned papers).
- **Parallelism:** the app sends one request at a time by default (a setting, "requests at once"). If the server can
  run several in parallel without slowing each one much, note the number.
- **Timeout:** by default the app waits up to 900 s for the next piece of a streamed answer. A long prompt is read
  before the first token arrives, so prompt processing for a 100K-token prompt must finish within that.

## What has been tried (on the Mac, for reference)

- Ollama 0.40.15 with `gemma3:12b` (vision, 64K context) on an M2 Mac with 24 GB: about 10 output tokens/s, and one
  paper (eder1994) took 33 minutes end to end.
- Quality: 31 of 42 rows. Durations and temperatures were right, but table yields were mislabelled as starting
  concentrations, and conditions were filled in that don't apply.
- Conclusion: **a 12B model is a framework check, not a usable extractor.** About **30B parameters or more** is the
  realistic floor.
- What to look for in a model:
  - strong instruction following and structured JSON output over long contexts;
  - at least a 64K usable context (128K better);
  - ideally vision.
- The reference results come from Claude Sonnet, so the goal is the closest open model that fits this GPU.

## What to do

1. **Hardware:** find the GPU(s), VRAM, system RAM and free disk. Check that GPU drivers and CUDA (or ROCm) are
   current enough for the server.
2. **Server:** install Ollama (or LM Studio / llama.cpp if there's a reason to). Make it start reliably, as a service
   or at login.
3. **Network:**
   - Listen on the LAN, not only on localhost. For Ollama, set the environment variable `OLLAMA_HOST=0.0.0.0:11434`
     and restart Ollama.
   - Add a Windows Firewall inbound rule for that port, restricted to the private network or the Mac's IP if
     possible.
   - Ollama has no authentication, so keep it on a trusted network and don't expose it to the internet.
   - Note the machine's LAN IP, and give it a fixed IP or DHCP reservation if possible.
4. **Model:** choose a model as above. Pull one or two candidates, for example a larger text model plus a
   vision-capable one if they differ.
5. **Test with plain HTTP**, no app needed (curl or PowerShell `Invoke-RestMethod`):
   - `GET /api/tags`, from this machine **and** from another machine on the network if possible.
   - A structured-output request: `POST /api/chat` with `"format"` set to a small JSON Schema, `"options":
     {"num_ctx": 65536, "temperature": 0}` and a long prompt (paste 30–40K tokens of any long text and ask for a JSON
     summary that fits the schema). Check that the answer is valid JSON matching the schema, and time it.
   - Repeat at the largest context that fits (e.g. 131072), and watch GPU memory to see whether the model spills onto
     the CPU, which is much slower.
   - If the model does vision, send one image of a table and ask for its cells as JSON.
6. **Report back** what the app needs to be configured with:
   - server type (Ollama or OpenAI-compatible) and the address, e.g. `http://192.168.1.50:11434`;
   - each model's exact name, the context length that works, and whether it reads images;
   - measured prompt-processing speed and output tokens/s at the working context;
   - how many requests can run at once;
   - anything that needed a workaround.

## What happens next (on the Mac, not your job)

The user opens Parameter Extractor's Models › Connections (before 2026-11-11: Settings › Model provider) and enters:

- the server type and address,
- each model's context length and whether it reads images,
- a model profile: which model plans the rows, which does the extraction steps, which suggests figure settings.

*Test connection* lists the models the server reports. Runs then go to this machine at no API cost, and every result
is flagged as coming from an unvalidated local model.
