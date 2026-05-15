"""
Module 1: Contradiction Mining for Autonomous Analysis
Purpose: Find productive tensions between ideas in the user's Obsidian vault.

This module identifies genuine intellectual conflicts across knowledge clusters
and scores them for novelty, severity, and relevance to current interests.
"""

import logging
import os
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional
import dotenv
import anthropic

from myalicia.skills.safe_io import atomic_write_text, locked_file
from myalicia.skills.bridge_protocol import write_bridge_text
from myalicia.config import config, ALICIA_HOME, MEMORY_DIR
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
SYNTHESIS_FOLDER = VAULT_ROOT / 'Alicia/Wisdom/Synthesis'

MEMORY_FOLDER = MEMORY_DIR
BRIDGE_FOLDER = VAULT_ROOT / 'Alicia/Bridge'
INSIGHTS_FILE = MEMORY_FOLDER / 'insights.md'
HOT_TOPICS_FILE = MEMORY_FOLDER / 'hot_topics.md'
ANALYSIS_INSIGHTS_FILE = MEMORY_FOLDER / 'analysis_insights.md'

# Starter knowledge clusters — replace with your own thematic groupings.
# Each entry is "Theme name (a few keywords/authors that anchor it)".
# These are passed as prompt context so Sonnet knows what bins to think in.
KNOWLEDGE_CLUSTERS = [
    'Theme A (anchor concepts and authors)',
    'Theme B (anchor concepts and authors)',
    'Theme C (anchor concepts and authors)',
    'Theme D (anchor concepts and authors)',
    'Theme E (anchor concepts and authors)',
    'Theme F (anchor concepts and authors)',
    'Theme G (anchor concepts and authors)',
    'Theme H (anchor concepts and authors)',
]

SONNET_MODEL = 'claude-sonnet-4-20250514'


def read_recent_synthesis_notes(limit: int = 20) -> dict:
    """
    Read recent synthesis notes by modification time.

    Args:
        limit: Number of recent files to read

    Returns:
        Dict mapping filename to content
    """
    notes = {}

    if not SYNTHESIS_FOLDER.exists():
        logger.warning(f'Synthesis folder not found: {SYNTHESIS_FOLDER}')
        return notes

    try:
        # Get all markdown files sorted by mtime (most recent first)
        md_files = sorted(
            SYNTHESIS_FOLDER.glob('*.md'),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )[:limit]

        for file_path in md_files:
            try:
                content = file_path.read_text(encoding='utf-8')
                notes[file_path.name] = content
                logger.info(f'Loaded synthesis note: {file_path.name}')
            except Exception as e:
                logger.error(f'Error reading {file_path.name}: {e}')

        logger.info(f'Loaded {len(notes)} synthesis notes')
    except Exception as e:
        logger.error(f'Error reading synthesis folder: {e}')

    return notes


def extract_scored_insights(limit: int = 10) -> list:
    """
    Extract recent insights with score 4-5 from insights.md.

    Args:
        limit: Maximum number of insights to extract

    Returns:
        List of insight strings
    """
    insights = []

    if not INSIGHTS_FILE.exists():
        logger.warning(f'Insights file not found: {INSIGHTS_FILE}')
        return insights

    try:
        content = INSIGHTS_FILE.read_text(encoding='utf-8')

        # Pattern: find lines with score 4 or 5 (typically marked with ★★★★ or similar)
        # This is a simplified pattern; adjust based on actual format
        for line in content.split('\n'):
            # Look for patterns indicating high-scoring insights
            if re.search(r'(★{4,5}|score.*[45]|high.*relevance)', line, re.IGNORECASE):
                cleaned = line.strip()
                if cleaned and len(cleaned) > 10:
                    insights.append(cleaned)
                    if len(insights) >= limit:
                        break

        logger.info(f'Extracted {len(insights)} high-scoring insights')
    except Exception as e:
        logger.error(f'Error reading insights file: {e}')

    return insights


def read_hot_topics() -> list:
    """
    Read current hot topics from hot_topics.md.

    Returns:
        List of hot topic strings
    """
    topics = []

    if not HOT_TOPICS_FILE.exists():
        logger.warning(f'Hot topics file not found: {HOT_TOPICS_FILE}')
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


def prepare_synthesis_prompt(
    notes: dict,
    insights: list,
    hot_topics: list
) -> str:
    """
    Prepare the prompt for Sonnet to identify contradictions.

    Args:
        notes: Dict of synthesis notes
        insights: List of recent insights
        hot_topics: List of current hot topics

    Returns:
        Formatted prompt string
    """
    clusters_str = '\n'.join(f'{i + 1}. {cluster}' for i, cluster in enumerate(KNOWLEDGE_CLUSTERS))

    notes_summary = '\n\n'.join(
        f'**{fname}**:\n{content[:500]}...' if len(content) > 500 else f'**{fname}**:\n{content}'
        for fname, content in list(notes.items())[:10]
    ) or '(No synthesis notes available)'

    insights_str = '\n'.join(f'- {insight}' for insight in insights) or '(No insights available)'

    hot_topics_str = '\n'.join(f'- {topic}' for topic in hot_topics) or '(No hot topics available)'

    prompt = f"""You are analyzing ideas from {USER_NAME}'s personal knowledge vault to identify productive tensions—genuine intellectual conflicts that reveal deeper complexity, not surface contradictions.

KNOWLEDGE CLUSTERS (context for organization):
{clusters_str}

RECENT SYNTHESIS NOTES:
{notes_summary}

HIGH-SCORING INSIGHTS:
{insights_str}

CURRENT HOT TOPICS:
{hot_topics_str}

TASK:
Identify 3-5 productive tensions within this material. A productive tension is:
1. A genuine intellectual conflict (not wording differences)
2. Between two substantive positions or frameworks
3. That reveals something important about complexity or tradeoffs
4. Not previously surfaced (novel, not obvious)

For each tension, provide:
- NAME: Short title for the tension
- CLUSTERS: Which 2 knowledge clusters are in conflict
- CLAIMS: The opposing positions (2-3 sentences each)
- PRODUCTIVE VALUE: Why this tension matters (1-2 sentences)
- SEVERITY: minor/moderate/major
- NOVELTY: How new is this observation? (novel/somewhat-known/obvious)
- RELEVANCE_TO_HOT_TOPICS: Does it relate to current interests? (yes/somewhat/no)

Format your response as valid JSON with key "tensions" containing an array of tension objects.
Be rigorous. If you find fewer than 3 genuine tensions, list only what you find."""

    return prompt


def call_sonnet(prompt: str) -> Optional[dict]:
    """
    Call Sonnet to analyze tensions.

    Args:
        prompt: The prompt to send to Sonnet

    Returns:
        Parsed response dict or None on error
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

        # Try to parse JSON from response
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            logger.info('Successfully parsed Sonnet response')
            return parsed
        else:
            logger.warning('Could not find JSON in Sonnet response')
            return None

    except anthropic.APIError as e:
        logger.error(f'Anthropic API error: {e}')
        return None
    except json.JSONDecodeError as e:
        logger.error(f'JSON decode error: {e}')
        return None
    except Exception as e:
        logger.error(f'Unexpected error calling Sonnet: {e}')
        return None


def write_analysis_insights(tensions: list) -> None:
    """
    Append top finding to analysis_insights.md with timestamp.

    Args:
        tensions: List of tension dicts from Sonnet
    """
    if not tensions:
        logger.info('No tensions to write')
        return

    try:
        # Ensure memory folder exists
        MEMORY_FOLDER.mkdir(parents=True, exist_ok=True)

        # Find the most novel/severe tension
        top_tension = max(
            tensions,
            key=lambda t: (
                2 if t.get('novelty') == 'novel' else (1 if t.get('novelty') == 'somewhat-known' else 0),
                {'major': 3, 'moderate': 2, 'minor': 1}.get(t.get('severity', 'minor'), 0)
            )
        )

        timestamp = datetime.now().isoformat()
        tension_name = top_tension.get('name', 'Unknown tension')
        claims_summary = top_tension.get('productive_value', 'Productive tension identified')

        entry = f'\n## [{timestamp}] Contradiction Mining: {tension_name}\n- Top finding: {claims_summary}\n- Severity: {top_tension.get("severity", "unknown")}\n- Source: contradiction_mining\n'

        # Append under exclusive lock — multiple analysis modules share this file
        mode = 'a' if ANALYSIS_INSIGHTS_FILE.exists() else 'w'
        with locked_file(ANALYSIS_INSIGHTS_FILE, mode, encoding='utf-8') as f:
            if mode == 'w':
                f.write('# Analysis Insights\n\n')
            f.write(entry)

        logger.info(f'Wrote analysis insight to {ANALYSIS_INSIGHTS_FILE}')

    except Exception as e:
        logger.error(f'Error writing analysis insights: {e}')


def write_contradiction_report(tensions: list) -> str:
    """
    Write full report to Bridge folder.

    Args:
        tensions: List of tension dicts

    Returns:
        Path to the report file
    """
    try:
        date_str = datetime.now().strftime('%Y-%m-%d')
        report_filename = f'contradiction-report-{date_str}.md'

        # Build report content
        content = f"""# Contradiction Mining Report
Generated: {datetime.now().isoformat()}

## Summary
Found {len(tensions)} productive tensions across knowledge clusters.

## Tensions

"""

        for i, tension in enumerate(tensions, 1):
            content += f"""### {i}. {tension.get('name', 'Unknown')}

**Clusters in Conflict:** {tension.get('clusters', 'Unknown')}

**Claim A:** {tension.get('claims', {}).get('position_a', 'Not available')}

**Claim B:** {tension.get('claims', {}).get('position_b', 'Not available')}

**Productive Value:** {tension.get('productive_value', 'Not available')}

**Severity:** {tension.get('severity', 'unknown')}
**Novelty:** {tension.get('novelty', 'unknown')}
**Relevance to Hot Topics:** {tension.get('relevance_to_hot_topics', 'unknown')}

---

"""

        content += f"""## Methodology

This analysis scanned {len([n for n in range(20)])} recent synthesis notes, extracted high-scoring insights, and identified genuine intellectual conflicts across {len(KNOWLEDGE_CLUSTERS)} knowledge clusters using the Sonnet model.

Productive tensions differ from surface contradictions by revealing underlying complexity or meaningful tradeoffs rather than mere disagreement.
"""

        report_path = write_bridge_text(report_filename, content)
        logger.info(f'Wrote contradiction report to {report_path}')
        return str(report_path)

    except Exception as e:
        logger.error(f'Error writing contradiction report: {e}')
        return ''


def run_contradiction_mining() -> dict:
    """
    Main entry point: orchestrate contradiction mining.

    Returns:
        Dict with keys:
            - status: 'success' or 'partial'
            - tensions_found: int count
            - report_path: str path to Bridge report
            - tensions: list of tension dicts (if any)
            - errors: list of error messages (if any)
    """
    result = {
        'status': 'success',
        'tensions_found': 0,
        'report_path': '',
        'tensions': [],
        'errors': []
    }

    logger.info('Starting contradiction mining analysis')

    try:
        # 1. Read data sources
        logger.info('Reading data sources...')
        notes = read_recent_synthesis_notes(limit=20)
        insights = extract_scored_insights(limit=10)
        hot_topics = read_hot_topics()

        if not notes and not insights:
            result['errors'].append('No synthesis notes or insights found')
            result['status'] = 'partial'
            logger.warning('Insufficient data for analysis')
            return result

        # 2. Prepare prompt for Sonnet
        logger.info('Preparing analysis prompt...')
        prompt = prepare_synthesis_prompt(notes, insights, hot_topics)

        # 3. Call Sonnet
        logger.info('Calling Sonnet for contradiction analysis...')
        response = call_sonnet(prompt)

        if not response:
            result['errors'].append('Sonnet API call failed or returned invalid JSON')
            result['status'] = 'partial'
            logger.error('Sonnet call failed')
            return result

        # 4. Extract and validate tensions
        tensions = response.get('tensions', [])
        if not tensions:
            result['errors'].append('No tensions found in Sonnet response')
            result['status'] = 'partial'
            logger.warning('Sonnet returned no tensions')
            return result

        result['tensions'] = tensions
        result['tensions_found'] = len(tensions)
        logger.info(f'Found {len(tensions)} productive tensions')

        # 5. Write analysis insights
        logger.info('Writing analysis insights...')
        write_analysis_insights(tensions)

        # 6. Write full report
        logger.info('Writing full contradiction report...')
        report_path = write_contradiction_report(tensions)
        result['report_path'] = report_path

        logger.info('Contradiction mining completed successfully')
        return result

    except Exception as e:
        logger.error(f'Unexpected error in contradiction mining: {e}')
        result['status'] = 'partial'
        result['errors'].append(str(e))
        return result


if __name__ == '__main__':
    # Test the module
    result = run_contradiction_mining()
    print(json.dumps(result, indent=2))
