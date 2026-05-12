#!/usr/bin/env bash
# pdf-a11y bootstrap (macOS / Linux)
#
# Installs system deps (verapdf, openjdk, tesseract) plus uv, then installs
# the pdf-a11y CLI as a `uv tool`. Designed to be safe to re-run.
#
# Once published, intended invocation will be:
#   curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/bootstrap.sh | bash
#
# For now, run locally:
#   bash bootstrap.sh

set -euo pipefail

REPO_URL_DEFAULT="${PDF_A11Y_REPO:-}"  # empty until published
THIS_DIR="$(cd "$(dirname "$0")" && pwd)"

err() { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }
say() { printf '\033[0;36m%s\033[0m\n' "$*"; }
ok()  { printf '\033[0;32m%s\033[0m\n' "$*"; }

# ----- detect platform -----------------------------------------------------
unameOut="$(uname -s)"
case "${unameOut}" in
    Darwin*) platform=mac ;;
    Linux*)  platform=linux ;;
    *)       err "Unsupported platform: ${unameOut}"; exit 1 ;;
esac
say "Detected platform: $platform"

# ----- install uv ----------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
    say "Installing uv (https://astral.sh/uv)…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # uv installs into ~/.local/bin or ~/.cargo/bin depending on the platform;
    # add the canonical location for this session if needed.
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
else
    ok "uv already installed: $(uv --version)"
fi

# ----- install system deps -------------------------------------------------
if [ "$platform" = "mac" ]; then
    if ! command -v brew >/dev/null 2>&1; then
        err "Homebrew is required on macOS. Install it from https://brew.sh, then re-run."
        exit 1
    fi
    say "Installing veraPDF, OpenJDK, Tesseract, and PDF-export libs via Homebrew (skips already-installed)…"
    # pango/glib/cairo are needed by WeasyPrint for PDF export.
    for pkg in verapdf openjdk tesseract pango glib cairo; do
        if brew list --formula | grep -qx "$pkg"; then
            ok "  $pkg already installed"
        else
            brew install "$pkg"
        fi
    done
else
    # Linux: keep this minimal and informative; we don't try to detect distro.
    say "Linux detected. Please install veraPDF, OpenJDK, and Tesseract:"
    cat <<'EOM'
  Debian/Ubuntu:
    sudo apt update && sudo apt install -y openjdk-21-jre tesseract-ocr
    Then download veraPDF: https://github.com/veraPDF/veraPDF-apps/releases
  Fedora/RHEL:
    sudo dnf install -y java-21-openjdk tesseract
    Then download veraPDF: https://github.com/veraPDF/veraPDF-apps/releases
EOM
    say "(Skipping system-deps install — re-run after installing them.)"
fi

# ----- install pdf-a11y as a uv tool --------------------------------------
say "Installing pdf-a11y as a uv tool…"
if [ -n "$REPO_URL_DEFAULT" ]; then
    uv tool install --force "git+$REPO_URL_DEFAULT"
elif [ -f "$THIS_DIR/pyproject.toml" ]; then
    say "  (installing from local source: $THIS_DIR)"
    uv tool install --force "$THIS_DIR"
else
    err "Don't know where to install pdf-a11y from. Set PDF_A11Y_REPO=<git-url> and re-run."
    exit 1
fi

ok ""
ok "✓ Done. Start the local web app with:"
ok "    pdf-a11y serve"
ok ""
ok "If 'pdf-a11y' isn't on your PATH yet, open a new terminal or run:"
ok "    export PATH=\"\$HOME/.local/bin:\$PATH\""
