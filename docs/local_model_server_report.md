# Local model server: setup report

Set up 2026-11-10 on this Windows PC, following `local_model_server_brief.md`.

## Enter in Parameter Extractor (Settings › Model provider)

| Setting | Value |
|---|---|
| Server type | **Ollama** |
| Address | **`http://192.168.1.129:11434`** |
| Requests at once | **1** |

| Model (exact name) | Context length to enter | Reads images | Notes |
|---|---|---|---|
| `qwen3.8:27b` | **131072** | yes | Covers every paper, including the 80–120K-token exoplanet catalogues. |
| `gemma4:31b` | **81920** | yes | Faster, but only for prompts under about 75K tokens. Above 81920 it starts moving layers to the CPU. |

**Suggested model profile:** `qwen3.8:27b` for all three roles (planning, extraction, figure settings).
- The two models don't fit in VRAM together. Mixing them in one profile reloads a model at every switch, at about 10–20 s each.
- If you only process prebiotic papers (under 75K tokens), an all-`gemma4:31b` profile is about 1.5× faster.

## Measured performance (RTX 3090 24 GB, Ollama 0.40.16, q8_0 KV cache, flash attention)

Test request: shaped like the app's. Streamed `/api/chat`, a JSON Schema in `format`, `temperature: 0`, no `think` field. It asked for 12 measurements hidden in a long text (Darwin's *Origin of Species* as filler).

| Model | num_ctx | Prompt tokens | Prompt tok/s | Wait for first token | Output tok/s | On GPU | Result |
|---|---|---|---|---|---|---|---|
| qwen3.8:27b | 65536 | 31.8K | 283 | 142 s | **39.8** | 100% | valid JSON, 12/12 |
| qwen3.8:27b | 131072 | 95.9K | 374 | 262 s | **29.3** | 100% | valid JSON, 12/12 |
| qwen3.8:27b | 131072, default 2 GB VRAM margin (before fix) | 95.9K | 467 | 214 s | 6.5 | 74% | valid JSON, 12/12 |
| gemma4:31b | 65536 | 30.9K | 452 | 80 s | **42.2** | 100% | valid JSON, 12/12 |

- **Vision:** both models read a 5×5 table image (PNG) perfectly into JSON: 46 s for qwen, 23 s for gemma, model load included.
- **Prompt processing:** a 100K-token prompt finishes in about 4.5 min, well inside the app's 900 s timeout.
- **Planning estimate:** a 12K-token answer takes about 5–7 min at 128K context. A whole paper (10–25K output tokens) takes about 10–20 min of generation, plus about 2–4 min of prompt reading per step.
- **Parallelism:** with `OLLAMA_NUM_PARALLEL=2`, two concurrent 64K requests each fell to 6–8 tok/s (536 s for the pair, against about 400 s run one after the other). Keep it at **1**.
- **Thinking:** both are thinking models. Without a `think` field they reason for about 2.5–5K characters (roughly 1K tokens) before the JSON. That counts against `num_predict` but didn't cause any problem; the JSON was always valid.

## What was configured

- **Ollama:** upgraded from 0.40.11 to 0.40.16. Starts at login via `Startup\Ollama.lnk`, which runs `ollama app.exe`.
- **User environment variables:**
  - `OLLAMA_HOST=0.0.0.0:11434`
  - `OLLAMA_MODELS=D:\Ollama\models`
  - `OLLAMA_FLASH_ATTENTION=1`
  - `OLLAMA_KV_CACHE_TYPE=q8_0`
  - `OLLAMA_KEEP_ALIVE=30m`
  - `LLAMA_ARG_FIT_TARGET=512`
- **Model storage:** `D:\Ollama\models` (C: had only 53 GB free). `llama3:8b-instruct-q4_K_M` was copied there too. The old copy in `C:\Users\Mickey\.ollama\models` (about 5 GB) can be deleted.
- **Firewall:** the existing rule `ollama.exe` allows inbound TCP/UDP on the **Private** profile from any address. The network is set to Private, so the Mac can connect.

## Workarounds that were needed

1. **The Ollama desktop app ignores `OLLAMA_MODELS`.**
   - It keeps its own "model location" in `%LOCALAPPDATA%\Ollama\db.sqlite` (`settings.models`), which overrode the environment variable.
   - Set to `D:\Ollama\models`, and `expose` set to 1. The original database is backed up as `db.backup-20261110.sqlite*`.
   - If you change the model location in the app's Settings, it overrides this again.
2. **VRAM safety margin.**
   - By default the new llama.cpp runner keeps about 2 GB of VRAM free. That pushed qwen onto the CPU at anything above 64K, and gemma already at 64K, cutting output speed from about 30 to 6.5 tok/s.
   - `LLAMA_ARG_FIT_TARGET=512` lowers the margin to 512 MiB, so both models fit as listed above.

## Caveats and to-dos

- **VRAM is nearly full at 128K.**
  - Peak use was 24.1 of 24.6 GB. The desktop (Chrome, Discord, iCUE and others) also uses 1–2 GB of the 3090.
  - If a long run slows down sharply, close GPU-heavy apps, or plug the monitor into the motherboard's video output (the Ryzen's integrated graphics) to free about 1–2 GB.
  - Alternatively, use 98304 as qwen's context.
- **Tighter firewall rule (optional, needs admin).** Run this in an elevated PowerShell. You can then turn off the broad `ollama.exe` rules in *Windows Defender Firewall › Inbound Rules*:
  ```powershell
  New-NetFirewallRule -DisplayName 'Ollama LAN (TCP 11434)' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 11434 -Profile Private -RemoteAddress LocalSubnet
  ```
- **Fixed IP.** The address is currently from DHCP. In the router (gateway `192.168.1.1`), reserve `192.168.1.129` for MAC `C8-7F-54-70-38-FE` (Ethernet 3, Realtek 2.5GbE).
- **Auto-update** is on in the Ollama app. A future version could change memory behaviour; rerun a quick test after an update.
- **No authentication.** Ollama has none, so keep this machine on the trusted home network only, and never forward port 11434 on the router.
- **Not yet tested from the Mac.** Run this there:
  ```bash
  curl http://192.168.1.129:11434/api/tags
  ```

The test scripts are in the Claude session scratchpad (`bench.py`, `vision.py`). They are temporary and can be recreated if needed.
