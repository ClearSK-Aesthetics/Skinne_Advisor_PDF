import streamlit as st
import pandas as pd
import json
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from io import BytesIO

import uuid

def generate_voucher_code():
    """Generate a unique voucher code."""
    return str(uuid.uuid4())[:8]  # Use the first 8 characters of a UUID


# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Skinne Advisor", layout="wide", initial_sidebar_state="collapsed")

# --- LOAD DATA FILES ---
@st.cache_data
def load_questions():
    """Load survey questions from a JSON file."""
    with open("questions.json", "r") as file:
        return json.load(file)

@st.cache_data
def load_concerns():
    """Load specific concerns and their mappings from a JSON file."""
    with open("concerns.json", "r") as file:
        return json.load(file)

@st.cache_data
@st.cache_data
def load_data(sheet_name):
    """Load treatment attribute data from a specified Excel sheet."""
    filepath = "Treatment Attribute Master (Skinne Advisor & Trainer).xlsx"
    try:
        return pd.read_excel(filepath, sheet_name=sheet_name)
    except Exception as e:
        st.error(f"Error loading data from sheet '{sheet_name}': {e}")
        return pd.DataFrame()


questions = load_questions()
concerns = load_concerns()

# --- HELPER FUNCTIONS ---
def render_question(question_data):
    """Render a single question with numbered options and return the selected option."""
    numbered_options = [f"{i + 1}) {option}" for i, option in enumerate(question_data["options"])]
    response = st.selectbox(
        question_data["question"],
        ["Select one option"] + numbered_options,
        index=0,
    )
    if response != "Select one option":
        return int(response.split(")")[0])
    return None

def render_survey(questions):
    """Render all survey questions and collect responses."""
    if "responses" not in st.session_state:
        st.session_state.responses = {}
    responses = st.session_state.responses

    # Render the primary concern question
    primary_concern_index = render_question(questions[0])
    if primary_concern_index:
        primary_concern = questions[0]["options"][primary_concern_index - 1]
        responses["Primary Concern"] = primary_concern

        # Render specific interest question based on primary concern
        specific_options = concerns.get(primary_concern, [])
        numbered_specific_options = [f"{i + 1}) {option}" for i, option in enumerate(specific_options)]
        specific_choice = st.selectbox(
            "Please select your specific interest:",
            ["Select one option"] + numbered_specific_options,
            index=0,
        )
        if specific_choice != "Select one option":
            responses["Specific Interest"] = numbered_specific_options[int(specific_choice.split(")")[0]) - 1]

    # Render general survey questions
    for i, question in enumerate(questions[1:], start=1):
        response = render_question(question)
        if response:
            responses[question["question"]] = response

        # Handle injectable preference for Question 6
        if i + 1 == 6:  # Adjust index for Question 6
            responses["Delivery Mode"] = response

    return responses


def extract_concern_code(specific_interest):
    """Extract concern code from the specific interest string."""
    if specific_interest:
        parts = specific_interest.split(" ")
        if len(parts) > 1:
            return parts[1]
    return None

def display_p_score():
    """Calculate P-Score, trigger treatment recommendations, and generate a voucher code."""
    responses = st.session_state.get("responses", {})

    # Validate questions data
    if not questions or not isinstance(questions, list):
        st.error("Questions data is missing or improperly formatted.")
        return

    # Extract specific interest code
    specific_interest_code = extract_concern_code(responses.get("Specific Interest", ""))
    if not specific_interest_code:
        st.error("Specific Interest Code is invalid or missing. Please ensure you have completed the survey.")
        return

    # Construct P-Score, handle KeyError exceptions
    try:
        scores = [specific_interest_code] + [responses.get(q["question"], 1) for q in questions[1:]]
    except KeyError as e:
        st.error(f"Missing question key: {e}")
        return

    # Validate scores length
    if len(scores) != len(questions):
        st.error("Incomplete data. Please answer all the questions before submitting.")
        print(len(scores))
        print(len(questions))
        return

    # Call the treatment recommendation function
    recommend_treatments(scores)

    # Generate a unique voucher code
    voucher_code = generate_voucher_code()
    st.session_state["voucher_code"] = voucher_code

    # Display voucher code
    st.success(f"Thank you for completing the survey! Your unique voucher code is: **{voucher_code}**")


def convert_t_score(t_score_str):
    """
    Convert T-Score from string to a list of values.
    
    Args:
        t_score_str (str): A string representing a T-Score, formatted as '[id, value1, value2, ...]'.
    
    Returns:
        list: A list where the first element is the ID (str) and subsequent elements are integers.
    """
    if not t_score_str or not isinstance(t_score_str, str):
        raise ValueError("Input must be a non-empty string representing a T-Score.")

    elements = t_score_str.strip("[]").replace("'", "").split(", ")
    if len(elements) < 1:
        raise ValueError("Input string is not in the expected format. Must contain at least one element.")

    def safe_int_conversion(value):
        try:
            return int(value.strip())
        except ValueError:
            return -1

    return [elements[0]] + [safe_int_conversion(i) for i in elements[1:]]

def filter_treatments(data, concern_code):
    """
    Filter treatments based on Concern Code.
    
    Args:
        data (pd.DataFrame): A Pandas DataFrame containing treatment data.
        concern_code (str): The Concern Code to filter treatments by.
    
    Returns:
        pd.DataFrame: A filtered DataFrame containing treatments matching the Concern Code.
    """
    if not isinstance(data, pd.DataFrame) or data.empty:
        raise ValueError("Input data must be a non-empty Pandas DataFrame.")

    if "Concern Code" not in data.columns:
        raise ValueError("Data does not contain the required 'Concern Code' column.")

    if not isinstance(concern_code, str) or not concern_code.strip():
        raise ValueError("Concern Code must be a non-empty string.")

    data = data.dropna(subset=["Concern Code"])
    filtered_data = data[data["Concern Code"].str.startswith(concern_code)]

    if filtered_data.empty:
        raise ValueError(f"No treatments found for Concern Code: {concern_code}")

    return filtered_data

def calculate_d_score(p_score, t_score):
    """
    Calculate D-Score based on P-Score and T-Score.
    
    Args:
        p_score (list): A list where the first element is an identifier (e.g., concern code),
                        and the subsequent elements are numerical scores.
        t_score (list): A list in the same format as p_score.
    
    Returns:
        int: The calculated D-Score, representing the sum of absolute differences between scores.
    """
    if not isinstance(p_score, list) or not isinstance(t_score, list):
        raise ValueError("Both p_score and t_score must be lists.")

    if len(p_score) != len(t_score):
        raise ValueError("p_score and t_score must have the same length.")

    if len(p_score) <= 1 or len(t_score) <= 1:
        raise ValueError("p_score and t_score must contain at least one scoring element beyond the first identifier.")

    def safe_int_conversion(value):
        try:
            return int(value)
        except ValueError:
            return -1

    return sum(abs(p - safe_int_conversion(t)) for p, t in zip(p_score[1:], t_score[1:]))

def recommend_treatments(p_score):
    """Generate treatment recommendations based on injectable preference."""
    # Retrieve the injectable preference from responses
    responses = st.session_state.get("responses", {})
    injectable_preference = responses.get("Delivery Mode")
    if injectable_preference == 1:
        sheet_name = "Non-injectable"  # Open to all treatments
    elif injectable_preference == 2:
        sheet_name = "All treatments"  # Non-injectable treatments only
    else:
        st.error("Invalid selection for injectable preference.")
        return

    # Load data from the appropriate sheet
    data = load_data(sheet_name)
    if data.empty:
        st.error(f"Unable to load data from the '{sheet_name}' sheet.")
        return

    concern_code = p_score[0]
    if not concern_code:
        st.error("Invalid concern code extracted. Please check your responses.")
        return

    # Continue with filtering, scoring, and displaying recommendations
    data["T-Score"] = data["T-Score"].apply(convert_t_score)
    data["D-Score"] = data.apply(lambda row: calculate_d_score(p_score, row["T-Score"]), axis=1)

    filtered_data = filter_treatments(data, concern_code)
    if filtered_data.empty:
        st.error(f"No treatments found for the Concern Code '{concern_code}'.")
        return

    # Select the top 5 treatments with the smallest D-Score
    top_recommendations = filtered_data.nsmallest(5, "D-Score")

    # Rename columns for better readability
    top_recommendations = top_recommendations.rename(columns={
        'Treatment Brand/Name': 'Treatment Name',
        'Budget Level:\n(Price Per Session)\n\n1: SGD 20 - 99\n2: SGD 100 - 199\n3: SGD 200 - 299\n4: SGD 300 - 399\n5: SGD 400 - 499\n6: SGD 500 - 699\n7: SGD 700 - 999\n8: SGD 1000 - 1499\n9: SGD 1500 - 3000\n10: Above SGD 3000': 'Budget Level (SGD)',
        'Duration of Results:\n\n1: 12 months\n2: 6 months\n': 'Duration of Results (months)',
        'Number of Sessions Required:\n\n1: 1 session\n2: 2 sessions\n3: 4 sessions\n4: 6 sessions': 'Sessions Required',
        'Level of Discomfort:\n\n1: Low\n2: Low-moderate\n3: Moderate\n4: Moderate-high\n5: High': 'Discomfort Level',
        'Amount of Downtime:\n\n1: None\n2: 1 day\n3: 3 days\n4: 7 days ': 'Downtime',
        'Prescribed Intervals between Sessions:\n\n1: 1 day\n2: 1 week\n3: 2 weeks\n4: 1 month\n5: 3 months\n6: 6 months': 'Interval Between Sessions',
        'Delivery Mode': 'Delivery Mode'
    })

    top_recommendations.index = range(1, len(top_recommendations) + 1)

    # Define the columns to display
    columns_to_display = [
        'Treatment Name', 'Budget Level (SGD)', 'Duration of Results (months)',
        'Sessions Required', 'Discomfort Level', 'Delivery Mode', 'Downtime',
        'Interval Between Sessions'
    ]

    # Select the columns for display
    final_table = top_recommendations[columns_to_display]

    # Save final_table to session_state
    st.session_state["final_table"] = final_table

    # Display the recommendations or show an error if empty
    if not final_table.empty:
        st.write("### Top 5 Recommended Treatments")
        st.table(final_table)
    else:
        st.error("No matching treatments found after filtering and scoring.")



from reportlab.lib.pagesizes import landscape

# Define a custom longer paper size
CUSTOM_LONG_PAGE = (1200, 600)  # Width x Height in points

def generate_pdf_from_dataframe(df):
    buffer = BytesIO()
    
    # Use the custom page size
    pdf = SimpleDocTemplate(buffer, pagesize=landscape(CUSTOM_LONG_PAGE))
    
    # Add voucher code to the data
    voucher_code = st.session_state.get("voucher_code", "N/A")
    voucher_row = ["VOUCHER CODE", voucher_code] + [""] * (len(df.columns) - 2)
    
    data = [df.columns.tolist()] + df.values.tolist() + [voucher_row]
    table = Table(data)
    
    # Set table styles
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),  # Header background color
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),  # Header text color
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),  # Center align all cells
        ('GRID', (0, 0), (-1, -1), 1, colors.black),  # Add grid lines
        ('TEXTCOLOR', (0, len(data)-1), (1, len(data)-1), colors.green),  # Voucher code row text color
    ]))
    
    pdf.build([table])
    buffer.seek(0)
    return buffer




# --- MAIN APPLICATION LOGIC ---
def main():
    # Center the title and subtitle using a custom HTML container with inline CSS
    st.markdown(
        """
        <div style="
            display: flex; 
            flex-direction: column; 
            align-items: center; 
            justify-content: center; 
            text-align: center; 
            height: 150px; 
            margin-bottom: 20px;">
            <h1 style="font-size: 2.5rem; color: #4d4d4d; margin: 0;">Welcome to Skinne Advisor!</h1>
            <p style="font-size: 1.2rem; color: #6d6d6d; margin-top: 10px;">Participate in our survey to discover treatments tailored for you.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Render the survey
    render_survey(questions)

    # Add a submit button
    if st.button("Submit"):
        display_p_score()

    if "final_table" in st.session_state and st.session_state["final_table"] is not None:
        # Generate PDF from the dataframe
        pdf_buffer = generate_pdf_from_dataframe(st.session_state["final_table"])
        
        # Create two columns
        col1, col2 = st.columns([1, 2])  # Adjust column proportions if needed
        
        with col1:
            st.write("**Please download the pdf and this will be your exclusive coupon!**")
            # Add the download button in the first column
            st.download_button(
                label="Download Table as PDF",
                data=pdf_buffer,
                file_name="ClearSK_Top_5_Treatments.pdf",
                mime="application/pdf",
            )

# Entry point for the application
if __name__ == "__main__":
    main()

 
