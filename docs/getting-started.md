# Getting started

This guide is for everyone, no programming needed. Supertonic turns text into natural
speech, in 31 languages, on your own computer. It is free, and what you type stays on
your computer.

You need a Mac, a Windows PC or a Linux PC, an internet connection for the first start,
and about 1 GB of free disk space.

## 1. Download Supertonic

1. Open <https://github.com/saifulbabo67646/supertonic> in your browser.
2. Click the green **Code** button, then **Download ZIP**.
3. Unzip the file:
   - **Mac:** double-click the ZIP file in your Downloads folder.
   - **Windows:** right-click the ZIP file, choose **Extract All...**, then **Extract**.
     Do not start Supertonic from inside the ZIP file; it needs the unzipped folder.
4. You now have a folder called `supertonic-main`. You can move it anywhere you like, for
   example to your Documents folder. Do this before the first start.

## 2. Start it

Open the `supertonic-main` folder and double-click the start file for your computer.

### Mac

Double-click **Start Supertonic.command**.

The first time, macOS may block it with a message that Apple "could not verify" it or
that it is "from an unidentified developer". That is normal for files downloaded from the
internet that are not from the App Store. To allow it:

1. Click **Done** (or **OK**) in the message.
2. Open **System Settings > Privacy & Security** and scroll down to **Security**.
3. Next to the message about "Start Supertonic.command", click **Open Anyway** and confirm
   (with your password or Touch ID if asked). If you don't see **Open Anyway**, double-click
   the file once more, then look again.
4. Double-click **Start Supertonic.command** again, and click **Open** if asked.

macOS remembers this, so you only do it once. On older macOS versions (before macOS 15
Sequoia), right-clicking the file and choosing **Open** also works.

### Windows

Double-click **Start Supertonic.bat**.

The first time, Windows may show "Windows protected your PC". Click **More info**, then
**Run anyway**. Windows shows this for downloaded files that are not signed.

Supertonic only talks to your own computer, so it never needs to be allowed through a
firewall.

### Linux

Double-click **start-supertonic.sh**. If your file manager opens it as text instead, open
a terminal in the folder and type `./start-supertonic.sh`.

### What happens next

A window with text opens. The first time, Supertonic installs what it needs and downloads
its voice model (about 750 MB in total). This takes a few minutes, and you see dots while
it works. Later starts take a few seconds.

When it is ready, the window says "Supertonic is ready" and the **Supertonic Studio** opens
in your browser. Keep the window open while you use Supertonic.

Something went wrong? Look for the message in [troubleshooting.md](troubleshooting.md).

## 3. A tour of the Studio

The Studio has three tabs at the top: **Speak**, **Voices** and **Connect**. **Help** at
the top right opens this guide.

### Speak

1. Type or paste your text in the big box. **Try a sample sentence** fills in an example.
2. Pick a **voice**, for example Mia or Hugo. ▶ next to it plays a short sample.
3. Pick the **language** your text is written in.
4. If you like, move **Speed** to the left to slow down or to the right to speed up.
5. Press **Generate**. After a moment you hear your text.
6. Press **Download** to save it. **File type** chooses MP3 (smaller) or WAV.

Everything you make is listed under **Recent**, so you can make it again later.

### Voices

The voice library. Press ▶ to hear any voice in any language, and **Use in Speak** to pick
it. The ten built-in voices have names like Mia, Nora, Hugo and Diego; what each one sounds
like is in [voices.md](voices.md).

Voices you make or add appear under **Your voices**. You can rename them, delete them, or
save them as a file with **Download voice file** to keep a copy or use them on another
computer. To add such a file, use **Add a voice from a file**.

### New voice

On the Voices page, **New voice** makes a new voice from a recording of someone speaking.
See the next section.

### Connect

For using Supertonic from other apps, scripts and AI assistants such as Claude Code. It
shows the address to give those apps and ready-to-copy examples. You only need this page if
you want to connect something; the Studio itself works without it.

## 4. Make your own voice

Supertonic can learn a voice from about a minute of recording. Building it takes a lot of
computing power, so it needs an **NVIDIA graphics card** (on Windows or Linux). Macs and
computers without such a card cannot build voices themselves; the Studio then explains
your options, such as sending the work to another computer that has one
([builder.md](builder.md)). Voices made elsewhere work on every computer.

1. Go to **Voices** and press **New voice**.
2. **Record or upload the voice.** Upload a recording, or press **Or record yourself now**
   and read the text shown. Tips:
   - a quiet room, no music, TV or other people talking;
   - only one person speaking: the voice you want;
   - keep the microphone close, and talk naturally for 30 to 60 seconds.
3. **Name it and confirm permission.** Give the voice a name, say where the recording is
   from, and tick the box to confirm you have the speaker's permission. Only make voices
   of yourself or of people who agreed.
4. **Choose how to build it:**
   - **Best match**, about 1½ hours: sounds closest to the speaker.
   - **Quick draft**, about 15 minutes: a fast first try.
5. Press **Build voice**. You can leave the page while it builds. **Finish now** stops early
   and keeps the best result so far.
6. When it is done, try your voice right there, then find it in **Voices** and in **Speak**.

## 5. Stop and start

- **Stop:** close the Supertonic window (or click into it and press Ctrl+C). Closing only
  the browser tab does not stop Supertonic.
- **Start again:** double-click the start file again. If Supertonic is already running, it
  just opens the Studio again.
- **Open the Studio again** while Supertonic runs: go to <http://127.0.0.1:8787/> in your
  browser. If the window said another number than 8787, use that one.

## 6. Where your files are

| What | Where |
|---|---|
| Speech you download | your browser's Downloads folder |
| Your own voices | the `.supertonic-server` folder in your home folder |
| The voice model | the `.cache/supertonic3` folder in your home folder |
| Supertonic itself | the `supertonic-main` folder you unzipped |

Folders that start with a dot are hidden. On a Mac, press Cmd+Shift+. (period) in Finder to
show them. On Windows, choose **View > Show > Hidden items** in File Explorer.

To keep your voices safe, save them with **Download voice file** on the Voices page.

## 7. Update to a new version

1. Stop Supertonic.
2. Download the new ZIP and unzip it (steps 1 to 4 at the top).
3. Start the new version. Your own voices are kept, because they live in your home
   folder, not in the Supertonic folder. You can delete the old Supertonic folder.

## 8. Uninstall

1. Stop Supertonic.
2. Delete the `supertonic-main` folder.
3. Delete the voice model: the `.cache/supertonic3` folder in your home folder.
4. Delete your own voices, if you no longer want them: the `.supertonic-server` folder in
   your home folder. This cannot be undone.
5. Optional: Supertonic's installer tool, uv, may also be used by other programs. If you
   know it is not, delete it too: on a Mac or Linux, `.local/bin/uv`, `.local/bin/uvx`,
   `.cache/uv` and `.local/share/uv` in your home folder; on Windows, `uv.exe` and
   `uvx.exe` in `.local\bin` in your home folder, and the `uv` folders in `AppData\Local`
   and `AppData\Roaming`.

## Questions

**Is it really free?** Yes. Supertonic's code is free and open source (MIT licence). The
voice model has its own licence (OpenRAIL-M) that allows free use but forbids harmful
uses: never use a voice to impersonate, deceive or harm anyone. Read it on the
[model page](https://huggingface.co/Supertone/supertonic-3).

**Does it need the internet?** Only for the first start. After that it works offline.

**Is what I type private?** Yes. Your text and audio never leave your computer.

**Which languages does it speak?** 31, including English, Spanish, French, German,
Japanese, Korean, Arabic and Hindi. Every voice speaks every language. The Language list
on the Speak page shows them all.

**Do I need a powerful computer?** No. Speaking works on an ordinary laptop. Only building
new voices needs an NVIDIA graphics card.

**Can I use it on my phone or another computer?** Not out of the box: Supertonic only
answers on the computer it runs on, which keeps it safe. A technical friend can set it up
with an access key ([remote-access.md](remote-access.md)).

**The Studio asks for an access key.** Someone set up this Supertonic with a key, like a
password. Ask them for it.

**Can I use these voices in my videos?** Yes, within the model licence above. For a voice
you build, you also need the speaker's permission.

**Can an AI assistant set it up for me?** Yes, if you use one such as Claude Code: see
[agent-setup.md](agent-setup.md).

More help: [troubleshooting.md](troubleshooting.md). Still stuck? Open an issue on the
[GitHub page](https://github.com/saifulbabo67646/supertonic/issues) and paste the messages
from the Supertonic window (remove any access keys first).
