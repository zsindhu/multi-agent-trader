# Deploy Setup — GitHub Actions to Droplet

This is a one-time setup for the GitHub Actions continuous deployment
workflow. After this is configured, every push to `main` automatically
deploys to the droplet.

## Prerequisites

- SSH access to the droplet (you can already `ssh root@DROPLET_IP`)
- Admin access to the GitHub repo
- About 10 minutes

## Step 1: Generate a dedicated SSH key for GitHub Actions

On your Mac:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/github_actions_premium_trader -C "github-actions-deploy"
```

When prompted for a passphrase, press Enter twice to leave it empty.
GitHub Actions cannot enter a passphrase, so this key MUST have no passphrase.

This creates two files:
- `~/.ssh/github_actions_premium_trader` (private key — never share)
- `~/.ssh/github_actions_premium_trader.pub` (public key — safe to share)

## Step 2: Add the public key to the droplet

Copy the public key to your clipboard:

```bash
cat ~/.ssh/github_actions_premium_trader.pub | pbcopy
```

SSH into the droplet:

```bash
ssh root@YOUR_DROPLET_IP
```

Append the public key to authorized_keys:

```bash
echo "PASTE_THE_PUBLIC_KEY_HERE" >> ~/.ssh/authorized_keys
```

Replace `PASTE_THE_PUBLIC_KEY_HERE` with the actual public key string from
your clipboard. Make sure it's all on one line with no extra whitespace.

Verify the key works by exiting and reconnecting with the new key:

```bash
exit
ssh -i ~/.ssh/github_actions_premium_trader root@YOUR_DROPLET_IP
```

If you log in successfully without a password prompt, the key is working.

## Step 3: Add the private key to GitHub Secrets

Copy the private key to your clipboard:

```bash
cat ~/.ssh/github_actions_premium_trader | pbcopy
```

In your browser:

1. Go to https://github.com/zsindhu/multi-agent-trader
2. Click Settings → Secrets and variables → Actions
3. Click "New repository secret"
4. Create four secrets:

   | Name | Value |
   |---|---|
   | `DROPLET_SSH_KEY` | The full private key (paste from clipboard) |
   | `DROPLET_HOST` | Your droplet IP, e.g. `45.55.56.245` |
   | `DROPLET_USER` | `root` |
   | `DROPLET_DIR` | `/opt/multi-agent-trader` |

For `DROPLET_SSH_KEY`, paste the entire contents of the private key file
including the `-----BEGIN OPENSSH PRIVATE KEY-----` and
`-----END OPENSSH PRIVATE KEY-----` lines.

## Step 4: Test the deploy

Make a trivial commit and push:

```bash
cd ~/Desktop/agent_trader
git commit --allow-empty -m "test: trigger CI deploy"
git push origin main
```

Watch the deploy in real time:

1. Go to https://github.com/zsindhu/multi-agent-trader/actions
2. Click the running workflow
3. Watch each step execute
4. Confirm the final step shows healthy container logs

If the deploy fails, the workflow will show exactly which step broke. Most
common issues:

- **`Permission denied (publickey)`** — the public key wasn't appended to
  authorized_keys correctly. Re-do Step 2.
- **`Host key verification failed`** — `ssh-keyscan` didn't run. Re-check
  the workflow file.
- **`Preflight failed`** — `scripts/preflight.py` raised an error. Fix the
  underlying issue locally, then push again.

## After setup

Your new deploy workflow:

1. Make changes locally
2. `git add` + `git commit`
3. `git push origin main`
4. Watch the GitHub Actions tab in the browser (or on your phone)
5. If the workflow shows green, you're done. The droplet has the new code.
6. Hard refresh the dashboard (Cmd+Shift+R) — actually, with the cache
   busting from the content-hashed bundles, you don't need to hard refresh
   anymore.
