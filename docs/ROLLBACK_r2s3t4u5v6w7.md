# Rollback Plan: News Architecture Split (r2s3t4u5v6w7)

## What this migration does

- Creates `macro_news_events` table
- Creates `symbol_news_headlines` table
- Renames `news_headlines` → `news_headlines_legacy` (PostgreSQL only)

## Rollback steps

### 1. Revert code

```bash
git revert <commit-hash>
git push origin main
```

### 2. Downgrade the Alembic migration

```bash
# On the droplet:
docker compose exec app alembic downgrade q1r2s3t4u5v6
```

This will:
- Rename `news_headlines_legacy` back to `news_headlines`
- Drop `symbol_news_headlines` table
- Drop `macro_news_events` table

### 3. Redeploy

```bash
docker compose up -d --build
```

### 4. If migration is partially applied

If the migration errored partway through (some tables exist, some don't):

```sql
-- Check what exists:
SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('macro_news_events', 'symbol_news_headlines', 'news_headlines', 'news_headlines_legacy');

-- If news_headlines was renamed but new tables don't exist:
ALTER TABLE news_headlines_legacy RENAME TO news_headlines;

-- If new tables exist but old one wasn't renamed:
DROP TABLE IF EXISTS macro_news_events;
DROP TABLE IF EXISTS symbol_news_headlines;

-- Force alembic version back:
UPDATE alembic_version SET version_num = 'q1r2s3t4u5v6';
```

Then redeploy with the reverted code.
