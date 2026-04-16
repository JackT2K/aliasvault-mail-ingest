## AliasVault Mail Ingest
AliasVault Mail Ingest is a mail ingestion add on for pulling messages from Microsoft 365 Exchange Online via IMAP using OAuth (application permissions) and delivering them to AliasVault via SMTP.
This project is designed for environments where a shared mailbox (such as a catch-all mailbox) receives mail for many aliases, and AliasVault determines which messages are accepted based on configured aliases.

Link to AliasVault's GitHub Repo: https://github.com/aliasvault/aliasvault

> Transparency note: AI tooling was used to assist in the development of this project. Final design decisions, validation, and responsibility remain with the author.

### FEATURES

Microsoft 365 IMAP using OAuth (no Basic Authentication)

Application-only authentication (no user credentials)

Shared mailbox support

IMAP connection reuse with throttling backoff handling

Alias-aware SMTP routing (RCPT TO per alias)

SQLite-based deduplication (safe to re-run)

Optional mark-as-read behavior

Designed to run continuously as a system service


### HOW IT WORKS

Connects to Exchange Online using IMAP with OAuth (application permissions)

Reads UNSEEN messages from a shared mailbox

Extracts recipients from message headers

Filters recipients to a configured domain (example: @domain.tld)

Sends the message to AliasVault SMTP using the alias as the SMTP recipient

AliasVault accepts or rejects the message based on configured aliases

Successfully processed messages are recorded in a local SQLite database to prevent duplicate processing


AliasVault is responsible for alias enforcement. This service does not attempt to create or guess aliases.

### REQUIREMENTS

Python 3.10 or newer

Microsoft 365 tenant with Exchange Online

App registration with IMAP application permissions

AliasVault SMTP endpoint

Linux host recommended


### SETUP GUIDE
#### STEP 1: CLONE THE REPOSITORY

`` git clone https://github.com/JackT2k/aliasvault-mail-ingest.git ``

`` cd aliasvault-mail-ingest ``

#### STEP 2: INSTALL DEPENDENCIES

`` pip install -r requirements.txt ``

#### STEP 3: CREATE CONFIGURATION FILE
Copy the example configuration:

`` cp config.env.example config.env ``

Edit config.env and populate:

Azure tenant ID

Application (client) ID

Client secret

Shared mailbox address

AliasVault SMTP host and port


#### STEP 4: MICROSOFT 365 CONFIGURATION
The following must already be configured in Microsoft 365:

App registration with IMAP.AccessAsApp application permission

Admin consent granted

Exchange service principal created

Application access policy permitting the shared mailbox

FullAccess permission on the shared mailbox for the application


Tenant configuration is not automated by this project.

#### STEP 5: RUN MANUALLY (TESTING)
Load the environment and start the script:

`` export $(cat config.env | xargs) ``

`` python3 ingest.py `` 

To test without sending mail to AliasVault, set the following in config.env:

DRY_RUN=true 

#### STEP 6: RUN AS A SYSTEM SERVICE (RECOMMENDED)
Copy the project to a persistent location:

`` sudo mkdir -p /opt/aliasvault-mail-ingest ``

`` sudo cp -r . /opt/aliasvault-mail-ingest ``

Install the systemd service:

`` sudo cp systemd/aliasvault-mail-ingest.service /etc/systemd/system/ ``

`` sudo systemctl daemon-reload ``

`` sudo systemctl enable --now aliasvault-mail-ingest ``

View logs with:

`` journalctl -u aliasvault-mail-ingest -f ``

### MARKING MESSAGES AS READ
By default, messages remain unread in the shared mailbox.

To mark messages as read after successful processing, set the following in config.env:

KEEP_UNSEEN=false

MARK_AS_READ=true

### SMTP REJECTIONS
AliasVault may return SMTP 554 errors when a recipient alias is not configured.

This is expected behavior and indicates correct alias enforcement.
