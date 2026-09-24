# Features

What the app does today, written as a walk-through for testing it by hand. Start it with
`uv run python desktop.py` (native window) or `uv run streamlit run app.py` (browser).

## Contacts tab

| # | Feature | How to check |
| --- | --- | --- |
| 1 | Contacts are listed in a table, sorted by name, case-insensitively | Add `bob` and `Alice`; `Alice` comes first |
| 2 | A contact has a name, phone, email and address; the row count is shown under the table | Add a contact with every field filled |
| 3 | Search filters on all four fields at once | Search for part of an address or a phone number |
| 4 | Search treats `%` and `_` as plain text, not as wildcards | Search `_`; only contacts that really contain `_` match |
| 5 | The form panel on the right adds a new contact when no row is being edited | Fill it in and press **Add** |
| 6 | A name is required, and an email is checked when it is filled in | Press **Add** with an empty name, or with `bad` as the email |
| 7 | Invalid input stays in the form; a successful add clears it | Trigger an error, correct it, add |
| 8 | Leading and trailing spaces are removed from every field | Add `  Alice  `, then search for `Alice` |
| 9 | Every row has an Edit button that loads that contact into the panel | Press ✏️ on a row |
| 10 | Editing survives a search that hides the contact | Open a contact, then search for something else; the panel stays |
| 11 | **Save** writes the change, closes the panel and shows a toast | Rename a contact |
| 12 | **Cancel** closes the panel without writing | Change a field, press Cancel, reopen the contact |
| 13 | Every row has a Delete button that asks first | Press 🗑 on a row |
| 14 | The dialog deletes on **Delete**, keeps the contact on **Cancel**, and does not come back when dismissed with Esc | Try all three |
| 15 | Deleting another contact leaves an open edit panel and its unsaved input alone | Edit A, type something, delete B |

## MCP tab

| # | Feature | How to check |
| --- | --- | --- |
| 16 | An SSE MCP server can be started and stopped from the tab | Press **Start server**, then **Stop server** |
| 17 | Host and port are configurable; the default is `127.0.0.1:8765` | Start on another port and connect there |
| 18 | A bearer token is optional and off by default; when on, it is pre-filled with a generated value | Switch **Require a bearer token** on |
| 19 | Requests without the token, or with a wrong one, are rejected with 401 | `curl -i http://127.0.0.1:8765/sse` while a token is required |
| 20 | An empty host or an empty token blocks starting, with the reason shown | Clear either field |
| 21 | Binding to a non-local address without a token shows a warning | Set the host to `0.0.0.0` with the token off |
| 22 | A failed start says why, for example that the port is taken, and the app stays usable | Start on a port another program listens on |
| 23 | The tab shows ready-made configuration for the Claude Code CLI, Cursor, VS Code, Windsurf and other clients | Switch between the clients in the picker |
| 24 | The snippets carry the token when one is required, and show a reachable URL for a wildcard bind | Turn the token on; set the host to `0.0.0.0` |
| 25 | Agents get five tools: `list_contacts`, `get_contact`, `create_contact`, `update_contact`, `delete_contact` | Connect an agent and list its tools |
| 26 | A write from an agent shows up in the table at once, with no click and no refresh | Have an agent add a contact while the window is open |
| 27 | A server left running is started again with the app; **Stop** makes that stop | Start the server, close the app, open it again |

## Desktop app

| # | Feature | How to check |
| --- | --- | --- |
| 28 | `desktop.py` opens the app in a native window on a free port on `127.0.0.1` | `uv run python desktop.py` |
| 29 | Closing the window stops the Streamlit server and leaves no process behind | Close it, then look for a leftover `streamlit run` process |
| 30 | Streamlit's developer UI is hidden: no Deploy button, no developer menu | Look at the top right of the window |
| 31 | Errors appear as plain messages; tracebacks go to the terminal only | Trigger a failing start (#22) and compare window and terminal |

## Data and security

| # | Feature | How to check |
| --- | --- | --- |
| 32 | Contacts live in `contacts.db` next to the app and survive a restart | Add a contact, restart |
| 33 | The database runs in WAL mode, so the UI can read while the MCP server writes | `sqlite3 contacts.db "PRAGMA journal_mode;"` |
| 34 | The UI server binds to `localhost` only | `lsof -nP -iTCP -sTCP:LISTEN \| grep python` |
| 35 | `contacts.db` and `mcp_state.json` are git-ignored; the state file holds the token and is readable by its owner only | `git status`, `ls -l mcp_state.json` |

## Known limitations

- Search is case-insensitive for ASCII letters only: `café` does not match `CAFÉ`.
- The UI has no authentication. Anyone who can reach the port can use it, which is why it stays on `localhost`.
- Killing `desktop.py` instead of closing the window leaves the Streamlit process running; the window's native event loop blocks Python's signal handling.
- The MCP server starts with the first browser session, so with `streamlit run` it only comes up once the page is open.
- With the app open in two places at once, deleting a contact in one can make the other show an error until it is reloaded.
