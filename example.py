# example.py
# A small example demonstrating how to use the naive_backlink
# library to find and display a graph of related identity links.

import asyncio
import logging

from naive_backlink import crawl_and_score

# --- Configuration ---
# You can enable logging to see the crawler's progress and decisions.
# This is helpful for debugging.
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# The URL you want to investigate. A personal website, a GitHub profile,
# or a Keybase profile are all great starting points.
# We'll use the profile of a well-known open source developer.
TARGET_URL = "https://github.com/hynek"


async def main():
    """
    Main function to run the crawl, score, and print the results.
    """
    print(f"[*] Starting identity graph crawl for: {TARGET_URL}\n")

    try:
        # This is the primary API call. It handles everything:
        # - Crawling the web starting from the target URL.
        # - Finding pages that link back.
        # - Classifying links (e.g., as strong rel="me" links or weak backlinks).
        # - Calculating a final identity score.
        # The function returns a single `Result` object.
        result = await crawl_and_score(TARGET_URL)

        # --- Displaying the Results ---
        print("\n--- CRAWL COMPLETE ---")
        print(f"Final Score: {result.score} (Label: {result.label})")

        if result.errors:
            print("\n--- Errors Encountered ---")
            for error in result.errors:
                print(f"- {error}")

        if not result.evidence:
            print("\nNo backlinks were found.")
            return

        # --- Building and Printing the Link Graph ---
        print("\n--- Discovered Identity Graph ---")

        # The 'origin' is our starting point.
        origin = result.origin_url
        print(origin)

        # We'll collect all the pages that link directly back to the origin.
        # These are the "pivots" or first-hop links.
        direct_links = set()
        # We'll also collect indirect links, grouping them by the pivot they
        # were found through (e.g., Origin -> GitHub -> Twitter).
        indirect_links: dict[str, list[str]] = {}

        for evidence in result.evidence:
            if evidence.classification in ("strong", "weak"):
                direct_links.add(evidence.target.url)
            elif evidence.classification == "indirect" and evidence.notes:
                # The pivot URL is stored in the 'notes' field for indirect links.
                try:
                    pivot_url = evidence.notes.split("pivot=")[1].split(" ")[0]
                    if pivot_url not in indirect_links:
                        indirect_links[pivot_url] = []
                    indirect_links[pivot_url].append(evidence.target.url)
                except IndexError:
                    # Fallback if notes format is unexpected
                    print(f"Could not parse pivot from: {evidence.notes}")


        # Now, print the graph in a readable tree format.
        sorted_direct_links = sorted(list(direct_links))
        for i, link in enumerate(sorted_direct_links):
            is_last_direct = (i == len(sorted_direct_links) - 1)
            # Use different box-drawing characters for the last item in a list.
            direct_prefix = "└──" if is_last_direct else "├──"
            indirect_prefix = "    " if is_last_direct else "│   "

            print(f"{direct_prefix} {link}")

            # If this direct link was also a pivot for indirect links, print them.
            if link in indirect_links:
                sorted_indirect = sorted(indirect_links[link])
                for j, indirect_link in enumerate(sorted_indirect):
                    is_last_indirect = (j == len(sorted_indirect) - 1)
                    end_prefix = "└──" if is_last_indirect else "├──"
                    print(f"{indirect_prefix}{end_prefix} {indirect_link}")


    except Exception as e:
        print(f"\n[!] An unexpected error occurred: {e}")


if __name__ == "__main__":
    # The library is async, so we use asyncio.run() to start it.
    asyncio.run(main())
