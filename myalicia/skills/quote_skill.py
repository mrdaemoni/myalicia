#!/usr/bin/env python3
"""
Alicia — Daily Quote Skill
Picks a random quote from the Obsidian Quotes folder
and formats it beautifully for Telegram
"""

import os
import random
import re
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

QUOTES_FOLDER = str(config.vault.root / "Quotes")


def extract_quote_content(filepath: str) -> dict:
    """Parse a quote note and extract the key pieces."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None

    # Skip empty or very short files
    if len(content.strip()) < 20:
        return None

    lines = content.strip().split("\n")
    result = {
        "filename": os.path.basename(filepath).replace(".md", ""),
        "quote": "",
        "author": "",
        "reflection": "",
        "themes": "",
    }

    full_text = content

    # Extract author from #quotes by pattern
    author_match = re.search(r'#quotes\s+by\s+\[\[(.+?)\]\]|#quotes\s+by\s+(.+)', content)
    if author_match:
        result["author"] = (author_match.group(1) or author_match.group(2)).strip()

    # Extract themes
    themes_match = re.search(r'\*Wisdom themes:\*\s*(.+)', content)
    if themes_match:
        themes_raw = themes_match.group(1).strip()
        # Clean up hashtags and formatting
        themes_clean = re.sub(r'#theme/', '', themes_raw)
        themes_clean = re.sub(r'#\w+', '', themes_clean).strip()
        result["themes"] = themes_clean

    # Try to find a quoted string (in " " or ** **)
    quote_patterns = [
        r'"([^"]{30,})"',           # "quoted text"
        r'\*\*([^*]{20,})\*\*',     # **bold text**
        r'"([^"]{30,})"',           # smart quotes
    ]
    for pattern in quote_patterns:
        match = re.search(pattern, content)
        if match:
            result["quote"] = match.group(1).strip()
            break

    # If no quoted string found, use first meaningful line
    if not result["quote"]:
        for line in lines:
            line = line.strip()
            if (len(line) > 30
                    and not line.startswith("#")
                    and not line.startswith("*")
                    and not line.startswith("[[")
                    and not line.startswith("---")):
                result["quote"] = line
                break

    # Extract the user's personal reflection
    # Look for a paragraph that seems personal (contains "I ", "me ", "my ", shaped, believe)
    reflection_patterns = [
        r'Shaped me:?\s*(.{30,}?)(?:\n\n|---|\Z)',
        r'(?:I believe|I think|I learned|For me|This reminds|This means)(.{20,}?)(?:\n\n|---|\Z)',
    ]
    for pattern in reflection_patterns:
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        if match:
            reflection = match.group(1).strip()
            # Clean up and truncate
            reflection = re.sub(r'\s+', ' ', reflection)
            if len(reflection) > 20:
                result["reflection"] = reflection[:300]
                break

    return result if result["quote"] else None


def get_random_quote() -> str:
    """Pick a random quote file and format it for Telegram."""
    try:
        files = [
            f for f in os.listdir(QUOTES_FOLDER)
            if f.endswith(".md") and f != "All quotes.md"
        ]
    except Exception as e:
        return f"⚠️ Could not read quotes folder: {e}"

    if not files:
        return "📭 No quote files found."

    # Try up to 10 random files to find one with good content
    for _ in range(10):
        chosen = random.choice(files)
        filepath = os.path.join(QUOTES_FOLDER, chosen)
        data = extract_quote_content(filepath)
        if data and data["quote"]:
            break
    else:
        return "💭 Couldn't parse a quote today — try again!"

    # Format for Telegram
    lines = ["✨ *Daily Quote*\n"]

    lines.append(f'_{data["quote"]}_')

    if data["author"]:
        lines.append(f'\n— *{data["author"]}*')

    if data["reflection"]:
        lines.append(f'\n💭 *Your reflection:*\n{data["reflection"]}')

    if data["themes"]:
        lines.append(f'\n🏷 {data["themes"]}')

    return "\n".join(lines)


if __name__ == "__main__":
    print(get_random_quote())