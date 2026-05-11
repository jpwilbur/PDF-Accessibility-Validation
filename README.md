# ObservePoint PDF Validation

A local web app that audits PDFs for accessibility. Point it at an
ObservePoint saved report (or paste in your own list of URLs) and it
will download every PDF, run each one through a full check battery
covering PDF/UA-1, WCAG 2.1 A/AA, Section 508, and the HHS PDF
Accessibility Checklist, and produce a remediation-focused report per
document.

Everything runs on your laptop. No cloud, no extra account, no data
leaves your machine.

---

## Before you start

You'll need:

- A **Mac** (macOS 12 or newer) or a **Windows 10/11** PC
- An **ObservePoint account** with an API key
- A **saved report** in ObservePoint that exposes a `LINK_URL` column
  (instructions below — this is the only ObservePoint-side setup)

The install is about five minutes of copy-paste, no compilation, no
Python knowledge required.

---

## Install — macOS

Open **Terminal**. Paste each block, hit Enter, wait for it to finish
before pasting the next one.

### 1. Homebrew (skip if you already have it)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2. System tools

```bash
brew install uv openjdk verapdf tesseract
```

### 3. The app itself

```bash
uv tool install git+https://github.com/jpwilbur/PDF-Accessibility-Validation
```

### 4. Run it

```bash
pdf-a11y serve
```

A browser tab opens at <http://127.0.0.1:8765>. Leave the Terminal
window running while you use the app. Press `Ctrl+C` to stop.

---

## Install — Windows

Open **PowerShell** (right-click Start → "Windows Terminal" or
"PowerShell"). Paste each block, hit Enter, wait for it to finish
before pasting the next one.

### 1. uv, Java, and Tesseract (via winget)

```powershell
winget install --id=astral-sh.uv -e
winget install --id=EclipseAdoptium.Temurin.21.JDK -e
winget install --id=UB-Mannheim.TesseractOCR -e
```

### 2. veraPDF

veraPDF doesn't ship a winget package. Download the installer:

<https://github.com/veraPDF/veraPDF-apps/releases/latest>

Pick the "veraPDF-installer-X.Y.Z.zip" asset, unzip it, then
double-click `verapdf-install.bat`. Accept the defaults — the
installer puts `verapdf` on your PATH.

### 3. Re-open PowerShell

Close the current PowerShell window and open a new one. This is
needed so the new tools land on your PATH.

### 4. The app itself

```powershell
uv tool install git+https://github.com/jpwilbur/PDF-Accessibility-Validation
```

### 5. Run it

```powershell
pdf-a11y serve
```

A browser tab opens at <http://127.0.0.1:8765>. Leave PowerShell
running while you use the app. Press `Ctrl+C` to stop.

---

## Using the app

### Get your ObservePoint API key

Log in to ObservePoint, then go to
<https://app.observepoint.com/my-profile>. Copy the API key shown
there.

### Set up the saved report

The app needs a saved report whose grid includes the **Link URL**
column — that's what tells it which PDFs to validate.

1. Run any audit that visits the pages you care about. (If you need
   to seed it with PDF discovery, the sibling
   [PDFScraper](https://github.com/jpwilbur/PDFScraper) README has a
   JavaScript snippet that drops into an ObservePoint
   "Execute JavaScript" on-page action.)
2. Open the audit's grid view. Add the **Link URL** column if it
   isn't there.
3. Save the grid as a report. Copy the saved-report ID from the URL
   in your browser.

### Start a validation

In the browser tab the app opened:

1. Paste your **API key** and **saved-report ID** into the form.
2. Optionally check **Remember this machine** so you don't have to
   paste them next time.
3. Click **Start run**.

You'll be sent to the run page, which shows:

- **URLs submitted** — how many came back from the ObservePoint report
- **PDFs evaluated** — how many of those were actually valid PDFs
- **Critical fails** — documents unusable by assistive tech
  (untagged, scan-only, encryption-blocking)
- **Non-PDF URLs** — links that returned HTML, 404s, redirects, etc.
  (skipped automatically, doesn't count against you)
- A live progress bar with each PDF's grade as it finishes
- The full HTML report below, with sortable / filterable rows per PDF

### Reviewing past runs

Click **History** in the top nav. Every run is recorded with its
counts, status, and a link to its report. Use **Delete** to free the
disk space for a run you no longer need.

---

## Updating

When new versions land, run:

```bash
uv tool upgrade pdf-a11y
```

(Same command on Mac and Windows.)

---

## Where your data lives

Everything stays on your machine, in one folder:

- **Mac:** `~/Library/Application Support/pdf-a11y/`
- **Windows:** `%LOCALAPPDATA%\pdf-a11y\`

That folder contains:

- `runs.db` — index of every run
- `runs/<run_id>/` — each run's reports (HTML, CSV, JSON). The
  downloaded PDFs themselves are deleted right after each run
  finishes, so the folder doesn't grow unboundedly.
- `settings.json` — your saved API key, stored in plaintext
  (the file is user-only readable; the app only sends the key to
  ObservePoint and nowhere else)

Delete the folder to wipe everything.

---

## Troubleshooting

**"command not found: pdf-a11y"** *(or PowerShell equivalent)*
Open a brand-new Terminal / PowerShell window. `uv tool install`
puts the command on PATH for *new* shells.

**"veraPDF: ✗ missing" on the home page**
Java isn't on PATH, or veraPDF isn't installed. The **System
dependencies** card on the home page tells you the exact install
command for your OS and gives you a one-click Copy button — paste
it into your terminal and re-run `pdf-a11y serve`.

**"Saved report 'X' has no LINK_URL column"**
The app refuses to download anything without that column. Open
the saved report in the ObservePoint grid, add the **Link URL**
column, re-save, and re-submit.

**A whole bunch of "Non-PDF URLs"**
Normal. Many websites have links that look like PDFs (or include
the word "pdf" in their URL) but return HTML, redirect to a login,
or 404. They're silently skipped and tallied in the **Non-PDF
URLs** stat — they don't count against your score and aren't in
the grade distribution.

**The run page sits at "running" forever**
The run probably actually completed but the live progress stream
disconnected. Refresh the page — the server has the current state
and will redraw correctly.

**I want to expose the app on a network address**
The app deliberately rejects any request whose `Host` header isn't
`127.0.0.1` or `localhost`. This is a security measure (against
DNS rebinding attacks that would otherwise let any web page read
your saved API key). The app is designed for single-user local
use; running it on a shared host isn't supported.

---

## Uninstall

```bash
uv tool uninstall pdf-a11y
```

Then delete the data folder:

- **Mac:** `rm -rf ~/Library/Application\ Support/pdf-a11y`
- **Windows:** `Remove-Item -Recurse "$env:LOCALAPPDATA\pdf-a11y"`

---

## What it checks

41 registered checks across six categories. See:

- [`docs/checks.md`](docs/checks.md) — the full catalog, grouped by
  category (Structure, Semantics, Text, Visual, Navigation, Forms,
  Multimedia)
- [`docs/standards-mapping.md`](docs/standards-mapping.md) — reverse
  index from every cited standard clause back to the check(s) that
  verify it

Each PDF gets its own A–F grade. By design, there is **no aggregate
run score** — only per-PDF scores. Three checks force an automatic
F regardless of the rest:

- Document isn't tagged
- PDF/permissions disable accessibility content extraction
- Pages are scanned images with no real text layer

---

## Standards covered

- **PDF/UA-1** (ISO 14289-1) — via veraPDF, ~30 mapped rules + catch-all
- **Matterhorn Protocol** — via veraPDF rule mapping
- **WCAG 2.1 A and AA** (and WCAG 2.2 deltas where applicable)
- **Section 508** (Revised, 2018)
- **HHS PDF Accessibility Checklist**

---

## Development

If you want to hack on the code itself:

```bash
git clone https://github.com/jpwilbur/PDF-Accessibility-Validation
cd PDF-Accessibility-Validation
uv sync --extra dev
uv run pytest        # 79 tests
uv run ruff check src tests
uv run mypy src/pdf_a11y/checks src/pdf_a11y/models.py src/pdf_a11y/scoring.py
uv run pdf-a11y serve
```
