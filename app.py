import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="3 movie picks")
st.title("3 movie picks")

if "saved_name" not in st.session_state:
    st.session_state.saved_name = ""

name_input = st.text_input("Type your name")

if st.button("Save"):
    st.session_state.saved_name = name_input
    st.success("Name saved.")

if st.button("Call name"):
    if st.session_state.saved_name:
        st.write(f"hello, {st.session_state.saved_name}")
    else:
        st.write("No saved name yet. Please save your name first.")

st.divider()
st.subheader("Color chatbot")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.write(message["content"])

user_prompt = st.chat_input("Ask for a color suggestion")

if user_prompt:
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})

    if not st.session_state.saved_name:
        bot_reply = "Please save your name first so I can suggest a color."
    elif "OPENAI_API_KEY" not in st.secrets:
        bot_reply = "Missing OPENAI_API_KEY in Streamlit secrets."
    else:
        client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=(
                "You are a color recommendation chatbot. "
                f"The saved name is '{st.session_state.saved_name}'. "
                f"User message: '{user_prompt}'. "
                "Suggest one color that fits the name and explain in one short sentence."
            ),
        )
        bot_reply = response.output_text

    st.session_state.chat_history.append({"role": "assistant", "content": bot_reply})
    st.rerun()
