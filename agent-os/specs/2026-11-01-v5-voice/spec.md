# Spec: v5 voice

Status: shaped 1.11.2026 (bonus item from the brief, owner asked for it after the must-haves shipped).

## Goal

Voice in the chat page at zero backend cost: a microphone button that dictates a question with the browser's
Web Speech API and submits it, and a read-aloud toggle that speaks answers. Nothing reaches the server but text.

## Scope

**In:** `src/app/api/static/index.html` only (mic button, speaker toggle, speech recognition, speech synthesis,
preference remembered in localStorage); README and DESIGN notes. **Out:** server-side speech, audio upload,
non-English recognition.

## Acceptance criteria

1. The page has a mic button that is hidden unless the browser exposes `SpeechRecognition` or `webkitSpeechRecognition`, and a read-aloud toggle button with `aria-pressed` state; both are inline SVG icons, no external scripts.
2. A recognition result fills the input and submits the form; the answer to a spoken question is read aloud even when the toggle is off, and only the answer text is spoken, never sources, limitations or the technical line.
3. The read-aloud preference is stored under `airportiq.readAloud` in localStorage and restored on load; turning it off cancels any speech in progress.
4. The page still contains no external script and no `https://` URL inside its script; the server receives only `POST /api/chat` with text (no new routes, no audio).

## Design

Lifted from hubrisk v8: `const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition`; mic
`hidden` until supported; `rec.onresult` sets `q.value`, marks the turn as spoken and calls `requestSubmit()`;
`sayAnswer(text)` speaks when the turn was spoken or the toggle is on, cancelling any prior utterance; the
toggle persists through `localStorage` in a try/catch (private windows throw). Tests assert the served HTML.

## Tasks

1. Save spec documentation.
2. Edit `index.html`; `tests/test_v5_voice.py`; README voice note; DESIGN architecture bullet; roadmap; commit, push.
