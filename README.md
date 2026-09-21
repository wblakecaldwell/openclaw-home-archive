# OpenClaw Personal Archive

> **Status:** Experimental / pre-release. Back up important data and review changes before relying on this skill.

Personal Archive is an OpenClaw skill for preserving and retrieving durable, evidence-backed personal records. It keeps original evidence, structured facts, provenance, and history outside conversational memory so important information does not disappear when chats are summarized or forgotten.

Save a model-label photo, a receipt, a manual, or a contractor's business card through conversation, then ask for the details when you need them months or years later.

## An archive you can talk to

Which filter fits the furnace? What is the serial number on my bicycle? Who built the deck? Where is the water heater receipt? What did the contractor invoice say?

Personal Archive is designed to make those answers—and the original documents—easy to find. You describe what you're saving in ordinary language, and the assistant uses the skill to organize and retrieve it. There are no categories to design or record IDs to memorize.

Each item, asset, or project has a lasting record that can grow over time. Save a new bicycle now, add its receipt later, and attach a service invoice or serial number photo next season. The record brings those details together with their sources and history.

## What it offers

- **Capture through conversation.** Supply photos, documents, or a simple note and
  explain what they belong to. The assistant interprets the request and identifies
  useful details such as models, purchase dates, serial numbers, parts, and contractor information.
- **Keep the original evidence.** Attachments are copied into the archive alongside
  the recorded facts, so you can return to the receipt, label, document, or business card.
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
  images to a regular `Personal Archive` album with descriptive metadata. The album can
  be rebuilt from the files stored in the archive.

## Everyday use cases

These examples illustrate the conversational workflow the skill is designed to support:

| What you're keeping track of | Save or add | Ask later |
| --- | --- | --- |
| Appliances & Equipment | “Save this toaster label and receipt.” | “What toaster do we have, and when did we buy it?” |
| Vehicles & Bicycles | “Save my bike's serial number and purchase receipt.” | “What is the serial number on my bicycle?” |
| Repairs & Maintenance | “This is the invoice for the water heater replacement.” | “Show me the water heater invoice.” |
| Contractors & Projects | “Here's the builder's business card. They built our deck.” | “Who built the deck? Show me their card.” |
| Equipment parts | “Save this furnace filter label.” | “What size furnace filter do I need?” |
| Finishes & Materials | “This is the paint we used in the guest room.” | “What color and finish did we use in the guest room?” |
| Belongings & Maintenance | “Add this service receipt to the lawnmower.” | “Show me the lawnmower service records.” |

For example, a deck project record might start with a completion photo and a note about the
builder. Later, you can add the builder's card, the final invoice, and care instructions.
When you ask about the deck, those related materials are available together. If an
attachment could belong to more than one record, the skill instructs the assistant
to ask which one you mean.

## How it fits into OpenClaw

Personal Archive is an OpenClaw skill backed by a Python command-line tool. OpenClaw handles
the conversation and delegates archive operations to the dedicated `archivist` agent;
the tool handles durable records, identifiers, attachment copies, search, and updates.
Image and document interpretation depends on the model and tools available in your OpenClaw setup.

The archive directory, shown as `<archive-root>` in these docs, is configured through
`PERSONAL_ARCHIVE_ROOT`. That on-disk archive is the source of truth. Apple Photos provides
an optional browsing view of its images.

## Installation & Setup

### First-Time Installation
```bash
git clone https://github.com/wblakecaldwell/openclaw-personal-archive.git
cd openclaw-personal-archive
./install.sh --archive-root ~/Documents/OpenClaw/PersonalArchive

# One-time OpenClaw integration:
# Follow docs/OPENCLAW_SETUP.md to configure the dedicated agent and routing

# Verify integration health:
./install.sh --check
```

Requires Python 3 and the `openclaw` command on `PATH`.

The installer owns Personal Archive software artifacts:
- Installs the skill to `~/.openclaw/workspace/skills/personal-archive/`
- Provisions the dedicated agent workspace at `~/.openclaw/workspaces/archivist/`
- Initializes the archive root directory if it does not exist, or preserves it if it does
- Runs `personal_archive.py doctor`

It does **not** automatically administer or modify your OpenClaw configuration file (`openclaw.json5`) or the main agent. For the one-time OpenClaw agent and routing setup, follow [`docs/OPENCLAW_SETUP.md`](docs/OPENCLAW_SETUP.md).

### Future Software Updates
```bash
git pull
./install.sh
./install.sh --check
```

### Uninstallation
```bash
./install.sh --uninstall
```
Removes the installed skill and dedicated agent workspace files. **Never** touches or deletes your archive data at `~/Documents/OpenClaw/PersonalArchive` or Apple Photos assets. Follow [`docs/OPENCLAW_SETUP.md#uninstall`](docs/OPENCLAW_SETUP.md#uninstall) to clean up OpenClaw configuration references.

## Privacy and repository hygiene

The repository contains the skill code only. Personal archive data is stored outside
the repository at the configured `<archive-root>`.

Do not commit archive data, logs, `.env` files, credentials, message exports, or
other personal material. The included `.gitignore` provides additional protection,
but it is not a substitute for reviewing changes before committing.

## License

MIT. See `LICENSE`.

## Development with coding agents

Before making implementation changes, read [`AGENTS.md`](AGENTS.md) and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). They document the repository invariants,
storage model, safety boundaries, and current development priorities.
