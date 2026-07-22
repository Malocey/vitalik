# Obsidian Secure Configuration

These configuration files provide a secure and robust default setup for Obsidian when used with the VG Delikatessen LLM-Wiki.

## Installation

1. Create a `.obsidian` directory inside your root wiki folder (if it doesn't exist already):
   `mkdir -p .obsidian`
2. Copy these JSON files into the `.obsidian` directory:
   `cp config/obsidian/*.json .obsidian/`

## Configuration Highlights

* **Automatic update of internal links**: Ensures renaming files doesn't break links (`alwaysUpdateLinks: true`).
* **Relative new links**: Ensures all new links are relative, maximizing compatibility (`newLinkFormat: "relative"`).
* **Attachment folder**: All pasted images and attachments go to a central `assets/` folder (`attachmentFolderPath: "assets"`).
* **Graph filter**: Excludes the `archive` and `review` directories from the graph view.
* **Safe Mode**: Safe Mode should NOT be disabled. No community plugins are strictly required to run or view the wiki. Dataview remains optional.
