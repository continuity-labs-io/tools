# oura-sync

A zero-dependency Python CLI for Oura API V2 OAuth2 authentication and nightly autonomic telemetry distillation.

Since Oura deprecated static Personal Access Tokens (PATs), querying personal ring telemetry requires implementing a full OAuth2 flow with PKCE and handling strictly single-use refresh tokens. `oura-sync` handles the entire handshake, atomic token rotation, and data distillation in a single file using only the Python standard library—producing compact, high-signal JSON built for CLI pipes and AI agents.

## Key Features

- **Zero Dependencies:** Written entirely in the Python 3 standard library (`urllib`, `http.server`, `hashlib`, `json`). No `pip install`, virtual environments, or third-party packages required.
- **Automated OAuth2 + PKCE Handshake:** Spins up an ephemeral local callback listener on `127.0.0.1:8765`, opens the browser for a one-time consent click, and exchanges the authorization code automatically.
- **Atomic Single-Use Token Rotation:** Oura V2 invalidates refresh tokens immediately upon use. Tokens are persisted to `~/.oura_tokens.json` (`0600` permissions) using atomic file replacement (`os.replace`) so interrupted runs never corrupt your credential chain.
- **Heart Rate Geometry & Metabolic Distillation:** Instead of dumping verbose 5-minute time-series arrays that bloat LLM context windows, `oura-sync` inspects the overnight heart rate trajectory, locates the exact timing of the resting heart rate nadir (`nadir_timing_pct`), and classifies the autonomic recovery curve:
  - `hammock` (Nadir between 35%–70% of sleep): Balanced parasympathetic recovery and cleared evening glycemic load.
  - `late_slope` (Nadir after 70% of sleep): Delayed autonomic recovery, typically driven by late meals, glycemic overload, alcohol, or acute evening stress.
  - `early_drop` (Nadir before 35% of sleep): Early exhaustion followed by late-night sympathetic/cortisol elevation (often seen in caloric/glycogen depletion).

## Quick Start

### 1. Register a Local Oura Application

1. Go to the [Oura Developer Applications Portal](https://cloud.ouraring.com/oauth/applications) and click **Create New Application**.
2. Set the **Redirect URI** to:
   ```text
   http://localhost:8765/callback
   ```
3. Save your **Client ID** and **Client Secret**.

### 2. Configure Credentials

Export your credentials as environment variables (or inject them dynamically via your preferred secret manager):

```bash
export OURA_CLIENT_ID="your_client_id"
export OURA_CLIENT_SECRET="your_client_secret"
```

*Optional:* If an environment variable value is prefixed with `cmd:`, `oura-sync` will lazily execute the command only when performing initial auth or refreshing an expired token:

```bash
export OURA_CLIENT_ID="cmd:your-secret-cli read client_id"
export OURA_CLIENT_SECRET="cmd:your-secret-cli read client_secret"
```

### 3. Authenticate (One-Time Setup)

Run the initial OAuth2 handshake:

```bash
python3 src/oura/oura_sync.py --auth
```

Your default browser will open to the Oura authorization screen. Click **Approve**, and the CLI will capture the redirect, exchange the PKCE code, and store your token pair in `~/.oura_tokens.json`.

### 4. Fetch Distilled Telemetry

Pull the last 7 days of primary sleep and readiness records (default):

```bash
python3 src/oura/oura_sync.py
```

Pull a custom window (e.g., 14 days) and write to a file:

```bash
python3 src/oura/oura_sync.py --days 14 --out sleep.json
```

## Example Output

```json
{
  "generated_at": "2026-10-23T12:02:59-07:00",
  "start_date": "2026-10-16",
  "end_date": "2026-10-24",
  "nights": [
    {
      "day": "2026-10-23",
      "bedtime_start": "2026-10-22T22:28:30.000-07:00",
      "bedtime_end": "2026-10-23T08:26:00.000-07:00",
      "total_sleep_hours": 8.12,
      "deep_sleep_hours": 1.77,
      "rem_sleep_hours": 1.89,
      "lowest_heart_rate": 55,
      "average_heart_rate": 60.2,
      "average_hrv": 28,
      "temperature_delta": -0.07,
      "respiratory_rate": 13.62,
      "readiness_score": 89,
      "nadir_timing_pct": 0.552,
      "hr_curve_shape": "hammock"
    }
  ]
}
```

## Security & Privacy Notes

- `~/.oura_tokens.json` is written with strict user-only read/write permissions (`0600`).
- Ensure any exported telemetry files (`*.json`) and local `.env` files remain in `.gitignore` before pushing to a public repository.

## License

MIT
