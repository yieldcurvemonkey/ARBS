---
name: story-bridge-development
description: Build Story Bridge PWA with Allie/Lu personas and ladybug theming. Use when developing features for age-appropriate content, implementing Lu's high standards (IQ 140 S&P analyst), or designing parent-child interaction patterns. Lu is the judge - if she doesn't approve, we've failed.
---

# Story Bridge Development

**Purpose**: Build PWA for Allie with Lu's high standards and ladybug theme.

## Critical Context

### User Personas

**Lu (The Judge)**:
- S&P Global analyst, IQ 140
- Uses app tired, one-handed at 11 PM
- If she doesn't approve → we've failed
- Would she show this to S&P colleagues?

**Chong Chong 虫虫 (The User)**:
- Allie, loves ladybugs
- Age-appropriate content and interaction
- Parent-supervised usage

**Success Metric**: The Ladybug Standard 🐞
- If Lu loves it enough to add ladybug themes → SUCCESS

### Key Decision

**PWA-Only (No APK)**:
- ONE codebase that works everywhere
- Instant updates, no app store
- Modern PWAs can do everything native apps can

## Project Structure

```
/home/peter/kids/
  public/
    pwa/           # PWA assets
      manifest.json
      icons/
  app/
    layout.tsx     # Root layout
    page.tsx       # Landing
    stories/       # Story features
  components/
    Ladybug*.tsx   # Ladybug-themed components
```

**Repository**: https://github.com/pfin/kids.git
**Production**: https://kids-pfin1s-projects.vercel.app/

## Development Principles

### 1. Lu's Testing Standard

**Always test as Lu**:
- Tired (evening usage)
- Skeptical (doesn't trust tech easily)
- One-handed (holding baby/coffee)
- 11 PM (after long day)

**Questions to ask**:
- Is this obvious enough for tired brain?
- Can this be done one-handed?
- Would I be embarrassed to show colleagues?
- Is this truly helping or just flashy tech?

### 2. Allie's Experience

**Age-Appropriate**:
- Simple, clear interactions
- Immediate feedback
- No complex navigation
- Parent can supervise easily

**Ladybug Theme**:
- Cute but not overwhelming
- Consistent visual language
- Delightful micro-interactions

## Common Workflows

### Workflow 1: New Feature Development

```bash
# In WSL
cd /home/peter/kids

# Create feature branch
git checkout -b feature/new-story-mode

# Develop with Lu's standards in mind
npm run dev

# Test checklist:
# [ ] Works one-handed
# [ ] Clear to tired brain
# [ ] Age-appropriate for Allie
# [ ] Ladybug theme consistent
# [ ] Lu would show colleagues

# Commit and deploy
git add .
git commit -m "feat: add interactive story mode

- Simple one-tap interactions
- Ladybug narrator guide
- Parent progress tracking
- Tested with tired-Lu persona"

git push origin feature/new-story-mode

# Check preview deployment
# Test on mobile (critical!)

# If Lu approves → merge to main
git checkout main
git merge feature/new-story-mode
git push origin main
```

### Workflow 2: Ladybug Component

```tsx
// components/LadybugButton.tsx
'use client';
import { FC } from 'react';
import styles from './LadybugButton.module.css';

interface LadybugButtonProps {
  onClick: () => void;
  children: React.ReactNode;
  size?: 'small' | 'large';
}

export const LadybugButton: FC<LadybugButtonProps> = ({
  onClick,
  children,
  size = 'large'
}) => {
  return (
    <button
      onClick={onClick}
      className={`${styles.ladybugButton} ${styles[size]}`}
      aria-label={typeof children === 'string' ? children : 'Ladybug button'}
    >
      <span className={styles.ladybugIcon}>🐞</span>
      {children}
    </button>
  );
};
```

**Styling** (Lu's standards):
```css
/* LadybugButton.module.css */
.ladybugButton {
  /* LARGE tap target (tired, one-handed) */
  min-width: 120px;
  min-height: 60px;

  /* CLEAR visual feedback */
  background: #ff6b6b;
  color: white;
  border: 3px solid #c92a2a;
  border-radius: 12px;

  /* OBVIOUS interaction */
  font-size: 1.2rem;
  font-weight: bold;

  /* Touch-friendly */
  padding: 16px 24px;
  cursor: pointer;
  transition: transform 0.1s;
}

.ladybugButton:active {
  transform: scale(0.95);
}

.ladybugButton.large {
  min-width: 200px;
  min-height: 80px;
}
```

### Workflow 3: PWA Configuration

```json
// public/pwa/manifest.json
{
  "name": "Story Bridge - Chong Chong's Stories",
  "short_name": "Story Bridge",
  "description": "Interactive stories for Allie",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#ff6b6b",
  "icons": [
    {
      "src": "/pwa/icons/icon-192.png",
      "sizes": "192x192",
      "type": "image/png",
      "purpose": "any maskable"
    },
    {
      "src": "/pwa/icons/icon-512.png",
      "sizes": "512x512",
      "type": "image/png"
    }
  ]
}
```

**Install in layout**:
```tsx
// app/layout.tsx
export const metadata = {
  manifest: '/pwa/manifest.json',
  title: 'Story Bridge',
  description: "Chong Chong's Interactive Stories"
};
```

## Lu's Review Checklist

Before showing to Lu, verify:

- [ ] **Mobile-first**: Tested on actual phone (not just desktop)
- [ ] **One-handed**: All interactions reachable with thumb
- [ ] **Tired-brain friendly**: No complex instructions needed
- [ ] **Clear feedback**: Every action has obvious result
- [ ] **Age-appropriate**: Allie can use with parent nearby
- [ ] **Professional quality**: Lu would show S&P colleagues
- [ ] **Ladybug theme**: Consistent and delightful
- [ ] **Performance**: Loads fast even on spotty connection
- [ ] **Offline capable**: PWA works without internet (basic features)

## Technical Patterns

### Pattern 1: Parent Dashboard

```tsx
// app/parent/page.tsx
'use server';
import { supabase } from '@/lib/supabase';
import { redirect } from 'next/navigation';

export default async function ParentDashboard() {
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect('/login');

  const { data: activities } = await supabase
    .from('child_activities')
    .select('*')
    .eq('parent_id', user.id)
    .order('created_at', { ascending: false })
    .limit(10);

  return (
    <div className="parent-dashboard">
      <h1>Allie's Activity</h1>
      {activities?.map(activity => (
        <div key={activity.id}>
          {activity.story_title} - {activity.completed_at}
        </div>
      ))}
    </div>
  );
}
```

### Pattern 2: Age-Appropriate Content Filter

```tsx
// lib/content-filter.ts
export function filterForAge(content: Story[], ageYears: number): Story[] {
  return content.filter(story => {
    // Lu's safety standards
    if (story.min_age > ageYears) return false;
    if (story.requires_supervision && ageYears < 8) return false;
    if (story.has_external_links && ageYears < 10) return false;

    return true;
  });
}
```

### Pattern 3: Offline-First

```tsx
// app/sw.ts (Service Worker)
self.addEventListener('fetch', (event) => {
  event.respondWith(
    caches.match(event.request).then((response) => {
      // Return cached version or fetch new
      return response || fetch(event.request);
    })
  );
});
```

## Deployment Flow

```bash
# Local testing (always first)
npm run dev
# Test on localhost:3000

# Build test (catches issues)
npm run build
# Fixes any build errors

# Commit
git add .
git commit -m "feat: new ladybug story mode for Allie

Lu Testing Checklist:
✓ One-handed operation
✓ Clear tired-brain UX
✓ Age-appropriate content
✓ Professional quality
✓ Ladybug theme consistent"

# Push (triggers Vercel deployment)
git push origin main

# Monitor deployment
# https://vercel.com/pfin1s-projects/kids

# Lu's real test (critical!)
# Share URL with Lu on her phone
# Get feedback before calling it done
```

## Integration with Other Skills

**Use with**:
- `building-with-nextjs` - Next.js patterns
- `deploying-to-vercel` - Automatic deployment
- `integrating-supabase` - User data and auth
- `evaluating-alpha-beta-gamma` - Alpha (prototype for Lu), Beta (refined), Gamma (platform)
- `expanding-then-compressing` - Try multiple UX approaches, compress to simplest
- `midnight-building` - Focused development sessions

## Checklist

- [ ] Feature tested as tired Lu (one-handed, 11 PM)
- [ ] Age-appropriate for Allie
- [ ] Ladybug theme consistent
- [ ] Mobile-first design (tested on actual phone)
- [ ] Offline capability for core features
- [ ] Parent dashboard shows activity
- [ ] Professional quality (Lu would show colleagues)
- [ ] Deployed and monitored on Vercel
- [ ] Lu's actual approval received 🐞

## Common Mistakes

**Mistake 1: Desktop-First Thinking**
- Problem: Looks good on laptop, unusable on phone
- Fix: Design and test mobile-first always

**Mistake 2: Too Complex for Tired Lu**
- Problem: Multi-step flows, unclear navigation
- Fix: Test at 11 PM yourself - if confused, simplify

**Mistake 3: Ignoring Ladybug Theme**
- Problem: Inconsistent visual language
- Fix: Ladybug components library, use consistently

**Mistake 4: Assuming Good Connection**
- Problem: App fails on spotty WiFi
- Fix: Offline-first, progressive enhancement

## Related Skills

- `building-with-nextjs` - Framework
- `deploying-to-vercel` - Deployment
- `integrating-supabase` - Backend
- `managing-wsl-workflows` - Development environment
- `evaluating-alpha-beta-gamma` - Feature prioritization
- `midnight-building` - Focused implementation

## Advanced Topics

See resources in this skill folder:
- `advanced-1-pwa-features.md` - Push notifications, background sync
- `advanced-2-accessibility.md` - WCAG compliance for all users
- `advanced-3-analytics.md` - Privacy-respecting usage tracking
