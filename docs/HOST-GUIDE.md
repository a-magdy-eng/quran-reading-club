# Host guide (the laptop that runs the club)

## 1. Install

1. Unzip `QuranReadingClub-win64.zip` somewhere permanent and writable, for example `C:\QuranReadingClub` or `Documents\QuranReadingClub`.
   Avoid `C:\Program Files`, because the app keeps its data next to the program.
2. Double-click **`QuranReadingClub.exe`**. Nothing else needs to be installed: Python, the web server and the Quran text are all inside.
3. On first start, Windows may ask whether to allow the app on networks. Tick **Private networks** only and click *Allow*.
   If Windows SmartScreen warns about an unknown publisher, click *More info → Run anyway*. The program is not code-signed.

The **host window** opens and your browser opens `http://localhost:8765`.

## 2. Create the group (once)

In the browser on the **host laptop**, click **Create a new group (host)**:

* group name, timezone and daily minimums (default **2 pages** and **20 minutes**), plus maximum members;
* your own account, which becomes the group **administrator**.

For safety, new groups can only be created from the host computer itself.

## 3. Invite friends

Open **Admin → Invite friends**. You can:

* share the **invitation code**, or the invitation link, which fills the code in for them; or
* use **Add a member directly**. This creates the account and shows a temporary password once, for you to pass on.

You can turn invitations off, generate a new code (the old one stops working), and set the maximum group size.

## 4. Let friends connect

The host window lists the addresses to share:

| Row | Who uses it |
|---|---|
| This computer: `http://localhost:8765` | you, on the laptop |
| Friends on your Wi-Fi/LAN: `http://192.168.x.x:8765` | phones and laptops on the same network |
| Friends via Tailscale: `http://100.x.y.z:8765` | friends anywhere, through your private Tailscale network |

### Windows Firewall

Click **Allow through Windows Firewall** in the host window and accept the Windows prompt. This adds two inbound rules for TCP port 8765:

* **Quran Reading Club**: Private networks, local subnet only.
* **Quran Reading Club (Tailscale)**: only the Tailscale address range `100.64.0.0/10`.

To add them by hand, run this in an **administrator** PowerShell:

```powershell
netsh advfirewall firewall add rule name="Quran Reading Club" dir=in action=allow protocol=TCP localport=8765 profile=private remoteip=LocalSubnet
netsh advfirewall firewall add rule name="Quran Reading Club (Tailscale)" dir=in action=allow protocol=TCP localport=8765 profile=any remoteip=100.64.0.0/10
```

Your home Wi-Fi must be set as a **Private** network: *Settings → Network & internet → Wi-Fi → (your network) → Private*.

### Friends anywhere: Share online (built in, easiest)

Click **Share online** in the host window. The first time, the app downloads **cloudflared**, Cloudflare's official free tunnel program (about 55 MB).
It is used only if its Windows digital signature is valid and issued to Cloudflare.

A few seconds later the window shows a secure link such as `https://some-random-words.trycloudflare.com`.
Send it to your friends: it works from mobile data and other homes, and they don't install anything.
The same link appears in the web **Admin → Invite friends** card, and "Copy invite link" uses it automatically.

How it works:

* The laptop makes an **outgoing**, encrypted connection to Cloudflare, and Cloudflare forwards visitors through it.
* **Nothing changes on your router or Windows Firewall**, and your home IP address is not revealed.
* Visitors use HTTPS.

Security while online:

* Anyone with the link can see the sign-in page. Only people with an account, or your invitation code, can get further.
* Requests arriving through the tunnel are **never** treated as the host, so nobody online can create groups.
* Wrong passwords are throttled per visitor IP and per username, and wrong invitation codes per visitor IP.
* Turn invitations off in Admin once everyone has joined.
* Click **Stop sharing**, or close the app, to take the link offline immediately.

Limits of the free quick link:

* **The address changes every time sharing starts.** Share the new link after a restart.
* Cloudflare offers quick tunnels as a free service without an uptime guarantee. That suits a small reading club, but it is not a commercial service.
* Tick **Start sharing automatically** if you want it on whenever the club starts.

**A permanent address (optional):** with a free Cloudflare account and a domain you own, create a *named tunnel*.

1. In the Cloudflare dashboard go to *Zero Trust → Networks → Tunnels → Create a tunnel* and choose *cloudflared*.
2. Copy the **token**.
3. Add a *Public hostname*, for example `quran.yourdomain.com`, pointing to `http://localhost:8765`.
4. In `data\config.json` set:

   ```json
   "cloudflare_tunnel_token": "eyJh...",
   "public_url": "https://quran.yourdomain.com"
   ```

5. Restart the app. **Share online** now always uses that address.

Headless: `QuranReadingClub.exe --headless --online`.

### Friends outside your home: Tailscale (alternative, fully private)

1. Install Tailscale on the host laptop (<https://tailscale.com/download>) and sign in.
2. Each friend installs Tailscale and joins your tailnet: invite them from the Tailscale admin console, or share your machine with them.
3. Friends open the **Tailscale** address shown in the host window, for example `http://100.101.102.103:8765`.
   The MagicDNS name `http://your-laptop-name:8765` also works.

Traffic between Tailscale devices is end-to-end encrypted.

### Don't use port forwarding

Use **Share online** or Tailscale instead, and **don't** set up port forwarding on your router.

The server's own port speaks plain HTTP and refuses any direct connection from a non-private address (only LAN, Tailscale and localhost are allowed), even if a port is opened by mistake.
Internet visitors only ever arrive through the HTTPS tunnel.

## 5. Everyday use

* Start `QuranReadingClub.exe` whenever the group may read. **The laptop must be on and awake** for friends to connect.
  Consider *Settings → System → Power → Screen and sleep → "When plugged in, put my device to sleep after: Never"*.
* **Stop safely** with **Stop server & exit**, or by closing the window and confirming. Every heartbeat is committed to the database as it happens, so nothing is lost even after a crash or power cut.
* Starting the exe a second time opens the browser on the running club instead of starting another copy.

### Start automatically with Windows (optional)

Press `Win + R`, type `shell:startup`, and put a **shortcut** to `QuranReadingClub.exe` in that folder.

### Command-line options

```
QuranReadingClub.exe --headless          run without a window (Ctrl+C to stop)
QuranReadingClub.exe --headless --online also share online through Cloudflare Tunnel
QuranReadingClub.exe --no-browser        don't open the browser on start
QuranReadingClub.exe --port 9000         use another port this time
QuranReadingClub.exe --data D:\club      use another data folder
QuranReadingClub.exe --backup            write a backup and exit
QuranReadingClub.exe --restore FILE.zip  restore a backup (server stopped) and exit
```

## 6. Configuration file

`data\config.json` is created on first start:

```json
{
  "host": "0.0.0.0",
  "port": 8765,
  "allow_remote_group_creation": false,
  "allowed_networks": ["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "..."],
  "token_ttl_days": 30,
  "auto_backup_hours": 24,
  "backups_to_keep": 14,
  "open_browser_on_start": true
}
```

Restart the app after editing it. If you change the port, update the firewall rules too.

The reading rules (pages, minutes, timezone, reset time, inactivity timeout, seconds per page) are set in the web **Admin** page, not in this file.

## 7. Data, backups and restore

Everything lives in the `data` folder next to the exe:

| Path | Contents |
|---|---|
| `data\readingclub.db` | the SQLite database: accounts, groups, sessions, daily records, streaks |
| `data\config.json` | server configuration |
| `data\backups\` | backup zips |
| `data\logs\server.log` | server log, rotated automatically |

The Quran text is bundled inside the program. There are no uploads to store.

**Automatic backups:** the server writes a backup when it starts if the last one is older than 24 hours, and checks again every minute while it runs. It keeps the newest 14.
Backups are taken with SQLite's online backup API, so they are consistent even while people are reading.

**Manual backup:** click **Back up now** in the host window, or run `QuranReadingClub.exe --backup`.

**Restore:** click **Restore…** in the host window and choose a `readingclub-backup-*.zip`.
The server stops, your current data is saved as a `...-pre-restore.zip` backup, the backup is checked (integrity check plus the required tables) and swapped in, and the server restarts.
From the command line: close the app, then run `QuranReadingClub.exe --restore path\to\backup.zip`.

**Moving to a new laptop:** copy the whole folder, including `data`, or install fresh and restore a backup.

**Off-site copy:** occasionally copy `data\backups` to a USB stick or cloud drive.

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| Friends can't connect on Wi-Fi | Add the firewall rules; make sure the network is *Private*; both devices on the same Wi-Fi; try the exact address shown in the host window |
| Friends can't connect via Tailscale | Both devices show *Connected* in Tailscale; use the `100.x` address; the Tailscale firewall rule exists |
| "Port 8765 is used by another program" | Set another `port` in `data\config.json` |
| Timer keeps pausing | Raise the inactivity timeout in Admin; scroll a little while reading |
| Anything else | Look at `data\logs\server.log` |
