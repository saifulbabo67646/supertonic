# Troubleshooting

Help for starting Supertonic with the double-click launchers (`Start Supertonic.command` on
macOS, `Start Supertonic.bat` on Windows, `start-supertonic.sh` on Linux). Most problems
show a message in the launcher window; find it below.

## Starting and stopping

**Start:** double-click the launcher for your system in the Supertonic folder. A window
opens, installs what is needed (only the first time), starts Supertonic and then opens the
Studio in your browser.

**Stop:** close that window, or click into it and press Ctrl+C. Closing the browser tab
does not stop Supertonic; closing the window does.

**Restart:** stop it, then double-click the launcher again. If Supertonic is already
running, the launcher just opens the Studio again instead of starting a second copy.

## The first start

| What you see | What to do |
|---|---|
| A message about installing **uv** | Normal on the first start. uv is a small free tool from Astral that installs Python and everything Supertonic needs. It goes into a folder in your home directory and needs no administrator rights. |
| Dots for several minutes after "The first start downloads the voice model" | Normal. The voice model is about 400 MB and is downloaded once. Later starts take a few seconds. |
| "installing uv failed" or "installing Supertonic's dependencies failed" | The first start needs an internet connection. Check that you are online (and that a company proxy or firewall allows downloads), then start the launcher again. It continues where it left off. |
| The model download stops with an error | Start the launcher again; the download starts over cleanly (a half-finished download is never used). If it keeps failing, your network may block Hugging Face (`huggingface.co`), where the model is hosted. |
| "taking much longer than usual to start" | Usually a slow connection during the model download. Leave the window open a little longer. If the window shows an error, start again. |

No internet after the first start is fine: everything Supertonic needs is then on your
computer.

## macOS

| What you see | What to do |
|---|---|
| "Start Supertonic.command cannot be opened because it is from an unidentified developer" (or "Apple could not verify...") | Right-click (or Control-click) the file, choose **Open**, then **Open** again. macOS remembers this, so you only do it once. On recent macOS versions you may instead need **System Settings > Privacy & Security > Open Anyway**. |
| "You do not have permission to open the application" or nothing happens | The file lost its "executable" mark (this can happen with some unzip tools). Open the Terminal app, type `chmod +x ` (with a space), drag the file into the Terminal window, and press Enter. |
| Apple Silicon or Intel? | Both work; nothing to choose. |

## Windows

| What you see | What to do |
|---|---|
| "Windows protected your PC" (SmartScreen) | Click **More info**, then **Run anyway**. Windows shows this for files downloaded from the internet that are not signed. |
| Your antivirus blocks or quarantines the launcher | The launcher only runs `scripts\launch.ps1` from the same folder. Allow it, or add the Supertonic folder as an exception. |
| A firewall prompt for Python | Supertonic only listens on your own computer (`127.0.0.1`), so it does not need network access from other machines. You can click **Cancel** or allow it on private networks only. |
| "running scripts is disabled on this system" | Start with `Start Supertonic.bat`, not by double-clicking the `.ps1` file. The `.bat` file allows the script for that one window only; it never changes your system settings. |

## Ports

Supertonic uses port 8787. If another program already uses it, the launcher picks the next
free one (up to 8799) and says which; the Studio opens at that address. If all of them are
in use, close the program using them, or choose another port: start from a terminal with
`--port 9000` added, or put `SUPERTONIC_PORT=9000` in a `.env` file in the Supertonic folder.

## The voice builder (NVIDIA graphics cards)

On Windows and Linux with an NVIDIA graphics card, the launcher also installs the voice
builder (PyTorch with CUDA, about 3 GB) so you can build new voices from recordings on this
computer. macOS has no NVIDIA GPU support, so building happens on another machine there (see
[builder.md](builder.md), "Forwarding builds").

If the builder install fails, Supertonic still starts with the built-in and imported voices;
only building on this computer is unavailable. Common causes: no internet, not enough disk
space (keep about 5 GB free), or an outdated NVIDIA driver (`nvidia-smi` in a terminal must
work). To skip the builder install altogether, set `SUPERTONIC_SKIP_BUILDER=1` before
starting. More builder problems: [builder.md](builder.md#troubleshooting).

## Where your data lives and how to reset

| What | Where |
|---|---|
| Your custom voices | `.supertonic-server` in your home folder (`~/.supertonic-server` on macOS and Linux, `%USERPROFILE%\.supertonic-server` on Windows), or `SUPERTONIC_DATA_DIR` if set |
| The voice model (about 400 MB) | `.cache/supertonic3` in your home folder, or `SUPERTONIC_MODEL_DIR` if set |
| Python and the installed dependencies | the `.venv` folder inside the Supertonic folder |
| uv itself | `.local/bin` in your home folder |

To reset, stop Supertonic first. Then:

- **Reinstall dependencies:** delete the `.venv` folder in the Supertonic folder and start
  again.
- **Download the model again:** delete `.cache/supertonic3` in your home folder.
- **Remove your custom voices:** delete `.supertonic-server` in your home folder. This
  cannot be undone; export voices you want to keep from the Voices page first.

Saved API keys and settings in the Studio live in your browser; clear them on the Connect
page (Forget key).

## Still stuck?

Copy the messages from the launcher window and open an issue on the project's GitHub page.
Remove any API keys from the text first.
