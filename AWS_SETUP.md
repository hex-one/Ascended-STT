# AWS Transcribe Setup

Ascended STT needs three things from AWS to run this engine: an
**Access Key ID**, a **Secret Access Key**, and a **Region**. AWS's
free tier includes 60 minutes of Transcribe streaming per month for
your first 12 months — after that, or once you're past 12 months, it's
pay-as-you-go with no free allowance, so this is the one engine in the
lineup that's genuinely free only for a limited window.

**Before you start:** like Google Cloud above, this engine transcribes
only — Amazon Translate is a separate service this app doesn't chain
into, so the output-language dropdown only offers "No translation."

## 1. Create an AWS account (if you don't have one)

1. Go to [aws.amazon.com](https://aws.amazon.com) and click
   **Create an AWS Account**.
2. Verify your email, phone number, and a payment card — AWS asks for
   this on every account. Nothing gets billed automatically at the
   free-tier usage level described below.

## 2. Create an IAM user for this app

Using your AWS root account's own keys directly works, but a
dedicated, narrowly-scoped user is the safer habit — if this key ever
leaks, the damage is contained to exactly one permission.

1. Search for **IAM** in the AWS Console, click **Users** → **Create
   user**.
2. Name it something like `ascended-stt`. Leave "Provide user access to
   the AWS Management Console" unchecked — this user only needs
   programmatic access.
3. On the permissions step, click **Attach policies directly** and
   search for `AmazonTranscribeFullAccess`. Attach it. (A more
   locked-down custom policy scoped to just
   `transcribe:StartStreamTranscription` also works if you want to go
   narrower — `AmazonTranscribeFullAccess` is just the fast path.)
4. Finish creating the user.

## 3. Create an access key

1. Click into the user you just made → **Security credentials** tab →
   **Create access key**.
2. Choose **Application running outside AWS** as the use case.
3. Copy both the **Access Key ID** and **Secret Access Key** shown —
   the secret key is shown exactly once. If you lose it, you'll need
   to create a new key pair.

Treat both values like a password, especially the secret key. Anyone
who has them can rack up usage against your account.

## 4. Plug it into Ascended STT

Launch the app, click the gear icon → **Config**, choose **AWS
Transcribe** from the Speech Service dropdown, and fill in the Access
Key ID, Secret Access Key, and Region (e.g. `us-east-1` — needs to be a
region where Transcribe streaming is available; most major regions
qualify). Click **Save AWS Settings** — it runs a real credentials
check before saving.

**Note on what that test actually checks:** it verifies the
credentials are real and active (via AWS STS), not that they
specifically have Transcribe permission. If the Config test passes but
nothing transcribes once you start talking, double-check step 2 — the
policy attachment is the more likely gap.

## Staying inside the free tier

- **60 minutes of streaming transcription per month, for your first 12
  months** from account creation — not a rolling allowance like
  Azure's, a one-time 12-month window.
- After 12 months, or past 60 minutes in a month, standard pay-as-you-go
  Transcribe pricing applies automatically — AWS does not stop the
  service the way Azure's F0 tier does. Keep an eye on
  **Billing → Cost Explorer** if you're using this heavily, and check
  [aws.amazon.com/transcribe/pricing](https://aws.amazon.com/transcribe/pricing)
  for current numbers.

## Honesty note

Same as Google Cloud: this engine is built correctly against AWS
Transcribe's documented real-time streaming SDK shape
(`amazon-transcribe`, not boto3's batch client — a live mic needs
streaming, not a file-based job), but it hasn't been tested against a
real AWS account by whoever built it. An unexpected failure is more
likely an untested edge than a wrong API entirely.

## Troubleshooting

- **STS check passes in Config, but nothing transcribes** — almost
  always the IAM policy from step 2. Confirm the user has
  `AmazonTranscribeFullAccess` or an equivalent custom policy attached.
- **"Region not supported"** — not every AWS region offers Transcribe
  streaming. Try `us-east-1` if your first choice doesn't work.
- **Secret key rejected** — secret keys are shown exactly once at
  creation. If you didn't save it, delete the old access key in IAM
  and create a fresh pair.
