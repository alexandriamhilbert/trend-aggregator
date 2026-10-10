import time
import math
import httpx
import re
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

class AllInOneTrendScorer:
    """
    Aggregates trending items across low-friction public endpoints (Wikimedia, 
    Reddit RSS/Atom, and Hacker News Firebase API), normalizes their metrics, 
    and scores them on a normalized 0-100 Trend Velocity Scale.
    """
    def __init__(self):
        self.wiki_client = httpx.Client(
            headers={"User-Agent": "TrendAnalyzerBot/1.0 (contact@example.com)"},
            timeout=12.0,
            follow_redirects=True
        )
        self.reddit_client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "application/atom+xml,application/xml,text/xml;q=0.9"
            },
            timeout=12.0,
            follow_redirects=True
        )
        self.hn_client = httpx.Client(
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=12.0,
            follow_redirects=True
        )

    # -------------------------------------------------------------------------
    # 1. NO-TOKEN DATA SOURCES
    # -------------------------------------------------------------------------

    def fetch_wikipedia_trends(self, country_code: str = "US") -> List[Dict[str, Any]]:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y/%m/%d")
        url = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top-per-country/{country_code}/all-access/{yesterday}"
        
        excluded_pages = {
            "Main Page", "Special:Search", "Wikipedia:Portada", "メインページ",
            "Wikipédia:Accueil principal", "Wikipedia:Hauptseite", "Pagina principale",
            "Заглавная страница", "Cookie (informatique)"
        }

        try:
            res = self.wiki_client.get(url)
            res.raise_for_status()
            items = res.json()["items"][0]["articles"]

            results = []
            for item in items[:40]:
                title = item["article"].replace("_", " ")
                if title in excluded_pages or title.startswith(("File:", "Special:", "Category:", "Wikipedia:", "Wikipédia:")):
                    continue

                results.append({
                    "topic": title,
                    "platform": "Wikimedia",
                    "raw_engagement": float(item["views_ceil"]),
                    "age_hours": 24.0,
                    "url": f"https://en.wikipedia.org/wiki/{item['article']}"
                })
                if len(results) >= 20:
                    break
            return results
        except Exception as e:
            print(f"[Warning] Wikimedia fetch failed: {e}")
            return []

    def fetch_reddit_hot(self, subreddit: str = "popular", limit: int = 25) -> List[Dict[str, Any]]:
        """
        Pulls hot topics from Reddit's public RSS/Atom feed. 
        Extremely reliable and bypasses the 403 / HTML captcha blocks of .json endpoints.
        """
        url = f"https://www.reddit.com/r/{subreddit}/hot.rss?limit={limit}"
        try:
            res = self.reddit_client.get(url)
            res.raise_for_status()

            # Parse Atom XML payload
            root = ET.fromstring(res.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            now = datetime.now(timezone.utc)

            results = []
            entries = root.findall("atom:entry", ns)

            for entry in entries[:limit]:
                title_elem = entry.find("atom:title", ns)
                updated_elem = entry.find("atom:updated", ns)
                link_elem = entry.find("atom:link", ns)

                title = title_elem.text if title_elem is not None else "Reddit Discussion"
                post_url = link_elem.attrib.get("href", f"https://reddit.com/r/{subreddit}") if link_elem is not None else ""

                # Estimate age from updated timestamp
                if updated_elem is not None and updated_elem.text:
                    try:
                        pub_dt = datetime.fromisoformat(updated_elem.text.replace("Z", "+00:00"))
                        age_hours = max((now - pub_dt).total_seconds() / 3600.0, 0.1)
                    except ValueError:
                        age_hours = 6.0
                else:
                    age_hours = 6.0

                # Assign standard baseline engagement score for trending RSS items
                results.append({
                    "topic": f"r/{subreddit}: {title}",
                    "platform": "Reddit",
                    "raw_engagement": 5000.0,  # Baseline weight for items surfacing on /r/popular
                    "age_hours": age_hours,
                    "url": post_url
                })

            return results
        except Exception as e:
            print(f"[Warning] Reddit fetch failed: {e}")
            return []

    def fetch_hackernews_top(self, limit: int = 20) -> List[Dict[str, Any]]:
        top_ids_url = "https://hacker-news.firebaseio.com/v0/topstories.json"
        try:
            res = self.hn_client.get(top_ids_url)
            res.raise_for_status()
            story_ids = res.json()[:limit]

            now = datetime.now(timezone.utc).timestamp()
            results = []
            for item_id in story_ids:
                item_url = f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
                item_res = self.hn_client.get(item_url)
                if item_res.status_code != 200:
                    continue

                data = item_res.json()
                if not data:
                    continue

                age_hours = max((now - data.get("time", now)) / 3600.0, 0.1)

                results.append({
                    "topic": data.get("title", ""),
                    "platform": "HackerNews",
                    "raw_engagement": float(data.get("score", 0) + (data.get("descendants", 0) * 2.0)),
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
        return engagement / math.pow(age_hours + 2.0, gravity)

    def process_and_score(self, raw_trends: List[Dict[str, Any]]) -> pd.DataFrame:
        expected_cols = ["Trend Index (0-100)", "Platform", "Topic/Title", "Raw Metric", "Age (Hours)", "url"]
        if not raw_trends:
            return pd.DataFrame(columns=expected_cols)

        df = pd.DataFrame(raw_trends)

        # 1. Calculate raw velocity score
        df["velocity_score"] = df.apply(
            lambda row: self._calculate_trend_score(row["raw_engagement"], row["age_hours"]), axis=1
        )

        # 2. Min-Max Normalize velocity WITHIN each platform group
        def min_max_scale(series):
            min_v, max_v = series.min(), series.max()
            if max_v == min_v:
                return pd.Series(50.0, index=series.index)
            return ((series - min_v) / (max_v - min_v)) * 100.0

        df["Trend Index (0-100)"] = df.groupby("platform")["velocity_score"].transform(min_max_scale)

        # 3. Clean and format
        df["Trend Index (0-100)"] = df["Trend Index (0-100)"].round(1)
        df["Age (Hours)"] = df["age_hours"].round(1)
        
        df = df.rename(columns={
            "topic": "Topic/Title",
            "platform": "Platform",
            "raw_engagement": "Raw Metric"
        })

        output_cols = ["Trend Index (0-100)", "Platform", "Topic/Title", "Raw Metric", "Age (Hours)", "url"]
        existing_cols = [c for c in output_cols if c in df.columns]
        
        return df[existing_cols].sort_values(by="Trend Index (0-100)", ascending=False).reset_index(drop=True)

    # -------------------------------------------------------------------------
    # 3. EXPORT FUNCTIONS
    # -------------------------------------------------------------------------

    @staticmethod
    def export_to_txt(df: pd.DataFrame, filename: str = "top_trends.txt"):
        if df.empty:
            print("DataFrame is empty. Nothing to export.")
            return

        with open(filename, "w", encoding="utf-8") as f:
            f.write("================ TOP TRENDS REPORT ================\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            for idx, row in df.iterrows():
                f.write(f"#{idx + 1} [{row.get('Platform', 'N/A')}] Score: {row.get('Trend Index (0-100)', 'N/A')}/100\n")
                f.write(f"    Topic: {row.get('Topic/Title', 'N/A')}\n")
                f.write(f"    Metric: {row.get('Raw Metric', 'N/A')} | Age: {row.get('Age (Hours)', 'N/A')} hrs\n")
                f.write(f"    Link: {row.get('url', 'N/A')}\n")
                f.write("-" * 60 + "\n")

        print(f"Successfully exported trend report to '{filename}'")

    # -------------------------------------------------------------------------
    # 4. MAIN RUNNER
    # -------------------------------------------------------------------------

    def get_all_trends(self) -> pd.DataFrame:
        print("Fetching trends from Wikipedia, Reddit, and Hacker News...")
        wiki_data = self.fetch_wikipedia_trends()
        reddit_data = self.fetch_reddit_hot()
        hn_data = self.fetch_hackernews_top()

        combined = wiki_data + reddit_data + hn_data
        print(f"Retrieved {len(combined)} raw trend items. Calculating scores...")
        return self.process_and_score(combined)


if __name__ == "__main__":
    aggregator = AllInOneTrendScorer()
    trends_df = aggregator.get_all_trends()

    if not trends_df.empty:
        print("\n================ TOP TRENDS RANKING ================")
        print(trends_df[["Trend Index (0-100)", "Platform", "Topic/Title", "Raw Metric", "Age (Hours)"]].head(15).to_string(index=False))

        # Export to plain text report (.txt)
        aggregator.export_to_txt(trends_df, filename="top_trends.txt")
    else:
        print("\nNo trend items retrieved across all sources.")