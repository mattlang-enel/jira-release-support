import csv
import io

import streamlit as st

from jira_issues import (
    BASE_URL,
    DEFAULT_ASSIGNEE,
    PROJECT_KEY,
    fetch_component_dashboard,
    fetch_components,
    fetch_open_issues_for_assignee,
    load_saved_token,
)


st.set_page_config(page_title="Jira System Manager", layout="wide")
st.title("Jira System Manager")
st.caption(f"Progetto {PROJECT_KEY} · sola lettura")


def render_filtered_table(title, rows, key_prefix):
    searchable_columns = [column for column in rows[0] if column != "Link"]
    selected_column = st.selectbox(
        f"Campo in {title}",
        ["Tutti i campi", *searchable_columns],
        key=f"{key_prefix}_column",
    )
    search_text = st.text_input(
        f"Cerca in {title}",
        placeholder="Es. chiave, riepilogo, stato...",
        key=f"{key_prefix}_query",
    ).strip().casefold()

    filtered_rows = [
        row
        for row in rows
        if not search_text
        or any(
            search_text in str(row[column]).casefold()
            for column in searchable_columns
            if selected_column == "Tutti i campi" or column == selected_column
        )
    ]
    st.caption(f"Mostrate {len(filtered_rows)} di {len(rows)} issue")
    if filtered_rows:
        st.dataframe(
            filtered_rows,
            hide_index=True,
            width="stretch",
            column_config={
                "Link": st.column_config.LinkColumn(
                    "Apri issue",
                    display_text="↗",
                )
            },
        )
    else:
        st.info("Nessuna issue corrisponde al filtro.")
    return filtered_rows


try:
    token = load_saved_token()
except RuntimeError as error:
    st.error(str(error))
    st.stop()

components = []
try:
    components = fetch_components(BASE_URL, PROJECT_KEY, token)
except RuntimeError as error:
    st.error(f"Non riesco a caricare i componenti da Jira: {error}")

if components:
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
    elif st.session_state.get("dashboard_component_id") != selected_component["id"]:
        st.info("Il componente è cambiato. Premi **Aggiorna dashboard** per caricare i dati.")
    else:
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
            render_filtered_table(
                title,
                rows,
                f"component_{selected_component['id']}_{title}",
            )

st.divider()
st.header("Estrazione issue non chiuse per utente")
assignee = st.text_input(
    "Matricola o identificativo Jira (Assignee)",
    value=DEFAULT_ASSIGNEE,
    help="La ricerca copre tutto il progetto, indipendentemente dal componente selezionato.",
)

if st.button("Estrai issue utente"):
    try:
        st.session_state["assignee_issues"] = fetch_open_issues_for_assignee(
            BASE_URL,
            PROJECT_KEY,
            assignee,
            token,
        )
        st.session_state["assignee_issues_user"] = assignee.strip()
    except RuntimeError as error:
        st.session_state.pop("assignee_issues", None)
        st.session_state.pop("assignee_issues_user", None)
        st.error(f"Non riesco a estrarre le issue per l'utente: {error}")

if (
    "assignee_issues" in st.session_state
    and st.session_state.get("assignee_issues_user") == assignee.strip()
):
    user_issues = st.session_state["assignee_issues"]
    st.metric("Issue non chiuse assegnate", len(user_issues))
    if user_issues:
        rows = [
            {
                "Chiave": issue["key"],
                "Riepilogo": issue["summary"],
                "Tipo": issue["type"],
                "Stato": issue["status"],
                "Creata": issue["created"],
                "Priorità": issue["priority"],
                "Assegnatario": issue["assignee"],
                "Link": f"{BASE_URL.rstrip('/')}/browse/{issue['key']}",
            }
            for issue in user_issues
        ]
        filtered_rows = render_filtered_table(
            "Estrazione utente",
            rows,
            f"assignee_{assignee.strip()}",
        )
        csv_buffer = io.StringIO(newline="")
        writer = csv.DictWriter(
            csv_buffer,
            fieldnames=rows[0].keys(),
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(filtered_rows)
        st.download_button(
            "Scarica CSV filtrato",
            data=("\ufeff" + csv_buffer.getvalue()).encode("utf-8"),
            file_name=f"jira_issue_aperte_{assignee.strip()}.csv",
            mime="text/csv",
        )
    else:
        st.info("Nessuna issue non chiusa trovata per questo utente.")
