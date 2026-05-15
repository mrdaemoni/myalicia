"""
Module 5: Analytical Briefing Compiler for Autonomous Analysis

Purpose: Compile all analysis reports from modules 1-4 into a structured briefing
that proactive_messages.py reads for morning greetings and evening reflections.

This module aggregates insights from:
- analysis_contradiction.py: Productive tensions
- analysis_temporal.py: Temporal patterns and growth windows
- analysis_growth_edge.py: Bleeding-edge explorations
- analysis_dialogue_depth.py: Conversation depth analysis
- weekly-architecture-scout (Desktop): New AI/agent architecture signal (sources 5)
- daily-outward-research (Desktop): New authors/thinkers surfaced (source 6)

Entry point: compile_analytical_briefing() -> str
"""

import logging
import os
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import dotenv
import anthropic

from myalicia.skills.bridge_protocol import list_bridge_reports
from myalicia.config import config
USER_NAME = config.user.name
USER_HANDLE = config.user.handle

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Load environment variables
dotenv.load_dotenv()

# Constants
VAULT_ROOT = config.vault.root
BRIDGE_FOLDER = VAULT_ROOT / 'Alicia/Bridge'
SCOUT_FOLDER = VAULT_ROOT / 'Alicia/architecture-scout'
AUTHORS_FOLDER = VAULT_ROOT / 'Authors'
MEMORY_FOLDER = Path.home() / 'alicia/memory'
HOT_TOPICS_FILE = MEMORY_FOLDER / 'hot_topics.md'
PROMPT_EFFECTIVENESS_FILE = MEMORY_FOLDER / 'prompt_effectiveness.tsv'
ANALYTICAL_BRIEFING_FILE = MEMORY_FOLDER / 'analytical_briefing.md'

SONNET_MODEL = 'claude-sonnet-4-20250514'


def _find_latest_report(pattern: str) -> Optional[str]:
    """
    Find the most recent report matching a pattern in Bridge/ folder.

    Args:
        pattern: Glob pattern to match (e.g., 'contradiction-report-*.md').
                 Single `*` wildcard expected (prefix*suffix).

    Returns:
        Content of the most recent matching file, or None if not found.

    Routes through bridge_protocol.list_bridge_reports for uniform
    discovery (§6.4).
    """
    try:
        if "*" in pattern:
            prefix, suffix = pattern.split("*", 1)
        else:
            prefix, suffix = pattern, ""
        matches = list_bridge_reports(prefix, suffix=suffix, max_results=1)
        if not matches:
            logger.debug(f'No files matching pattern: {pattern}')
            return None
        latest_file = matches[0]
        content = latest_file.read_text(encoding='utf-8')
        logger.info(f'Loaded latest report: {latest_file.name}')
        return content
    except Exception as e:
        logger.error(f'Error reading latest report for pattern {pattern}: {e}')
        return None


def _find_latest_scout_report(max_age_days: int = 14) -> Optional[str]:
    """
    Read the most recent architecture-scout-YYYY-MM-DD.md from the scout folder.

    The Desktop weekly-architecture-scout runs Monday 07:03 and writes a digest
    to Alicia/architecture-scout/. We want the briefing compiler (Thursday
    10:03) to pick up Monday's fresh signal so morning messages surface new
    framework/paper ideas.

    Args:
        max_age_days: Ignore reports older than this (default 14 — one scout
            cycle plus buffer).

    Returns:
        Report content or None if nothing fresh is available.
    """
    try:
        if not SCOUT_FOLDER.exists():
            logger.debug(f'Scout folder not found: {SCOUT_FOLDER}')
            return None
        candidates = sorted(
            SCOUT_FOLDER.glob('architecture-scout-*.md'),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            logger.debug('No architecture-scout reports found')
            return None
        latest = candidates[0]
        age_days = (datetime.now().timestamp() - latest.stat().st_mtime) / 86400
        if age_days > max_age_days:
            logger.info(
                f'Latest scout report {latest.name} is {age_days:.1f}d old '
                f'(>{max_age_days}d) — skipping.'
            )
            return None
        content = latest.read_text(encoding='utf-8')
        logger.info(f'Loaded scout report: {latest.name} ({age_days:.1f}d old)')
        return content
    except Exception as e:
        logger.error(f'Error reading latest scout report: {e}')
        return None


def _summarize_recent_authors(days: int = 7, max_authors: int = 8) -> Optional[str]:
    """
    Summarize Author profiles added/modified in the last `days` days.

    The Desktop daily-outward-research task (Mon-Fri 15:34) writes new Author
    profiles to ~/Documents/user-alicia/Authors/. There is no single
    "report" file for this task, so we derive a summary from the folder's
    recent contents — each profile's filename (the author's name) plus the
    first 200 chars of its body (the bio/core-concepts hook).

    Args:
        days: Look-back window in days.
        max_authors: Cap the number of authors included in the summary.

    Returns:
        Markdown summary or None if no recent authors.
    """
    try:
        if not AUTHORS_FOLDER.exists():
            logger.debug(f'Authors folder not found: {AUTHORS_FOLDER}')
            return None
        cutoff = datetime.now().timestamp() - (days * 86400)
        recent = [
            p for p in AUTHORS_FOLDER.glob('*.md')
            if p.stat().st_mtime >= cutoff
        ]
        if not recent:
            logger.debug(f'No Author profiles modified in last {days}d')
            return None
        recent.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        recent = recent[:max_authors]

        lines = [f'New/updated Author profiles ({len(recent)} in last {days}d):']
        for p in recent:
            name = p.stem
            try:
                # Pull first non-header paragraph as a hook.
                body = p.read_text(encoding='utf-8')
                body = re.sub(r'^---.*?---\s*', '', body, count=1, flags=re.DOTALL)
                paragraphs = [
                    para.strip() for para in body.split('\n\n')
                    if para.strip() and not para.lstrip().startswith('#')
                ]
                hook = paragraphs[0] if paragraphs else ''
                hook = re.sub(r'\s+', ' ', hook)[:200]
            except Exception:
                hook = ''
            lines.append(f'- **{name}** — {hook}' if hook else f'- **{name}**')
        summary = '\n'.join(lines)
        logger.info(f'Summarized {len(recent)} recent Author profiles')
        return summary
    except Exception as e:
        logger.error(f'Error summarizing recent Authors: {e}')
        return None


def _read_hot_topics() -> list:
    """
    Read current hot topics from hot_topics.md.

    Returns:
        List of topic strings, or empty list if file not found
    """
    topics = []

    if not HOT_TOPICS_FILE.exists():
        logger.debug(f'Hot topics file not found: {HOT_TOPICS_FILE}')
        return topics

    try:
        content = HOT_TOPICS_FILE.read_text(encoding='utf-8')

        # Extract topics (usually bullet points or list items)
        for line in content.split('\n'):
            cleaned = line.strip().lstrip('- * • ').strip()
            if cleaned and not cleaned.startswith('#'):
                topics.append(cleaned)

        logger.info(f'Loaded {len(topics)} hot topics')
    except Exception as e:
        logger.error(f'Error reading hot topics file: {e}')

    return topics


def _read_prompt_effectiveness_summary() -> str:
    """
    Read the last 7 days of prompt_effectiveness.tsv for engagement summary.

    Returns:
        Summary text describing recent engagement patterns, or empty string
    """
    if not PROMPT_EFFECTIVENESS_FILE.exists():
        logger.debug(f'Prompt effectiveness file not found: {PROMPT_EFFECTIVENESS_FILE}')
        return ''

    try:
        lines = PROMPT_EFFECTIVENESS_FILE.read_text(encoding='utf-8').split('\n')
        if not lines:
            return ''

        # Skip header
        data_lines = lines[1:] if len(lines) > 1 else []

        # Filter to last 7 days
        cutoff_date = datetime.now() - timedelta(days=7)
        recent_lines = []

        for line in data_lines:
            if not line.strip():
                continue
            parts = line.split('\t')
            if len(parts) >= 6:
                try:
                    timestamp_str = parts[0]
                    # Parse "YYYY-MM-DD HH:MM" format
                    msg_date = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M')
                    if msg_date >= cutoff_date:
                        recent_lines.append(line)
                except ValueError:
                    # Skip lines with unparseable timestamps
                    pass

        if not recent_lines:
            return 'No prompt effectiveness data from last 7 days.'

        # Build summary from the data
        msg_types = {}
        total_depth = 0

        for line in recent_lines:
            parts = line.split('\t')
            if len(parts) >= 6:
                msg_type = parts[1].strip()
                try:
                    depth = int(parts[5].strip())
                except (ValueError, IndexError):
                    depth = 2

                if msg_type not in msg_types:
                    msg_types[msg_type] = {'count': 0, 'total_depth': 0}
                msg_types[msg_type]['count'] += 1
                msg_types[msg_type]['total_depth'] += depth
                total_depth += depth

        # Create summary text
        summary_parts = [f'Last 7 days: {len(recent_lines)} prompted interactions.']

        for msg_type, stats in sorted(msg_types.items(), key=lambda x: x[1]['count'], reverse=True):
            avg_depth = stats['total_depth'] / stats['count'] if stats['count'] > 0 else 0
            summary_parts.append(f'{msg_type}: {stats["count"]} messages (avg depth: {avg_depth:.1f})')

        logger.info(f'Summarized prompt effectiveness: {len(recent_lines)} entries from last 7 days')
        return '\n'.join(summary_parts)

    except Exception as e:
        logger.error(f'Error reading prompt effectiveness file: {e}')
        return ''


def _prepare_briefing_prompt(
    contradiction_report: Optional[str],
    temporal_report: Optional[str],
    growth_edge_report: Optional[str],
    dialogue_depth_report: Optional[str],
    hot_topics: list,
    effectiveness_summary: str,
    scout_report: Optional[str] = None,
    outward_research_summary: Optional[str] = None,
) -> str:
    """
    Prepare the prompt for Sonnet to compile the analytical briefing.

    Args:
        contradiction_report: Content of latest contradiction-report-*.md
        temporal_report: Content of latest temporal-report-*.md
        growth_edge_report: Content of latest growth-edge-report-*.md
        dialogue_depth_report: Content of latest dialogue-depth-report-*.md
        hot_topics: List of current hot topics
        effectiveness_summary: Summary of prompt effectiveness from last 7 days
        scout_report: Content of latest architecture-scout-*.md (Desktop weekly task)
        outward_research_summary: Markdown summary of recent Author profiles
            from daily-outward-research (Desktop)

    Returns:
        Formatted prompt string
    """
    # Truncate reports to avoid token bloat
    def truncate(content, limit=1000):
        return content[:limit] + '...' if len(content) > limit else content

    contradiction_text = truncate(contradiction_report) if contradiction_report else '(No contradiction report available)'
    temporal_text = truncate(temporal_report) if temporal_report else '(No temporal report available)'
    growth_text = truncate(growth_edge_report) if growth_edge_report else '(No growth edge report available)'
    dialogue_text = truncate(dialogue_depth_report) if dialogue_depth_report else '(No dialogue depth report available)'
    scout_text = truncate(scout_report, 1500) if scout_report else '(No recent architecture-scout digest available)'
    outward_text = truncate(outward_research_summary, 800) if outward_research_summary else '(No new authors surfaced this week)'

    hot_topics_str = '\n'.join(f'- {topic}' for topic in hot_topics) if hot_topics else '(No hot topics available)'

    prompt = f"""You are analyzing autonomous analysis reports from {USER_NAME}'s thinking system to create a structured briefing.

LATEST ANALYSIS REPORTS:

**CONTRADICTION MINING (productive tensions):**
{contradiction_text}

**TEMPORAL ANALYSIS (patterns and growth windows):**
{temporal_text}

**GROWTH EDGE (bleeding-edge explorations):**
{growth_text}

**DIALOGUE DEPTH (conversation analysis):**
{dialogue_text}

**ARCHITECTURE SCOUT (new AI/agent ideas, frameworks, papers — for self-improvement signal):**
{scout_text}

**OUTWARD RESEARCH (new thinkers/authors surfaced this week — for vault expansion signal):**
{outward_text}

CURRENT HOT TOPICS:
{hot_topics_str}

ENGAGEMENT EFFECTIVENESS (last 7 days):
{effectiveness_summary}

TASK:
Distill these into a structured briefing with these sections:

1. **Most Alive Tension** — The most productive intellectual tension right now. One paragraph. What makes it alive? Why does {USER_NAME} need to engage with it?

2. **Active Growth Edge** — Where {USER_NAME} is stretching intellectually right now. One paragraph. What's at the bleeding edge of his exploration?

3. **Depth Trend** — Pattern in how deep his recent conversations have been. One paragraph. Is engagement deepening? Broadening? Shifting?

4. **Architecture Signal** — One paragraph synthesizing the most useful idea from the architecture-scout digest. What new framework, paper, or pattern is worth {USER_NAME}'s attention this week, and why? Skip this section entirely if no scout digest is available.

5. **New Voices** — Brief paragraph naming the most interesting newly-surfaced thinker(s) from outward-research and what they connect to in {USER_NAME}'s existing work. Skip if none surfaced.

6. **Suggested Prompts** — 2-3 specific, provocative questions derived from the analysis. Each on its own line, starting with "- Q: "

7. **Message Effectiveness** — Which types of proactive messages generated the deepest engagement recently? Brief assessment.

Format as Markdown with clear ## section headers. Keep language precise, specific to {USER_NAME}'s actual work, not generic.
Start with a timestamp line: # Analytical Briefing — YYYY-MM-DD"""

    return prompt


def call_sonnet(prompt: str) -> Optional[str]:
    """
    Call Sonnet to compile the briefing.

    Args:
        prompt: The prompt to send to Sonnet

    Returns:
        Response text or None on error
    """
    try:
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            logger.error('ANTHROPIC_API_KEY not set in environment')
            return None

        client = anthropic.Anthropic(api_key=api_key, max_retries=5)

        message = client.messages.create(
            model=SONNET_MODEL,
            max_tokens=2000,
            messages=[
                {
                    'role': 'user',
                    'content': prompt
                }
            ]
        )

        # Extract response text
        response_text = message.content[0].text
        logger.info('Successfully retrieved briefing from Sonnet')
        return response_text

    except anthropic.APIError as e:
        logger.error(f'Anthropic API error: {e}')
        return None
    except Exception as e:
        logger.error(f'Unexpected error calling Sonnet: {e}')
        return None


def _write_analytical_briefing(briefing_text: str) -> None:
    """
    Write the briefing to analytical_briefing.md (OVERWRITE).

    Args:
        briefing_text: The compiled briefing markdown
    """
    try:
        # Ensure memory folder exists
        MEMORY_FOLDER.mkdir(parents=True, exist_ok=True)

        # OVERWRITE the file (unlike analysis_insights.md which appends)
        ANALYTICAL_BRIEFING_FILE.write_text(briefing_text, encoding='utf-8')
        logger.info(f'Wrote analytical briefing to {ANALYTICAL_BRIEFING_FILE}')

    except Exception as e:
        logger.error(f'Error writing analytical briefing: {e}')


def _create_placeholder_briefing() -> str:
    """
    Create a placeholder briefing when analysis modules haven't run yet.

    Returns:
        Placeholder briefing markdown
    """
    timestamp = datetime.now().strftime('%Y-%m-%d')
    placeholder = f"""# Analytical Briefing — {timestamp}

## Most Alive Tension

_Analysis modules have not yet generated reports. Run the autonomous analysis suite to populate this section._

## Active Growth Edge

_Awaiting growth edge analysis. Check back after the next analysis cycle._

## Depth Trend

_No engagement data available yet. This section will populate as proactive messages are sent and engagement is tracked._

## Suggested Prompts

- Q: What aspect of your current work feels most uncertain right now?
- Q: Which of your recent insights surprised you the most?

## Message Effectiveness

No tracked engagement data available yet. This briefing will become more personalized as the system learns which message types generate the deepest thinking.
"""
    return placeholder


def compile_analytical_briefing() -> str:
    """
    Main entry point: compile all analysis reports into a structured briefing.

    Returns:
        The compiled briefing as a markdown string
    """
    logger.info('Starting analytical briefing compilation')

    try:
        # 1. Read all latest reports from Bridge folder
        logger.info('Reading latest analysis reports...')
        contradiction_report = _find_latest_report('contradiction-report-*.md')
        temporal_report = _find_latest_report('temporal-report-*.md')
        growth_edge_report = _find_latest_report('growth-edge-report-*.md')
        dialogue_depth_report = _find_latest_report('dialogue-depth-report-*.md')

        # 1b. Read Desktop-side signals: architecture scout + outward research
        logger.info('Reading Desktop scout + outward-research signals...')
        scout_report = _find_latest_scout_report()
        outward_research_summary = _summarize_recent_authors()

        # Check if we have any reports at all
        has_reports = any([
            contradiction_report, temporal_report, growth_edge_report,
            dialogue_depth_report, scout_report, outward_research_summary,
        ])

        if not has_reports:
            logger.warning('No analysis reports found in Bridge folder — using placeholder')
            placeholder = _create_placeholder_briefing()
            _write_analytical_briefing(placeholder)
            return placeholder

        # 2. Read hot topics and prompt effectiveness
        logger.info('Reading hot topics and engagement data...')
        hot_topics = _read_hot_topics()
        effectiveness_summary = _read_prompt_effectiveness_summary()

        # 3. Prepare prompt for Sonnet
        logger.info('Preparing briefing compilation prompt...')
        prompt = _prepare_briefing_prompt(
            contradiction_report,
            temporal_report,
            growth_edge_report,
            dialogue_depth_report,
            hot_topics,
            effectiveness_summary,
            scout_report=scout_report,
            outward_research_summary=outward_research_summary,
        )

        # 4. Call Sonnet
        logger.info('Calling Sonnet to compile briefing...')
        briefing_text = call_sonnet(prompt)

        if not briefing_text:
            logger.error('Sonnet API call failed — using placeholder')
            placeholder = _create_placeholder_briefing()
            _write_analytical_briefing(placeholder)
            return placeholder

        # 5. Write to analytical_briefing.md
        logger.info('Writing analytical briefing to file...')
        _write_analytical_briefing(briefing_text)

        logger.info('Analytical briefing compilation completed successfully')
        return briefing_text

    except Exception as e:
        logger.error(f'Unexpected error in briefing compilation: {e}')
        placeholder = _create_placeholder_briefing()
        _write_analytical_briefing(placeholder)
        return placeholder


if __name__ == '__main__':
    # Test the module
    briefing = compile_analytical_briefing()
    print(briefing)
