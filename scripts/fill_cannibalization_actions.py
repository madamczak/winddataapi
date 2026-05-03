"""
Script to fill the 'Action' column in specialist_blinds_FINAL_v2.xlsx
with keyword cannibalization fix recommendations.

Logic:
- For each keyword group, the URL with the BEST (lowest) ranking position
  is designated the "winner" and gets an OPTIMIZE action.
- All other URLs in that keyword group get a DEOPTIMIZE action.
- If all URLs for a keyword are editorial/advice pages with no clear
  commercial intent match, a NEW CONTENT suggestion is added.
- Severity (High/Medium) influences the urgency language used.
"""

import pandas as pd

INPUT  = r'C:\Users\adamc\PycharmProjects\winddataAPI\excelfile\specialist_blinds_FINAL_v2.xlsx'
OUTPUT = r'C:\Users\adamc\PycharmProjects\winddataAPI\excelfile\specialist_blinds_FINAL_v2.xlsx'


def url_type(url: str) -> str:
    """Classify a URL as 'commercial' or 'editorial'."""
    if '/inspiration-advice/' in url or '/blog/' in url or '/news/' in url:
        return 'editorial'
    return 'commercial'


def build_action(row, winner_url: str, keyword: str, severity: str, is_winner: bool) -> str:
    url = row['URL']
    urgency = "[HIGH PRIORITY] " if severity == 'High' else "[MEDIUM PRIORITY] "
    u_type  = url_type(url)
    w_type  = url_type(winner_url)

    if is_winner:
        return (
            f"{urgency}OPTIMIZE: Set this as the primary page for '{keyword}'. "
            f"Strengthen title tag, H1, meta description and internal-link anchor text "
            f"to reinforce relevance. Consolidate any thin content from competing pages here."
        )

    # Cannibalizing page actions
    if u_type == 'commercial' and w_type == 'commercial':
        return (
            f"{urgency}DEOPTIMIZE: Remove '{keyword}' from title/H1 on this page. "
            f"Update internal links so they point to the winner page ({winner_url}). "
            f"Consider a 301 redirect if this page overlaps heavily in content."
        )

    if u_type == 'editorial' and w_type == 'commercial':
        return (
            f"{urgency}DEOPTIMIZE: Reduce keyword prominence for '{keyword}' on this editorial page. "
            f"Add a prominent internal link/CTA pointing to the category page ({winner_url}). "
            f"Ensure the page focuses on informational intent, not transactional."
        )

    if u_type == 'commercial' and w_type == 'editorial':
        # Unusual: editorial is winning over commercial — recommend new content or restructure
        return (
            f"{urgency}NEW CONTENT / RESTRUCTURE: The editorial page is outranking the "
            f"commercial page for '{keyword}'. Create or improve a dedicated commercial/category "
            f"page that better targets transactional intent. Deoptimize this page by shifting "
            f"its keyword focus away from '{keyword}' and linking to the new target page."
        )

    # editorial vs editorial
    return (
        f"{urgency}DEOPTIMIZE: Two editorial pages compete for '{keyword}'. "
        f"Merge or consolidate content from this page into the winner ({winner_url}), "
        f"then 301 redirect this URL, or significantly rewrite this page to target a "
        f"different (complementary) keyword."
    )


def main():
    df = pd.read_excel(INPUT)
    print(f"Loaded {len(df)} rows, columns: {list(df.columns)}")

    actions = [''] * len(df)

    # Group by keyword
    for keyword, group in df.groupby('Keyword', sort=False):
        severity = group['Cannibalisation Severity'].iloc[0]

        # Deduplicate URLs per keyword: pick best (lowest) ranking per URL
        best_per_url = (
            group.groupby('URL')['Ranking']
            .min()
            .reset_index()
            .sort_values('Ranking')
        )

        winner_url = best_per_url.iloc[0]['URL']

        # Assign actions row by row
        for idx, row in group.iterrows():
            is_winner = (row['URL'] == winner_url)
            actions[idx] = build_action(row, winner_url, keyword, severity, is_winner)

    df['Action'] = actions

    # Save back
    df.to_excel(OUTPUT, index=False)
    print(f"Saved updated file to {OUTPUT}")

    # Summary stats
    optimize_count    = sum(1 for a in actions if 'OPTIMIZE:' in a and 'DEOPTIMIZE' not in a and 'NEW CONTENT' not in a)
    deoptimize_count  = sum(1 for a in actions if 'DEOPTIMIZE' in a and 'NEW CONTENT' not in a)
    new_content_count = sum(1 for a in actions if 'NEW CONTENT' in a)
    print(f"\nSummary:")
    print(f"  OPTIMIZE      : {optimize_count}")
    print(f"  DEOPTIMIZE    : {deoptimize_count}")
    print(f"  NEW CONTENT   : {new_content_count}")


if __name__ == '__main__':
    import sys
    log_path = r'C:\Users\adamc\PycharmProjects\winddataAPI\scripts\fill_actions_log.txt'
    with open(log_path, 'w', encoding='utf-8') as log:
        sys.stdout = log
        main()
        sys.stdout = sys.__stdout__
    # also print to real stdout
    with open(log_path, encoding='utf-8') as f:
        sys.__stdout__.write(f.read())

