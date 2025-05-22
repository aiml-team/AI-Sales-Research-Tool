import os
import re
import requests
import streamlit as st
from dotenv import load_dotenv
from PIL import Image
from bs4 import BeautifulSoup
from langchain.prompts import PromptTemplate
from langchain_openai import AzureChatOpenAI
from langchain.agents import initialize_agent, Tool
from langchain.agents.agent_types import AgentType
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_tavily import TavilySearch
from langchain_community.utilities import SerpAPIWrapper
from fill_template import fill_word_template

# -------------------------
# Load environment variables from .env file
load_dotenv()

# Set Azure API Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION")

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# -------------------------
# Google Fallback
def google_search(query):
    search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(search_url, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")
    for g in soup.find_all('div', class_='tF2Cxc'):
        link = g.find('a')['href']
        return link
    return None

# -------------------------
# Scraper
def scrape_company_website(company_name):
    company_info = {
        "company_name": company_name,
        "address": "",
        "employee_count": "",
        "annual_revenue": "",
        "leadership_changes": "",
        "recent_news": "",
        "recent_funding": "",
        "current_erp": "",
        "recent_sap_job_postings": "",
        "phone_number": "",
        "sic_codes": "",
        "company_official_website": "",
        "strengths": "",
        "weaknesses": "",
        "opportunities": "",
        "threats": ""
    }

    company_website = google_search(f"{company_name} official site")
    if not company_website:
        return company_info

    try:
        response = requests.get(company_website, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(separator=" ", strip=True)

        phone_match = re.search(r'(\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9})', text)
        if phone_match:
            company_info["phone_number"] = phone_match.group(0)

        address_match = re.search(r'\d{1,5}\s[\w\s.,-]+,\s\w+,\s[A-Z]{2}\s\d{5}(-\d{4})?', text)
        if address_match:
            company_info["address"] = address_match.group(0)

        emp_match = re.search(r'([0-9,]+)\s+(employees|staff|workers|team)', text, re.I)
        if emp_match:
            company_info["employee_count"] = emp_match.group(1).replace(',', '')

        revenue_match = re.search(r'(revenue|annual revenue|sales|turnover)[\s\w]{0,20}?\$?([\d,.]+)\s?(million|billion)?', text, re.I)
        if revenue_match:
            rev_num = revenue_match.group(2).replace(',', '')
            rev_unit = revenue_match.group(3) or ''
            company_info["annual_revenue"] = f"${rev_num} {rev_unit}".strip()

        leadership_snippets = [line.strip() for line in text.split('.') if any(word in line.lower() for word in ['ceo', 'appointed', 'named', 'joined', 'leadership'])]
        company_info["leadership_changes"] = ' '.join(leadership_snippets[:3])

        news_snippets = [line.strip() for line in text.split('.') if any(word in line.lower() for word in ['news', 'announcement', 'press release', 'update'])]
        company_info["recent_news"] = ' '.join(news_snippets[:3])

        funding_match = re.search(r'\$?([\d,.]+)\s?(million|billion)?\s+(funding|investment|raised|round)', text, re.I)
        if funding_match:
            amt = funding_match.group(1).replace(',', '')
            unit = funding_match.group(2) or ''
            company_info["recent_funding"] = f"${amt} {unit}".strip()

        erp_keywords = ['SAP', 'Oracle ERP', 'Microsoft Dynamics', 'NetSuite', 'Infor']
        for erp in erp_keywords:
            if erp.lower() in text.lower():
                company_info["current_erp"] = erp
                break

        job_postings = [a.get_text(strip=True) for a in soup.find_all('a') if any(keyword.lower() in a.get_text(strip=True).lower() for keyword in ['sap', 'erp'])]
        company_info["recent_sap_job_postings"] = ', '.join(job_postings) if job_postings else "No SAP job postings found."

        sic_match = re.search(r'SIC Code[:\s]*([\d]{4})', text, re.I)
        if sic_match:
            company_info["sic_codes"] = sic_match.group(1)

        strengths = [line.strip() for line in text.split('.') if 'strength' in line.lower()]
        weaknesses = [line.strip() for line in text.split('.') if 'weakness' in line.lower()]
        opportunities = [line.strip() for line in text.split('.') if 'opportunit' in line.lower()]
        threats = [line.strip() for line in text.split('.') if 'threat' in line.lower()]

        company_info["strengths"] = ' '.join(strengths) if strengths else "Not Available"
        company_info["weaknesses"] = ' '.join(weaknesses) if weaknesses else "Not Available"
        company_info["opportunities"] = ' '.join(opportunities) if opportunities else "Not Available"
        company_info["threats"] = ' '.join(threats) if threats else "Not Available"
        company_info["company_official_website"] = company_website

    except Exception as e:
        print(f"Error scraping {company_name}: {e}")

    return company_info

# -------------------------
# Initialize LLM and Agent

llm = AzureChatOpenAI(deployment_name="gpt-4o", model_name="gpt-4o", temperature=0.7)

tavily_tool = TavilySearch()
duckduckgo_tool = DuckDuckGoSearchRun()
serpapi_tool = SerpAPIWrapper()

tools = [
    Tool(
        name="Tavily Search",
        func=tavily_tool.run,
        description="FAST and ACCURATE. Use this for company ERP systems, SAP jobs, funding updates, leadership changes, SWOT, or financials."
    ),
    Tool(
        name="DuckDuckGo Search",
        func=duckduckgo_tool.run,
        description="Basic search. Use ONLY if Tavily fails."
    ),
    Tool(
        name="Google Search via SerpAPI",
        func=serpapi_tool.run,
        description="Google search via SerpAPI. Only use if Tavily returns nothing."
    )
]

agent = initialize_agent(tools, llm=llm, agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION, verbose=True, handle_parsing_errors=True)

# -------------------------
# Prompt Template

prompt_template = PromptTemplate(
    input_variables=["company_name", "scraped_data"],
    template="""
You are a business intelligence assistant creating a report on **{company_name}**.
Use the **Tavily Search tool** to enrich any missing information.

**Company Report**

## Company Overview
- **Company Name:** {company_name}
- **Address:** {scraped_data[address]}
- **Employee Count:** {scraped_data[employee_count]}
- **Annual Revenue:** {scraped_data[annual_revenue]}

## Recent Developments
- **Leadership Changes:** {scraped_data[leadership_changes]}
- **Recent News:** {scraped_data[recent_news]}
- **Recent SAP Job Postings:** {scraped_data[recent_sap_job_postings]}

## Financial & Industry Insights
- **Recent Funding:** {scraped_data[recent_funding]}
- **ERP System:** {scraped_data[current_erp]}
- **SIC Codes:** {scraped_data[sic_codes]}

## SWOT Analysis
- **Strengths:** {scraped_data[strengths]}
- **Weaknesses:** {scraped_data[weaknesses]}
- **Opportunities:** {scraped_data[opportunities]}
- **Threats:** {scraped_data[threats]}

## Contact Information
- **Phone:** {scraped_data[phone_number]}
- **Address:** {scraped_data[address]}
- **Official Website:** {scraped_data[company_official_website]}

## Disclaimer
Some info may be outdated. Refer to the official website for the latest updates.
"""
)

# -------------------------
# Final Report Generator

def generate_summary(company_name, scraped_data):
    prompt = prompt_template.format(company_name=company_name, scraped_data=scraped_data)
    try:
        response = llm.invoke(prompt)
        return response.content.strip()
    except Exception as e:
        st.error(f"Error generating summary: {e}")
        return "Summary generation failed."

# -------------------------
# Streamlit UI

st.set_page_config(page_title="AI Sales Research", page_icon="🤖", layout="wide")
logo = Image.open("Logo-White.png")

st.markdown(
    """
    <style>
    .top-right {
        position: absolute;
        top: 12px;
        right: 12px;
        z-index: 9999;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# Page Design
st.markdown(
    """
    <style>
    /* Entire background */
    .stApp, .block-container {
        background-color: #070f26;
    }

    /* Sidebar background */
    section[data-testid="stSidebar"] {
        background-color: #1e458e !important;
    }

    /* Chat input box at the bottom */
    div.stChatInputContainer {
        background-color: #1e458e !important;
        border-top: 1px solid #133168;
    }

    /* Input field inside chat input */
    div.stChatInputContainer input {
        background-color: #133168 !important;
        color: white !important;
    }

    /* Chat submit arrow */
    button[kind="secondary"] {
        background-color: #133168 !important;
        color: white !important;
    }

    /* Default font color for everything */
    body, .markdown-text-container, .stTextInput>div>div>input, .css-qrbaxs {
        color: white !important;
    }

    /* Optional: Deselect button background and text */
    button {
        background-color: #133168 !important;
        color: white !important;
        border: none;
    }

    /* Optional: Improve spacing if needed */
    .css-1kyxreq {
        padding: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True
)
with st.sidebar:
    st.image(logo, width=250)

st.sidebar.title("Search History")
st.title("AI Sales Research")
st.write("ℹ️ Enter a company name to fetch insights and generate a structured summary.")

# Session State Initialization
if "search_history" not in st.session_state:
    st.session_state["search_history"] = []

if "selected_company" not in st.session_state:
    st.session_state["selected_company"] = None

# Sidebar with history
selected_company = st.sidebar.radio(
    "Click a company to reload report:",
    st.session_state["search_history"],
    index=st.session_state["search_history"].index(st.session_state["selected_company"])
    if st.session_state["selected_company"] else 0
    if st.session_state["search_history"] else 0
)

# Handle deselect
if st.sidebar.button("Deselect"):
    st.session_state["selected_company"] = None
    st.rerun()

# Update session state
st.session_state["selected_company"] = selected_company if selected_company else None

# Display Report for selected company 
if selected_company:
    st.write(f"### Report for {selected_company}")
    if selected_company in st.session_state:
        report_text = st.session_state[selected_company]
        st.markdown(report_text)

        # Download Button for previous report
        template_path = "ModelTemplate.docx"
        doc_file = fill_word_template(template_path, report_text)

        st.download_button(
            label="📄 Download Again",
            data=doc_file,
            file_name=f"{selected_company}_Report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    else:
        st.warning("No previous report found for this company.")

# Input for new company 
user_input = st.chat_input("Enter a company name (Ex. Apple)...")

if user_input:
    if user_input not in st.session_state["search_history"]:
        st.session_state["search_history"].append(user_input)

    with st.spinner(f"Searching for **{user_input}**..."):
        company_info = scrape_company_website(user_input)

    with st.spinner("Generating report..."):
        report = generate_summary(user_input, company_info)

    # Save report
    st.session_state[user_input] = report

    st.write(f"### Report for {user_input}")
    st.markdown(report)

    template_path = "ModelTemplate.docx"
    doc_file = fill_word_template(template_path, report)

    st.download_button(
        label="📄 Download Report",
        data=doc_file,
        file_name=f"{user_input}_Report.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )