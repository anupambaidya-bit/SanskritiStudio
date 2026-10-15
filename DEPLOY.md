# Deploying sanskritistudy.com on Railway + Supabase

About 30 minutes. You need accounts on GitHub, Supabase and Railway. Cloudflare already runs the domain's DNS.

## 1. Put the code on GitHub
1. Create a **private** repository on GitHub, e.g. `sanskriti-app`.
2. Upload the contents of this folder (Add file → Upload files, or `git push`).
   Don't upload a `.env` file.

## 2. Supabase: database and photo storage
1. supabase.com → **New project** → name `sanskriti`, region **Mumbai (ap-south-1)**, set a database password and save it.
2. **Database URL:** click **Connect** (top of the project) → **Session pooler** → copy the URI.
   Replace `[YOUR-PASSWORD]` in it with your database password. This is `DATABASE_URL`.
   (Use the *pooler* URL; Railway can't reach the direct one.)
3. **Storage:** Storage → **New bucket** → name `uploads` → turn on **Public bucket** → Create.
4. **Keys:** Project Settings → **API Keys** → copy the **service_role** secret key. This is `SUPABASE_SERVICE_KEY`.
   Project Settings → **Data API** → copy the **Project URL** (`https://xxxx.supabase.co`). This is `SUPABASE_URL`.
   Keep the service key secret: it can read and write everything.

## 3. Railway: the website
1. railway.com → **New Project** → **Deploy from GitHub repo** → pick `sanskriti-app`.
2. Open the service → **Variables** → add:

   | Variable | Value |
   |---|---|
   | `SECRET_KEY` | a long random string (e.g. from a password generator) |
   | `ADMIN_PHONES` | admin WhatsApp numbers, separated by commas, e.g. `98450 12345, 99000 11111` |
   | `PUBLIC_BASE_URL` | `https://sanskritistudy.com` |
   | `TZ` | `Asia/Kolkata` |
   | `DATABASE_URL` | from step 2.2 |
   | `SUPABASE_URL` | from step 2.4 |
   | `SUPABASE_SERVICE_KEY` | from step 2.4 |
   | `SEED_SAMPLE_DATA` | `0` for an empty start, `1` to start with the sample classes |
   | `WHATSAPP_PROVIDER` | `msg91` (same as NyayaMitra), then add `MSG91_AUTH_KEY` with NyayaMitra's MSG91 auth key. Leave as `console` to show login codes on screen while testing. |

3. Railway redeploys. Open **Settings → Networking → Generate Domain** to get a `*.up.railway.app` link and check the site works there. Log in with an admin number; in demo mode the code shows on screen.

## 4. Daily reminders (9 AM India time)
1. In the same Railway project: **New → GitHub Repo** → the same repo again. Name it `reminders`.
2. Its **Settings → Deploy**: Custom Start Command `flask --app app send-reminders`, Cron Schedule `30 3 * * *` (03:30 UTC = 9:00 IST).
3. Its **Variables**: the same as the website (Railway's "Shared Variables" saves retyping).

## 5. Point sanskritistudy.com at Railway
1. Railway website service → **Settings → Networking → Custom Domain** → `sanskritistudy.com`. Railway shows a CNAME target (and sometimes a TXT record to verify).
2. Cloudflare → sanskritistudy.com → **DNS → Records**:
   - Delete the two old `A` records for `sanskritistudy.com` (the GoDaddy Website Builder ones).
   - Add `CNAME` `@` → the Railway target. Add any TXT record Railway asked for.
   - Edit `www` to `CNAME` → the same Railway target (and add `www.sanskritistudy.com` as a second custom domain in Railway).
   - Leave them **DNS only (grey)** until Railway shows the domain as verified with a certificate, then switch to **Proxied (orange)**.
3. If the site shows a Cloudflare 526 error once proxied, set SSL/TLS mode to **Full** instead of Full (strict).
4. Open https://sanskritistudy.com and log in as admin. Then set the studio address, Maps location and UPI ID in **Admin → Settings**.

## 6. Then cancel GoDaddy
Once the new site is live, cancel the GoDaddy Website Builder and any other GoDaddy products (checklist step 5).

## Notes
- Uploads are capped at 50 MB per file (Supabase free plan limit). Change `MAX_UPLOAD_MB` if you upgrade.
- Supabase free projects pause after about a week with no activity and have limited backups. A live site with regular visitors stays awake; for peace of mind, upgrade to Supabase Pro once the studio relies on it, or export the data now and then (Admin → People → CSV covers the student list).
