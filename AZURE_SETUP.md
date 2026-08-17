# Azure Setup — the free tier, and nothing more than that

Ascended STT needs exactly two things from Azure to run at all: a
**Speech key** and a **region**. That's it. This walks through getting
both without spending a cent — Azure's Speech service has a real,
permanent free tier, not just a trial that quietly turns into a bill
later. Fifteen minutes, no card charged, ready to talk.

## 1. Create an Azure account

1. Go to [azure.microsoft.com/free](https://azure.microsoft.com/free)
   and click **Start free**.
2. Sign in with a Microsoft account, or create one if you don't have
   one.
3. Verify your identity — phone number, and yes, a payment card.
   Azure asks for this on every account, free tier or not; it's
   identity verification, not a hidden opt-in. **Nothing gets charged
   automatically** — you'd have to deliberately upgrade a resource to
   a paid tier for that to happen, which this guide never does.
4. Finish the signup. You'll land in the Azure Portal
   ([portal.azure.com](https://portal.azure.com)) — that's home base
   for everything below.

You technically get $200 in trial credit for 30 days on top of this,
but ignore it entirely for this app — the Speech free tier below
doesn't touch that credit and doesn't expire with it.

## 2. Create a Speech resource

1. In the Azure Portal, click the search bar at the top and type
   **Speech**. Select **Speech services** from the results (listed
   under Azure AI services).
2. Click **+ Create**.
3. Fill in the form:
   - **Subscription** — whatever your account created by default
     (often "Azure subscription 1" or "Free Trial").
   - **Resource group** — click **Create new**, name it something
     you'll recognize later, e.g. `ascended-stt-rg`. Just a folder for
     this resource to live in.
   - **Region** — pick whichever's actually closest to you (e.g.
     `East US`, `West Europe`). Lower latency to a closer region;
     otherwise any of them work. **Write down whatever you pick** —
     you'll need its short form in a minute.
   - **Name** — anything, e.g. `ascended-stt-speech`.
   - **Pricing tier** — **this is the one field that actually
     matters: pick `Free F0`**, not `Standard S0`. F0 is 5 hours of
     speech recognition a month, free forever, no card touched. S0 is
     the paid, unlimited tier — skip it unless you specifically want
     to pay for more than 5 hours/month later.
4. Click **Review + create**, then **Create**. Give it about a minute
   to deploy.

## 3. Get your key and region

1. Once deployment finishes, click **Go to resource**.
2. In the left sidebar, click **Keys and Endpoint**.
3. Copy **KEY 1** (KEY 2 works identically — it's just a backup key,
   pick either). This is your `AZURE_SPEECH_KEY`.
4. Note the **Location/Region** value shown on that same page — this
   is your `AZURE_SPEECH_REGION`, and it needs to be the exact short
   form shown here (e.g. `eastus`, not `East US`).

Treat that key like a password. Anyone who has it can rack up usage
against your account.

## 4. Plug it into Ascended STT

Either:

- Copy `.env.example` to `.env` and fill in the two values:
  ```
  AZURE_SPEECH_KEY=your_actual_key_here
  AZURE_SPEECH_REGION=eastus
  ```
- **Or**, easier: launch the app, click the gear icon → **Config**,
  paste the key and region into the Azure Speech Key/Region fields,
  and hit **Save Azure Settings**. It tests the connection for real
  against Azure before saving, so a typo gets caught immediately
  instead of surfacing later as a confusing runtime error.

## Staying inside the free tier

- **F0 = 5 hours of speech recognition per month**, resets on a
  rolling monthly cycle, genuinely free forever at that usage level.
- **Only one F0 resource is allowed per Azure subscription.** If a
  second Speech resource on the same subscription refuses to offer
  the Free tier, that's why — reuse the key/region from the one you
  already have instead of trying to create a second free one.
- Going over 5 hours in a month just stops working until the next
  reset — Azure does not silently switch you to paid and start
  billing. Upgrading to `Standard S0` is a manual, deliberate action
  you'd take in the portal, not something that happens by accident.
- Live translation (the output-language dropdown in Config) runs
  through the same resource but may carry its own separate quota —
  check Azure's current Speech pricing page for the exact up-to-date
  numbers, since these do shift over time and I'd rather point you at
  the source of truth than bake a number in here that goes stale.

## Troubleshooting

- **"Azure rejected this key"** — double-check the key was copied in
  full with no trailing space or newline, and that the region matches
  the portal's short form exactly (`eastus`, not `East US`, not
  `East US 2` if that's not actually what you created).
- **Can't select Free tier on a new resource** — you likely already
  have an F0 resource elsewhere on this subscription. Go find it
  (Azure Portal → search "Speech" → look under your resource group)
  and reuse its key/region instead.
- **Deployment "failed" or stuck** — rare, but a region can
  occasionally be out of capacity for a given tier. Try a different
  region from step 2.

Fifteen minutes in, five free hours a month, forever. Go talk.
