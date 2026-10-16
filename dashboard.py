import streamlit as st

from jira_issues import (
    BASE_URL,
    PROJECT_KEY,
    fetch_component_dashboard,
    fetch_components,
    load_saved_token,
)


st.set_page_config(page_title="Jira System Manager", layout="wide")
st.title("Jira System Manager")
st.caption(f"Progetto {PROJECT_KEY} · sola lettura")

try:
    token = load_saved_token()
except RuntimeError as error:
    st.error(str(error))
    st.stop()

try:
    components = fetch_components(BASE_URL, PROJECT_KEY, token)
except RuntimeError as error:
    st.error(f"Non riesco a caricare i componenti da Jira: {error}")
    st.stop()

component_names = {component["name"]: component for component in components}
selected_name = st.selectbox("Componente", list(component_names))
selected_component = component_names[selected_name]

if st.button("Aggiorna dashboard", type="primary"):
    try:
        st.session_state["dashboard_issues"] = fetch_component_dashboard(
            BASE_URL,
            PROJECT_KEY,
            selected_component["id"],
            token,
        )
        st.session_state["dashboard_component_id"] = selected_component["id"]
    except RuntimeError as error:
        st.error(f"Non riesco a caricare le issue da Jira: {error}")

if "dashboard_issues" not in st.session_state:
    st.info("Seleziona un componente e premi **Aggiorna dashboard**.")
    st.stop()

if st.session_state.get("dashboard_component_id") != selected_component["id"]:
    st.info("Il componente è cambiato. Premi **Aggiorna dashboard** per caricare i dati.")
    st.stop()

all_issues = st.session_state["dashboard_issues"]
categories = {
    "Bug aperti": {"bug", "defect"},
    "Release non chiuse": {"release"},
    "Story aperte": {"story"},
}

for title, issue_types in categories.items():
    group = [
        issue for issue in all_issues
        if issue["type"].casefold() in issue_types
    ]
    st.subheader(title)
    st.metric("Issue", len(group))
    if not group:
        st.info("Nessuna issue aperta.")
        continue

    rows = [
        {
            "Chiave": issue["key"],
            "Riepilogo": issue["summary"],
            "Stato": issue["status"],
            "Creata": issue["created"],
            "Priorità": issue["priority"],
            **({"Assegnatario": issue["assignee"]} if title == "Bug aperti" else {}),
            "Link": f"{BASE_URL.rstrip('/')}/browse/{issue['key']}",
        }
        for issue in group
    ]
    st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        column_config={
            "Link": st.column_config.LinkColumn(
                "Apri issue",
                display_text="↗",
            )
        },
    )
