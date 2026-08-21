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

### Environment Configuration (Gemini Vision Fallback)

The pipeline uses Google's Gemini Vision API as an enhanced fallback for scanned/rasterized PDFs. This requires a free-tier API key.

1. Copy the `.env.example` file in the `backend/` folder to `.env`:
   ```bash
   cp backend/.env.example backend/.env
   ```
2. Open `backend/.env` and add your Gemini API key (you can get one for free at [Google AI Studio](https://aistudio.google.com/apikey)):
   ```env
   GEMINI_API_KEY=your-key-here
   ```
3. (Optional) Override the model via `GEMINI_MODEL` if the default needs to change:
   ```env
   GEMINI_MODEL=gemini-2.5-flash
   ```
   Google periodically retires Gemini model ids — `gemini-2.5-flash` is confirmed active as of 2026-08 but Google
   has announced its retirement for 2026-10-16. If Gemini calls start failing with a "not found"/"deprecated"
   error (visible in the `/api/extract/health-check` response and in extraction warnings), check
   [the current model list](https://ai.google.dev/gemini-api/docs/models) and update this value — no code change
   needed.

*Note: If no key is provided, the system will gracefully fall back to using local Tesseract OCR for scanned PDFs.
Gemini is only ever used for pages with no real text layer — pages pdfplumber can already read directly never
go through this fallback chain at all, and Gemini-sourced values are always capped at amber confidence, never
green, since they are a single-source AI read of an image rather than an extracted value.*

### Health Check

You can verify that all dependencies and the Gemini API key are correctly configured by visiting the health check endpoint while the backend is running:

`GET http://localhost:8000/api/extract/health-check`
