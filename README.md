# Multi-Platform Trend Velocity Radar

An automated, keyless trend aggregator and normalized velocity scorer built with Python and deployed as a real-time interactive dashboard on Streamlit Cloud.

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://appapppy-f2fw7kyjnnunoxtv9thxqw.streamlit.app/)

> **Live Dashboard:** [https://appapppy-f2fw7kyjnnunoxtv9thxqw.streamlit.app/](https://appapppy-f2fw7kyjnnunoxtv9thxqw.streamlit.app/)

---

## Overview

The **Trend Velocity Radar** scrapes and aggregates real-time trending topics across multiple high-traffic networks without requiring developer API keys or complex authentication tokens. 

By applying a time-decay algorithm and Min-Max normalization, it scores content on a unified 0–100 velocity index so you can easily identify what is rising fastest across the web right now.

---

## Data Sources (Zero-Token / Public APIs)

This project operates on public, low-friction HTTP endpoints:

* **Wikimedia:** Top Pageviews API (`/metrics/pageviews/top/en.wikipedia/all-access`)
* **Reddit:** Public RSS/Atom feed (`r/popular/.rss`)
* **Hacker News:** Official Firebase REST API (`/v0/topstories.json`)

---

## Scoring & Normalization Methodology

To compare different platforms (e.g., millions of Wikipedia pageviews vs. thousands of Reddit upvotes) on a single scale, the aggregator applies a two-stage calculation:

### 1. Time-Decay Velocity Score
First, raw engagement metrics are weighted against content age using a power-law decay formula:

$$\text{Velocity} = \frac{\text{Engagement}}{(\text{Age in Hours} + 2)^{1.5}}$$

### 2. Min-Max Group Normalization
Next, velocity scores are scaled per platform to a unified **0.0 to 100.0** index:

$$\text{Normalized Score} = \left( \frac{\text{Score} - \text{Min}}{\text{Max} - \text{Min}} \right) \times 100$$

---

## Repository Structure

```text
trend-aggregator/
├── trend_aggregator.py          # Core Python scraper & scoring engine
├── streamlit_app.py             # Streamlit web interface & filtering UI
├── trend_aggregator_exporter.py # CLI runner for text/CSV/JSON exports
├── requirements.txt             # Python package dependencies
├── .gitignore                   # Excludes temporary cache and data exports
└── README.md                    # Project documentation
