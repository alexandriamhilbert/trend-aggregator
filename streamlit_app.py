import streamlit as st
import pandas as pd
from trend_aggregator import AllInOneTrendScorer

st.set_page_config(page_title="Real-Time Trend Radar", page_icon="📈", layout="wide")

st.title("📈 Multi-Platform Trend Velocity Radar")
st.markdown("Real-time trending topics scored and normalized across **Wikimedia**, **Reddit**, and **Hacker News**.")

@st.cache_data(ttl=1800)  # Cache trends for 30 minutes to reduce API calls
def load_data():
    aggregator = AllInOneTrendScorer()
    return aggregator.get_all_trends()

with st.spinner("Fetching latest trends across networks..."):
    df = load_data()

if not df.empty:
    # Sidebar Filters
    st.sidebar.header("Filter Options")
    selected_platforms = st.sidebar.multiselect(
        "Platforms",
        options=df["Platform"].unique(),
        default=df["Platform"].unique()
    )
    
    filtered_df = df[df["Platform"].isin(selected_platforms)]

    # Metrics Summary
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Stories", len(filtered_df))
    col2.metric("Top Platform", filtered_df.iloc[0]["Platform"] if not filtered_df.empty else "N/A")
    col3.metric("Peak Score", f"{filtered_df['Trend Index (0-100)'].max()}/100" if not filtered_df.empty else "0")

    st.subheader("Top Ranked Trends")

    # Interactive Table Display
    st.dataframe(
        filtered_df,
        column_config={
            "url": st.column_config.LinkColumn("Story Link", display_text="Open Link"),
            "Trend Index (0-100)": st.column_config.ProgressColumn(
                "Velocity Score",
                format="%.1f",
                min_value=0,
                max_value=100,
            ),
        },
        hide_index=True,
        use_container_width=True
    )
else:
    st.warning("No trend data retrieved.")