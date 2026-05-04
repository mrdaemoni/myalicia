#!/usr/bin/env python3
"""
Alicia — Tool-Use Router

Replaces brittle keyword-based intent detection with Anthropic's native tool-use API.
Sonnet decides which skill to call based on the conversation, not regex.

This is the single biggest architectural upgrade to Alicia's natural language understanding.
Instead of:   if "create a pdf" in text → pdf_skill()
We now have:  Sonnet sees tools → decides → calls generate_pdf(note_name="S3E01")

Benefits:
- No more stopword lists or keyword matching
- Handles pronouns: "create a pdf of THAT" works because Sonnet has conversation context
- Multi-step: "find notes about quality and make a pdf" → search + pdf
- New skills register as tools without writing new intent detectors
"""

import os
import re
import json
import logging
from anthropic import Anthropic
from dotenv import load_dotenv
from myalicia.config import config, ALICIA_HOME, LOGS_DIR, MEMORY_DIR, ENV_FILE
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

load_dotenv(str(ENV_FILE))

log = logging.getLogger(__name__)

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=5)

MODEL_SONNET = "claude-sonnet-4-20250514"

# ── Tool Definitions ─────────────────────────────────────────────────────────
# These are what Sonnet sees. Each tool maps to a real function in Alicia's skills.

TOOLS = [
    {
        "name": "generate_pdf",
        "description": (
            "Generate a PDF from a vault note. Use when the user wants to create, make, "
            "export, or convert a note to PDF. The note_name can be a full filename, partial "
            "name, or descriptive reference — the resolver will fuzzy-match it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note_name": {
                    "type": "string",
                    "description": "The name or identifier of the vault note to convert. Examples: 'S3E01', 'ALICIA', 'quality-before-objects', 'From Measurement to Meaning'"
                }
            },
            "required": ["note_name"]
        }
    },
    {
        "name": "search_vault",
        "description": (
            f"Fresh semantic lookup of {USER_NAME}'s Obsidian vault. Use ONLY when the user "
            "EXPLICITLY asks to find, retrieve, or discover content in the vault AND "
            "answering requires a new vault query (beyond what's already in the system "
            "prompt's vault context or recent conversation history).\n\n"
            "Fires on explicit search phrases: 'find me', 'look up', 'look for', "
            "'search my notes for', 'search the vault for', 'what notes do I have on X', "
            "'is there anything in the vault about X', 'any pages on X', 'show me a note about X', "
            "'retrieve', 'pull up'.\n\n"
            "DO NOT use when the user is:\n"
            "- Reacting, affirming, or responding emotionally ('that's beautiful', "
            "  'I love that', 'sounds good', 'interesting')\n"
            "- Asking for YOUR subjective pick, favorite, or opinion ('your favorite one', "
            "  'what do you think', 'which resonates most', 'tell me your take')\n"
            "- Continuing a thread from something you JUST said (referring to 'that one', "
            "  'it', 'those' without a new topic)\n"
            "- Sending a short reactive phrase (<~20 chars of emotional/acknowledging content)\n"
            "- Asking a conversational 'tell me about X' where existing context is enough\n\n"
            "If unsure whether a fresh vault lookup is needed, prefer replying in your own "
            "voice using vault context already in the system prompt. The user can always "
            "ask you to 'find' or 'search' explicitly.\n\n"
            "Use read_vault_note instead when the user EXPLICITLY asks to hear a note "
            "spoken aloud ('read me aloud', 'read me the note')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query — can be a concept, question, or topic"
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default 5)",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "send_email",
        "description": (
            f"Send an email on {USER_NAME}'s behalf. ALWAYS requires confirmation before actually sending. "
            "Use when the user wants to email, message, or write to someone."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address"
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line"
                },
                "body": {
                    "type": "string",
                    "description": "Email body text"
                }
            },
            "required": ["to", "subject", "body"]
        }
    },
    {
        "name": "get_vault_stats",
        "description": (
            "Get current vault statistics including note counts, knowledge level, "
            "synthesis progress, and cluster coverage. Use when the user asks about "
            "vault health, progress, stats, or metrics."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        }
    },
    {
        "name": "remember",
        "description": (
            f"Store something in Alicia's persistent memory about {USER_NAME} — preferences, "
            "facts, decisions, patterns, insights, moods, moments, and personal "
            f"observations. Use whenever {USER_NAME} shares something he wants kept about "
            "himself, his life, his feelings, his opinions, his day, his relationships, "
            "or a realisation he just had.\n\n"
            "STRONG TRIGGERS (route here, not anywhere else):\n"
            "- 'remember X', 'remember this', 'remember that I...', 'remember I...'\n"
            "- 'save this', 'note that', 'don't forget that', 'make a note'\n"
            "- First-person personal observations or moods: 'I found the rain "
            "beautiful today', 'I'm feeling anxious about X', 'today I realised Y', "
            "'I love Z', 'X matters to me because...'\n\n"
            "Do NOT use for: recalling existing memory ('what do you remember about me' "
            "→ recall_memory), reading vault notes ('read me X' → read_vault_note), "
            "research, or anything about external content. This tool is ONLY for "
            f"storing a new personal fact about {USER_NAME}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": (
                        f"Short label for this memory, derived from the SUBJECT {USER_NAME} "
                        "just named in his current message (e.g., 'favorite_book', "
                        "'design_philosophy', 'sound_on_face_beauty'). Do NOT re-use "
                        "a key from earlier in the conversation if the subject changed."
                    ),
                },
                "value": {
                    "type": "string",
                    "description": (
                        "The thing to remember. CRITICAL: must be a close paraphrase "
                        f"of what {USER_NAME} said in THIS message — not a previous turn, "
                        "not vault context, not something semantically related. If "
                        "he said 'I found the sound on my face beautiful today', the "
                        "value is about 'the sound on my face', NOT 'the rain'. "
                        "Never substitute with a topic from conversation history or "
                        "retrieved vault notes, even when it feels like a rephrasing."
                    ),
                }
            },
            "required": ["key", "value"]
        }
    },
    {
        "name": "generate_concept_note",
        "description": (
            "Generate a new Obsidian concept note with wikilinks and connections to existing "
            "vault content. Use when the user wants to create a concept note, explore an idea, "
            "or add a new concept to the vault."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The concept or topic for the note"
                }
            },
            "required": ["topic"]
        }
    },
    {
        "name": "research",
        "description": (
            "Research a topic and write findings as an Obsidian note. Use for 'research X', "
            "'look into X', 'what do we know about X', or 'deep dive on X'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic to research"
                },
                "depth": {
                    "type": "string",
                    "enum": ["quick", "brief", "deep"],
                    "description": "Research depth — quick (1 min), brief (3 min), deep (Opus, 10+ min)",
                    "default": "brief"
                }
            },
            "required": ["topic"]
        }
    },
    {
        "name": "get_random_quote",
        "description": (
            f"Get a random quote from {USER_NAME}'s personal quote vault. Use when the user "
            "asks for a quote, inspiration, or something to think about."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        }
    },
    {
        "name": "inbox_summary",
        "description": (
            f"Get a summary of {USER_NAME}'s recent emails. Use when the user asks about "
            "email, inbox, unread messages, or mail."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        }
    },
    {
        "name": "synthesise_vault",
        "description": (
            "Find cross-book patterns and generate synthesis notes in the vault. "
            "Use when the user asks to synthesise, find connections, bridge ideas, "
            "or strengthen the knowledge graph."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        }
    },
    {
        "name": "find_contradictions",
        "description": (
            "Find contradictions and tensions between ideas in the vault. "
            "Use when the user asks about conflicts, tensions, contradictions, "
            "or disagreements between thinkers or ideas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        }
    },
    {
        "name": "knowledge_dashboard",
        "description": (
            "Show the full knowledge dashboard with level, synthesis count, "
            "cluster pairs, coverage, and voice ratio. Use when the user asks "
            "about their knowledge level, progress, dashboard, or wisdom metrics."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        }
    },
    {
        "name": "recall_memory",
        "description": (
            f"Recall what Alicia remembers about {USER_NAME}. Use when the user asks "
            "'what do you remember about me', 'what do you know about me', "
            "'tell me everything you remember', 'what have you learned about me', "
            "or any question about Alicia's memories, observations, or stored "
            f"knowledge about {USER_NAME}. Returns memory organized by category. "
            "The focus parameter controls what to return — if the user asks broadly, "
            "set focus to 'all'. If they ask about something specific (e.g., 'what do "
            "you remember about my parenting'), set focus to that topic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": "What aspect to focus on: 'all' for everything, or a specific topic like 'parenting', 'patterns', 'preferences', 'insights', 'recent'. Default: 'all'",
                    "default": "all"
                }
            },
        }
    },
    {
        "name": "consolidate_memory",
        "description": (
            "Clean up and consolidate Alicia's memory files — merge duplicates, "
            "remove noise, keep only high-signal observations. Use when the user "
            "asks to clean memory, consolidate, tidy up, or when memory feels noisy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        }
    },
    {
        "name": "read_vault_note",
        "description": (
            "Read a vault note aloud as a Telegram voice message. ONLY use this tool "
            "when the user EXPLICITLY asks to hear a note spoken aloud using phrases "
            "like 'read me [note]', 'read aloud', 'read out loud', or 'read me the "
            "[note]'. Do NOT use for: 'share what he says', 'tell me about', 'what does "
            "page X say', or general questions about vault content — use search_vault "
            "for those instead. This tool converts a full note to audio voice messages.\n\n"
            "CRITICAL NEGATIVE GUARD: Do NOT use this tool when the user says "
            "'remember X', 'remember that I...', 'remember I...', 'save this', "
            "'note that', or shares a personal observation or moment about themselves. "
            "Those are memory-storage phrases — route them to the `remember` tool, NOT "
            "here. 'remember' is never a read-aloud verb.\n\n"
            "Smart retrieval: the note_name supports many natural patterns:\n"
            "- By title: 'S3E01', 'Antifragile', 'quality-before-objects'\n"
            "- By author: 'something by Pirsig', 'a Taleb note'\n"
            "- By theme: 'something about quality', 'a note on mastery'\n"
            "- By type: 'a quote about resilience', 'a synthesis note'\n"
            "- By recency: 'latest synthesis', 'newest note'\n"
            "- By idea: 'the one about gumption', 'that antifragile page'\n"
            "Pass the user's natural language — the resolver handles the rest."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note_name": {
                    "type": "string",
                    "description": "The user's natural description of what to read. Pass their exact words — the smart resolver handles title matching, author lookup, semantic search, theme filtering, and recency. Examples: 'latest synthesis', 'something by Pirsig about quality', 'a quote on resilience', 'S3E01', 'the gumption note'. NEVER guess — use the user's actual words."
                },
                "style": {
                    "type": "string",
                    "enum": ["warm", "measured", "excited", "gentle"],
                    "description": "Voice tone — 'measured' for reading notes (default), 'warm' for personal, 'excited' for discoveries, 'gentle' for reflections",
                    "default": "measured"
                }
            },
            "required": ["note_name"]
        }
    },
    {
        "name": "ask_retro",
        "description": (
            f"Answer {USER_NAME}'s question about his own week (or month) "
            "from the same signals the Sunday self-portrait composer "
            "uses: mood-of-the-week, dashboard engagement, noticings, "
            f"becoming-arc, captures. Use WHENEVER {USER_NAME} asks about "
            "his recent past in natural language: 'how was this week?', "
            "'what was hardest about this week?', 'show me my last "
            "week', 'what stood out this week', 'how was the past "
            "month?', 'how am I doing lately'.\n\n"
            "CRITICAL: NEVER reply 'I don't know how to look at your "
            "week' — you do, and this is the tool. Beatrice's voice — "
            "witnessing, not advising. After firing, your reply text "
            "should be ONE LINE introducing the answer; the answer "
            "speaks for itself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        f"{USER_NAME}'s question, verbatim. Pass his words "
                        "exactly — don't paraphrase. Examples: 'what "
                        "was hardest about this week', 'how was last "
                        "week', 'did I write more this week'. Required."
                    ),
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "financial",
        "description": (
            "Surface a summary of recent financial emails (last ~7 days). "
            f"Use when {USER_NAME} says 'check my finances', 'what's in my "
            "financial inbox', 'any bills lately', or similar. Wraps "
            "the same skill `/financial` invokes. NEVER reply 'I can't "
            "look at financial info' — you can scan the inbox; you just "
            "can't enter financial data into forms or execute trades. "
            "After calling, your reply text should be ONE LINE introducing "
            "the summary."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "start_thinking_session",
        "description": (
            "Start one of Alicia's interactive thinking modes — walk, "
            f"drive, or unpack. Use WHENEVER {USER_NAME} says 'let's go on a "
            "walk', 'walk with me about X', 'let's drive on Y', 'do a "
            "5-minute drive on Z', 'unpack this for me', 'let's go deep "
            "on W', 'help me think aloud about V', etc.\n\n"
            "MODES:\n"
            f"- walk: stream-of-consciousness mode. {USER_NAME} talks (voice or "
            "text); Alicia listens without interrupting until /done.\n"
            "- drive: 5-minute rapid-synthesis mode. Alicia throws vault "
            "connections back fast.\n"
            f"- unpack: deep extraction from a voice monologue. {USER_NAME} "
            "records; Alicia extracts insights at the end.\n\n"
            "CRITICAL: thinking sessions ARE real first-class capabilities "
            "— the tool actually starts the session, sends a voice "
            f"greeting, and routes {USER_NAME}'s next messages through the "
            "right handler. NEVER reply 'I can't start a walk' or 'let "
            "me explain how that works' — fire the tool. After firing, "
            "your reply text should be SHORT (one line) — the voice "
            "greeting is the real start."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["walk", "drive", "unpack"],
                    "description": (
                        "Which thinking mode to start. Pick walk for "
                        "stream-of-consciousness, drive for rapid "
                        "synthesis, unpack for deep extraction."
                    ),
                },
                "topic": {
                    "type": "string",
                    "description": (
                        f"Optional topic seed. Pass {USER_NAME}'s exact words "
                        "for what he wants to think about (e.g. 'the "
                        "quality piece I'm writing'). Leave empty for an "
                        "open session."
                    ),
                },
            },
            "required": ["mode"],
        },
    },
    {
        "name": "note",
        "description": (
            f"Save a quick thought as a note in {USER_NAME}'s Obsidian Inbox. "
            f"Use WHENEVER {USER_NAME} says 'note that I X', 'save this thought: "
            "Y', 'capture: Z', 'log: W', 'remember this conversation', "
            "'jot down V', 'put this in the inbox', etc.\n\n"
            "The text is saved as a timestamped markdown file in "
            "`/Alicia/Inbox/`. The daily-pass picks it up later for "
            "tagging and routing into the graph.\n\n"
            "CRITICAL: saving notes IS a real first-class capability. "
            "NEVER reply 'I can't save notes' or 'tell me what you'd "
            "like to remember' — fire the tool with the exact text "
            f"{USER_NAME} said. After saving, your reply should be ONE LINE "
            "confirming (e.g. 'noted — in the inbox')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        f"The exact note text to save. Pass {USER_NAME}'s words "
                        "verbatim — don't paraphrase, don't summarise, "
                        "don't add framing. The note is for him to see "
                        "later, not a memory entry for you."
                    ),
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "show_dashboard",
        "description": (
            "Render and return one of Alicia's observability dashboards. "
            f"Use WHENEVER {USER_NAME} asks for any of these views in natural "
            "language: 'show me my becoming', 'how are we doing on the "
            "loops', 'what are you noticing', 'show wisdom', 'what's "
            "landing', 'where are you in your season', 'how is the "
            "smart decider', 'what's effective right now'.\n\n"
            "AVAILABLE DASHBOARDS:\n"
            f"- becoming: {USER_NAME}'s developmental arc (10 dimensions)\n"
            "- season: Alicia's developmental trajectory\n"
            "- noticings: themes Alicia is tracking quietly\n"
            "- loops: four-loop circulatory view\n"
            "- multichannel: smart-decider observability (voice + drawing)\n"
            "- wisdom: Wisdom Engine inner loop\n"
            "- effectiveness: feedback-signal dashboard\n\n"
            "CRITICAL: NEVER reply 'I can't show that dashboard' — fire "
            "the tool. The tool returns the rendered text directly. Your "
            "text reply should be ONE LINE introducing it, then the "
            "dashboard text speaks for itself. (Don't summarise the "
            f"dashboard back at {USER_NAME} — he reads it directly.)"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "enum": [
                        "becoming", "season", "noticings", "loops",
                        "multichannel", "wisdom", "effectiveness",
                    ],
                    "description": "Which dashboard to render.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "draw",
        "description": (
            "Render a flow-field drawing in one of Alicia's six archetype "
            "voices (beatrice / daimon / ariadne / psyche / musubi / muse) "
            f"and SEND IT directly to {USER_NAME} as an image. Use this WHENEVER "
            f"{USER_NAME} asks for a drawing — 'draw me X', 'make a drawing about "
            "Y', 'visualise this', 'render that idea', 'show me this as an "
            "image', 'illustrate Z' — or whenever rendering a synthesis or "
            "note as a visual would deepen the moment.\n\n"
            "CRITICAL: drawing IS a real first-class capability — the tool "
            "actually renders and sends a PNG/GIF. NEVER reply 'I can't draw' "
            "or 'I don't have drawing capabilities' — you do, and this is "
            "the tool. After calling, your reply should be SHORT (one or two "
            "lines) — the drawing speaks for itself.\n\n"
            "The phrase argument is interpreted by Haiku into archetype + "
            "density + energy + whitespace + stroke + caption. To force a "
            "specific archetype, pass its name as the phrase (e.g. "
            "'beatrice'). Leave phrase empty to let Alicia's current "
            "archetype weather drive the rendering."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phrase": {
                    "type": "string",
                    "description": (
                        "Short freeform phrase describing what to draw "
                        "(e.g. 'discipline as inhabited structure', 'your "
                        "current thinking', 'this morning's quiet'), OR an "
                        "explicit archetype name (beatrice / daimon / "
                        "ariadne / psyche / musubi / muse). Empty string "
                        "lets her current weather decide."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "ingest_vault",
        "description": (
            "Scan the vault for new or modified source notes and run the cascading "
            "ingest pipeline. This reads new sources, summarizes them, updates "
            "existing synthesis and concept pages with new references, checks for "
            "contradictions, rebuilds the vault index, and logs everything. "
            f"Use when {USER_NAME} says 'ingest', 'process new notes', 'update the vault', "
            "'check for new sources', 'run ingest', or 'sync the vault'. "
            f"Also useful after {USER_NAME} adds new book pages, quotes, or articles."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max number of sources to process in one pass. Default: 5",
                    "default": 5
                },
                "initialize": {
                    "type": "boolean",
                    "description": "Set to true for first-time setup — baselines all existing files so only truly new ones trigger ingest. Default: false",
                    "default": False
                }
            },
        }
    },
    {
        "name": "clarify",
        "description": (
            f"Ask {USER_NAME} a clarifying question before acting. Use this when the request "
            "is ambiguous and you could interpret it multiple ways. Present 2-4 concise "
            f"options for {USER_NAME} to choose from. Examples of when to use:\n"
            "- 'Tell me about quality' → Do you mean (1) Pirsig's Quality, (2) vault notes about craftsmanship, (3) the quality theme cluster?\n"
            "- 'Read me something' → without specifying what\n"
            "- 'What do you think about X' when X could be personal opinion vs vault lookup\n"
            "Do NOT use for clear, specific requests. Only clarify when genuinely ambiguous."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The clarifying question to ask, with numbered options"
                }
            },
            "required": ["question"]
        }
    },
    {
        "name": "recent_responses",
        "description": (
            f"Look up {USER_NAME}'s most-recent captured replies for a specific "
            "synthesis. Returns up to `max_recent` past responses with their "
            "captured_at timestamp, channel, archetype, and a body excerpt — "
            "drawn from the writing/Responses/ and writing/Captures/ archives "
            f"that the response-capture system writes whenever {USER_NAME} replies "
            "to one of Alicia's proactive messages.\n\n"
            "USE THIS TOOL when:\n"
            f"  • You're about to surface a synthesis {USER_NAME} has already "
            "responded to. The past response IS the conversation continuing — "
            "weave it in.\n"
            f"  • {USER_NAME} mentions or quotes a synthesis and you want to "
            "remember what he last said about it.\n"
            "  • A composer-driven proactive on a specific synthesis is "
            "about to render.\n\n"
            "DO NOT use this tool for general vault search — that's "
            f"search_vault. recent_responses is specifically for *{USER_NAME}'s "
            "own captured voice on a synthesis*.\n\n"
            "Empty result is normal — most syntheses haven't been responded "
            "to yet. When that happens, just compose normally without "
            "referring to past responses."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "synthesis_title": {
                    "type": "string",
                    "description": "Exact title of the synthesis (matches the H1 / filename of the .md)"
                },
                "max_recent": {
                    "type": "integer",
                    "description": "Cap on number of responses returned. Default: 5",
                    "default": 5,
                },
            },
            "required": ["synthesis_title"]
        }
    },
]


# ── Vault Reading Helpers ─────────────────────────────────────────────────────

VAULT_ROOT = str(config.vault.root)
SYNTHESIS_DIR = os.path.join(VAULT_ROOT, "Alicia", "Wisdom", "Synthesis")

# Patterns that mean "give me the most recent file in a folder"
_RECENCY_PATTERNS = [
    (r"(?:latest|last|newest|most recent|new)\s+synthesis", SYNTHESIS_DIR),
    (r"(?:latest|last|newest|most recent)\s+(?:note|concept)", VAULT_ROOT),
    (r"(?:latest|last|newest|most recent)\s+quote", os.path.join(VAULT_ROOT, "Quotes")),
    (r"(?:latest|last|newest|most recent)\s+(?:page|book)", os.path.join(VAULT_ROOT, "Books")),
]

# Known author names → vault folders/substrings for filtering
# This gets augmented at runtime by scanning the Authors/ folder
_AUTHOR_ALIASES = {
    "pirsig": "Robert Pirsig",
    "taleb": "Nassim Nicholas Taleb",
    "vervaeke": "John Vervaeke",
    "mcgilchrist": "Iain McGilchrist",
    "frankl": "Viktor Frankl",
    "peterson": "Jordan Peterson",
    "seneca": "Seneca",
    "epictetus": "Epictetus",
    "marcus aurelius": "Marcus Aurelius",
    "marcus": "Marcus Aurelius",
    "aurelius": "Marcus Aurelius",
    "nietzsche": "Friedrich Nietzsche",
    "dostoevsky": "Fyodor Dostoevsky",
    "dostoyevsky": "Fyodor Dostoevsky",
    "jung": "Carl Jung",
    "heidegger": "Martin Heidegger",
    "kierkegaard": "Søren Kierkegaard",
    "camus": "Albert Camus",
    "watts": "Alan Watts",
    "campbell": "Joseph Campbell",
}

# Type patterns → folder filters for semantic search
_TYPE_PATTERNS = {
    r"\bquote\b": "Quotes",
    r"\bsynthesis\b": "Synthesis",
    r"\bbook\b|\bpage\b|\bpg\b": "Books",
    r"\bauthor\b": "Authors",
    r"\bpodcast\b|\bepisode\b": "Podcasts",
    r"\bstoic\b": "Stoic",
    r"\bwriting\b|\bessay\b|\bdraft\b": "Writing drafts",
    r"\bshort read\b": "Short reads",
    r"\bresearch\b": "Research",
}

# Resonance tracking file
RESONANCE_FILE = str(MEMORY_DIR / "resonance.md")


# A "readable" vault note needs this many speakable chars AFTER frontmatter,
# wikilinks, tags, and other markdown scaffolding are stripped. Files below
# the threshold are stubs (e.g. /Authors/Lila.md = "#book by [[Robert M. Pirsig]]",
# 30 bytes → ~19 post-strip chars) and reading them aloud produces a 2-second
# voice note. The threshold is a floor, not a perfect indicator — the
# resolver skips sub-threshold hits and falls through to the next strategy,
# which typically surfaces a proper content page.
MIN_READABLE_CHARS = 120


def _speakable_chars(path: str) -> int:
    """
    Return the count of speakable characters in a note — i.e., the length
    of what the TTS cleaner would actually utter. 0 on any read error.
    Kept cheap: only reads the first 4 KB which is plenty to confirm a
    real content page while still catching stubs.
    """
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read(4096)
        # Lazy import — voice_skill pulls ffmpeg/anthropic deps we don't want
        # to force into every module that imports tool_router.
        from myalicia.skills.voice_skill import _clean_for_tts
        return len(_clean_for_tts(raw))
    except Exception:
        return 0


def _is_substantial(path: str) -> bool:
    """Hit passes the stub filter iff its speakable content >= the threshold."""
    return _speakable_chars(path) >= MIN_READABLE_CHARS


def _resolve_note_for_reading(query: str) -> tuple:
    """
    Smart resolver for read_vault_note. Chains 5 strategies:
    1. Recency patterns ("latest synthesis", "newest quote")
    2. Direct name matching via vault_resolver (exact/fuzzy)
    3. Author-based search ("something by Pirsig")
    4. Type-filtered semantic search ("a quote about resilience")
    5. Pure semantic search (any natural language query)

    Returns (path, title) or (None, None).

    Stub filter (2026-04-18): every strategy's candidate path is now
    checked against _is_substantial before being returned. Stub files
    (author-index pointers like /Authors/Lila.md) are skipped so they
    can't produce 2-second voice notes that read the stub text and
    nothing else. If a strategy's top hit is a stub, the resolver
    falls through to the next strategy rather than returning the stub.
    """
    query_lower = query.lower().strip()

    # ── Strategy 1: Recency-based ────────────────────────────────────────
    for pattern, folder in _RECENCY_PATTERNS:
        if re.search(pattern, query_lower):
            result = _get_most_recent_note(folder)
            if result and _is_substantial(result[0]):
                log.info(f"Smart resolve [{query}] → recency match in {folder}")
                return result
            elif result:
                log.info(
                    f"Smart resolve [{query}] → recency hit '{result[1]}' "
                    f"is a stub ({_speakable_chars(result[0])} chars); "
                    f"falling through"
                )

    # ── Strategy 2: Direct name matching (vault_resolver) ────────────────
    from myalicia.skills.vault_resolver import resolve_note
    note = resolve_note(query)
    if note and note.get("found") and note.get("score", 0) >= 0.6:
        if _is_substantial(note["path"]):
            log.info(f"Smart resolve [{query}] → name match: {note['title']} (score={note['score']}, method={note['method']})")
            return (note["path"], note["title"])
        else:
            log.info(
                f"Smart resolve [{query}] → name match '{note['title']}' "
                f"is a stub ({_speakable_chars(note['path'])} chars); "
                f"falling through"
            )

    # ── Strategy 3: Author-based search ──────────────────────────────────
    author = _detect_author(query_lower)
    if author:
        topic = _strip_author_from_query(query_lower, author)
        result = _search_by_author(author, topic)
        if result and _is_substantial(result[0]):
            log.info(f"Smart resolve [{query}] → author search: {author} → {result[1]}")
            return result
        elif result:
            log.info(
                f"Smart resolve [{query}] → author hit '{result[1]}' is "
                f"a stub ({_speakable_chars(result[0])} chars); falling through"
            )

    # ── Strategy 4: Type-filtered semantic search ────────────────────────
    folder_filter = _detect_type_filter(query_lower)
    if folder_filter:
        topic = _strip_type_from_query(query_lower)
        result = _semantic_resolve(topic or query, folder_filter=folder_filter)
        if result and _is_substantial(result[0]):
            log.info(f"Smart resolve [{query}] → type-filtered semantic ({folder_filter}): {result[1]}")
            return result

    # ── Strategy 5: Pure semantic search ─────────────────────────────────
    result = _semantic_resolve(query)
    if result and _is_substantial(result[0]):
        log.info(f"Smart resolve [{query}] → semantic search: {result[1]}")
        return result

    # ── Fallback: Accept lower-confidence name matches ───────────────────
    #
    # <earlier development>: tightened after 'something by Pirsig' → 'How to criticize
    # something you disagree with' misfire. The old fallback accepted ANY
    # fuzzy match, so the filler word 'something' in a no-real-content query
    # produced a confident-sounding wrong pick. Two guards now:
    #   1. Minimum score ≥ 0.55 (was: any score).
    #   2. The matched title must share at least one NON-FILLER word with
    #      the query. A match on 'something' alone is not an attribution.
    if note and note.get("found") and _is_substantial(note["path"]):
        score = note.get("score", 0)
        title_lower = note["title"].lower()
        # Filler words carry no attribution signal. "by/from" are connectors,
        # the rest are request-framing or generic referents.
        FILLER = {
            "something", "anything", "a", "an", "the", "by", "from", "on",
            "about", "read", "me", "read me", "note", "a note", "some",
        }
        query_words = {w for w in re.findall(r"\w+", query_lower) if w not in FILLER}
        title_words = set(re.findall(r"\w+", title_lower))
        shared_non_filler = query_words & title_words
        if score >= 0.55 and shared_non_filler:
            log.info(
                f"Smart resolve [{query}] → low-confidence name match: "
                f"{note['title']} (score={score}, shared={shared_non_filler})"
            )
            return (note["path"], note["title"])
        else:
            log.info(
                f"Smart resolve [{query}] → rejecting low-confidence match "
                f"'{note['title']}' (score={score}, "
                f"shared_non_filler={shared_non_filler}) — too weak"
            )

    log.warning(f"Smart resolve [{query}] → no substantial match found")
    return (None, None)


def _detect_author(query: str) -> str:
    """
    Detect if the query references an author.
    Checks for patterns like "by Pirsig", "a Taleb note", "Pirsig on quality".
    Returns canonical author name or None.
    """
    # Pattern: "by <author>" or "from <author>"
    by_match = re.search(r"(?:by|from)\s+(\w+(?:\s+\w+)?)", query)
    if by_match:
        name = by_match.group(1).lower().strip()
        for alias, canonical in _AUTHOR_ALIASES.items():
            if alias in name or name in alias:
                return canonical

    # Pattern: "<author> on/about" or "a <author> note"
    for alias, canonical in _AUTHOR_ALIASES.items():
        if alias in query:
            return canonical

    # Dynamic check: scan Authors/ folder for matching names
    authors_dir = os.path.join(VAULT_ROOT, "Authors")
    if os.path.isdir(authors_dir):
        for f in os.listdir(authors_dir):
            if f.endswith(".md"):
                author_name = f.replace(".md", "").lower()
                # Check if any word from the author name appears in query
                words = author_name.split()
                for w in words:
                    if len(w) > 3 and w in query:
                        return f.replace(".md", "")

    return None


def _strip_author_from_query(query: str, author: str) -> str:
    """Remove author name and connector words from query to get the topic."""
    result = query
    # Remove author name (case-insensitive)
    for word in author.lower().split():
        result = re.sub(r'\b' + re.escape(word) + r'\b', '', result, flags=re.IGNORECASE)
    # Remove connector words
    result = re.sub(r'\b(by|from|something|a note|note|on|about|read me|read)\b', '', result, flags=re.IGNORECASE)
    return result.strip()


def _search_by_author(author: str, topic: str = "") -> tuple:
    """
    Find a note by a specific author, optionally filtered by topic.
    Searches semantically within author-related folders.

    Attribution policy (2026-04-18 fix for 'Pirsig → Robert Hughes' misfire):
    the SURNAME is treated as a hard attribution filter. Given names alone
    ("Robert", "John") collide with too many authors, so hits without the
    surname somewhere in path/title/folder are dropped. Bonuses are additive:
    +0.3 for the surname, +0.1 for each additional name part. If no hit
    carries the surname, the search returns None and the caller falls
    through to strategies 4-5 (type-filtered + pure semantic) which can
    still surface the author's content on content-similarity alone.
    """
    from myalicia.skills.semantic_search import semantic_search

    # Build a search query that combines author + topic
    search_query = f"{author} {topic}".strip() if topic else author

    # Search with author name to bias results
    hits = semantic_search(search_query, n_results=10)

    if not hits:
        return None

    author_lower = author.lower()
    # Keep only informative name parts (drop 1-2 char fragments).
    author_words = [w for w in author_lower.split() if len(w) >= 3]
    if not author_words:
        return None
    # Surname = the last word of the canonical name. This is the
    # distinguishing token for multi-part names ("Robert Pirsig" → "pirsig").
    # For single-word authors ("Seneca") the surname IS the whole name.
    surname = author_words[-1]
    extra_name_parts = author_words[:-1]

    scored = []
    for h in hits:
        path_lower = h["filepath"].lower()
        title_lower = h["title"].lower()
        folder_lower = h["folder"].lower()
        haystack = f"{path_lower} {title_lower} {folder_lower}"

        # Hard filter: surname must appear. Without it, the hit is about
        # a different author who happens to share a given name.
        if surname not in haystack:
            continue

        # Strong bonus for surname presence + extra bonus for each
        # additional name part that also matches.
        author_bonus = 0.3
        for w in extra_name_parts:
            if w in haystack:
                author_bonus += 0.1

        final_score = h["score"] + author_bonus
        scored.append((final_score, h))

    if not scored:
        # Log for diagnosis — author was detected but no hit carried the
        # surname. Caller will fall through to semantic search.
        top_title = hits[0].get("title", "?") if hits else "?"
        log.info(
            f"_search_by_author: surname '{surname}' missing from all "
            f"{len(hits)} hits (top was: {top_title}); "
            f"falling through to semantic search"
        )
        return None

    scored.sort(key=lambda x: x[0], reverse=True)

    # Stub filter (<earlier development>): walk down the ranked list until we find a
    # hit whose file has enough speakable content to read aloud. A 30-byte
    # author stub like /Authors/Lila.md can top the list on literal-title
    # match but produces a 2-second voice note — we'd rather take the
    # next-ranked hit, which is typically an actual content page.
    for score_val, h in scored:
        if score_val < 0.3:  # Minimum relevance threshold
            break
        if _is_substantial(h["filepath"]):
            return (h["filepath"], h["title"])

    return None


def _detect_type_filter(query: str) -> str:
    """Detect if the query implies a specific note type/folder."""
    for pattern, folder in _TYPE_PATTERNS.items():
        if re.search(pattern, query):
            return folder
    return None


def _strip_type_from_query(query: str) -> str:
    """Remove type keywords and filler words from query to get the core topic."""
    result = query
    # Remove type keywords
    for pattern in _TYPE_PATTERNS:
        result = re.sub(pattern, '', result)
    # Remove filler
    result = re.sub(r'\b(a|an|the|something|about|on|read me|read|me)\b', '', result, flags=re.IGNORECASE)
    return result.strip()


def _semantic_resolve(query: str, folder_filter: str = None) -> tuple:
    """
    Use semantic search to find the best matching note.
    Returns (path, title) or None.

    Stub filter (2026-04-18): walk the ranked hits list and take the first
    hit that's above the relevance threshold AND has enough speakable
    content. A stub like /Authors/Lila.md can top literal-title searches
    but yields a 2-second voice note, so we rather keep walking.
    """
    from myalicia.skills.semantic_search import semantic_search

    hits = semantic_search(query, n_results=5, folder_filter=folder_filter)
    for h in hits:
        if h["score"] < 0.25:
            break
        if _is_substantial(h["filepath"]):
            return (h["filepath"], h["title"])
    return None


def _get_most_recent_note(folder: str) -> tuple:
    """
    Get the most recently modified .md file in a folder.
    Returns (path, title) or None.
    """
    if not os.path.isdir(folder):
        log.warning(f"Folder not found for recency lookup: {folder}")
        return None

    md_files = []
    for f in os.listdir(folder):
        if f.endswith(".md") and not f.startswith("."):
            fp = os.path.join(folder, f)
            if os.path.isfile(fp):
                md_files.append((os.path.getmtime(fp), fp, f.replace(".md", "")))

    if not md_files:
        return None

    md_files.sort(reverse=True)  # Most recent first
    _, path, title = md_files[0]
    return (path, title)


# ── Resonance Tracking ───────────────────────────────────────────────────────

def track_resonance(note_title: str, note_path: str, context: str = ""):
    """
    Record that a note was read aloud. Over time, this builds a profile
    of what resonates most with the user.

    Called from alicia.py after successful read_aloud.
    """
    from datetime import datetime
    os.makedirs(os.path.dirname(RESONANCE_FILE), exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    folder = os.path.dirname(note_path).replace(VAULT_ROOT + "/", "") if note_path else "unknown"

    entry = f"- [{timestamp}] **{note_title}** ({folder})"
    if context:
        entry += f" — _{context}_"
    entry += "\n"

    # Create file with header if it doesn't exist
    if not os.path.exists(RESONANCE_FILE):
        header = (
            "# Resonance Tracking\n"
            f"*Notes {USER_NAME} has asked Alicia to read aloud — a map of what resonates.*\n\n"
            "## Reading History\n\n"
        )
        with open(RESONANCE_FILE, "w", encoding="utf-8") as f:
            f.write(header)

    with open(RESONANCE_FILE, "a", encoding="utf-8") as f:
        f.write(entry)

    log.info(f"Resonance tracked: {note_title}")


def get_resonance_summary() -> str:
    """
    Analyze resonance.md to find patterns in what the user reads most.
    Returns a summary string for use in proactive messages or context.
    """
    if not os.path.exists(RESONANCE_FILE):
        return ""

    with open(RESONANCE_FILE, encoding="utf-8") as f:
        content = f.read()

    # Count note occurrences
    titles = re.findall(r'\*\*(.+?)\*\*', content)
    if not titles:
        return ""

    from collections import Counter
    counts = Counter(titles)
    total = len(titles)

    # Build summary
    top = counts.most_common(5)
    lines = [f"📖 *Reading resonance* ({total} total reads):"]
    for title, count in top:
        bar = "█" * count
        lines.append(f"  {bar} {title} ({count}x)")

    # Most-read folders
    folders = re.findall(r'\*\* \((.+?)\)', content)
    folder_counts = Counter(folders)
    top_folders = folder_counts.most_common(3)
    if top_folders:
        folder_str = ", ".join(f"{f} ({c}x)" for f, c in top_folders)
        lines.append(f"  Favorite areas: {folder_str}")

    return "\n".join(lines)


# ── Tool Execution ───────────────────────────────────────────────────────────

# Lethal-trifecta classification — see LETHAL_TRIFECTA_AUDIT.md.
# external_send: leaves the local machine and can't be recalled (email, posts).
# vault_write_large: large-scope mutation of vault or memory; deserves a YES gate
#   when triggered from chat (untrusted-content channel) so attacker-injected
#   instructions in email/web content can't auto-chain into a global vault edit.
# vault_write_small: narrow, easily reversible writes (single concept note,
#   single timestamped inbox file). No gate — the audit log is sufficient.
TOOL_SIDE_EFFECT_CLASS = {
    "send_email": "external_send",                 # already gated below
    "synthesise_vault": "vault_write_large",
    "consolidate_memory": "vault_write_large",
    "ingest_vault": "vault_write_large",
    "research": "vault_write_small",               # writes single research note
    "generate_concept_note": "vault_write_small",
    "note": "vault_write_small",
    "remember": "vault_write_small",
    "generate_pdf": "vault_write_small",
    "draw": "vault_write_small",                   # sends image but content from the user
    "read_vault_note": "vault_write_small",        # voice message — already sent
}


def get_side_effect_class(tool_name: str) -> str:
    """Return the side-effect class for a tool, or 'none' for read-only/pure tools."""
    return TOOL_SIDE_EFFECT_CLASS.get(tool_name, "none")


def execute_tool(tool_name: str, tool_input: dict) -> dict:
    """
    Execute a tool and return the result.
    Returns dict with 'success', 'result', 'error', and optionally 'file_path' for sendable files.

    Trifecta gate: tools classified as `vault_write_large` return a
    confirmation request instead of executing immediately when called
    from a chat path. The caller (handle_message) presents the request
    to the user, who must reply YES. Scheduler-originated calls bypass
    the gate by passing `tool_input["_internal"] = True`.
    """
    try:
        # Trifecta gate — large-scope vault mutations
        if (
            get_side_effect_class(tool_name) == "vault_write_large"
            and not tool_input.get("_internal")
        ):
            return {
                "success": True,
                "action": "confirm_vault_write",
                "result": (
                    f"Ready to run {tool_name}. This is a large-scope vault "
                    "mutation; reply YES to confirm."
                ),
                "data": {"tool_name": tool_name, "tool_input": tool_input},
            }
        if tool_name == "generate_pdf":
            from myalicia.skills.pdf_skill import generate_pdf_from_query
            result = generate_pdf_from_query(tool_input["note_name"], same_folder=True)
            if result["success"]:
                return {
                    "success": True,
                    "result": f"PDF created: {result['note_title']}.pdf",
                    "file_path": result["pdf_path"],
                    "file_name": f"{result['note_title']}.pdf",
                    "action": "send_document",
                }
            else:
                return {"success": False, "error": result["error"]}

        elif tool_name == "search_vault":
            from myalicia.skills.semantic_search import semantic_search_formatted
            results = semantic_search_formatted(tool_input["query"], n_results=tool_input.get("top_k", 5))
            return {"success": True, "result": results}

        elif tool_name == "send_email":
            # Don't actually send — return confirmation request
            return {
                "success": True,
                "result": f"Ready to send email to {tool_input['to']}",
                "action": "confirm_email",
                "data": tool_input,
            }

        elif tool_name == "get_vault_stats":
            from myalicia.skills.vault_intelligence import get_vault_stats
            stats = get_vault_stats()
            return {"success": True, "result": stats or "Could not retrieve vault stats."}

        elif tool_name == "remember":
            from myalicia.skills.memory_skill import remember_manual
            result = remember_manual(tool_input["key"], tool_input["value"])
            return {"success": True, "result": result}

        elif tool_name == "generate_concept_note":
            from myalicia.skills.memory_skill import generate_concept_note
            content, path, title = generate_concept_note(tool_input["topic"])
            return {"success": True, "result": f"Created concept note: {title}\nPath: {path}"}

        elif tool_name == "research":
            depth = tool_input.get("depth", "brief")
            topic = tool_input["topic"]
            if depth == "quick":
                from myalicia.skills.research_skill import research_quick
                result = research_quick(topic)
                return {"success": True, "result": result or f"Research complete: {topic}"}
            elif depth == "deep":
                from myalicia.skills.research_skill import research_deep
                summary, path = research_deep(topic)
                return {"success": True, "result": summary or f"Deep research saved to {path}"}
            else:
                from myalicia.skills.research_skill import research_brief
                summary, path = research_brief(topic)
                return {"success": True, "result": summary or f"Research saved to {path}"}

        elif tool_name == "get_random_quote":
            from myalicia.skills.quote_skill import get_random_quote
            quote = get_random_quote()
            return {"success": True, "result": quote or "Could not retrieve a quote right now."}

        elif tool_name == "inbox_summary":
            from myalicia.skills.gmail_skill import get_inbox_summary
            summary = get_inbox_summary()
            return {"success": True, "result": summary or "Could not retrieve inbox summary."}

        elif tool_name == "synthesise_vault":
            from myalicia.skills.memory_skill import synthesise_vault
            result = synthesise_vault()
            return {"success": True, "result": result or "Synthesis complete — check vault for new connections."}

        elif tool_name == "find_contradictions":
            from myalicia.skills.memory_skill import find_contradictions
            result = find_contradictions()
            return {"success": True, "result": result or "No clear contradictions found in current vault scan."}

        elif tool_name == "knowledge_dashboard":
            from myalicia.skills.vault_metrics import compute_all_metrics, format_knowledge_dashboard
            metrics = compute_all_metrics()
            dashboard = format_knowledge_dashboard(metrics)
            return {"success": True, "result": dashboard or "Could not compute knowledge dashboard."}

        elif tool_name == "recall_memory":
            from myalicia.skills.memory_skill import (
                MEMORY_FILE, PATTERNS_FILE, INSIGHTS_FILE,
                PREFERENCES_FILE, CONCEPTS_FILE, ensure_memory_structure,
            )
            ensure_memory_structure()
            focus = tool_input.get("focus", "all")

            # Map focus topics to specific files
            file_map = {
                "core": [("Core Memory", MEMORY_FILE)],
                "patterns": [("Patterns", PATTERNS_FILE)],
                "insights": [("Insights", INSIGHTS_FILE)],
                "preferences": [("Preferences", PREFERENCES_FILE)],
                "concepts": [("Concepts", CONCEPTS_FILE)],
                "recent": [("Insights", INSIGHTS_FILE), ("Patterns", PATTERNS_FILE)],
            }

            if focus == "all":
                files_to_read = [
                    ("Core Memory", MEMORY_FILE),
                    ("Patterns", PATTERNS_FILE),
                    ("Insights", INSIGHTS_FILE),
                    ("Preferences", PREFERENCES_FILE),
                    ("Concepts", CONCEPTS_FILE),
                ]
            else:
                # Check for exact match first, then keyword match
                files_to_read = file_map.get(focus.lower(), None)
                if not files_to_read:
                    # Keyword search across all memory files
                    files_to_read = [
                        ("Core Memory", MEMORY_FILE),
                        ("Patterns", PATTERNS_FILE),
                        ("Insights", INSIGHTS_FILE),
                        ("Preferences", PREFERENCES_FILE),
                        ("Concepts", CONCEPTS_FILE),
                    ]

            sections = []
            for label, fpath in files_to_read:
                try:
                    with open(fpath, encoding="utf-8") as f:
                        content = f.read().strip()
                    if content:
                        # For focused queries, only include relevant lines
                        if focus != "all" and focus.lower() not in file_map:
                            relevant = [l for l in content.split("\n")
                                       if focus.lower() in l.lower() or l.startswith("#")]
                            if relevant:
                                sections.append(f"## {label}\n\n" + "\n".join(relevant))
                        else:
                            sections.append(f"## {label}\n\n{content}")
                except Exception:
                    pass

            # Add resonance data if available
            if focus in ("all", "reading", "resonance") and os.path.exists(RESONANCE_FILE):
                try:
                    res_summary = get_resonance_summary()
                    if res_summary:
                        sections.append(f"## Reading Resonance\n\n{res_summary}")
                except Exception:
                    pass

            if sections:
                full_result = "\n\n---\n\n".join(sections)
                # Flag that this is memory content — Sonnet should summarize, not dump
                return {
                    "success": True,
                    "result": full_result,
                    "action": "summarize_memory",
                    "data": {"focus": focus, "char_count": len(full_result)},
                }
            else:
                return {"success": True, "result": "No memories stored yet."}

        elif tool_name == "consolidate_memory":
            from myalicia.skills.memory_skill import consolidate_all_memory
            results = consolidate_all_memory()
            return {"success": True, "result": "Memory consolidated:\n" + "\n".join(results)}

        elif tool_name == "read_vault_note":
            note_name = tool_input["note_name"]
            style = tool_input.get("style", "measured")
            note_path, note_title = _resolve_note_for_reading(note_name)
            if not note_path:
                return {"success": False, "error": f"Could not find note matching: {note_name}"}
            # Read the actual file content
            try:
                with open(note_path, encoding="utf-8") as f:
                    note_content = f.read()
            except Exception as e:
                return {"success": False, "error": f"Could not read '{note_title}': {e}"}
            if not note_content.strip():
                return {"success": False, "error": f"Note '{note_title}' is empty."}
            # Track resonance — what the user asks to hear
            try:
                track_resonance(note_title, note_path, context=note_name)
            except Exception as re_err:
                log.warning(f"Resonance tracking failed: {re_err}")
            return {
                "success": True,
                "result": f"Reading '{note_title}' aloud...",
                "action": "read_aloud",
                "data": {
                    "content": note_content,
                    "title": note_title,
                    "path": note_path,
                    "style": style,
                },
            }

        elif tool_name == "ask_retro":
            # Phase 17.11 — `ask_retro` wraps the same answer_retro_question
            # Phase 22.0 exposes via /retro <question>. Lets the model
            # answer "how was this week" mid-conversation without the
            # slash. Cached by hash(question, week_key) so repeat asks
            # in the same week skip the Sonnet call.
            question = (tool_input.get("question") or "").strip()
            if not question:
                return {
                    "success": False,
                    "error": "ask_retro requires a question",
                }
            try:
                from myalicia.skills.weekly_self_portrait import answer_retro_question
                answer = answer_retro_question(question)
            except Exception as e:
                return {
                    "success": False,
                    "error": f"retro Q&A failed: {e}",
                }
            if not answer:
                return {
                    "success": False,
                    "error": (
                        "Couldn't compose an answer — composer error "
                        "or no week signal yet."
                    ),
                }
            return {
                "success": True,
                "result": answer,
                # Beatrice prose — already user-ready; skip reformat
                "action": "skip_reformat",
            }

        elif tool_name == "financial":
            # Phase 17.10 — `financial` as a conversational tool. Wraps
            # the same `summarise_financial_emails` /financial uses.
            try:
                from myalicia.skills.gmail_skill import summarise_financial_emails
                summary = summarise_financial_emails(days=7)
            except Exception as e:
                return {
                    "success": False,
                    "error": f"financial scan failed: {e}",
                }
            return {
                "success": True,
                "result": summary or "No financial emails in the last 7 days.",
            }

        elif tool_name == "start_thinking_session":
            # Phase 17.6 — `walk`/`drive`/`unpack` as conversational tools.
            # Before this fix, the model knew about /walk /drive /unpack
            # from the system prompt but no tool existed in the registry,
            # so it would either route them through cmd-style hints OR
            # hallucinate a tool call → 'Unknown tool' → capability denial
            # (the same bug class as Phase 17.5's draw fix).
            mode = (tool_input.get("mode") or "").strip().lower()
            topic = (tool_input.get("topic") or "").strip()
            if mode not in ("walk", "drive", "unpack"):
                return {
                    "success": False,
                    "error": f"unknown mode: {mode!r} (expected walk/drive/unpack)",
                }
            return {
                "success": True,
                "result": (
                    f"Starting {mode} session"
                    f"{f' on: {topic}' if topic else ''}. "
                    f"alicia.py will send the voice greeting and route "
                    f"the next messages through the {mode} handler. Your "
                    f"reply text should be ONE SHORT line acknowledging "
                    f"the start — the voice greeting is the real opening."
                ),
                "action": "start_thinking_session",
                "data": {"mode": mode, "topic": topic},
            }

        elif tool_name == "note":
            # Phase 17.6 — quick-save into the Obsidian Inbox. Wraps the
            # same `write_to_obsidian` call cmd_note uses, so notes saved
            # via the conversational tool look identical to /note saves
            # for the daily-pass + downstream routing.
            text = (tool_input.get("text") or "").strip()
            if not text:
                return {"success": False, "error": "note text is empty"}
            try:
                # Local import — avoid coupling tool_router to alicia.py
                # at module load. write_to_obsidian lives in alicia.py;
                # the canonical path is via memory_skill so we use that.
                from myalicia.skills.memory_skill import write_inbox_note
                rel_path = write_inbox_note(text)
            except Exception as e:
                # Fallback: write directly if write_inbox_note isn't
                # exposed. Mirrors cmd_note's inline behavior.
                try:
                    from datetime import datetime as _dt
                    import os as _os
                    obsidian_root = _os.path.expanduser(
                        f"~/Documents/{USER_HANDLE}-alicia/Alicia/Inbox"
                    )
                    _os.makedirs(obsidian_root, exist_ok=True)
                    now = _dt.now()
                    fname = f"{now.strftime('%Y-%m-%d-%H%M')}-note.md"
                    fpath = _os.path.join(obsidian_root, fname)
                    body = (
                        f"# Quick Note\n"
                        f"**Saved:** {now.strftime('%Y-%m-%d %H:%M')}\n"
                        f"**Source:** conversational tool (Phase 17.6)\n\n"
                        f"{text}\n"
                    )
                    with open(fpath, "w", encoding="utf-8") as f:
                        f.write(body)
                    rel_path = f"Inbox/{fname}"
                except Exception as e2:
                    return {
                        "success": False,
                        "error": f"note save failed: {e2}",
                    }
            return {
                "success": True,
                "result": (
                    f"Note saved to Obsidian Inbox: {rel_path}. Your "
                    f"reply should be ONE LINE confirming (e.g. "
                    f"'noted — it's in the inbox')."
                ),
            }

        elif tool_name == "show_dashboard":
            # Phase 17.6 — wraps every read-only observability dashboard
            # so 'show me X' / 'how are the loops' / 'what's noticing'
            # land the right view.
            name = (tool_input.get("name") or "").strip().lower()
            try:
                if name == "becoming":
                    from myalicia.skills.user_model import render_becoming_dashboard
                    text = render_becoming_dashboard()
                elif name == "season":
                    from myalicia.skills.season_dashboard import render_season_dashboard
                    text = render_season_dashboard()
                elif name == "noticings":
                    from myalicia.skills.emergent_themes import (
                        render_noticings_for_telegram,
                    )
                    text = render_noticings_for_telegram()
                elif name == "loops":
                    from myalicia.skills.loops_dashboard import render_loops_dashboard
                    text = render_loops_dashboard()
                elif name == "multichannel":
                    from myalicia.skills.multichannel_dashboard import (
                        render_multichannel_dashboard,
                    )
                    text = render_multichannel_dashboard()
                elif name == "wisdom":
                    from myalicia.skills.wisdom_dashboard import render_wisdom_dashboard
                    text = render_wisdom_dashboard()
                elif name == "effectiveness":
                    from myalicia.skills.effectiveness_dashboard import (
                        render_effectiveness_dashboard,
                    )
                    text = render_effectiveness_dashboard()
                else:
                    return {
                        "success": False,
                        "error": (
                            f"unknown dashboard: {name!r} (expected one of "
                            f"becoming/season/noticings/loops/"
                            f"multichannel/wisdom/effectiveness)"
                        ),
                    }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"dashboard render failed: {e}",
                }
            if not text:
                return {
                    "success": False,
                    "error": f"dashboard {name!r} returned empty text",
                }
            return {
                "success": True,
                "result": text,
                # Skip the Sonnet reformat — these dashboards are
                # already user-ready text. Reformatting would lose the
                # markdown structure.
                "action": "skip_reformat",
            }

        elif tool_name == "draw":
            # Phase 17.5 — `draw` as a real conversational tool.
            # Before this fix, the model knew about /draw from the system
            # prompt but no tool existed in the registry, so it would
            # hallucinate a `draw` tool call, get "Unknown tool", then
            # tell the user "I don't have drawing capabilities yet" — even
            # though the visual voice has been live since Phase 10. This
            # tool wraps generate_drawing() so the model can actually
            # render and send.
            try:
                from myalicia.skills.drawing_skill import (
                    generate_drawing, can_draw_now,
                    build_drawing_state_snapshot, record_drawing_sent,
                )
            except Exception as imp_e:
                return {
                    "success": False,
                    "error": f"drawing_skill unavailable: {imp_e}",
                }
            phrase = (tool_input.get("phrase") or "").strip()
            try:
                state = build_drawing_state_snapshot()
            except Exception as se:
                log.debug(f"build_drawing_state_snapshot failed: {se}")
                state = None
            try:
                if phrase:
                    result = generate_drawing(prompt=phrase, state=state)
                else:
                    result = generate_drawing(state=state)
            except Exception as ge:
                return {
                    "success": False,
                    "error": f"drawing render failed: {ge}",
                }
            if not result or not result.get("path"):
                return {
                    "success": False,
                    "error": "drawing render returned no path",
                }
            archetype = result.get("archetype", "mixed")
            caption = (result.get("caption") or "").strip()
            return {
                "success": True,
                # The MODEL'S text reply context — what it sees as the
                # tool result. Tells it the drawing was sent so its own
                # text reply can stay short and human.
                "result": (
                    f"Drawing rendered ({archetype}) and sent to {USER_NAME}. "
                    f"Caption: \"{caption[:120]}\". Your reply text should "
                    f"be SHORT (one or two lines) — the drawing speaks for "
                    f"itself. Do NOT describe what the drawing looks like."
                ),
                "action": "send_drawing",
                "data": {
                    "result": result,
                    "phrase": phrase,
                    "source_kind": "drawing_tool",
                },
            }

        elif tool_name == "ingest_vault":
            from myalicia.skills.vault_ingest import run_ingest_scan, format_ingest_report, initialize_ingest
            if tool_input.get("initialize"):
                init_result = initialize_ingest()
                return {
                    "success": True,
                    "result": (
                        f"Ingest pipeline initialized.\n"
                        f"Sources baselined: {init_result['sources_baselined']}\n"
                        f"Wiki pages indexed: {init_result['wiki_pages_indexed']}\n\n"
                        f"Future scans will only pick up new or modified files."
                    ),
                }
            limit = tool_input.get("limit", 5)
            result = run_ingest_scan(limit=limit)
            report = format_ingest_report(result)
            return {"success": True, "result": report}

        elif tool_name == "clarify":
            question = tool_input.get("question", "Could you be more specific?")
            return {
                "success": True,
                "result": question,
                "action": "clarify",
            }

        elif tool_name == "recent_responses":
            try:
                from myalicia.skills.response_capture import get_responses_for_synthesis
            except Exception as e:
                return {"success": False, "error": f"response_capture import failed: {e}"}
            title = (tool_input.get("synthesis_title") or "").strip()
            if not title:
                return {"success": False, "error": "synthesis_title is required"}
            max_recent = int(tool_input.get("max_recent", 5))
            try:
                responses = get_responses_for_synthesis(title, max_recent=max_recent)
            except Exception as e:
                return {"success": False, "error": f"lookup failed: {e}"}
            if not responses:
                return {
                    "success": True,
                    "result": (
                        f"No captured responses on '{title}' yet. Compose "
                        f"normally — there's no past conversation to weave in."
                    ),
                }
            # Compact format Sonnet can parse and quote naturally.
            lines = [f"Past responses on '{title}' (newest first):"]
            for r in responses:
                ts = (r.get("captured_at") or "").split("T")[0] or "?"
                arch = r.get("archetype") or "—"
                channel = r.get("channel") or "text"
                excerpt = (r.get("body_excerpt") or "").strip()
                lines.append(
                    f"\n• {ts} ({channel}, archetype={arch}):\n  \"{excerpt}\""
                )
            return {"success": True, "result": "\n".join(lines)}

        else:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        log.error(f"Tool execution error ({tool_name}): {e}")
        return {"success": False, "error": str(e)}


# ── Dynamic Tool Registry ───────────────────────────────────────────────────
# Split tools into always-loaded core and on-demand specialist sets.
# Core tools cover ~80% of interactions. Specialists load based on message intent.

CORE_TOOL_NAMES = {
    # search_vault was moved to specialists (<earlier development>) to stop over-triggering
    # on conversational/emotional messages. It only loads now when the message
    # contains explicit search-intent keywords. Conversation is the default.
    "read_vault_note", "remember", "recall_memory", "clarify",
    # Phase 17.5 — `draw` is a CORE tool. The model already knows about
    # /draw from the system prompt; before this fix it would hallucinate
    # the tool, get "Unknown tool", then deny the capability. Loading
    # `draw` as core means the conversational path can fulfil drawing
    # requests at any moment without intent-keyword gymnastics.
    "draw",
    # Phase 17.6 — command/tool parity audit. Three more tools join CORE
    # to close the same drift class for every Telegram command exposing
    # a generative or read-only capability:
    #   - start_thinking_session: wraps /walk, /drive, /unpack
    #   - note: wraps /note, /log, /capture
    #   - show_dashboard: wraps /becoming, /season, /noticings, /loops,
    #     /multichannel, /wisdom, /effectiveness
    # Without these as CORE, conversational paraphrases ("let's walk
    # about X", "save this thought", "show me my becoming") would
    # re-trigger the Phase 17.5 capability-denial bug class.
    "start_thinking_session", "note", "show_dashboard",
}

# Keyword triggers for specialist tools
_SPECIALIST_TRIGGERS = {
    "search_vault":        ["find", "look up", "look for", "search", "show me a note",
                            "show me notes", "show me the note", "what notes", "what pages",
                            "what do i have on", "is there a note", "is there anything",
                            "any notes on", "any pages on", "from the vault", "in the vault",
                            "retrieve", "pull up"],
    "generate_pdf":        ["pdf", "export", "convert", "document"],
    "send_email":          ["email", "mail", "message to", "write to", "send to"],
    "get_vault_stats":     ["stats", "metrics", "progress", "health", "vault stat"],
    "generate_concept_note": ["concept", "concept note", "new idea", "explore idea"],
    "research":            ["research", "look into", "deep dive", "investigate"],
    "get_random_quote":    ["quote", "inspiration", "wisdom", "something to think"],
    "inbox_summary":       ["inbox", "email", "mail", "unread"],
    "synthesise_vault":    ["synthesi", "synthesise", "synthesize", "cross-book", "connections", "bridge"],
    "find_contradictions": ["contradiction", "tension", "conflict", "disagree"],
    "knowledge_dashboard": ["dashboard", "knowledge level", "level", "wisdom metric"],
    "consolidate_memory":  ["consolidate", "clean memory", "tidy", "deduplicate"],
    "ingest_vault":        ["ingest", "process new", "sync vault", "update vault", "new sources"],
    # Phase 17.10 — finance scan; specialist (rare, gated by explicit keywords)
    "financial":           ["financial", "finances", "money", "bill", "invoice",
                            "bank email", "what's in my financial"],
    # Phase 17.11 — retro Q&A over the week's signals; specialist gated
    # by week/month phrasing.
    "ask_retro":           ["this week", "last week", "past week", "this month",
                            "last month", "how was this", "how was last",
                            "what was hardest", "how am i doing",
                            "sunday portrait", "stood out this week",
                            "stood out last week"],
    # Phase 11.6 — the user's past captured responses on a synthesis. Triggers
    # on resurfacing-flavored keywords; the primary path is the intent
    # resolver (specialist passed explicitly when the composer picks a
    # surfacing).
    "recent_responses":    ["last time you said", "what did i say about",
                            "i told you about", "we talked about",
                            "remember our conversation", "my reply to",
                            "what was my response", "past responses"],
}

CORE_TOOLS = [t for t in TOOLS if t["name"] in CORE_TOOL_NAMES]
SPECIALIST_TOOLS = {t["name"]: t for t in TOOLS if t["name"] not in CORE_TOOL_NAMES}


def resolve_tools(user_message: str) -> list:
    """
    Keyword-based fallback tool registry. Returns core tools + any specialist
    tools triggered by the message content.

    NOTE: As of 2026-04-17 this is the FALLBACK path. The primary routing
    goes through skills.context_resolver.resolve_intent() which returns
    specialist tool names in a single unified Haiku call. Callers that only
    need the old keyword-based behaviour still work unchanged.
    """
    lowered = user_message.lower()
    active_tools = list(CORE_TOOLS)
    added = set()

    for tool_name, keywords in _SPECIALIST_TRIGGERS.items():
        if tool_name in added:
            continue
        for kw in keywords:
            if kw in lowered:
                tool_def = SPECIALIST_TOOLS.get(tool_name)
                if tool_def:
                    active_tools.append(tool_def)
                    added.add(tool_name)
                break

    log.info(
        f"Tool registry [kw]: {len(active_tools)}/{len(TOOLS)} tools loaded "
        f"(+{len(added)} specialists: {sorted(added) if added else 'none'})"
    )
    return active_tools


def build_active_tools(specialist_names: list) -> list:
    """
    Compose the final Sonnet tool list from core tools + an explicit list
    of specialist names (usually produced by context_resolver.resolve_intent).

    Core tools are always included. Unknown or duplicate specialist names
    are silently dropped.

    Args:
        specialist_names: e.g. ['search_vault', 'generate_pdf']; can be empty.
    Returns:
        list of tool dicts, ready to pass as tools=... to the Anthropic API.
    """
    active = list(CORE_TOOLS)
    seen = {t["name"] for t in active}
    added = []
    for name in specialist_names or []:
        if name in seen:
            continue
        tool_def = SPECIALIST_TOOLS.get(name)
        if tool_def:
            active.append(tool_def)
            seen.add(name)
            added.append(name)

    log.info(
        f"Tool registry [intent]: {len(active)}/{len(TOOLS)} tools loaded "
        f"(+{len(added)} specialists: {sorted(added) if added else 'none'})"
    )
    return active


# ── Main Router ──────────────────────────────────────────────────────────────

def route_message(system_prompt: str, messages: list, model: str = None, active_tools: list = None) -> dict:
    """
    Send the conversation to Claude with tools available.
    Defaults to Sonnet; pass model=MODEL_OPUS for escalated tasks.
    Returns dict with:
      - 'type': 'text' | 'tool_use'
      - 'text': the reply text (if type is text)
      - 'tool_name', 'tool_input': the tool call (if type is tool_use)
      - 'thinking': any text Sonnet produced before calling the tool
    """
    tools_to_use = active_tools if active_tools is not None else TOOLS
    try:
        response = client.messages.create(
            model=model or MODEL_SONNET,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=tools_to_use,
        )

        # Parse response
        text_parts = []
        tool_use = None

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_use = {
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }

        # Guard: if the model hit max_tokens while generating a tool call,
        # the JSON parameters are likely truncated (root cause of the
        # remember-truncation bug).  Log a warning and retry once with a
        # higher budget rather than silently storing mangled content.
        if tool_use and response.stop_reason == "max_tokens":
            log.warning(
                "Tool call truncated (stop_reason=max_tokens, tool=%s). "
                "Retrying with extended budget.",
                tool_use["name"],
            )
            retry = client.messages.create(
                model=model or MODEL_SONNET,
                max_tokens=8192,
                system=system_prompt,
                messages=messages,
                tools=tools_to_use,
            )
            text_parts = []
            tool_use = None
            for block in retry.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_use = {
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
            if tool_use:
                return {
                    "type": "tool_use",
                    "tool_name": tool_use["name"],
                    "tool_input": tool_use["input"],
                    "tool_id": tool_use["id"],
                    "thinking": "\n".join(text_parts) if text_parts else None,
                    "stop_reason": retry.stop_reason,
                }

        if tool_use:
            return {
                "type": "tool_use",
                "tool_name": tool_use["name"],
                "tool_input": tool_use["input"],
                "tool_id": tool_use["id"],
                "thinking": "\n".join(text_parts) if text_parts else None,
                "stop_reason": response.stop_reason,
            }
        else:
            return {
                "type": "text",
                "text": "\n".join(text_parts),
                "stop_reason": response.stop_reason,
            }

    except Exception as e:
        log.error(f"Router error: {e}")
        return {
            "type": "error",
            "error": str(e),
        }
