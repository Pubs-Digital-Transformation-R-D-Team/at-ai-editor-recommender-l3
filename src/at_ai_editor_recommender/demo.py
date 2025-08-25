import streamlit as st
import requests

st.title("Editor Assignment Demo")

# Example manuscript data
default_data = {
    "manuscript_number": "jm-2024-02780t",
    "coden": "jmcmar",
    "manuscript_type": "Article",
    "manuscript_title": "Investigation of the ameliorative effects of amygdalin against arsenic trioxide-induced cardiac toxicity in rat",
    "manuscript_abstract": (
        "Amygdalin, recognized as vitamin B17, is celebrated for its antioxidant and anti-inflammatory prowess, "
        "which underpins its utility in averting disease and decelerating the aging process. This study ventures to elucidate "
        "the cardioprotective mechanisms of amygdalin against arsenic trioxide (ATO)-induced cardiac injury, with a spotlight "
        "on the AMP-activated protein kinase (AMPK) and sirtuin-1 (SIRT1) signaling cascade. Employing a Sprague-Dawley rat model, "
        "we administered amygdalin followed by ATO and conducted a 15-day longitudinal study. Our findings underscore the ameliorative "
        "impact of amygdalin on histopathological cardiac anomalies, a reduction in cardiac biomarkers, and an invigoration of antioxidant "
        "defenses, thereby attenuating oxidative stress and inflammation. Notably, amygdalin's intervention abrogated ATO-induced apoptosis "
        "and inflammatory cascades, modulating key proteins along the AMPK/SIRT1 pathway and significantly dampening inflammation. Collectively, "
        "these insights advocate for amygdalin's role as a guardian against ATO-induced cardiotoxicity, potentially through the activation of the "
        "AMPK/SIRT1 axis, offering a novel therapeutic vista in mitigating oxidative stress, apoptosis, and inflammation."
    )
}

with st.form("manuscript_form"):
    manuscript_number = st.text_input("Manuscript Number", value=default_data["manuscript_number"])
    coden = st.text_input("Coden", value=default_data["coden"])
    manuscript_type = st.text_input("Manuscript Type", value=default_data["manuscript_type"])
    manuscript_title = st.text_input("Manuscript Title", value=default_data["manuscript_title"])
    manuscript_abstract = st.text_area("Manuscript Abstract", value=default_data["manuscript_abstract"], height=300)
    submit = st.form_submit_button("Submit Manuscript")

if submit:
    payload = {
        "manuscript_number": manuscript_number,
        "coden": coden,
        "manuscript_type": manuscript_type,
        "manuscript_title": manuscript_title,
        "manuscript_abstract": manuscript_abstract
    }
    st.write("Submitting manuscript...")
    try:
        response = requests.post("http://localhost:8011/execute_workflow", json=payload)
        if response.status_code == 200:
            st.success("Submission successful!")
            st.json(response.json())
        else:
            st.error(f"Error {response.status_code}: {response.text}")
    except Exception as e:
        st.error(f"Request failed: {e}")