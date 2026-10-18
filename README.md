# Autobackup to Cloud

aaPanel third-party plugin that backs up folders and databases to cloud storage on cron schedules.

![Facebook post](facebook-post.png)

## Features

- Multiple named backup schedules (create / start / stop / delete / run now)
- Folder backup with `zip -x` exclude patterns
- Optional MySQL and PostgreSQL dumps (`{db}-{time}.sql.gz`)
- Keep N latest backups on storage (per schedule)
- Optional keep local zip after upload
- Backup run logs

## Supported storage

| Provider | Type | Notes |
|----------|------|--------|
| Google Drive | OAuth | Desktop `credentials.json` |
| **OneDrive Business** | Microsoft Graph | **Work/school only** — personal OneDrive (`outlook.com` / `live.com`) is **not** supported |
| **SharePoint** | Microsoft Graph | Site document library + Entra ID app |
| AWS S3 | S3 API | |
| Cloudflare R2 | S3-compatible | |
| Backblaze B2 | S3-compatible | |
| DigitalOcean Spaces | S3-compatible | |
| Linode Object Storage | S3-compatible | |
| Wasabi / MinIO / other S3-compatible | S3-compatible | |

### OneDrive Business & SharePoint

1. Register an app in [Microsoft Entra ID](https://entra.microsoft.com/) (Azure AD).
2. Add redirect URI: `http://localhost` (public client / web — used like Google’s copy-code flow).
3. Add **delegated** permissions: `Files.ReadWrite`, `Sites.ReadWrite.All`, `User.Read`, `offline_access`. Grant admin consent if required by your tenant.
4. Create a **client secret** and paste Application (client) ID + secret into the plugin.
5. **OneDrive Business:** link with a Microsoft 365 **work or school** account.
6. **SharePoint:** also set the site URL, e.g. `https://contoso.sharepoint.com/sites/Backups`.

The plugin uses tenant `organizations` so personal Microsoft accounts cannot complete OAuth.

## Requirements

- aaPanel (Linux)
- `zip` on the server
- Panel Python packages (installed by `install.sh`): `boto3`, Google API libs, `msal`, `requests`

## Install

### Import zip (recommended)

1. Build the package:

```bash
python pack.py
```

2. In aaPanel: **App Store → Third-party → Import plugin**
3. Upload `dist/autobackup_cloud_storage_v*.zip`
4. Open the plugin → **Storage** → choose provider → configure → **Test connection**

### Manual copy

```bash
cp -r autobackup_cloud_storage /www/server/panel/plugin/
bash /www/server/panel/plugin/autobackup_cloud_storage/install.sh install
```

## Quick start

1. **Storage** — pick a provider and complete linking / credentials.
2. **Schedules** — source folder, cron, optional databases, retention count.
3. **Run** — use **Run**, or wait for cron.
4. **Logs** — check per-run status.

### Retention

**Keep on storage (latest backups)**:

- `0` — keep all remote archives (default)
- `N > 0` — after each successful upload, delete older archives of that schedule beyond N newest

Local zip cleanup is controlled by **Keep local zip**.

### Reserved POST fields

aaPanel reserves `action`, `s`, `name`, and `a` in plugin POST bodies. Schedule display name is sent as `schedule_name`.

## Project layout

```
autobackup_cloud_storage/
├── info.json
├── index.html
├── install.sh
├── autobackup_cloud_storage_main.py
├── backup_worker.py
├── icon.svg / icon.png
└── acs_lib/          # storage, schedules, dumps, logs, msgraph_*
```

Install path:

```text
/www/server/panel/plugin/autobackup_cloud_storage/
```

## Author

[Tuyen Pham](https://github.com/tuyenlaptrinh)

## License

[MIT](LICENSE.md)
