import streamlit as st

st.title("Name Caller")

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
