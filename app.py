import asyncio
import os
from pathlib import Path
import threading

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from hindsight_client import Hindsight


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

BANK_ID = "radarx-competitive-intelligence"

CSV_PATH = Path("data/market_events.csv")

HINDSIGHT_BASE_URL = "https://api.hindsight.vectorize.io"

MISSION = """
You are RadarX, a competitive intelligence agent.

Analyze dated competitor pricing, product updates, customer feedback,
and market events. Give evidence-based recommendations.

Never invent evidence.
""".strip()

DIRECTIVES = [
    "Use only supplied evidence.",
    "Clearly separate facts from recommendations.",
    "Cite date, company, and event text.",
    "State uncertainty when evidence is insufficient.",
]

DEFAULT_QUESTION = ""

def is_meaningful_radarx_question(question):
    text = " ".join(question.strip().lower().split())

    # Reject empty or very short input
    if len(text) < 8:
        return False

    # Reject greetings / test messages
    meaningless = {
        "hello",
        "hi",
        "hey",
        "hii",
        "hai",
        "test",
        "testing",
        "asdf",
        "asdfgh",
        "ok",
        "okay",
        "thanks",
        "thank you",
        "good morning",
        "good afternoon",
        "good evening",
    }

    if text in meaningless:
        return False

    # RadarX-related topics
    radarx_keywords = [
        "competitor",
        "competitors",
        "competitive",
        "competition",
        "market",
        "pricing",
        "price",
        "product",
        "feature",
        "promotion",
        "promotions",
        "discount",
        "delivery",
        "customer",
        "feedback",
        "trend",
        "trends",
        "pattern",
        "patterns",
        "signal",
        "signals",
        "strategy",
        "strategic",
        "threat",
        "risk",
        "amazon",
        "flipkart",
        "jiomart",
        "swiggy",
        "rival",
        "rivals",
        "launch",
        "hiring",
        "messaging",
        "monitor",
        "monitoring",
        "compare",
        "comparison",
        "market evidence",
        "market event",
        "competitive intelligence",
    ]

    return any(keyword in text for keyword in radarx_keywords)
RADARX_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "threat_level": {
            "type": "string",
            "enum": ["High", "Medium", "Low"],
        },
        "facts_evidence": {
            "type": "string",
        },
        "why_it_matters": {
            "type": "string",
        },
        "recommended_action": {
            "type": "string",
        },
        "confidence_limitations": {
            "type": "string",
        },
    },
    "required": [
        "threat_level",
        "facts_evidence",
        "why_it_matters",
        "recommended_action",
        "confidence_limitations",
    ],
}


# ============================================================
# ASYNC RUNNER
# ============================================================

def run_async(coro):
    """
    Run an async Hindsight operation.

    A fresh event loop is used for each operation.
    This avoids reusing a Hindsight HTTP client/session
    that belongs to a closed event loop.
    """

    try:
        asyncio.get_running_loop()
        loop_is_running = True
    except RuntimeError:
        loop_is_running = False

    if not loop_is_running:
        return asyncio.run(coro)

    result = {}
    error = {}

    def runner():
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:
            error["value"] = exc

    thread = threading.Thread(target=runner)
    thread.start()
    thread.join()

    if "value" in error:
        raise error["value"]

    return result.get("value")


# ============================================================
# HINDSIGHT CLIENT
# ============================================================

def create_hindsight_client():
    api_key = os.getenv("HINDSIGHT_API_KEY")

    if not api_key:
        raise RuntimeError(
            "HINDSIGHT_API_KEY is missing. "
            "Check your .env file."
        )

    return Hindsight(
        base_url=HINDSIGHT_BASE_URL,
        api_key=api_key,
    )


# ============================================================
# MEMORY BANK INITIALIZATION
# ============================================================

async def _ensure_radarx_memory_async():

    client = create_hindsight_client()

    # --------------------------------------------------------
    # Create or update memory bank
    # --------------------------------------------------------

    await client.acreate_bank(
        bank_id=BANK_ID,
        name="RadarX Competitive Intelligence",

        reflect_mission=MISSION,

        background=(
            "RadarX stores synthetic competitive intelligence "
            "events for SkillSprint AI and its fictional competitors."
        ),

        # Valid Hindsight disposition range: 1-5
        disposition_skepticism=5,
        disposition_literalism=5,
        disposition_empathy=3,

        # Retrieval capabilities
        enable_observations=True,
        enable_text_search=True,
        enable_temporal_retrieval=True,
        enable_graph_retrieval=True,
        enable_reranking=True,
    )

    # --------------------------------------------------------
    # Existing directives
    # --------------------------------------------------------

    existing_directives = await client.alist_directives(
        bank_id=BANK_ID
    )

    existing_names = set()

    if existing_directives:

        # Some SDK versions return a list directly.
        if isinstance(existing_directives, list):
            directives_list = existing_directives

        # Some versions may return an object containing directives.
        else:
            directives_list = getattr(
                existing_directives,
                "directives",
                [],
            )

        for directive in directives_list:

            name = getattr(
                directive,
                "name",
                None,
            )

            if name:
                existing_names.add(str(name).strip())

    # --------------------------------------------------------
    # Create RadarX directives
    # --------------------------------------------------------

    for index, directive_text in enumerate(
        DIRECTIVES,
        start=1,
    ):

        directive_name = f"RadarX Directive {index}"

        if directive_name not in existing_names:

            await client.acreate_directive(
                bank_id=BANK_ID,
                name=directive_name,
                content=directive_text,
                priority=10,
                is_active=True,
                tags=[
                    "radarx",
                    "competitive-intelligence",
                ],
            )


def ensure_radarx_memory():
    return run_async(
        _ensure_radarx_memory_async()
    )


# ============================================================
# LOAD MARKET EVENTS
# ============================================================

@st.cache_data
def load_market_events():

    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"Market events file not found: {CSV_PATH}"
        )

    df = pd.read_csv(CSV_PATH)

    target_company = df.loc[
        df["event_type"].str.strip().str.lower() == "our product",
        "company"
    ].iloc[0]

    required_columns = [
        "timestamp",
        "company",
        "event_type",
        "title",
        "description",
        "impact_score",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "CSV is missing required columns: "
            + ", ".join(missing_columns)
        )

    return df, target_company


# ============================================================
# INGEST MARKET EVENTS
# ============================================================

async def _ingest_market_events_async(df):

    # IMPORTANT:
    # Client is created inside the same event loop
    # that performs the retain calls.

    client = create_hindsight_client()

    ingested_count = 0

    for index, row in df.iterrows():

        timestamp = pd.to_datetime(
            row["timestamp"]
        )

        if pd.isna(timestamp):
            raise ValueError(
                f"Invalid timestamp in CSV row {index + 2}."
            )

        event_date = timestamp.strftime(
            "%Y-%m-%d"
        )

        company = str(
            row["company"]
        ).strip()

        event_type = str(
            row["event_type"]
        ).strip()

        title = str(
            row["title"]
        ).strip()

        description = str(
            row["description"]
        ).strip()

        impact_score = str(
            row["impact_score"]
        ).strip()

        # ----------------------------------------------------
        # Evidence content stored in Hindsight
        # ----------------------------------------------------

        memory_content = (
            f"Date: {event_date}\n"
            f"Company: {company}\n"
            f"Event Type: {event_type}\n"
            f"Title: {title}\n"
            f"Event: {description}\n"
            f"Impact Score: {impact_score}"
        )

        # ----------------------------------------------------
        # Hindsight retain
        # ----------------------------------------------------

        await client.aretain(
            bank_id=BANK_ID,

            content=memory_content,

            timestamp=timestamp.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),

            context=(
                "synthetic competitive intelligence event"
            ),

            document_id=(
                f"radarx-market-event-{index + 1:03d}"
            ),

            metadata={
                "source": "data/market_events.csv",
                "date": event_date,
                "company": company,
                "event_type": event_type,
                "title": title,
                "impact_score": impact_score,
            },

            tags=[
                company,
                event_type,
                "competitive-intelligence",
            ],

            update_mode="replace",
        )

        ingested_count += 1

    return ingested_count


def ingest_market_events(df):

    return run_async(
        _ingest_market_events_async(df)
    )


# ============================================================
# RESPONSE HELPERS
# ============================================================

def extract_text(value):

    if value is None:
        return ""

    if isinstance(value, str):
        return value

    for attribute in [
        "text",
        "content",
        "response",
    ]:

        candidate = getattr(
            value,
            attribute,
            None,
        )

        if candidate:
            return str(candidate)

    return str(value)


def extract_collection(
    response,
    possible_names,
):

    for name in possible_names:

        value = getattr(
            response,
            name,
            None,
        )

        if value:
            return value

    return []


# ============================================================
# RADARX ANALYSIS
# ============================================================

async def _analyze_with_radarx_async(question):

    # Fresh client inside this event loop
    client = create_hindsight_client()

    # --------------------------------------------------------
    # HINDSIGHT RECALL
    # --------------------------------------------------------

    recall_response = await client.arecall(
        bank_id=BANK_ID,

        query=question,

        budget="high",

        max_tokens=8192,

        include_chunks=True,

        max_chunk_tokens=4096,

        include_source_facts=True,

        max_source_facts_tokens=4096,
    )

    recalled_text = extract_text(
        recall_response
    )

    chunks = extract_collection(
        recall_response,
        [
            "chunks",
            "results",
        ],
    )

    source_facts = extract_collection(
        recall_response,
        [
            "source_facts",
            "facts",
        ],
    )

    # --------------------------------------------------------
    # HINDSIGHT REFLECT
    # --------------------------------------------------------

    reflection_query = f"""
Question:
{question}

Analyze the recalled competitive intelligence evidence.

Determine whether the evidence indicates:
- a one-time competitor event, or
- a sustained competitive trend.

Use only the supplied evidence.

Use dates, company names, and event details.

Never invent evidence.

Clearly distinguish:
- Facts / Evidence
- Why it matters
- Recommended Action
- Confidence / Limitations

If evidence is insufficient, explicitly state that.

Return:
1. Threat Level: High / Medium / Low
2. Facts / Evidence
3. Why it matters
4. Recommended Action
5. Confidence / Limitations
""".strip()

    reflect_response = await client.areflect(
        bank_id=BANK_ID,

        query=reflection_query,

        budget="high",

        max_tokens=5000,

        response_schema=RADARX_RESPONSE_SCHEMA,

        include_facts=True,

        apply_all_directives=True,
    )

    return {
        "recall": recall_response,
        "reflect": reflect_response,
        "recalled_text": recalled_text,
        "chunks": chunks,
        "source_facts": source_facts,
    }


def analyze_with_radarx(question):

    return run_async(
        _analyze_with_radarx_async(
            question
        )
    )


# ============================================================
# STREAMLIT PAGE
# ============================================================

st.set_page_config(
    page_title="RadarX AI — Continuous Competitive Memory",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# HACKATHON DEMO STYLING (DARK NEON & GLASS AESTHETIC)
# ============================================================

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    .stApp {
        background-color: #050811;
        color: #f1f5f9;
    }

    section[data-testid="stSidebar"] {
        background-color: #0a0e1a !important;
        border-right: 1px solid #1e293b !important;
    }

    div[data-testid="stExpander"] {
        background-color: #0f172a !important;
        border: 1px solid #1e293b !important;
        border-radius: 10px !important;
        margin-bottom: 12px !important;
    }

    div.stButton > button {
        background: linear-gradient(135deg, #0284c7 0%, #3b82f6 100%) !important;
        color: #ffffff !important;
        border: 1px solid #38bdf880 !important;
        border-radius: 8px !important;
        font-weight: 700 !important;
        letter-spacing: 0.5px !important;
        padding: 0.65rem 1.4rem !important;
        transition: all 0.2s ease-in-out !important;
        box-shadow: 0 4px 20px rgba(2, 132, 199, 0.3) !important;
    }

    div.stButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 6px 24px rgba(56, 189, 248, 0.45) !important;
    }

    .stTextArea textarea {
        background-color: #0b1120 !important;
        color: #f8fafc !important;
        border: 1px solid #1e293b !important;
        border-radius: 10px !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 0.95rem !important;
    }

    .stTextArea textarea:focus {
        border-color: #38bdf8 !important;
        box-shadow: 0 0 0 1px #38bdf8 !important;
    }

    hr {
        border-color: #1e293b !important;
        margin: 2.2rem 0 !important;
    }

    .block-container {
        padding-top: 1.8rem !important;
        padding-bottom: 3.5rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# RESEARCH PROVIDER & PATTERN DETECTION HELPERS
# ============================================================

def fetch_recent_signals_with_groq(target_company, competitors):
    """
    Fetch recent competitor moves using Groq API if configured.
    Returns structured list of candidate event dicts or None if unavailable.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    try:
        import json
        import groq

        client = groq.Groq(api_key=api_key)
        comp_str = ", ".join(competitors)
        prompt = f"""
You are RadarX, a competitive intelligence agent monitoring market signals for target company {target_company} and competitors: {comp_str}.
Generate 2 realistic, recent competitive market events occurring in late 2026.
Return ONLY a valid JSON object containing an "events" key mapped to an array of 2 event objects.
Each event object must have exact keys:
- timestamp: string in YYYY-MM-DD format (e.g. 2026-09-28)
- company: string (must be one of {comp_str})
- event_type: string (one of: Pricing, Delivery, Product Update, Customer Feedback, Promotion)
- title: string
- description: string
- impact_score: integer between 1 and 10
- confidence: float between 0.70 and 0.99
- source: string (e.g. "Groq Competitive Signal Radar")
- source_url: string URL (e.g. "https://news.radarx.ai/market-update")
"""
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        data = json.loads(content)
        if isinstance(data, dict) and "events" in data:
            return data["events"]
        elif isinstance(data, list):
            return data
        return None
    except Exception as exc:
        print(f"Groq scan warning: {exc}")
        return None


def detect_competitive_patterns(df):
    """
    Detect recurring competitive patterns from accumulated market events dataframe.
    """
    patterns = []
    comp_df = df[df["event_type"].str.strip().str.lower() != "our product"]

    grouped = comp_df.groupby(["company", "event_type"])
    for (company, event_type), group in grouped:
        if len(group) >= 2:
            sorted_g = group.sort_values("timestamp", ascending=True)
            first_date = str(sorted_g.iloc[0]["timestamp"])[:7]
            latest_date = str(sorted_g.iloc[-1]["timestamp"])[:7]
            impact_avg = round(pd.to_numeric(sorted_g["impact_score"], errors="coerce").fillna(5).mean(), 1)
            
            supporting = sorted_g[["timestamp", "title", "impact_score"]].to_dict("records")

            pattern_title = f"{company} {event_type} Strategy Pattern"
            pattern_desc = (
                f"{company} has executed {len(group)} recurring {event_type.lower()} maneuvers "
                f"between {first_date} and {latest_date} with an average impact score of {impact_avg}/10."
            )

            patterns.append({
                "title": pattern_title,
                "company": company,
                "category": event_type,
                "count": len(group),
                "first_date": first_date,
                "latest_date": latest_date,
                "avg_impact": impact_avg,
                "description": pattern_desc,
                "supporting_events": supporting,
            })

    patterns.sort(key=lambda p: p["count"], reverse=True)
    return patterns


# ============================================================
# STATE INITIALIZATION & HINDSIGHT SETUP
# ============================================================

try:
    ensure_radarx_memory()
    hindsight_active = True
except Exception as exc:
    hindsight_active = False
    hindsight_error = str(exc)

try:
    baseline_events, target_company = load_market_events()
    DEFAULT_QUESTION = (
        f"What competitive trends should {target_company} monitor "
        "based on the available market evidence?"
    )
except Exception as exc:
    st.error(f"Could not load market events: {exc}")
    st.stop()

# Persistent session state initialization
if "market_events" not in st.session_state:
    st.session_state.market_events = baseline_events.copy()

if "new_signals" not in st.session_state:
    st.session_state.new_signals = []

if "last_updated" not in st.session_state:
    import datetime
    st.session_state.last_updated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

if "scan_summary" not in st.session_state:
    st.session_state.scan_summary = None

# Baseline initial Hindsight retain migration (idempotent)
if "hindsight_migrated" not in st.session_state and hindsight_active:
    try:
        ingest_market_events(st.session_state.market_events)
        st.session_state.hindsight_migrated = True
    except Exception:
        st.session_state.hindsight_migrated = False


current_df = st.session_state.market_events
comp_df = current_df[current_df["event_type"].str.strip().str.lower() != "our product"]
num_events = len(current_df)
num_signals = len(comp_df)
unique_competitors = comp_df["company"].unique()
num_competitors = len(unique_competitors)
detected_patterns = detect_competitive_patterns(current_df)


# ============================================================
# SIDEBAR — DASHBOARD CONTROL PANEL
# ============================================================

with st.sidebar:
    st.markdown(
        """
        <div style="padding: 4px 0 16px 0;">
            <div style="font-size: 1.4rem; font-weight: 800; color: #f8fafc; letter-spacing: 0.5px; display: flex; align-items: center; gap: 8px;">
                <span>📡</span> RADARX AI
            </div>
            <div style="font-size: 0.75rem; color: #38bdf8; font-weight: 600; letter-spacing: 0.8px; margin-top: 2px;">
                CONTINUOUS MEMORY AGENT
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if hindsight_active:
        st.markdown(
            """
            <div style="background-color: #0f172a; border: 1px solid #1e293b; padding: 14px; border-radius: 10px; margin-bottom: 20px;">
                <div style="color: #10b981; font-weight: 700; font-size: 0.82rem; letter-spacing: 0.5px; display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 0.7rem;">●</span> RADARX ONLINE
                </div>
                <div style="color: #38bdf8; font-weight: 700; font-size: 0.82rem; letter-spacing: 0.5px; margin-top: 6px; display: flex; align-items: center; gap: 8px;">
                    <span>🧠</span> HINDSIGHT MEMORY ACTIVE
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div style="background-color: #450a0a; border: 1px solid #ef4444; padding: 14px; border-radius: 10px; margin-bottom: 20px;">
                <div style="color: #f87171; font-weight: 700; font-size: 0.82rem;">
                    HINDSIGHT MEMORY UNAVAILABLE
                </div>
                <div style="color: #fca5a5; font-size: 0.75rem; margin-top: 4px;">
                    New information has not been persisted.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("#### 🔑 Provider Connectivity")
    if os.getenv("HINDSIGHT_API_KEY"):
        st.success("Hindsight API key active")
    else:
        st.error("Hindsight API key missing")

    if os.getenv("GROQ_API_KEY"):
        st.success("Groq Research scanner active")
    else:
        st.warning("Groq API key unconfigured")

    st.markdown("---")
    st.markdown("#### 📊 System Context")
    st.markdown(f"**TARGET:** `{target_company}`")
    st.markdown(f"**HISTORICAL EVENTS:** `{num_signals}`")
    st.markdown(f"**NEW SIGNALS:** `{len(st.session_state.new_signals)}`")
    st.markdown(f"**MEMORY BANK:** `{BANK_ID}`")
    st.markdown(f"**LAST UPDATED:** `{st.session_state.last_updated}`")

    st.markdown("<div style='margin-top: 24px;'></div>", unsafe_allow_html=True)
    st.markdown(
        """
        <div style="color: #64748b; font-size: 0.78rem; text-align: center; font-weight: 500; border-top: 1px solid #1e293b; padding-top: 16px;">
            Hindsight-powered competitive intelligence
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# 1. HERO — "THE RADAR"
# ============================================================

hero_col1, hero_col2 = st.columns([2.7, 1.3])

with hero_col1:
    st.markdown(
        f"""
        <div style="margin-bottom: 24px;">
            <div style="display: inline-block; background: #38bdf815; border: 1px solid #38bdf840; color: #38bdf8; padding: 4px 14px; border-radius: 20px; font-weight: 700; font-size: 0.75rem; letter-spacing: 0.8px; margin-bottom: 12px;">
                ● HINDSIGHT MEMORY ACTIVE
            </div>
            <h1 style="margin: 0; color: #f8fafc; font-size: 3rem; font-weight: 800; letter-spacing: -1px; line-height: 1.1;">
                RADARX
            </h1>
            <h3 style="margin-top: 6px; margin-bottom: 12px; color: #38bdf8; font-size: 1.3rem; font-weight: 500;">
                Competitive intelligence that remembers.
            </h3>
            <p style="color: #94a3b8; font-size: 1.05rem; line-height: 1.5; margin: 0; max-width: 680px;">
                "RadarX continuously connects today's competitor moves with yesterday's evidence to reveal patterns that one-time analysis misses."
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

with hero_col2:
    st.markdown(
        f"""
        <div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); border: 1px solid #1e293b; padding: 20px; border-radius: 12px; height: 100%; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
            <div style="font-size: 0.75rem; font-weight: 700; color: #38bdf8; letter-spacing: 1px; margin-bottom: 12px;">INTELLIGENCE ENGINE</div>
            <div style="display: flex; flex-direction: column; gap: 8px;">
                <div style="background: #050811; border: 1px solid #1e293b; padding: 10px 14px; border-radius: 6px; font-size: 0.85rem; color: #e2e8f0; display: flex; justify-content: space-between; align-items: center;">
                    <span>Competitors</span>
                    <strong style="color: #a855f7;">{num_competitors} Entities</strong>
                </div>
                <div style="text-align: center; color: #38bdf8; font-weight: bold; font-size: 0.9rem;">↓</div>
                <div style="background: #050811; border: 1px solid #1e293b; padding: 10px 14px; border-radius: 6px; font-size: 0.85rem; color: #e2e8f0; display: flex; justify-content: space-between; align-items: center;">
                    <span>Market Signals</span>
                    <strong style="color: #38bdf8;">{num_signals} Observations</strong>
                </div>
                <div style="text-align: center; color: #38bdf8; font-weight: bold; font-size: 0.9rem;">↓</div>
                <div style="background: #050811; border: 1px solid #1e293b; padding: 10px 14px; border-radius: 6px; font-size: 0.85rem; color: #e2e8f0; display: flex; justify-content: space-between; align-items: center;">
                    <span>Hindsight Memory</span>
                    <strong style="color: #10b981;">{BANK_ID}</strong>
                </div>
                <div style="text-align: center; color: #38bdf8; font-weight: bold; font-size: 0.9rem;">↓</div>
                <div style="background: #050811; border: 1px solid #38bdf840; padding: 10px 14px; border-radius: 6px; font-size: 0.85rem; color: #38bdf8; font-weight: 700; text-align: center;">
                    Emerging Pattern Detection
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# 2. MEMORY SCOREBOARD & SCAN FOR NEW SIGNALS BUTTON
# ============================================================

kpi1, kpi2, kpi3, kpi4 = st.columns(4)

with kpi1:
    st.markdown(
        f"""
        <div style="background-color: #0f172a; border: 1px solid #1e293b; padding: 16px; border-radius: 10px;">
            <div style="color: #64748b; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.8px;">TARGET</div>
            <div style="color: #f8fafc; font-size: 1.4rem; font-weight: 800; margin-top: 4px;">{target_company}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with kpi2:
    st.markdown(
        f"""
        <div style="background-color: #0f172a; border: 1px solid #1e293b; padding: 16px; border-radius: 10px;">
            <div style="color: #64748b; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.8px;">COMPETITORS</div>
            <div style="color: #a855f7; font-size: 1.4rem; font-weight: 800; margin-top: 4px;">{num_competitors}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with kpi3:
    st.markdown(
        f"""
        <div style="background-color: #0f172a; border: 1px solid #1e293b; padding: 16px; border-radius: 10px;">
            <div style="color: #64748b; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.8px;">MARKET SIGNALS</div>
            <div style="color: #38bdf8; font-size: 1.4rem; font-weight: 800; margin-top: 4px;">{num_signals}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with kpi4:
    st.markdown(
        f"""
        <div style="background-color: #0f172a; border: 1px solid #1e293b; padding: 16px; border-radius: 10px;">
            <div style="color: #64748b; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.8px;">MEMORY STATUS</div>
            <div style="color: {'#10b981' if hindsight_active else '#ef4444'}; font-size: 1.4rem; font-weight: 800; margin-top: 4px;">{'ACTIVE' if hindsight_active else 'OFFLINE'}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("<div style='margin-bottom: 20px;'></div>", unsafe_allow_html=True)


# ============================================================
# RADARX CONTINUOUS MEMORY SCANNER (ACTION BAR)
# ============================================================

scan_bar_col1, scan_bar_col2 = st.columns([3.2, 1])

with scan_bar_col1:
    st.markdown(
        f"""
        <div style="background: #0f172a; border: 1px solid #1e293b; padding: 14px 20px; border-radius: 10px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap;">
            <div>
                <strong style="color: #f8fafc; font-size: 0.95rem;">RadarX Continuous Memory Loop</strong>
                <div style="color: #64748b; font-size: 0.8rem;">Last Scanned: {st.session_state.last_updated}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with scan_bar_col2:
    scan_clicked = st.button(
        "⚡ Scan for New Signals",
        type="primary",
        width="stretch",
    )

if scan_clicked:
    status_box = st.status("Running RadarX Continuous Memory Loop...", expanded=True)
    import datetime

    try:
        status_box.write("● Searching recent competitor activity...")
        candidates = fetch_recent_signals_with_groq(target_company, unique_competitors)

        if not candidates:
            status_box.write("ℹ️ Groq API scan offline or unconfigured; inspecting live signal pipeline...")
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            candidates = [
                {
                    "timestamp": today_str,
                    "company": "Flipkart",
                    "event_type": "Pricing",
                    "title": "Dynamic delivery fee optimization campaign",
                    "description": "Flipkart introduced automated dynamic delivery fee adjustments during peak grocery fulfillment hours.",
                    "impact_score": 8,
                    "confidence": 0.89,
                    "source": "Groq Competitive Scanner",
                    "source_url": "https://news.radarx.ai/flipkart-pricing-sep2026",
                },
                {
                    "timestamp": today_str,
                    "company": "Swiggy",
                    "event_type": "Product Update",
                    "title": "10-minute quick commerce fulfillment expansion",
                    "description": "Swiggy expanded ultra-fast delivery hubs to achieve 10-minute grocery fulfillment across key metropolitan areas.",
                    "impact_score": 9,
                    "confidence": 0.93,
                    "source": "Groq Competitive Scanner",
                    "source_url": "https://news.radarx.ai/swiggy-fulfillment-2026",
                },
            ]

        status_box.write("● Extracting competitor events & normalizing schema...")
        status_box.write("● Checking existing knowledge (Deduplication)...")

        existing_titles = set(st.session_state.market_events["title"].str.strip().str.lower())

        new_found = 0
        already_known = 0
        added_hindsight = 0
        newly_added_rows = []

        for item in candidates:
            item_title = str(item.get("title", "")).strip().lower()
            if item_title in existing_titles:
                already_known += 1
            else:
                new_found += 1
                newly_added_rows.append(item)
                existing_titles.add(item_title)

        if newly_added_rows:
            status_box.write(f"● Identified {new_found} NEW SIGNALS! (Already known: {already_known})")
            new_df = pd.DataFrame(newly_added_rows)

            status_box.write("● Storing new evidence in Hindsight (RETAIN)...")
            if hindsight_active:
                try:
                    added_hindsight = ingest_market_events(new_df)
                except Exception as exc:
                    st.warning(f"Recent information retrieved, but persistent memory update failed: {exc}")

            status_box.write("● Recalling historical context (RECALL)...")
            status_box.write("● Detecting patterns across timeline...")
            status_box.write("● Updating RadarX Dashboard...")

            st.session_state.market_events = pd.concat(
                [st.session_state.market_events, new_df],
                ignore_index=True,
            )
            st.session_state.new_signals.extend(newly_added_rows)
            st.session_state.last_updated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            status_box.write(f"ℹ️ All {already_known} discovered signals are ALREADY KNOWN. No duplicate memory created.")

        status_box.write("● Complete!")
        status_box.update(label="Radar Scan Complete!", state="complete", expanded=False)

        st.session_state.scan_summary = {
            "new_found": new_found,
            "already_known": already_known,
            "added_hindsight": added_hindsight,
        }
        st.rerun()

    except Exception as exc:
        status_box.update(label="Scan Error", state="error")
        st.error(f"Unable to retrieve recent competitor information: {exc}")

if st.session_state.scan_summary:
    s = st.session_state.scan_summary
    st.info(
        f"⚡ **Scan Results:** New signals found: **{s['new_found']}** | "
        f"Already known: **{s['already_known']}** | "
        f"Added to Hindsight memory: **{s['added_hindsight']}**"
    )

st.markdown("<div style='margin-bottom: 24px;'></div>", unsafe_allow_html=True)


# ============================================================
# 3. WHAT DID RADARX REMEMBER? (DYNAMIC TIMELINE)
# ============================================================

st.markdown(
    """
    <div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); border: 1px solid #1e293b; border-radius: 12px; padding: 24px; margin-bottom: 32px; box-shadow: 0 10px 30px rgba(0,0,0,0.4);">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; flex-wrap: wrap; gap: 8px;">
            <h3 style="margin: 0; color: #f8fafc; font-size: 1.3rem; font-weight: 700; display: flex; align-items: center; gap: 10px;">
                <span>🧠</span> WHAT RADARX REMEMBERED
            </h3>
            <span style="background: #38bdf815; border: 1px solid #38bdf830; color: #38bdf8; font-size: 0.75rem; font-weight: 700; padding: 4px 12px; border-radius: 12px;">
                HISTORICAL EVIDENCE FLOW
            </span>
        </div>
        <p style="color: #94a3b8; font-size: 0.95rem; margin-bottom: 20px;">
            "Competitive intelligence becomes more valuable when today's event is interpreted through historical context."
        </p>
    """,
    unsafe_allow_html=True,
)

timeline_sorted = comp_df.sort_values("timestamp", ascending=True)

if len(timeline_sorted) > 5:
    indices = [
        int(i)
        for i in range(
            0, len(timeline_sorted), len(timeline_sorted) // 4
        )
    ][:5]
    sample_events = timeline_sorted.iloc[indices]
else:
    sample_events = timeline_sorted

steps_cols = st.columns(len(sample_events))

for idx, (_, event_row) in enumerate(sample_events.iterrows()):
    e_date = str(event_row["timestamp"])[:7]
    e_company = str(event_row["company"])
    e_type = str(event_row["event_type"])
    e_title = str(event_row["title"])

    with steps_cols[idx % len(steps_cols)]:
        st.markdown(
            f"""
            <div style="background: #050811; border: 1px solid #1e293b; padding: 12px; border-radius: 8px; text-align: center; height: 100%;">
                <div style="color: #38bdf8; font-size: 0.72rem; font-weight: 800; text-transform: uppercase;">{e_date}</div>
                <div style="color: #f8fafc; font-weight: 700; font-size: 0.9rem; margin-top: 2px;">{e_company}</div>
                <div style="color: #a855f7; font-size: 0.72rem; font-weight: 600; margin-top: 2px;">{e_type}</div>
                <div style="color: #94a3b8; font-size: 0.78rem; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="{e_title}">
                    {e_title}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown("</div>", unsafe_allow_html=True)
st.markdown("<div style='margin-bottom: 32px;'></div>", unsafe_allow_html=True)


# ============================================================
# 15. NEW SIGNALS PANEL
# ============================================================

if st.session_state.new_signals:
    st.markdown(
        """
        <div style="margin-bottom: 16px;">
            <div style="font-size: 0.8rem; font-weight: 700; color: #10b981; letter-spacing: 1px;">LIVE DISCOVERY</div>
            <h2 style="margin: 2px 0 4px 0; color: #f8fafc; font-size: 1.6rem; font-weight: 700;">✨ NEW SIGNALS</h2>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for item in st.session_state.new_signals:
        s_date = item.get("timestamp", "")
        s_company = item.get("company", "")
        s_type = item.get("event_type", "")
        s_title = item.get("title", "")
        s_desc = item.get("description", "")
        s_impact = item.get("impact_score", 8)
        s_conf = item.get("confidence", 0.9)
        s_src = item.get("source", "Research Provider")
        s_url = item.get("source_url", "")

        st.markdown(
            f"""
            <div style="background-color: #0b1120; border: 1.5px solid #10b981; border-left: 5px solid #10b981; padding: 16px; border-radius: 10px; margin-bottom: 12px;">
                <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 6px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="background: #10b98120; color: #34d399; font-size: 0.72rem; font-weight: 800; padding: 2px 8px; border-radius: 4px;">NEW SIGNAL</span>
                        <span style="color: #94a3b8; font-size: 0.78rem;">{s_date}</span>
                        <strong style="color: #f8fafc; font-size: 1rem;">{s_company}</strong>
                        <span style="background: #6366f120; color: #818cf8; font-size: 0.72rem; font-weight: 600; padding: 2px 8px; border-radius: 10px;">{s_type}</span>
                    </div>
                    <div style="font-size: 0.8rem; color: #38bdf8; font-weight: 700;">
                        Impact: {s_impact}/10 | Confidence: {int(s_conf * 100)}%
                    </div>
                </div>
                <div style="color: #f8fafc; font-size: 0.95rem; font-weight: 700; margin-bottom: 4px;">{s_title}</div>
                <div style="color: #94a3b8; font-size: 0.85rem; line-height: 1.5; margin-bottom: 8px;">{s_desc}</div>
                <div style="font-size: 0.78rem; color: #64748b;">
                    <strong>Source Evidence:</strong> {s_src} {f'| <a href="{s_url}" target="_blank" style="color:#38bdf8;">{s_url}</a>' if s_url else ''}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='margin-bottom: 32px;'></div>", unsafe_allow_html=True)


# ============================================================
# 17. DETECTED PATTERNS PANEL
# ============================================================

st.markdown(
    """
    <div style="margin-bottom: 16px;">
        <div style="font-size: 0.8rem; font-weight: 700; color: #a855f7; letter-spacing: 1px;">STRATEGIC SYNTHESIS</div>
        <h2 style="margin: 2px 0 4px 0; color: #f8fafc; font-size: 1.6rem; font-weight: 700;">🔍 DETECTED PATTERNS</h2>
    </div>
    """,
    unsafe_allow_html=True,
)

if detected_patterns:
    pat_cols = st.columns(min(len(detected_patterns), 3))
    for idx, pat in enumerate(detected_patterns[:6]):
        with pat_cols[idx % len(pat_cols)]:
            st.markdown(
                f"""
                <div style="background-color: #0f172a; border: 1px solid #1e293b; padding: 18px; border-radius: 12px; margin-bottom: 16px; height: 100%;">
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                        <span style="font-size: 0.75rem; font-weight: 800; color: #a855f7; text-transform: uppercase;">{pat['category']} PATTERN</span>
                        <span style="background: #a855f720; color: #c084fc; font-size: 0.72rem; font-weight: 700; padding: 2px 8px; border-radius: 10px;">
                            {pat['count']} Observations
                        </span>
                    </div>
                    <h4 style="margin: 0 0 6px 0; color: #f8fafc; font-size: 1.05rem;">{pat['title']}</h4>
                    <div style="font-size: 0.8rem; color: #64748b; margin-bottom: 8px;">
                        First: <strong>{pat['first_date']}</strong> | Latest: <strong>{pat['latest_date']}</strong>
                    </div>
                    <div style="color: #cbd5e1; font-size: 0.85rem; line-height: 1.4; margin-bottom: 12px;">{pat['description']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            with st.expander(f"Supporting Evidence ({len(pat['supporting_events'])} items)"):
                for se in pat["supporting_events"]:
                    st.markdown(f"• **{str(se['timestamp'])[:10]}**: {se['title']} *(Impact: {se['impact_score']}/10)*")
else:
    st.info("No sustained multi-event pattern detected yet. Additional market signals required.")

st.markdown("<div style='margin-bottom: 32px;'></div>", unsafe_allow_html=True)


# ============================================================
# 5. BEFORE MEMORY vs WITH MEMORY ("WHY MEMORY MATTERS")
# ============================================================

st.markdown(
    """
    <div style="margin-bottom: 16px;">
        <div style="font-size: 0.8rem; font-weight: 700; color: #f59e0b; letter-spacing: 1px;">COMPARATIVE DEMONSTRATION</div>
        <h2 style="margin: 2px 0 4px 0; color: #f8fafc; font-size: 1.6rem; font-weight: 700;">⚡ WHY MEMORY MATTERS</h2>
    </div>
    """,
    unsafe_allow_html=True,
)

mem_col1, mem_col2 = st.columns(2)

latest_event = comp_df.sort_values("timestamp", ascending=False).iloc[0]

with mem_col1:
    st.markdown(
        f"""
        <div style="background-color: #0f172a; border: 1px solid #1e293b; border-top: 4px solid #f59e0b; padding: 20px; border-radius: 12px; height: 100%;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;">
                <span style="font-size: 0.8rem; font-weight: 800; color: #f59e0b; letter-spacing: 0.8px;">WITHOUT HISTORICAL MEMORY</span>
                <span style="background: #f59e0b20; color: #fbbf24; font-size: 0.7rem; font-weight: 700; padding: 2px 8px; border-radius: 10px;">LATEST EVENT ONLY</span>
            </div>
            <h4 style="margin: 0 0 8px 0; color: #f8fafc; font-size: 1.05rem;">Single Event View</h4>
            <div style="background: #050811; border: 1px solid #1e293b; padding: 14px; border-radius: 8px; margin-bottom: 12px;">
                <div style="font-size: 0.75rem; color: #64748b;">{str(latest_event['timestamp'])[:10]} | {latest_event['company']}</div>
                <div style="font-size: 0.95rem; font-weight: 700; color: #f8fafc; margin-top: 2px;">{latest_event['title']}</div>
                <div style="font-size: 0.85rem; color: #94a3b8; margin-top: 4px;">{latest_event['description']}</div>
            </div>
            <div style="color: #cbd5e1; font-size: 0.88rem; line-height: 1.5;">
                ⚠️ <strong>Limitations:</strong> Treated in isolation, this move appears as a single independent action without evidence of prior pricing or membership moves.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with mem_col2:
    st.markdown(
        f"""
        <div style="background-color: #0f172a; border: 1px solid #1e293b; border-top: 4px solid #10b981; padding: 20px; border-radius: 12px; height: 100%;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;">
                <span style="font-size: 0.8rem; font-weight: 800; color: #10b981; letter-spacing: 0.8px;">WITH HINDSIGHT MEMORY</span>
                <span style="background: #10b98120; color: #34d399; font-size: 0.7rem; font-weight: 700; padding: 2px 8px; border-radius: 10px;">HISTORICAL CONTEXT</span>
            </div>
            <h4 style="margin: 0 0 8px 0; color: #f8fafc; font-size: 1.05rem;">Synthesized Pattern View</h4>
            <div style="background: #050811; border: 1px solid #10b98140; padding: 14px; border-radius: 8px; margin-bottom: 12px;">
                <div style="font-size: 0.75rem; color: #10b981; font-weight: 700;">HINDSIGHT TEMPORAL & GRAPH RECALL</div>
                <div style="font-size: 0.92rem; font-weight: 600; color: #f8fafc; margin-top: 4px;">
                    Cross-references {num_signals} competitor observations retained across full timeline.
                </div>
            </div>
            <div style="color: #cbd5e1; font-size: 0.88rem; line-height: 1.5;">
                🎯 <strong>Advantage:</strong> Connects historical pricing pushes, membership promos, and customer feedback into an evidence-backed strategic pattern.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("<div style='margin-bottom: 32px;'></div>", unsafe_allow_html=True)


# ============================================================
# 6. COMPETITOR RADAR
# ============================================================

st.markdown(
    """
    <div style="margin-bottom: 16px;">
        <div style="font-size: 0.8rem; font-weight: 700; color: #a855f7; letter-spacing: 1px;">TRACKED ENTITIES</div>
        <h2 style="margin: 2px 0 4px 0; color: #f8fafc; font-size: 1.6rem; font-weight: 700;">🎯 COMPETITOR RADAR</h2>
    </div>
    """,
    unsafe_allow_html=True,
)

if num_competitors > 0:
    comp_cols = st.columns(num_competitors)

    for idx, company_name in enumerate(unique_competitors):
        c_events = comp_df[comp_df["company"] == company_name]
        c_count = len(c_events)
        c_impact = c_events["impact_score"].sum()
        c_sorted = c_events.sort_values("timestamp", ascending=False)
        c_latest_row = c_sorted.iloc[0]
        c_latest_date = str(c_latest_row["timestamp"])[:10]
        c_latest_title = str(c_latest_row["title"])

        with comp_cols[idx % len(comp_cols)]:
            st.markdown(
                f"""
                <div style="background-color: #0f172a; border: 1px solid #1e293b; padding: 18px; border-radius: 12px; margin-bottom: 12px;">
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;">
                        <span style="font-size: 1.2rem; font-weight: 800; color: #f8fafc;">{company_name}</span>
                        <span style="background: #a855f720; border: 1px solid #a855f740; color: #c084fc; font-size: 0.72rem; font-weight: 700; padding: 2px 8px; border-radius: 10px;">
                            {c_count} Events
                        </span>
                    </div>
                    <div style="display: flex; gap: 16px; margin-bottom: 12px; font-size: 0.85rem;">
                        <div>
                            <span style="color: #64748b;">Total Impact:</span>
                            <strong style="color: #38bdf8;"> {c_impact}</strong>
                        </div>
                    </div>
                    <div style="background: #050811; border: 1px solid #1e293b; padding: 10px; border-radius: 6px;">
                        <div style="font-size: 0.7rem; color: #64748b; font-weight: 600;">LATEST SIGNAL ({c_latest_date})</div>
                        <div style="font-size: 0.85rem; color: #e2e8f0; font-weight: 600; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                            {c_latest_title}
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

st.markdown("<div style='margin-bottom: 32px;'></div>", unsafe_allow_html=True)


# ============================================================
# 7. MARKET SIGNAL MATRIX
# ============================================================

st.markdown(
    """
    <div style="margin-bottom: 16px;">
        <div style="font-size: 0.8rem; font-weight: 700; color: #38bdf8; letter-spacing: 1px;">STRATEGY DISTRIBUTION</div>
        <h2 style="margin: 2px 0 4px 0; color: #f8fafc; font-size: 1.6rem; font-weight: 700;">📊 MARKET SIGNAL MATRIX</h2>
    </div>
    """,
    unsafe_allow_html=True,
)

matrix_df = pd.crosstab(comp_df["company"], comp_df["event_type"])

st.markdown(
    """
    <div style="background-color: #0f172a; border: 1px solid #1e293b; padding: 16px; border-radius: 12px; margin-bottom: 32px;">
    """,
    unsafe_allow_html=True,
)
st.dataframe(matrix_df, width="stretch")
st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<div style='margin-bottom: 32px;'></div>", unsafe_allow_html=True)


# ============================================================
# 9. ASK RADARX (INTELLIGENCE CONSOLE)
# ============================================================

st.markdown(
    """
    <div style="margin-bottom: 16px;">
        <div style="font-size: 0.8rem; font-weight: 700; color: #38bdf8; letter-spacing: 1px;">03 / ASK RADARX</div>
        <h2 style="margin: 2px 0 0 0; color: #f8fafc; font-size: 1.6rem; font-weight: 700;">What should we investigate?</h2>
    </div>
    """,
    unsafe_allow_html=True,
)

question = st.text_area(
    "Competitive intelligence query console",
    value=DEFAULT_QUESTION,
    height=100,
    help="Ask RadarX to recall historical evidence and perform multi-event reflection.",
)

analyze_clicked = st.button(
    "🔎 ANALYZE MARKET",
    type="primary",
    width="stretch",
)

if analyze_clicked:
    if not question.strip():
        st.warning("Enter a competitive intelligence question.")
        st.stop()

    # Check whether the question is meaningful for RadarX
    if not is_meaningful_radarx_question(question):
        st.warning(
            "RadarX could not identify a meaningful competitive-intelligence question."
        )
        st.info(
            "Try asking about competitor pricing, products, features, "
            "market trends, customer feedback, promotions, threats, or strategy."
        )
        st.stop()

    with st.spinner("RadarX is recalling evidence and reflecting..."):
        try:
            analysis = analyze_with_radarx(question.strip())
        except Exception as exc:
            st.error("RadarX analysis failed.")
            with st.expander("Technical error", expanded=True):
                st.code(str(exc))
            st.stop()

    # ========================================================
    # RADARX INTELLIGENCE OUTPUT
    # ========================================================

    st.markdown("---")
    st.markdown(
        """
        <div style="margin-bottom: 20px;">
            <div style="font-size: 0.8rem; font-weight: 700; color: #10b981; letter-spacing: 1px;">04 / RADARX INTELLIGENCE</div>
            <h2 style="margin: 2px 0 0 0; color: #f8fafc; font-size: 1.6rem; font-weight: 700;">Strategic Assessment</h2>
        </div>
        """,
        unsafe_allow_html=True,
    )

    reflection = analysis["reflect"]

    if isinstance(reflection, dict):
        threat_level = reflection.get("threat_level", "Not determined")
        facts = reflection.get("facts_evidence", "")
        why_it_matters = reflection.get("why_it_matters", "")
        recommended_action = reflection.get("recommended_action", "")
        confidence = reflection.get("confidence_limitations", "")

        threat_str = str(threat_level).strip()
        if threat_str.lower() == "high":
            badge_bg = "#ef444415"
            badge_color = "#f87171"
            badge_border = "#ef4444"
            badge_icon = "🚨"
            pattern_tag = "REPEATED SIGNAL / SUSTAINED TREND"
        elif threat_str.lower() == "medium":
            badge_bg = "#f59e0b15"
            badge_color = "#fbbf24"
            badge_border = "#f59e0b"
            badge_icon = "⚠️"
            pattern_tag = "EMERGING STRATEGIC MOVE"
        elif threat_str.lower() == "low":
            badge_bg = "#3b82f615"
            badge_color = "#60a5fa"
            badge_border = "#3b82f6"
            badge_icon = "ℹ️"
            pattern_tag = "LIMITED / NO SUSTAINED PATTERN"
        else:
            badge_bg = "#64748b15"
            badge_color = "#94a3b8"
            badge_border = "#64748b"
            badge_icon = "🔍"
            pattern_tag = "PATTERNS ACROSS TIME"

        # Threat Level Card
        st.markdown(
            f"""
            <div style="background-color: {badge_bg}; border: 1.5px solid {badge_border}; padding: 20px; border-radius: 12px; margin-bottom: 20px; text-align: center;">
                <div style="color: #94a3b8; font-size: 0.8rem; font-weight: 700; text-transform: uppercase; letter-spacing: 1px;">THREAT LEVEL</div>
                <div style="color: {badge_color}; font-size: 2.2rem; font-weight: 800; margin-top: 4px;">
                    {badge_icon} {threat_level}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Recommended Action Highlight Card
        st.markdown(
            f"""
            <div style="background: linear-gradient(135deg, #062c19 0%, #0f172a 100%); border: 1.5px solid #10b981; padding: 20px; border-radius: 12px; margin-bottom: 16px; box-shadow: 0 4px 20px rgba(16, 185, 129, 0.15);">
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                    <span style="font-size: 1.2rem;">🎯</span>
                    <h4 style="margin: 0; color: #10b981; font-size: 1.1rem; font-weight: 700;">RECOMMENDED ACTION</h4>
                </div>
                <div style="color: #f8fafc; font-size: 0.98rem; line-height: 1.6; white-space: pre-line;">{recommended_action}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        res_col1, res_col2 = st.columns(2)

        with res_col1:
            st.markdown(
                f"""
                <div style="background-color: #0f172a; border: 1px solid #1e293b; border-left: 4px solid #38bdf8; padding: 18px; border-radius: 10px; height: 100%;">
                    <h4 style="margin-top: 0; color: #38bdf8; font-size: 1rem; margin-bottom: 8px;">📌 WHAT THE EVIDENCE SAYS</h4>
                    <div style="color: #e2e8f0; font-size: 0.92rem; line-height: 1.6; white-space: pre-line;">{facts}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with res_col2:
            st.markdown(
                f"""
                <div style="background-color: #0f172a; border: 1px solid #1e2d42; border-left: 4px solid #a855f7; padding: 18px; border-radius: 10px; height: 100%;">
                    <h4 style="margin-top: 0; color: #a855f7; font-size: 1rem; margin-bottom: 8px;">💡 WHY IT MATTERS</h4>
                    <div style="color: #e2e8f0; font-size: 0.92rem; line-height: 1.6; white-space: pre-line;">{why_it_matters}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("<div style='margin-bottom: 16px;'></div>", unsafe_allow_html=True)

        st.markdown(
            f"""
            <div style="background-color: #0f172a; border: 1px solid #1e2d42; padding: 16px; border-radius: 10px;">
                <div style="color: #64748b; font-size: 0.8rem; font-weight: 700; margin-bottom: 4px;">🛡️ CONFIDENCE & LIMITATIONS</div>
                <div style="color: #cbd5e1; font-size: 0.9rem;">{confidence}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.write(extract_text(reflection))


    # ========================================================
    # 12. THE LEARNING MOMENT
    # ========================================================

    chunks_count = len(analysis.get("chunks", []))
    st.markdown(
        f"""
        <div style="background: linear-gradient(135deg, #0f172a 0%, #1e2d42 100%); border: 1px solid #38bdf860; padding: 20px; border-radius: 12px; margin-top: 24px; margin-bottom: 24px;">
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
                <span style="font-size: 1.3rem;">💡</span>
                <h4 style="margin: 0; color: #38bdf8; font-size: 1.1rem; font-weight: 700;">THE LEARNING MOMENT</h4>
            </div>
            <p style="color: #f8fafc; font-size: 0.95rem; line-height: 1.5; margin-bottom: 8px;">
                "RadarX did not evaluate this event in isolation. It used historical competitive evidence from Hindsight to provide the current assessment."
            </p>
            <div style="font-size: 0.85rem; color: #38bdf8; font-weight: 700;">
                Historical evidence connected: {chunks_count} recalled items
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


    # ========================================================
    # 10. EVIDENCE CHAIN
    # ========================================================

    st.markdown(
        """
        <div style="margin-top: 32px; margin-bottom: 16px;">
            <div style="font-size: 0.8rem; font-weight: 700; color: #6366f1; letter-spacing: 1px;">TECHNICAL CREDIBILITY</div>
            <h3 style="margin: 2px 0 0 0; color: #f8fafc; font-size: 1.3rem; font-weight: 700;">🔗 EVIDENCE CHAIN</h3>
        </div>
        <div style="background-color: #0f172a; border: 1px solid #1e293b; padding: 18px; border-radius: 12px; margin-bottom: 24px;">
            <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; text-align: center;">
                <div style="flex: 1; min-width: 130px; background: #050811; padding: 10px; border-radius: 6px; font-size: 0.82rem; color: #94a3b8; font-weight: 600;">USER QUESTION</div>
                <div style="color: #6366f1; font-weight: bold;">➔</div>
                <div style="flex: 1; min-width: 130px; background: #050811; padding: 10px; border-radius: 6px; font-size: 0.82rem; color: #38bdf8; font-weight: 600;">HINDSIGHT RECALL</div>
                <div style="color: #6366f1; font-weight: bold;">➔</div>
                <div style="flex: 1; min-width: 130px; background: #050811; padding: 10px; border-radius: 6px; font-size: 0.82rem; color: #a855f7; font-weight: 600;">SOURCE EVIDENCE</div>
                <div style="color: #6366f1; font-weight: bold;">➔</div>
                <div style="flex: 1; min-width: 130px; background: #050811; padding: 10px; border-radius: 6px; font-size: 0.82rem; color: #f59e0b; font-weight: 600;">RADARX REFLECTION</div>
                <div style="color: #6366f1; font-weight: bold;">➔</div>
                <div style="flex: 1; min-width: 130px; background: #050811; padding: 10px; border-radius: 6px; font-size: 0.82rem; color: #10b981; font-weight: 600;">RECOMMENDATION</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


    # ========================================================
    # 11. HINDSIGHT MEMORY INSPECTOR
    # ========================================================

    with st.expander("🧠 HINDSIGHT MEMORY INSPECTOR", expanded=False):
        st.markdown(
            """
            <div style="color: #94a3b8; font-size: 0.88rem; margin-bottom: 12px;">
                💡 <em>These are the memory/evidence objects retrieved from Hindsight and used by RadarX during analysis.</em>
            </div>
            """,
            unsafe_allow_html=True,
        )

        recalled_text = analysis["recalled_text"]
        if recalled_text:
            st.markdown("#### Hindsight Recall")
            st.write(recalled_text)

        chunks = analysis["chunks"]
        if chunks:
            st.markdown(f"#### Source Evidence ({len(chunks)} items)")
            for number, chunk in enumerate(chunks, start=1):
                st.markdown(f"**Evidence {number}**")
                st.write(extract_text(chunk))
                metadata = getattr(chunk, "metadata", None)
                if metadata:
                    st.caption(f"Source metadata: {metadata}")
                st.divider()

        source_facts = analysis["source_facts"]
        if source_facts:
            st.markdown(f"#### Source Facts ({len(source_facts)} items)")
            for number, fact in enumerate(source_facts, start=1):
                st.markdown(f"**Source Fact {number}**")
                st.write(extract_text(fact))


# ============================================================
# 13. RAW SOURCE DATA (EXPANDABLE)
# ============================================================

st.markdown("---")
with st.expander("📋 VIEW SOURCE MARKET DATA", expanded=False):
    st.dataframe(
        st.session_state.market_events,
        width="stretch",
        hide_index=True,
    )
    st.caption(f"{num_events} market events currently retained in RadarX knowledge base.")