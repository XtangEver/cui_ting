# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

cui_ting is a video transcription and summarization tool that downloads audio from Bilibili/YouTube, transcribes using Whisper (MLX for Apple Silicon), and generates structured summaries using LLMs.

## Commands

```bash
# Activate environment and run
conda activate cui_ting && python cli.py

# Install dependencies
pip install -r requirements.txt
```

## Architecture

The project uses a pipeline architecture:

```
cli.py → VideoSummarizer.process() → AudioDownloader → Transcriber → LLMProcessor → TextProcessor
```

**Core modules:**
- `cli.py` — Entry point. Reads `input_data.json` and processes batch tasks.
- `core/summarizer.py` — Main orchestrator. Coordinates the pipeline: download → transcribe → refine. Handles resume logic (checks for existing files).
- `core/downloader.py` — Audio download using yt-dlp. Handles Bilibili/YouTube cookies, multi-part videos, and FFmpeg merging.
- `core/transcriber.py` — MLX Whisper transcription with Metal GPU acceleration.
- `core/llm_processor.py` — LLM API calls for text refinement/denoising.
- `core/text_processor.py` — Text chunking and result merging.
- `core/config.py` — Configuration management from config.yaml.

**Configuration:**
- `config.yaml` — LLM models, Whisper path, chunk settings, I/O paths
- `input_data.json` — Batch task list (folder name → video URL)

## Key Patterns

- **Resume logic**: When rerunning, the tool checks for existing files:
  - `source*.mp3` → skip download
  - `*_raw.md` → skip transcription
  - `*_refined.md` → skip LLM processing
- **Directory structure**: Output can be flat or nested (`output_dir/video_id/`). The code searches both locations.
- **Cookie management**: Platform-specific cookies in `cookie/` directory, selected automatically based on URL.

## Data Flow

1. Extract video ID from URL
2. Download audio to output directory
3. Transcribe to `source_raw.md`
4. Split text into chunks, process each with LLM
5. Merge results to `source_refined.md`