import streamlit as st
from snowflake.snowpark.context import get_active_session
import pandas as pd
import json

st.set_page_config(layout="wide", page_title="CortexCare Clinical Intelligence")
session = get_active_session()
# -------------------------------------

st.markdown("""
    <style>
    .metric-card { background-color: #f1f5f9; padding: 20px; border-radius: 10px; border-left: 5px solid #0284c7; }
    .risk-high { border-left: 5px solid #ef4444; }
    .risk-low { border-left: 5px solid #22c55e; }
    </style>
""", unsafe_allow_html=True)

st.title("🏥 CortexCare: Clinical Intelligence Dashboard")
st.caption("Powered by Snowflake Cortex AI - Transforming the Unstructured Data Graveyard")

st.sidebar.header("Patient Directory")
patients_df = session.sql("SELECT PATIENT_ID, PATIENT_NAME FROM PATIENT_DEMOGRAPHICS").to_pandas()
patient_dict = dict(zip(patients_df['PATIENT_ID'], patients_df['PATIENT_NAME']))

selected_id = st.sidebar.selectbox("Select Patient", options=patient_dict.keys(), format_func=lambda x: f"{x} - {patient_dict[x]}")

if selected_id:
    # 1. Fetch unified data (Demographics + Clinical Notes)
    query = f"SELECT * FROM VW_UNIFIED_PATIENT_RECORD WHERE PATIENT_ID = '{selected_id}' ORDER BY NOTE_DATE DESC"
    patient_data = session.sql(query).to_pandas()
    
    # 2. Fetch Blood Reports Data directly
    lab_query = f"SELECT * FROM CORTEX_BLOOD_REPORTS WHERE PATIENT_ID = '{selected_id}' ORDER BY REPORT_DATE DESC"
    lab_data = session.sql(lab_query).to_pandas()

    if patient_data.empty:
        st.warning("No records found for this patient in the unified view.")
    else:
        # --- ROW 1: DEMOGRAPHICS ---
        st.subheader("👤 Patient Demographics (From EMR Table)")

        raw_ssn = patient_data['SSN'].iloc[0] if pd.notna(patient_data['SSN'].iloc[0]) else "N/A"
        masked_ssn = f"XXX-XX-{raw_ssn[-4:]}" if raw_ssn != "N/A" and len(raw_ssn) >= 4 else raw_ssn

        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f"<div class='metric-card'><b>Name:</b><br>{patient_dict[selected_id]}</div>", unsafe_allow_html=True)
        c2.markdown(f"<div class='metric-card'><b>ID & SSN:</b><br>{selected_id} | {masked_ssn}</div>", unsafe_allow_html=True)
        c3.markdown(f"<div class='metric-card'><b>Admission Date:</b><br>{patient_data['ADMITTION_DATE'].iloc[0]}</div>", unsafe_allow_html=True)
        c4.markdown(f"<div class='metric-card'><b>EMR Diagnosis:</b><br>{patient_data['PRIMARY_ADMISSION_DIAGNOSIS'].iloc[0]}</div>", unsafe_allow_html=True)

        st.divider()

        # --- ROW 2: CLINICAL NOTES ---
        st.subheader("📄 Longitudinal History & AI Risk Assessment (From Unstructured S3 PDFs)")

        pdf_data = patient_data.dropna(subset=['NOTE_FILE_NAME']).drop_duplicates(subset=['NOTE_FILE_NAME'])

        if pdf_data.empty:
            st.info("No unstructured clinical notes found in S3 for this patient.")
        else:
            avg_risk = pdf_data['RISK_SCORE'].mean()
            risk_class = "risk-high" if avg_risk > 0.2 else "risk-low"
            risk_label = "High Risk / Triage Priority" if avg_risk > 0.2 else "Stable"

            st.markdown(f"<div class='metric-card {risk_class}'><b>Overall AI Risk Score:</b> {avg_risk:.2f} ({risk_label})</div>", unsafe_allow_html=True)
            st.write("")

            for idx, row in pdf_data.iterrows():
                doc_date = row['NOTE_DATE']
                file_name = row['NOTE_FILE_NAME']
                risk = row['RISK_SCORE']

                with st.expander(f"📋 Document Date: {doc_date} | Source: {file_name} | Doc Risk Score: {risk:.2f}"):
                    tab1, tab2, tab3 = st.tabs(["🤖 AI Structured Output", "💡 Suggested Billing (ICD-10)", "📝 Original OCR Text"])

                    try:
                        structured_data = json.loads(row['NOTE_STRUCTURED_DATA']) if isinstance(row['NOTE_STRUCTURED_DATA'], str) else row['NOTE_STRUCTURED_DATA']
                    except:
                        structured_data = {"error": "Could not parse AI output"}

                    with tab1:
                        st.write("**Document Type:**", structured_data.get('document_type', 'Unknown'))
                        st.write("**Key Findings:**", structured_data.get('key_findings', 'None extracted'))
                        st.write("**Medications Found:**")
                        st.write(structured_data.get('medications', []))

                    with tab2:
                        st.write("Cortex AI automatically extracted these codes for the billing department:")
                        st.json(structured_data.get('icd10_codes', []))

                    with tab3:
                        st.text_area("Raw Text extracted via SNOWFLAKE.CORTEX.PARSE_DOCUMENT", row['NOTE_RAW_TEXT'], height=150, key=f"note_{idx}")
                        # st.text_area("Raw Text extracted via SNOWFLAKE.CORTEX.PARSE_DOCUMENT", row['NOTE_RAW_TEXT'], height=150)
        st.divider()

        # --- ROW 3: BLOOD REPORTS ---
        st.subheader("🩸 Laboratory Results (From Unstructured S3 Blood Reports)")

        if lab_data.empty:
            st.info("No unstructured blood report documents found in S3 for this patient.")
        else:
            for idx, row in lab_data.iterrows():
                with st.expander(f"🧪 Blood Panel - {row['REPORT_DATE']} | File: {row['FILE_NAME']}"):
                    try:
                        tests = json.loads(row['LAB_RESULTS_JSON']) if isinstance(row['LAB_RESULTS_JSON'], str) else row['LAB_RESULTS_JSON']
                        df_tests = pd.DataFrame(tests)
                        
                        # Highlighting function for abnormal results
                        def highlight_abnormal(val):
                            color = '#ffcccc' if str(val).lower() in ['high', 'low', 'abnormal'] else ''
                            return f'background-color: {color}'
                        
                        if 'flag' in df_tests.columns:
                            st.dataframe(df_tests.style.map(highlight_abnormal, subset=['flag']), use_container_width=True)
                        else:
                            st.dataframe(df_tests, use_container_width=True)
                            
                    except Exception as e:
                        st.error("Could not parse lab results into a table.")
                        st.write("Raw JSON Array:", row['LAB_RESULTS_JSON'])
                        st.write("Original Text:", row['RAW_OCR_TEXT'])

        # --- ROW 4: ASK CORTEX ---
        st.divider()
        st.subheader("💬 Ask Cortex (Clinical Assistant)")
        st.caption("Ask questions across the patient's entire medical record (Notes & Blood Reports).")
        
        user_query = st.text_input("Example: 'What was the patient's Hemoglobin level, and what is the doctor's follow-up plan?'")
        
        if user_query:
            with st.spinner("Cortex is reading the raw clinical notes and blood reports..."):
                
                # 1. Grab the EMR demographics
                emr_context = f"EMR Info - Name: {patient_dict[selected_id]}, Diagnosis: {patient_data['PRIMARY_ADMISSION_DIAGNOSIS'].iloc[0]}."
                
                # 2. Grab the ENTIRE RAW TEXT from all clinical PDFs
                raw_text_context = " ".join(pdf_data['NOTE_RAW_TEXT'].dropna().astype(str).tolist()) if not pdf_data.empty else "No clinical notes."
                
                # 3. Grab the ENTIRE RAW TEXT from all blood reports
                lab_text_context = " ".join(lab_data['RAW_OCR_TEXT'].dropna().astype(str).tolist()) if not lab_data.empty else "No lab reports."
                
                # 4. Build the prompt using all contexts
                prompt = f"""
                You are a highly capable medical AI assistant. 
                Read the following patient data carefully:
                
                {emr_context}
                
                Clinical Notes: {raw_text_context}
                
                Laboratory Reports: {lab_text_context}
                
                Based ONLY on the text above, answer the doctor's question concisely: 
                '{user_query}'
                """
                
                # 5. Ask Llama 3!
                try:
                    sql_query = f"""SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3-8b', $${prompt}$$)"""
                    response = session.sql(sql_query).collect()[0][0]
                    st.success(response)
                except Exception as e:
                    st.error(f"Error querying Cortex: {e}")


# -----v1----
# import streamlit as st
# from snowflake.snowpark.context import get_active_session
# import pandas as pd
# import json

# st.set_page_config(layout="wide", page_title="CortexCare Clinical Intelligence")
# session = get_active_session()

# st.markdown("""
#     <style>
#     .metric-card { background-color: #f1f5f9; padding: 20px; border-radius: 10px; border-left: 5px solid #0284c7; }
#     .risk-high { border-left: 5px solid #ef4444; }
#     .risk-low { border-left: 5px solid #22c55e; }
#     </style>
# """, unsafe_allow_html=True)

# st.title("🏥 CortexCare: Clinical Intelligence Dashboard")
# st.caption("Powered by Snowflake Cortex AI - Transforming the Unstructured Data Graveyard")

# st.sidebar.header("Patient Directory")
# patients_df = session.sql("SELECT PATIENT_ID, PATIENT_NAME FROM PATIENT_DEMOGRAPHICS").to_pandas()
# patient_dict = dict(zip(patients_df['PATIENT_ID'], patients_df['PATIENT_NAME']))

# selected_id = st.sidebar.selectbox("Select Patient", options=patient_dict.keys(), format_func=lambda x: f"{x} - {patient_dict[x]}")

# if selected_id:
#     query = f"SELECT * FROM VW_UNIFIED_PATIENT_RECORD WHERE PATIENT_ID = '{selected_id}' ORDER BY DOCUMENT_DATE DESC"
#     patient_data = session.sql(query).to_pandas()

#     if patient_data.empty:
#         st.warning("No records found for this patient in the unified view.")
#     else:
#         st.subheader("👤 Patient Demographics (From EMR Table)")

#         raw_ssn = patient_data['SSN'].iloc[0] if pd.notna(patient_data['SSN'].iloc[0]) else "N/A"
#         masked_ssn = f"XXX-XX-{raw_ssn[-4:]}" if raw_ssn != "N/A" and len(raw_ssn) >= 4 else raw_ssn

#         c1, c2, c3, c4 = st.columns(4)
#         c1.markdown(f"<div class='metric-card'><b>Name:</b><br>{patient_dict[selected_id]}</div>", unsafe_allow_html=True)
#         c2.markdown(f"<div class='metric-card'><b>ID & SSN:</b><br>{selected_id} | {masked_ssn}</div>", unsafe_allow_html=True)
#         c3.markdown(f"<div class='metric-card'><b>Admission Date:</b><br>{patient_data['ADMITTION_DATE'].iloc[0]}</div>", unsafe_allow_html=True)
#         c4.markdown(f"<div class='metric-card'><b>EMR Diagnosis:</b><br>{patient_data['PRIMARY_ADMISSION_DIAGNOSIS'].iloc[0]}</div>", unsafe_allow_html=True)

#         st.divider()

#         st.subheader("📄 Longitudinal History & AI Risk Assessment (From Unstructured S3 PDFs)")

#         pdf_data = patient_data.dropna(subset=['FILE_NAME'])

#         if pdf_data.empty:
#             st.info("No unstructured PDF documents found in S3 for this patient.")
#         else:
#             avg_risk = pdf_data['RISK_SCORE'].mean()
#             risk_class = "risk-high" if avg_risk > 0.2 else "risk-low"
#             risk_label = "High Risk / Triage Priority" if avg_risk > 0.2 else "Stable"

#             st.markdown(f"<div class='metric-card {risk_class}'><b>Overall AI Risk Score:</b> {avg_risk:.2f} ({risk_label})</div>", unsafe_allow_html=True)
#             st.write("")

#             for idx, row in pdf_data.iterrows():
#                 doc_date = row['DOCUMENT_DATE']
#                 file_name = row['FILE_NAME']
#                 risk = row['RISK_SCORE']

#                 with st.expander(f"📋 Document Date: {doc_date} | Source: {file_name} | Doc Risk Score: {risk:.2f}"):
#                     tab1, tab2, tab3 = st.tabs(["🤖 AI Structured Output", "💡 Suggested Billing (ICD-10)", "📝 Original OCR Text"])

#                     try:
#                         structured_data = json.loads(row['AI_STRUCTURED_DATA']) if isinstance(row['AI_STRUCTURED_DATA'], str) else row['AI_STRUCTURED_DATA']
#                     except:
#                         structured_data = {"error": "Could not parse AI output"}

#                     with tab1:
#                         st.write("**Document Type:**", structured_data.get('document_type', 'Unknown'))
#                         st.write("**Key Findings:**", structured_data.get('key_findings', 'None extracted'))
#                         st.write("**Medications Found:**")
#                         st.write(structured_data.get('medications', []))

#                     with tab2:
#                         st.write("Cortex AI automatically extracted these codes for the billing department:")
#                         st.json(structured_data.get('icd10_codes', []))

#                     with tab3:
#                         st.text_area("Raw Text extracted via SNOWFLAKE.CORTEX.PARSE_DOCUMENT", row['RAW_EXTRACTED_TEXT'], height=150)

#         # st.divider()
#         # st.subheader("💬 Ask Cortex (Clinical Assistant)")
#         # st.caption("Ask questions across both the structured EMR data and the unstructured PDF notes.")

#         # user_query = st.text_input("Example: 'What is the patient's EMR admission diagnosis, and what medications were found in their PDFs?'")

#         # if user_query:
#         #     with st.spinner("Cortex is analyzing the complete medical record..."):
#         #         emr_context = f"EMR Info - Name: {patient_dict[selected_id]}, Admission Date: {patient_data['ADMITTION_DATE'].iloc[0]}, Diagnosis: {patient_data['PRIMARY_ADMISSION_DIAGNOSIS'].iloc[0]}."
#         #         pdf_context = " ".join(pdf_data['AI_STRUCTURED_DATA'].astype(str).tolist()) if not pdf_data.empty else "No PDF data available."

#         #         full_context = f"{emr_context} Clinical Notes Data: {pdf_context}"

#         #         prompt = f"You are a medical AI assistant. Based on this patient data: {full_context}. Answer this question accurately and concisely: '{user_query}'"

#         #         response = session.sql(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3-70b', {repr(prompt)})").collect()[0][0]
#         #         st.success(response)
#         # --- ROW 3: ASK CORTEX ---
#     st.divider()
#     st.subheader("💬 Ask Cortex (Clinical Assistant)")
#     st.caption("Ask questions across the patient's entire medical record and raw doctor notes.")
    
#     user_query = st.text_input("Example: 'What is the follow up suggested by the doctor?'")
    
#     if user_query:
#         with st.spinner("Cortex is reading the raw clinical notes..."):
            
#             # 1. Grab the EMR demographics
#             emr_context = f"EMR Info - Name: {patient_dict[selected_id]}, Diagnosis: {patient_data['PRIMARY_ADMISSION_DIAGNOSIS'].iloc[0]}."
            
#             # 2. Grab the ENTIRE RAW TEXT from all their PDFs
#             raw_text_context = " ".join(pdf_data['RAW_EXTRACTED_TEXT'].dropna().astype(str).tolist())
            
#             # 3. Build the prompt using the raw text
#             prompt = f"""
#             You are a highly capable medical AI assistant. 
#             Read the following raw clinical notes and EMR data for the patient:
#             {emr_context}
#             Clinical Notes: {raw_text_context}
            
#             Based ONLY on the text above, answer the doctor's question concisely: 
#             '{user_query}'
#             """
            
#             # 4. Ask Llama 3!
#             try:
#                 # Using triple quotes around the prompt to safely handle any weird characters in the raw text
#                 sql_query = f"""SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3-70b', $${prompt}$$)"""
#                 response = session.sql(sql_query).collect()[0][0]
#                 st.success(response)
#             except Exception as e:
#                 st.error(f"Error querying Cortex: {e}")