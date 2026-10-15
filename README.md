# Sanskriti Studio website (Railway + Supabase)

A simple website for Sanskriti Studio (Ragam Gardens). It has two logins, one for students/parents and one for admins. Both log in with a WhatsApp number and a 6-digit code.

## What students can do
- **Sign up on one page**: name, age, community, the classes they're interested in, and an optional free demo. Students under 14 must give a parent or guardian's name.
- **Home page** shows only what needs doing: give demo feedback and pick a batch, pay pending fees, rate ongoing classes. Below that are their classes, upcoming demos (booked in one tap), promotions (ads with photos and videos) and the studio on Google Maps.
- **Calendar**: a month view of every class and demo, with a list view on phones. Tapping a class picks that batch, and tapping a demo books it.
- **Payments**: PhonePe, Google Pay and UPI-QR buttons go straight to the studio's UPI ID. After paying, the student taps "I've paid" and an admin confirms it.

## What admins can do
- **Funnel** (`/admin`): Interested → Demo booked → Feedback pending → Subscribed, then Payments (pending, awaiting confirmation, paid). Each person has one-tap actions such as *Attended*, *Remind*, *Mark paid* and *Invite to demo*, plus a WhatsApp chat link.
- **One-tap WhatsApp reminders**: pending payments, demo feedback, tomorrow's classes, tomorrow's demos, and demo invites for interested students.
- **Demo attendance**: one button marks everyone at a demo as attended. Each of them then gets a WhatsApp message asking for feedback and a batch choice.
- **Classes** (`/admin/classes`): add or edit classes with a photo, fee and calendar colour. Weekly timings and demo dates are edited inline, and a class can be hidden or shown. Adding a demo can WhatsApp the students who are interested in that class.
- **Promotions**: upload a photo or video. The promotion shows on the site, and it can also go out on WhatsApp to everyone, current students, people not yet subscribed, or people interested in one class.
- **People**: search the student list and download it as CSV. **Messages**: a log of every WhatsApp message. **Settings**: studio address, Google Maps location, UPI ID, admin numbers and fee due day.
- Admins get a WhatsApp alert for new registrations, demo bookings, subscriptions with feedback, and payments waiting for confirmation.

## Run it locally
```bash
cd sanskriti-app
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set ADMIN_PHONES to your number
flask --app app run --debug     # open http://localhost:5000
```
With `DATABASE_URL` empty the app uses a local SQLite file (`instance/sanskriti.db`) and saves uploads in `static/uploads`, so nothing else is needed for a trial. On the first run it creates **sample** classes, timings, demos and promotions. To start empty, set `SEED_SAMPLE_DATA=0`. To wipe everything and start over, run `flask --app app reset-db`.

Until WhatsApp is connected, the app runs in **demo mode**. The login code shows on screen, and every message is saved under **Admin → Messages** instead of being sent.

## Hosting: Railway + Supabase
- **Railway** runs the app (`railway.json` / `Procfile`: gunicorn on `$PORT`).
- **Supabase Postgres** holds the data (`DATABASE_URL`). Tables are created automatically on first start.
- **Supabase Storage** holds uploaded photos and videos (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, bucket `uploads`).
- A second Railway service runs `flask --app app send-reminders` once a day on a cron schedule.

Step by step: [DEPLOY.md](DEPLOY.md).

## What needs real accounts or credentials
| Feature | Now | To make it real |
|---|---|---|
| WhatsApp login codes and messages | Demo mode: logged, not sent | **MSG91 (same as NyayaMitra)**: `WHATSAPP_PROVIDER=msg91`, `MSG91_AUTH_KEY`. Login codes use the approved OTP template (defaults to NyayaMitra's number and `nyayamitra_otp` template; override with `MSG91_WA_NUMBER`, `MSG91_OTP_TEMPLATE`, `MSG91_OTP_NAMESPACE`). Other messages go as plain text, which WhatsApp only delivers within 24 hours of the person messaging the number. **Twilio**: set `WHATSAPP_PROVIDER=twilio`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`. **Or Meta WhatsApp Business Cloud API**: `WHATSAPP_PROVIDER=meta`, `META_WA_TOKEN`, `META_WA_PHONE_NUMBER_ID`. |
| WhatsApp message templates | Plain text | WhatsApp only allows free-text messages within 24 hours of the student's last message. For reminders and promotions sent outside that window, get message templates approved in Twilio or Meta. The code is in `whatsapp.py`. |
| PhonePe / Google Pay | UPI deep links + QR to the UPI ID in Settings, confirmed by an admin | Put your real UPI ID in **Settings**. For automatic confirmation, add a payment gateway such as Razorpay, PhonePe PG or Cashfree later. |
| Google Maps | Embed built from the place name in Settings | No key needed. Paste the exact place name or "lat,lng" in **Settings**. |
| Promotion photos/videos on WhatsApp | Text + link | Sent as media when `PUBLIC_BASE_URL` is https. |

## Project layout
```
app.py         routes and business logic
db.py          database helpers (Postgres or SQLite) + sample data
storage.py     uploads (Supabase Storage or local folder)
schema.sql     tables
whatsapp.py    WhatsApp providers (console / twilio / meta)
templates/     pages (admin pages in templates/admin)
static/        style.css, app.js, uploads/ (sample photos)
railway.json   Railway start command
```

## Website look (Admin → Website)

Admins can change the logo, background colour, the "What does Sanskriti mean?" text,
the background music (MP3/M4A) and the homepage carousel photos and videos without
touching code. The default music (`static/uploads/seed-music.mp3`) is an original soft
tanpura-and-flute piece in raga Mohanam, generated for this site. Browsers only allow
sound after a visitor's first tap or click, so the music starts then; visitors can turn
it off with the ♪ button and the choice is remembered.
