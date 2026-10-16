import argparse
import ctypes
from datetime import date
import getpass
import json
import os
import re
import sys
from ctypes import wintypes
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://jira.springlab.enel.com"
PROJECT_KEY = "FBTMOBDR"
PAGE_SIZE = 100
MAX_DESCRIPTION_CHARS = 5000


class DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def credential_path():
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA non è configurata: archivio Windows non disponibile.")
    return Path(local_app_data) / "JiraReleaseSupport" / "pat.dpapi"


def protect_with_dpapi(value, decrypt=False):
    if sys.platform != "win32":
        raise RuntimeError("La memorizzazione protetta è disponibile solo su Windows.")

    raw_value = value.encode("utf-8") if isinstance(value, str) else value
    input_buffer = ctypes.create_string_buffer(raw_value)
    input_blob = DataBlob(
        len(raw_value),
        ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    output_blob = DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    if decrypt:
        operation = crypt32.CryptUnprotectData
        operation.argtypes = [
            ctypes.POINTER(DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(DataBlob),
        ]
    else:
        operation = crypt32.CryptProtectData
        operation.argtypes = [
            ctypes.POINTER(DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(DataBlob),
        ]

    operation.restype = wintypes.BOOL
    if decrypt:
        success = operation(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            0x1,
            ctypes.byref(output_blob),
        )
    else:
        success = operation(
            ctypes.byref(input_blob),
            "Jira Release Support PAT",
            None,
            None,
            None,
            0x1,
            ctypes.byref(output_blob),
        )

    if not success:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        local_free(output_blob.pbData)


def save_token():
    token = getpass.getpass("Nuovo Personal Access Token Jira (input nascosto): ")
    if not token:
        raise RuntimeError("Il token non può essere vuoto.")
    confirmation = getpass.getpass("Ripeti il token per conferma (input nascosto): ")
    if token != confirmation:
        raise RuntimeError("I token inseriti non coincidono; nessun dato è stato salvato.")

    path = credential_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    encrypted = protect_with_dpapi(token)
    temporary_path = path.with_suffix(".tmp")
    try:
        temporary_path.write_bytes(encrypted)
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    print(f"Token salvato cifrato nell'archivio dell'utente Windows: {path}")


def forget_token():
    path = credential_path()
    if path.exists():
        path.unlink()
        print("Token locale eliminato.")
    else:
        print("Nessun token locale salvato.")


def load_token():
    path = credential_path()
    if path.exists():
        try:
            return protect_with_dpapi(path.read_bytes(), decrypt=True).decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise RuntimeError(
                "Impossibile leggere il token cifrato. "
                "Puoi rimuoverlo con --forget-token e salvarne uno nuovo."
            ) from error

    return getpass.getpass("Personal Access Token Jira (input nascosto): ")


def load_saved_token():
    path = credential_path()
    if not path.exists():
        raise RuntimeError(
            "Nessun PAT salvato. Esegui prima `py .\\jira_issues.py --save-token` "
            "da PowerShell."
        )
    try:
        return protect_with_dpapi(path.read_bytes(), decrypt=True).decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise RuntimeError(
            "Impossibile leggere il PAT cifrato. Puoi rimuoverlo con "
            "`py .\\jira_issues.py --forget-token` e salvarne uno nuovo."
        ) from error


def jira_get_json(base_url, path, token, query=None):
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )

    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(
            f"Jira ha risposto con HTTP {error.code} ({error.reason}). "
            "Verifica il PAT e i permessi sul progetto."
        ) from None
    except URLError as error:
        raise RuntimeError(f"Impossibile raggiungere Jira: {error.reason}") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RuntimeError("Jira ha restituito una risposta non valida.") from None


def fetch_components(base_url, project_key, token):
    encoded_project_key = quote(project_key, safe="")
    data = jira_get_json(
        base_url,
        f"/rest/api/2/project/{encoded_project_key}/components",
        token,
    )
    if not isinstance(data, list):
        raise RuntimeError("La risposta Jira non contiene l'elenco dei componenti.")

    components = []
    for component in data:
        if not isinstance(component, dict):
            continue
        component_id = component.get("id")
        name = component.get("name")
        if component_id is None or not isinstance(name, str) or not name.strip():
            continue
        component_id = str(component_id)
        if not component_id.isdigit():
            continue
        components.append({"id": component_id, "name": name})

    if not components:
        raise RuntimeError(f"Il progetto {project_key} non contiene componenti selezionabili.")
    return sorted(components, key=lambda item: (item["name"].casefold(), item["id"]))


def select_component(components):
    print(f"\nComponenti del progetto {PROJECT_KEY}:")
    for index, component in enumerate(components, start=1):
        print(f"{index}. {component['name']} (ID: {component['id']})")

    while True:
        selection = input("Seleziona il numero del componente: ").strip()
        try:
            index = int(selection)
        except ValueError:
            print("Inserisci il numero corrispondente a un componente.")
            continue
        if 1 <= index <= len(components):
            return components[index - 1]
        print(f"Scegli un numero tra 1 e {len(components)}.")


def select_action():
    print("\nSeleziona una funzione:")
    print("1. Ricerca BUG")
    print("2. Analisi issue")
    while True:
        selection = input("Scelta (1-2): ").strip()
        if selection == "1":
            return "bugs"
        if selection == "2":
            return "analyze"
        print("Inserisci 1 oppure 2.")


def parse_issue_keys(value):
    keys = []
    for key in re.split(r"[,;\s]+", value.strip().upper()):
        if not key:
            continue
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", key):
            raise RuntimeError(
                f"Chiave issue non valida: {key!r}. "
                "Usa chiavi Jira come FBTMOBDR-123, separate da virgole."
            )
        if key not in keys:
            keys.append(key)
    if not keys:
        raise RuntimeError("Inserisci almeno una chiave issue.")
    return keys


def jira_value_to_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(jira_value_to_text(item) for item in value)
    if not isinstance(value, dict):
        return ""
    if isinstance(value.get("text"), str):
        return value["text"]
    if value.get("type") == "hardBreak":
        return "\n"

    content = jira_value_to_text(value.get("content", []))
    if value.get("type") in {"paragraph", "heading", "listItem", "blockquote"}:
        return content + "\n"
    return content


def fetch_issues_by_keys(base_url, issue_keys, token):
    key_list = ", ".join(issue_keys)
    jql = f"key in ({key_list}) ORDER BY key ASC"
    issues = {}
    start_at = 0

    while True:
        data = jira_get_json(
            base_url,
            "/rest/api/2/search",
            token,
            {
                "jql": jql,
                "startAt": start_at,
                "maxResults": PAGE_SIZE,
                "fields": "summary,description,status,issuetype,created,environment,priority",
            },
        )
        if not isinstance(data, dict):
            raise RuntimeError("La risposta Jira per l'analisi non è nel formato previsto.")
        page = data.get("issues")
        if not isinstance(page, list):
            raise RuntimeError("La risposta Jira non contiene l'elenco delle issue.")

        for issue in page:
            fields = issue.get("fields") or {}
            status = fields.get("status") or {}
            issue_type = fields.get("issuetype") or {}
            priority = fields.get("priority") or {}
            description = jira_value_to_text(fields.get("description")).strip()
            environment = jira_value_to_text(fields.get("environment")).strip()
            issues[issue.get("key", "").upper()] = {
                "key": issue.get("key", ""),
                "summary": fields.get("summary") or "",
                "status": status.get("name", "Non disponibile"),
                "type": issue_type.get("name", "Non disponibile"),
                "created": fields.get("created") or "",
                "priority": priority.get("name", ""),
                "environment": environment,
                "description": description,
            }

        start_at += len(page)
        total = data.get("total", start_at)
        if not page or start_at >= total:
            return issues


def print_issue_analysis(issue_keys, issues):
    print("\n=== Analisi issue ===")
    for key in issue_keys:
        issue = issues.get(key)
        print(f"\n--- {key} ---")
        if issue is None:
            print("Issue non trovata o non accessibile con le autorizzazioni correnti.")
            continue

        created = issue["created"]
        created_date = created[:10] if created else "Non disponibile"
        print(f"Tipo: {issue['type']}")
        print(f"Stato: {issue['status']}")
        print(f"Creata: {created_date}")
        print(f"Riepilogo: {issue['summary'] or 'Non disponibile'}")
        if issue["priority"]:
            print(f"Priorità: {issue['priority']}")
        if issue["environment"]:
            print(f"Ambiente: {issue['environment']}")
        if issue["description"]:
            description = issue["description"]
            if len(description) > MAX_DESCRIPTION_CHARS:
                description = description[:MAX_DESCRIPTION_CHARS] + "\n[Descrizione abbreviata]"
            print("Descrizione:")
            print(description)
        else:
            print("Descrizione: non presente")

    print(
        "\nPer ricevere un commento sul tipo di bug e consigli su come affrontarlo, "
        "condividi con l'assistente solo i dettagli che puoi divulgare. "
        "La diagnosi non viene generata automaticamente dallo script."
    )


def fetch_issues(base_url, project_key, component_id, token):
    jql = (
        f'project = {project_key} AND '
        f'component = {component_id} AND '
        'issuetype in ("Bug", "Defect") AND '
        'statusCategory in ("To Do", "In Progress") ORDER BY key ASC'
    )
    issues = []
    start_at = 0

    while True:
        data = jira_get_json(
            base_url,
            "/rest/api/2/search",
            token,
            {
                "jql": jql,
                "startAt": start_at,
                "maxResults": PAGE_SIZE,
                "fields": "summary,status,created",
            },
        )

        if not isinstance(data, dict):
            raise RuntimeError("La risposta Jira per la ricerca non è nel formato previsto.")
        page = data.get("issues")
        if not isinstance(page, list):
            raise RuntimeError("La risposta Jira non contiene l'elenco delle issue.")

        for issue in page:
            fields = issue.get("fields") or {}
            status = fields.get("status") or {}
            created = fields.get("created") or ""
            created_date = date.fromisoformat(created[:10]).strftime("%d/%m/%Y") if created else ""
            issues.append(
                (
                    issue.get("key", ""),
                    fields.get("summary") or "",
                    status.get("name", ""),
                    created_date,
                )
            )

        start_at += len(page)
        total = data.get("total", start_at)
        if not page or start_at >= total:
            return issues


def fetch_component_dashboard(base_url, project_key, component_id, token):
    jql = (
        f"project = {project_key} AND component = {component_id} AND "
        'issuetype in ("Bug", "Defect", "Release", "Story", "Epic") AND '
        "statusCategory != Done ORDER BY created DESC, key ASC"
    )
    issues = []
    start_at = 0

    while True:
        data = jira_get_json(
            base_url,
            "/rest/api/2/search",
            token,
            {
                "jql": jql,
                "startAt": start_at,
                "maxResults": PAGE_SIZE,
                "fields": "summary,status,issuetype,created,priority,assignee",
            },
        )
        if not isinstance(data, dict):
            raise RuntimeError("La risposta Jira per la dashboard non è nel formato previsto.")
        page = data.get("issues")
        if not isinstance(page, list):
            raise RuntimeError("La risposta Jira non contiene l'elenco delle issue.")

        for issue in page:
            fields = issue.get("fields") or {}
            status = fields.get("status") or {}
            issue_type = fields.get("issuetype") or {}
            priority = fields.get("priority") or {}
            assignee = fields.get("assignee") or {}
            created = fields.get("created") or ""
            issues.append(
                {
                    "key": issue.get("key", ""),
                    "summary": fields.get("summary") or "",
                    "status": status.get("name", "Non disponibile"),
                    "type": issue_type.get("name", "Non disponibile"),
                    "created": created[:10] if created else "",
                    "priority": priority.get("name", ""),
                    "assignee": assignee.get("displayName", "Non assegnato"),
                }
            )

        start_at += len(page)
        total = data.get("total", start_at)
        if not page or start_at >= total:
            return issues


def print_issues(issues):
    headers = ("CHIAVE", "RIEPILOGO", "STATO", "DATA CREAZIONE")
    rows = [headers, *issues]
    widths = [
        max(len(str(row[index])) for row in rows)
        for index in range(len(headers))
    ]
    for row in rows:
        print("  ".join(str(value).ljust(width) for value, width in zip(row, widths)))

    print(f"\nIssue trovate: {len(issues)}")


def main():
    parser = argparse.ArgumentParser(description="Ricerca BUG e analisi issue Jira.")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--save-token",
        action="store_true",
        help="salva un nuovo PAT cifrato nell'archivio dell'utente Windows",
    )
    actions.add_argument(
        "--forget-token",
        action="store_true",
        help="elimina il PAT cifrato dall'archivio locale",
    )
    args = parser.parse_args()

    if args.save_token:
        save_token()
        return
    if args.forget_token:
        forget_token()
        return

    base_url = BASE_URL
    if not base_url.lower().startswith("https://"):
        raise RuntimeError("L'URL Jira deve usare HTTPS per proteggere il token.")

    token = load_token()
    if not token:
        raise RuntimeError("Il token non può essere vuoto.")

    action = select_action()
    if action == "bugs":
        components = fetch_components(base_url, PROJECT_KEY, token)
        print("\n=== Ricerca BUG ===")
        component = select_component(components)
        print(f"\nRicerca issue per il componente: {component['name']}")
        issues = fetch_issues(base_url, PROJECT_KEY, component["id"], token)
        print_issues(issues)
    else:
        entered_keys = input(
            "\nInserisci una o più chiavi issue separate da virgole: "
        )
        issue_keys = parse_issue_keys(entered_keys)
        issues = fetch_issues_by_keys(base_url, issue_keys, token)
        print_issue_analysis(issue_keys, issues)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyboardInterrupt) as error:
        if isinstance(error, KeyboardInterrupt):
            print("\nOperazione annullata.", file=sys.stderr)
            sys.exit(130)
        print(f"Errore: {error}", file=sys.stderr)
        sys.exit(1)
