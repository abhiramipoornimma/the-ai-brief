import logging
import os

from dotenv import load_dotenv
from google import genai

from news import (
    initialize_database,
    fetch_all_sources,
    remove_duplicates,
    filter_previously_seen,
)
from report import generate_story_content

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing from .env")

    initialize_database()
    all_stories = fetch_all_sources()
    unique_stories = remove_duplicates(all_stories)
    new_stories = filter_previously_seen(unique_stories)

    print(f"Stories collected: {len(all_stories)}")
    print(f"After duplicate removal: {len(unique_stories)}")
    print(f"Not previously recorded: {len(new_stories)}")

    # Test with a new story if available. Otherwise use a known story only
    # for testing; this script never marks any story as seen.
    if new_stories:
        story = new_stories[0]
        print("\nTesting with a new story.")
    elif unique_stories:
        story = unique_stories[0]
        print("\nNo new stories; testing with an existing story without saving it.")
    else:
        print("\nNo stories could be fetched from the configured RSS sources.")
        return

    print(f"\nOriginal headline: {story['title']}")
    print(f"Source: {story['source']}")
    print(f"Published: {story['published']}")
    print(f"Link: {story['link']}")

    client = genai.Client(api_key=api_key)
    generated = generate_story_content(story, client)
    print("\n--- Generated story content ---\n")
    print(generated)
    print("\nTest complete. No stories were marked as seen.")


if __name__ == "__main__":
    main()
