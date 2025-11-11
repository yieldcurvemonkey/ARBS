---
name: deploying-to-vercel
description: Deploy Next.js and React applications to Vercel with automatic GitHub integration. Use when setting up new projects, configuring build pipelines, managing environment variables, or troubleshooting deployment issues. Includes webhook automation patterns.
---

# Deploying to Vercel

**Purpose**: Deploy and manage web applications on Vercel with GitHub integration.

## When to Use

- Deploying Next.js or React applications
- Setting up automatic deployments from GitHub
- Managing environment variables securely
- Configuring build and deploy settings
- Troubleshooting deployment failures
- Setting up preview deployments for PRs

## GitHub-Vercel Automatic Pipeline

### How It Works

**Automatic Deployment Flow**:

1. **Push to GitHub**: `git push origin main`
2. **Vercel Webhook**: Detects push via webhook integration
3. **Build Trigger**: Starts new build automatically
4. **Build Process**:
   - Installs dependencies (`npm install`)
   - Runs build command (`npm run build`)
   - Generates static assets and server functions
5. **Deployment**: Deploys to production URL
6. **Instant Updates**: Changes live within 1-2 minutes

**Key URLs**:
- Production: `https://your-app.vercel.app`
- Dashboard: `https://vercel.com/your-username/your-project`
- Each commit gets unique preview URL for testing

### Initial Setup

**Step 1: Connect GitHub Repository**:
```bash
# Ensure code is in GitHub repo
git remote -v  # Verify GitHub remote

# From Vercel dashboard:
# 1. Click "Add New Project"
# 2. Import from GitHub
# 3. Select repository
# 4. Configure project settings
```

**Step 2: Configure Build Settings**:
```
Framework Preset: Next.js (auto-detected)
Root Directory: ./ (or specify if monorepo)
Build Command: npm run build
Output Directory: .next (for Next.js)
Install Command: npm install
```

**Step 3: Set Environment Variables**:
```
# In Vercel dashboard → Settings → Environment Variables
NEXT_PUBLIC_API_URL=https://api.example.com
DATABASE_URL=postgres://...
SECRET_KEY=...

# Specify environments:
✓ Production
✓ Preview
✓ Development
```

## Common Workflows

### Workflow 1: Deploy New Feature

```bash
# Local development
git checkout -b feature/new-component
# ... make changes ...
npm run build  # Test build locally

# Commit and push
git add .
git commit -m "feat: add new component"
git push origin feature/new-component

# Vercel automatically creates preview deployment
# Check URL in Vercel dashboard or GitHub PR

# Merge to main when ready
git checkout main
git merge feature/new-component
git push origin main

# Vercel deploys to production automatically
```

**Timeline**:
- Push to feature branch → Preview deployment in ~1-2 minutes
- Merge to main → Production deployment in ~1-2 minutes

### Workflow 2: Hotfix Production Issue

```bash
# Identify issue in production

# Create hotfix branch
git checkout main
git pull origin main
git checkout -b hotfix/critical-bug

# Fix and test locally
# ... make fix ...
npm run dev  # Test locally
npm run build  # Verify build succeeds

# Deploy quickly
git add .
git commit -m "fix: critical bug in production"
git push origin hotfix/critical-bug

# Check preview deployment looks good

# Merge to main for production
git checkout main
git merge hotfix/critical-bug
git push origin main

# Monitor deployment in Vercel dashboard
```

### Workflow 3: Environment Variable Update

```
# Vercel Dashboard → Project → Settings → Environment Variables

# Add/Edit variable
KEY=NEW_VALUE

# Select environments:
✓ Production  (for main branch)
✓ Preview     (for PR branches)
□ Development (for local only)

# Trigger redeployment
# Option A: Redeploy from dashboard
# Option B: Push empty commit
git commit --allow-empty -m "chore: trigger redeploy"
git push origin main
```

## Monitoring Deployments

### Vercel Dashboard

**Build Logs**:
```
Deployments tab → Select deployment → View logs

Look for:
✓ Installing dependencies
✓ Running build script
✓ Generating optimized production build
✓ Deployment complete
```

**Common Build Errors**:
```
Error: "Module not found"
→ Check package.json includes all dependencies
→ Run npm install locally and commit package-lock.json

Error: "Build failed: command exited with 1"
→ Check build logs for specific error
→ Try running npm run build locally first

Error: "Environment variable not found"
→ Verify env vars set in Vercel dashboard
→ Check variable names match code (case-sensitive)
```

### GitHub Integration

**Deployment Status in PRs**:
```
GitHub PR shows:
- ✓ Vercel build passed
- 🔗 Visit Preview (click to see deployment)
- 📋 View Logs
```

**Automatic Comments**:
Vercel bot comments on PRs with preview URLs

## Advanced Patterns

### Pattern 1: Monorepo Deployment

**Structure**:
```
repo/
  apps/
    web/          ← Deploy this
    admin/        ← Separate project
  packages/
    shared/
```

**Vercel Config** (each app):
```
Root Directory: apps/web
Build Command: cd ../.. && npm run build:web
```

### Pattern 2: Custom Domains

**Setup**:
```
Vercel Dashboard → Project → Settings → Domains

Add domain: example.com
Add www: www.example.com

DNS Configuration:
Type: A
Name: @
Value: 76.76.21.21

Type: CNAME
Name: www
Value: cname.vercel-dns.com
```

### Pattern 3: Build Caching

**Speed up builds** with proper caching:

```json
// package.json
{
  "scripts": {
    "build": "next build",
    "postinstall": "prisma generate"  // Runs after install
  }
}
```

**Vercel automatically caches**:
- `node_modules` (unless package-lock.json changes)
- `.next/cache` (Next.js build cache)
- Outputs from previous builds

### Pattern 4: Preview Deployments for Testing

**Every PR gets unique URL**:
```
PR #123: https://your-app-git-feature-branch-username.vercel.app

Benefits:
- Stakeholder review without deploying to production
- QA testing on real URLs
- Share with clients for feedback
```

## Integration with Story Bridge

**Story Bridge Specific Patterns** (kids project):

```bash
# Repository: https://github.com/pfin/kids.git
# Production: https://kids-pfin1s-projects.vercel.app/

# Deployment flow
cd /home/peter/kids
git status                    # Check changes
git add .
git commit -m "feat: ladybug theme for Allie"
git push origin main

# Vercel deploys automatically
# Monitor: https://vercel.com/pfin1s-projects/kids

# Lu reviews on mobile (the real test!)
# If approved by Lu → Ship it! 🐞
```

**Environment Variables for Kids App**:
```
NEXT_PUBLIC_APP_NAME=StoryBridge
NEXT_PUBLIC_THEME=ladybug
SUPABASE_URL=https://...
SUPABASE_ANON_KEY=...
```

## Checklist

- [ ] GitHub repository connected to Vercel
- [ ] Build settings configured correctly
- [ ] Environment variables set for all environments
- [ ] Custom domains configured (if needed)
- [ ] Build succeeds locally before pushing
- [ ] Preview deployment tested before merging to main
- [ ] Production deployment monitored in dashboard
- [ ] Rollback plan known (previous deployments easily restored)

## Common Pitfalls

**Pitfall 1: Forgetting Environment Variables**
- Problem: Build succeeds but app fails at runtime
- Fix: Check browser console, set missing env vars in Vercel

**Pitfall 2: Build Works Locally But Not on Vercel**
- Problem: Different Node versions or missing dependencies
- Fix: Specify Node version in `package.json`:
```json
"engines": {
  "node": "18.x"
}
```

**Pitfall 3: Slow Build Times**
- Problem: Installing dependencies every time
- Fix: Ensure `package-lock.json` is committed (enables caching)

**Pitfall 4: Not Testing Preview Before Production**
- Problem: Merge to main breaks production
- Fix: Always check preview deployment URL before merging

## Integration with Other Skills

**Use with**:
- `building-with-nextjs` - What to deploy to Vercel
- `integrating-supabase` - Environment variables for backend
- `story-bridge-development` - Allie/Lu deployment workflow
- `planning-multi-timeframe` - Alpha (preview), Beta (production), Gamma (custom domains)

## Related Skills

- `building-with-nextjs` - Application development
- `integrating-supabase` - Backend integration
- `story-bridge-development` - Kids project deployment
- `managing-wsl-workflows` - Local development environment

## Advanced Topics

See resources in this skill folder:
- `advanced-1-serverless-functions.md` - API routes deployment
- `advanced-2-edge-functions.md` - Edge middleware patterns
- `advanced-3-analytics.md` - Vercel Analytics integration
