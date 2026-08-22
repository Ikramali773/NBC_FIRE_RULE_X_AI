# FireRuleX

FireRuleX is an AI-powered fire extinguisher compliance checker based on IS 2190:2024 and NBC 2016 Part IV.

## Building Plan Extraction Module

FireRuleX includes a powerful, free-tier extraction module that can automatically extract building parameters (height, floors, area, occupancy, etc.) from uploaded building plans in **PDF** or **DWG** format.

### System Dependencies

To use the full capabilities of the extraction module, you must install the following system packages (these cannot be installed via pip):

1. **LibreDWG** (`dwg2dxf`)
   - Required for converting uploaded DWG files to DXF for analysis.
   - **Windows**: Download binaries from [LibreDWG Releases](https://github.com/LibreDWG/libredwg/releases) and add `dwg2dxf.exe` to your system PATH.
   - **Ubuntu/Debian**: `sudo apt-get install libredwg-tools`

2. **Poppler** (`pdf2image`)
   - Required for rasterizing scanned PDFs before OCR/Vision extraction.
   - **Windows**: Download poppler for Windows, extract, and add the `bin` folder to your PATH.
   - **Ubuntu/Debian**: `sudo apt-get install poppler-utils`

3. **Tesseract OCR**
   - Required as a guaranteed fallback for scanned PDF extraction.
   - **Windows**: Install from [UB-Mannheim Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) and add to PATH.
   - **Ubuntu/Debian**: `sudo apt-get install tesseract-ocr`

### Environment Configuration (Multi-Provider Vision Fallback Chain)

For scanned/rasterized PDF pages with no real text layer, the pipeline tries up to four free-tier AI vision
providers in order, before falling back to local Tesseract OCR:

1. **Gemini** (primary)
2. **Groq** (secondary)
3. **OpenRouter** free vision models (tertiary)
4. **Mistral OCR** (quaternary) — specifically the best option for dense, degraded, small-print content (e.g. area/FSI
   tables on scanned government-approved plans), since it's purpose-built for document OCR rather than general vision chat.
5. **Tesseract** (guaranteed final fallback) — always works, even with zero keys configured.

Every key below is optional and independent. Leave any subset blank; the chain simply skips that provider and
falls through to the next one. **Pages pdfplumber can already read directly never go through any of this** —
only pages with no extractable text reach the AI fallback chain at all.

1. Copy the `.env.example` file in the `backend/` folder to `.env`:
   ```bash
   cp backend/.env.example backend/.env
   ```
2. Open `backend/.env` and add whichever keys you have. Each is free-tier:

   | Provider | Get a free key at | Env var |
   |---|---|---|
   | Gemini | [Google AI Studio](https://aistudio.google.com/apikey) | `GEMINI_API_KEY` |
   | Groq | [console.groq.com/keys](https://console.groq.com/keys) | `GROQ_API_KEY` |
   | OpenRouter | [openrouter.ai/keys](https://openrouter.ai/keys) | `OPENROUTER_API_KEY` |
   | Mistral | [console.mistral.ai/api-keys](https://console.mistral.ai/api-keys) | `MISTRAL_API_KEY` |

   ```env
   GEMINI_API_KEY=your-key-here
   GROQ_API_KEY=your-key-here
   OPENROUTER_API_KEY=your-key-here
   MISTRAL_API_KEY=your-key-here
   ```
3. (Optional) Override the Gemini model via `GEMINI_MODEL` if the default needs to change:
   ```env
   GEMINI_MODEL=gemini-3.6-flash
   ```
   Google periodically retires Gemini model ids — `gemini-2.0-flash` was shut down 2026-06-01, and
   `gemini-2.5-flash` (this project's previous default) started 404ing for new API keys shortly after with
   Google's own error naming the replacement ("no longer available to new users... use models/gemini-3.6-flash").
   If Gemini calls start failing with a "not found"/"deprecated" error (visible in the `/api/extract/health-check`
   response and in extraction warnings), check [the current model list](https://ai.google.dev/gemini-api/docs/models)
   and update this value — no code change needed. Groq's and OpenRouter's models are selected automatically at
   call time from their current model listings rather than hardcoded, since free-tier vision model availability
   rotates on both platforms.

*Note: with zero keys configured, the system works exactly as before — falling back to local Tesseract OCR for
every scanned page. Every AI-provider-sourced value (Gemini, Groq, OpenRouter, or Mistral) is always capped at
amber confidence, never green, since each is a single-source AI read of an image rather than a directly
extracted value; the specific provider that answered is always recorded alongside the value.*

### Health Check

Two ways to confirm which providers are actually configured and working, without uploading a real file first:

- **Startup log** — when the backend starts, it prints one clear ENABLED/DISABLED line per provider
  (Gemini, Groq, OpenRouter, Mistral) plus a READY/MISSING line for Tesseract/Poppler.
- **Health-check endpoint** — makes one minimal, free metadata call per configured provider (never a
  generation call, so it costs no meaningful quota) to confirm each key is actually valid and not expired/revoked:

  `GET http://localhost:8000/api/extract/health-check`
