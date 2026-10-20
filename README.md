# Ricerca issue Jira per componente

Questo progetto Python include una dashboard Jira locale e le funzioni da
terminale:

- **Dashboard**: scegli un componente e visualizza in tre sezioni separate i
  Bug/Defect aperti, le Release non chiuse e le Story aperte (senza Epic).
  Le tabelle sono disposte verticalmente; la tabella Bug include anche
  l'assegnatario. Ogni colonna ricercabile ha il proprio campo di filtro
  direttamente sotto il nome; i filtri su più colonne si combinano.
- **Estrazione per utente**: cerca in tutto il progetto le issue non chiuse
  assegnate a una matricola o a un identificativo Jira. Il valore iniziale è
  `A408800`, modificabile dalla dashboard; i risultati possono essere scaricati
  in CSV.
- **Ricerca BUG**: recupera i componenti del progetto `FBTMOBDR`, mostra una
  lista numerata per selezionarne uno e cerca solo le issue di tipo Bug o
  Defect, aperte o in lavorazione. Mostra chiave, riepilogo, stato e data di
  creazione.
- **Analisi issue**: accetta una o più chiavi Jira e mostra stato, tipo,
  riepilogo e informazioni di contesto (descrizione, ambiente e priorità,
  quando disponibili). Puoi condividere qui i dettagli non riservati per
  ricevere un commento sul possibile tipo di bug e suggerimenti per affrontarlo.
  Lo script non genera diagnosi in automatico né invia i dettagli a servizi AI.

Interroga Jira Data Center via HTTPS, usa un Personal Access Token (PAT)
richiesto in modo nascosto e gestisce la paginazione dei risultati. Su Windows
il PAT può anche essere conservato cifrato con DPAPI nell'area locale dell'utente,
al di fuori della cartella del progetto.

## Requisiti

- Python 3.9 o successivo.
- Accesso HTTPS a `https://jira.springlab.enel.com`.
- Un PAT Jira valido con permesso di leggere le issue del progetto.

Le funzioni da terminale usano solo la libreria standard di Python. La
dashboard richiede Streamlit, elencato in `requirements.txt`.

## Protezione del token

Non scrivere il PAT nel codice, in un file di configurazione o nella riga di
comando e non inviarlo in chat. Puoi salvarlo nell'archivio protetto di Windows
con `--save-token`; il prompt non mostra i caratteri digitati e il PAT viene
cifrato tramite DPAPI per l'utente Windows corrente. Il file cifrato è salvato
in `%LOCALAPPDATA%\JiraReleaseSupport\pat.dpapi`, fuori dal repository. In
esecuzioni successive lo script lo decifra in memoria per la richiesta HTTPS.
Per rimuovere la copia locale esegui `py .\jira_issues.py --forget-token`.
Se un PAT viene esposto, revocalo in Jira e creane uno nuovo: la cifratura in
locale non rende sicuro un token già divulgato.

## Esecuzione su Windows

Apri PowerShell e spostati nella cartella del progetto:

```powershell
Set-Location 'C:\Users\a408800\Documents\Repositories\Test\jira-release-support'
py -m pip install -r .\requirements.txt
py -m streamlit run .\dashboard.py
```

La dashboard si apre nel browser locale. Il server è associato a `127.0.0.1`
e non è esposto sulla rete. Dopo aver scelto un componente, premi **Aggiorna
dashboard** per leggere le issue da Jira. Il token deve essere già registrato
nell'archivio protetto di Windows:

```powershell
py .\jira_issues.py --save-token
```

Per usare le funzioni interattive da terminale:

```powershell
py .\jira_issues.py
```

Se il PAT non è ancora stato salvato, esegui il comando `--save-token` da
PowerShell e inseriscilo due volte al prompt nascosto. Lo script da terminale
può anche richiederlo per la singola esecuzione; la dashboard, non essendo
interattiva su stdin, richiede invece il token salvato localmente.

All'avvio scegli `1` per **Ricerca BUG** o `2` per **Analisi issue**. Per
l'analisi puoi inserire una chiave o più chiavi separate da virgole, ad esempio
`FBTMOBDR-123, FBTMOBDR-456`. Lo script recupera le issue visibili al tuo
account e segnala quelle non trovate o non accessibili. La descrizione può
contenere informazioni aziendali: il rapporto viene mostrato solo nel terminale;
prima di condividerlo con l'assistente, controlla che tu possa farlo e rimuovi
eventuali dati riservati.

L'indirizzo Jira e la chiave progetto si modificano all'inizio di
`jira_issues.py`, nelle costanti `BASE_URL` e `PROJECT_KEY`. Il componente viene
scelto interattivamente dalla lista restituita da Jira a ogni esecuzione.

La dashboard ottiene la lista dei componenti chiamando l'endpoint Jira REST
`/rest/api/2/project/FBTMOBDR/components`. Dopo la selezione, cerca le issue
usando la JQL
`project = FBTMOBDR AND component = <ID selezionato> AND issuetype in ("Bug", "Defect", "Release", "Story", "Epic") AND statusCategory != Done ORDER BY created DESC, key ASC`
tramite `/rest/api/2/search`. Usa l'ID del componente scelto, così la query non
dipende da nomi duplicati o da caratteri speciali nel nome. Il filtro per
categoria include tutti gli stati diversi da `Done`, senza dipendere dai nomi
personalizzati degli stati del progetto. Le issue vengono suddivise per tipo:
Bug/Defect, Release e Story (gli Epic non sono inclusi). I nomi dei tipi issue
sono quelli previsti dal progetto Jira. Le tabelle sono in righe verticali e
mostrano conteggio, riepilogo, stato, elapsed in giorni dalla creazione, Fix
Version e link Jira; quella dei Bug mostra anche l'assegnatario. Le chiamate
sono in sola lettura.

La sezione **Estrazione issue non chiuse per utente** cerca in tutto il progetto
con `assignee = "<identificativo>" AND statusCategory != Done`, quindi non è
limitata al componente selezionato. La matricola iniziale `A408800` è
modificabile. L'estrazione mostra chiave, riepilogo, tipo, stato, data di
creazione espressa come elapsed in giorni, Fix Version, assegnatario e link
Jira. Ogni colonna ricercabile ha un campo di filtro direttamente sotto il
nome; i filtri su più colonne si combinano. Il pulsante **Scarica CSV filtrato**
esporta le righe visibili dopo il filtro. Jira deve riconoscere l'identificativo
nel campo Assignee; se la matricola non restituisce risultati, prova il nome
utente Jira corrispondente.
