import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
st.set_page_config(page_title="SamPhase Advanced Analytics", layout="wide")
st.title("SamPhase Global Operations Dashboard")
st.markdown("Deep-dive data extraction and cross-filtering engine.")

try:
    df = pd.read_sql("SELECT * FROM reports", con=engine)
except Exception:
    df = pd.DataFrame()

if df.empty:
    st.warning("No data found in the database. Please submit reports in the main portal first.")
else:
    # MULTI-SITE / DEPARTMENT FILTERING
    st.sidebar.header("Global Filters")
    selected_site = st.sidebar.multiselect("Filter by Department:", options=df['site_location'].unique(), default=df['site_location'].unique())
    selected_status = st.sidebar.multiselect("Filter by Status:", options=df['status'].unique(), default=df['status'].unique())
    
    filtered_df = df[(df['site_location'].isin(selected_site)) & (df['status'].isin(selected_status))]
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Filtered Entries", len(filtered_df))
    col2.metric("Open Concerns", len(filtered_df[filtered_df['status'] == 'Open']))
    col3.metric("Escalations", len(filtered_df[filtered_df['escalation_level'] > 0]))
    col4.metric("Active Pilots", len(filtered_df[filtered_df['is_pilot'] == True]))
    st.divider()

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Reports by Department")
        site_counts = filtered_df['site_location'].value_counts()
        st.bar_chart(site_counts, color="#4f46e5")
        
    with c2:
        st.subheader("Tiered Escalation Matrix")
        escalation_counts = filtered_df['escalation_level'].value_counts().sort_index()
        st.bar_chart(escalation_counts, color="#e11d48")

    st.divider()
    st.subheader("Root Cause Analysis (RCA) Extractor")
    rca_df = filtered_df.dropna(subset=['rca_5'])
    st.dataframe(rca_df[['id', 'site_location', 'report_type', 'title', 'rca_5', 'action_plan']])
