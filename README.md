# OpenClaw Home Archive

> **Status:** Experimental / pre-release. Back up important data and review changes before relying on this skill.

OpenClaw Home Archive gives your OpenClaw assistant a lasting reference for your home:
the things you own, the work you've had done, and the documents that go with them.
Save a model-label photo, a receipt, a manual, or a contractor's business card through
conversation, then ask for the details when you need them months or years later.

## A household archive you can talk to

Which filter fits the furnace? Who built the deck? Where is the water heater receipt?
Home Archive is designed to make those answers—and the original documents—easy to find.
You describe what you're saving in ordinary language, and the assistant uses the skill
to organize and retrieve it. There are no categories to design or record IDs to memorize.

Each item or project has a lasting record that can grow over time. Save your new
lawnmower now, add its receipt later, and attach a service invoice next season.
The record brings those details together with their sources and history.

## What it offers

- **Capture through conversation.** Supply photos, documents, or a simple note and
  explain what they belong to. The assistant interprets the request and identifies
  useful details such as models, purchase dates, parts, and contractor information.
- **Keep the original evidence.** Attachments are copied into the archive alongside
  the recorded facts, so you can return to the receipt, label, or business card.
  Content hashing detects files that have already been archived.
- **Build a history over time.** Add evidence to existing records, correct facts while
  retaining previous values, and merge duplicate records. Soft deletion keeps stored
  files in place.
- **Find details and their sources.** Search saved titles, facts, notes, and attachment
  descriptions. Facts retain source and confidence information to help answer
  “How do you know?”
- **Keep an inspectable archive on disk.** Records use readable Markdown, structured
  JSON, event history, and original files in a directory you configure. The archive
  remains available independently of the assistant's conversation history.
- **Browse images in Apple Photos.** Optional macOS integration publishes selected
  images to a regular `Home Archive` album with descriptive metadata. The album can
  be rebuilt from the files stored in the archive.

## Everyday use cases

These examples illustrate the conversational workflow the skill is designed to support:

| What you're keeping track of | Save or add | Ask later |
| --- | --- | --- |
| Appliances | “Save this toaster label and receipt.” | “What toaster do we have, and when did we buy it?” |
| Home repairs | “This is the invoice for the water heater replacement.” | “Show me the water heater invoice.” |
| Contractors and projects | “Here's the builder's business card. They built our deck.” | “Who built the deck? Show me their card.” |
| Replacement parts | “Save this furnace filter label.” | “What size furnace filter do I need?” |
| Paint and finishes | “This is the paint we used in the guest room.” | “What color and finish did we use in the guest room?” |
| Equipment maintenance | “Add this service receipt to the lawnmower.” | “Show me the lawnmower service records.” |

For example, a deck record might start with a completion photo and a note about the
builder. Later, you can add the builder's card, the final invoice, and care instructions.
When you ask about the deck, those related materials are available together. If an
attachment could belong to more than one record, the skill instructs the assistant
to ask which one you mean.

## How it fits into OpenClaw

Home Archive is an OpenClaw skill backed by a Python command-line tool. OpenClaw handles
the conversation and interprets supplied material; the tool handles durable records,
identifiers, attachment copies, search, and updates. Image and document interpretation
depends on the model and tools available in your OpenClaw setup.

The archive directory, shown as `<archive-root>` in these docs, is configured through
`HOME_ARCHIVE_ROOT`. That on-disk archive is the source of truth. Apple Photos provides
an optional browsing view of its images.

## Install
```bash
unzip home-archive-skill.zip
cd home-archive-skill
./install.sh
```
Requires Python 3 and the `openclaw` command on `PATH`. The installer reads
`skills.entries.home-archive.env.HOME_ARCHIVE_ROOT` from your active OpenClaw
configuration (normally `~/.openclaw/openclaw.json`). If configured, it displays
and preserves that location. Otherwise it prompts for an absolute path, with no
default, and saves it through `openclaw config set`.

For an unattended first installation, supply the location explicitly:

```bash
./install.sh --archive-root "<archive-root>"
```

Replace `<archive-root>` with your chosen absolute directory outside the installed
skill directory. A conflicting existing setting causes installation to stop; updates
never silently redirect an archive. A shell-only `HOME_ARCHIVE_ROOT` is offered as a
candidate during interactive setup and requires confirmation before it is saved.

Installs to `~/.openclaw/workspace/skills/home-archive/`.
Each installation replaces that directory completely, including hidden files and
local edits, with fresh skill code and documentation. No backup is created. Keep
configuration and household data outside the installed skill directory. Installation
configures a missing archive location but does not initialize the household archive.

OpenClaw supplies the configured environment variable during host-based skill runs.
For direct terminal use, export the same location before running the Python CLI:

```bash
export HOME_ARCHIVE_ROOT="<archive-root>"
```

The export applies to the current shell and its child processes. There is no fallback:
archive commands fail if the variable is missing or blank. `--help` still works without
configuration. Changing the location selects a different directory and does not move
existing archive data. Sandboxed OpenClaw runs need the variable and filesystem access
configured in the sandbox as well; host skill settings are not injected there.

See [OpenClaw skill configuration](https://docs.openclaw.ai/tools/skills-config) and
[configuration commands](https://docs.openclaw.ai/cli/config) for custom config paths
and deployment-specific setup.

Then run:
```bash
openclaw skills list | grep home-archive
python3 ~/.openclaw/workspace/skills/home-archive/scripts/home_archive.py init
python3 ~/.openclaw/workspace/skills/home-archive/scripts/home_archive.py doctor
```
The first Photos operation may trigger macOS Automation permission for Photos. Archive operations still work without Photos permission.


## Privacy and repository hygiene

The repository contains the skill code only. Household archive data is stored outside
the repository at the configured `<archive-root>`.

Do not commit archive data, logs, `.env` files, credentials, message exports, or
other personal material. The included `.gitignore` provides additional protection,
but it is not a substitute for reviewing changes before committing.

## License

MIT. See `LICENSE`.


## Development with coding agents

Before making implementation changes, read [`AGENTS.md`](AGENTS.md) and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). They document the repository invariants,
storage model, safety boundaries, known first integration regression, and current development
priorities.
