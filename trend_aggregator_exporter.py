import time
import math
import httpx
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

class AllInOneTrendScorer:
    """
    Aggregates trending items across Wikimedia, Reddit (public JSON), and Hacker News,
    normalizes their metrics, and scores them on a normalized 0-100 Trend Velocity Scale.
    """
    def __init__(self, user_agent: str = "MultiTrendScorer/1.0 (contact@example.com)"):
        self.headers = {"User-Agent": user_agent}
        self.client = httpx.Client(headers=self.headers, timeout=12.0)

    # -------------------------------------------------------------------------
    # 1. DATA SOURCES
    # -------------------------------------------------------------------------

    def fetch_wikipedia_trends(self, country_code: str = "US") -> List[Dict[str, Any]]:
        """
        Fetches top-viewed Wikipedia pages for yesterday (latest available aggregate).
        Requires ZERO API key setup.
        """
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y/%m/%d")
        url = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top-per-country/{country_code}/all-access/{yesterday}"
        
        try:
            res = self.client.get(url)
            res.raise_for_status()
            items = res.json()["items"][0]["articles"]

            results = []
            for item in items[:25]:
                title = item["article"].replace("_", " ")
                # Ignore generic meta-pages
                if title in ["Main Page", "Special:Search"] or title.startswith("File:"):
                    continue

                results.append({
                    "topic": title,
                    "platform": "Wikimedia",
                    "raw_engagement": item["views_ceil"],  # Total daily pageviews
                    "age_hours": 24.0,                      # 24-hour aggregate window
                    "url": f"https://en.wikipedia.org/wiki/{item['article']}"
                })
            return results
        except Exception as e:
            print(f"[Warning] Wikimedia fetch failed: {e}")
            return []

    def fetch_reddit_hot(self, subreddit: str = "popular", limit: int = 25) -> List[Dict[str, Any]]:
        """
        Pulls top hot discussions from Reddit via public JSON endpoints without needing full OAuth.
        """
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
        try:
            res = self.client.get(url)
            res.raise_for_status()
            posts = res.json()["data"]["children"]

            now = datetime.now(timezone.utc).timestamp()
            results = []
            for post in posts:
                data = post["data"]
                if data.get("stickied"):
                    continue

                created_utc = data.get("created_utc", now)
                age_hours = max((now - created_utc) / 3600.0, 0.1)

                results.append({
                    "topic": f"r/{data.get('subreddit')}: {data.get('title')}",
                    "platform": "Reddit",
                    "raw_engagement": data.get("score", 0) + (data.get("num_comments", 0) * 1.5), # Upvotes + weighted comments
                    "age_hours": age_hours,
                    "url": f"https://reddit.com{data.get('permalink')}"
                })
            return results
        except Exception as e:
            print(f"[Warning] Reddit fetch failed: {e}")
            return []

    def fetch_hackernews_top(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Pulls top engineering and tech trends from Firebase Hacker News API.
        Requires ZERO authentication.
        """
        top_ids_url = "https://hacker-news.firebaseio.com/v0/topstories.json"
        try:
            res = self.client.get(top_ids_url)
            res.raise_for_status()
            story_ids = res.json()[:limit]

            now = datetime.now(timezone.utc).timestamp()
            results = []
            for item_id in story_ids:
                item_url = f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
                item_res = self.client.get(item_url)
                if item_res.status_code != 200:
                    continue

                data = item_res.json()
                age_hours = max((now - data.get("time", now)) / 3600.0, 0.1)

                results.append({
                    "topic": data.get("title", ""),
                    "platform": "HackerNews",
                    "raw_engagement": data.get("score", 0) + (data.get("descendants", 0) * 2.0),
                    "age_hours": age_hours,
                    "url": data.get("url") or f"https://news.ycombinator.com/item?id={item_id}"
                })
            return results
        except Exception as e:
            print(f"[Warning] Hacker News fetch failed: {e}")
            return []

    # -------------------------------------------------------------------------
    # 2. SCORING & NORMALIZATION ENGINE
    # -------------------------------------------------------------------------

    def _calculate_trend_score(self, engagement: float, age_hours: float, gravity: float = 1.5) -> float:
        """
        Hacker News-style decay formula to score raw momentum:
        Velocity = (Engagement) / (Age + 2)^gravity
        """
        return engagement / math.pow(age_hours + 2.0, gravity)

    def process_and_score(self, raw_trends: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        Calculates velocity scores and normalizes them platform-by-platform to a 0-100 relative index.
        """
        if not raw_trends:
            return pd.DataFrame()

        df = pd.DataFrame(raw_trends)

        # 1. Calculate raw velocity per post/article
        df["velocity_score"] = df.apply(
            lambda row: self._calculate_trend_score(row["raw_engagement"], row["age_hours"]), axis=1
        )

        # 2. Min-Max Normalize velocity WITHIN each platform (scale to 0–100)
        def normalize_group(group):
            min_v = group["velocity_score"].min()
            max_v = group["velocity_score"].max()
            if max_v == min_v:
                group["Trend Index (0-100)"] = 50.0
            else:
                group["Trend Index (0-100)"] = ((group["velocity_score"] - min_v) / (max_v - min_v)) * 100
            return group

        df = df.groupby("platform", group_keys=False).apply(normalize_group)

        # 3. Clean and sort output table
        df["Trend Index (0-100)"] = df["Trend Index (0-100)"].round(1)
        df["Age (Hours)"] = df["age_hours"].round(1)
        df = df.rename(columns={"topic": "Topic/Title", "platform": "Platform", "raw_engagement": "Raw Metric"})
        
        output_cols = ["Trend Index (0-100)", "Platform", "Topic/Title", "Raw Metric", "Age (Hours)", "url"]
        return df[output_cols].sort_values(by="Trend Index (0-100)", ascending=False).reset_index(drop=True)

    # -------------------------------------------------------------------------
    # 3. MAIN RUNNER
    # -------------------------------------------------------------------------

    def get_all_trends(self) -> pd.DataFrame:
        print("Fetching trends from Wikipedia, Reddit, and Hacker News...")
        wiki_data = self.fetch_wikipedia_trends()
        reddit_data = self.fetch_reddit_hot()
        hn_data = self.fetch_hackernews_top()

        combined = wiki_data + reddit_data + hn_data
        print(f"Retrieved {len(combined)} raw trend items. Calculating scores...")
        return self.process_and_score(combined)

    # -------------------------------------------------------------------------
    # 4. EXPORT UTILITIES
    # -------------------------------------------------------------------------

    @staticmethod
    def export_to_txt(df: pd.DataFrame, filename: str = "trending_summary.txt", top_n: int = 25) -> None:
        """
        Exports the top N trends into a clean, human-readable text document (.txt).
        """
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        top_df = df.head(top_n)

        lines = [
            "=" * 60,
            f"             TOP TRENDS REPORT - {now_str}",
            "=" * 60,
            ""
        ]

        for idx, row in top_df.iterrows():
            lines.append(f"#{idx + 1:02d} [{row['Platform']}] Score: {row['Trend Index (0-100)']}/100")
            lines.append(f"    Topic: {row['Topic/Title']}")
            lines.append(f"    Age: {row['Age (Hours)']} hrs | Raw Metric: {int(row['Raw Metric']):,}")
            lines.append(f"    URL: {row['url']}")
            lines.append("-" * 60)

        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        print(f"Successfully saved text report to '{filename}'!")

    @staticmethod
    def export_to_csv(df: pd.DataFrame, filename: str = "trending_summary.csv") -> None:
        """
        Exports the dataframe to a CSV file for Excel/Google Sheets.
        """
        df.to_csv(filename, index=False)
        print(f"Successfully saved CSV report to '{filename}'!")


if __name__ == "__main__":
    aggregator = AllInOneTrendScorer()
    trends_df = aggregator.get_all_trends()

    # Display Top 15 Trends across all sources in terminal
    print("\n================ TOP TRENDS RANKING ================")
    print(trends_df[["Trend Index (0-100)", "Platform", "Topic/Title", "Raw Metric", "Age (Hours)"]].head(15).to_string(index=False))

    # --- Exporting Data ---
    # 1. Export as clean human-readable Text File
    AllInOneTrendScorer.export_to_txt(trends_df, filename="top_trends.txt", top_n=25)

    # 2. Export as CSV (optional, great for spreadsheets)
    AllInOneTrendScorer.export_to_csv(trends_df, filename="top_trends.csv")