# Example: Ladybug Button Feature Development

**Real workflow** showing how multiple skills integrate for Story Bridge PWA development.

## User Request

"Add a ladybug-themed button component that works well for Allie"

## Skill Chain Applied

### 1. Evaluating-Alpha-Beta-Gamma (Multi-Timeframe Planning)

**Alpha Horizon** (today):
```markdown
- Create basic LadybugButton component
- Test one-handed tap target size
- Verify ladybug emoji renders
- Deploy preview for Lu to test
```

**Beta Horizon** (this week):
```markdown
- Add haptic feedback
- Implement animation states
- Create button variations (sizes, colors)
- Document component API
```

**Gamma Horizon** (this month):
```markdown
- Build complete ladybug component library
- Accessibility testing
- Multi-language ladybug names
- Theme system for other animals
```

**Decision**: Focus on Alpha - Lu needs to approve basic button before investing in Beta/Gamma.

### 2. Decomposing-Into-Orthogonal-Tasks

**Orthogonal breakdown**:

```markdown
Task 1: Component file (5 min)
  File: components/LadybugButton.tsx
  Creates: Basic React component structure
  No dependencies (standalone)

Task 2: Styles file (5 min)
  File: components/LadybugButton.module.css
  Creates: Ladybug-themed CSS
  No dependencies (pure styles)

Task 3: Test file (10 min)
  File: components/LadybugButton.test.tsx
  Creates: Component tests
  Mocks: Nothing needed (pure component)

Task 4: Storybook story (5 min)
  File: stories/LadybugButton.stories.tsx
  Creates: Interactive demos
  No dependencies (imports component)

[RESERVE TASK]
Task 5: Integration (5 min)
  File: pages/stories.tsx
  Integrates: All components
  Depends on: Tasks 1-4
```

**Why orthogonal**:
- Different files
- Can develop simultaneously
- No shared state
- Clear integration point

### 3. Midnight-Building (Focused Implementation)

**Session structure**:

```markdown
## Midnight Session - Ladybug Button

Start time: 10:30 PM

**Warm-up** (10:30-10:40):
- Review Lu's feedback on previous components
- Check Story Bridge deployment status
- Load mental context on component patterns

**Deep work** (10:40-11:50):
Core task: Implement LadybugButton

10:40: Create component structure
10:50: Add tap target sizing (min 60px for Lu's tired fingers)
11:00: Implement ladybug emoji + animation
11:10: Test one-handed reach on phone
11:20: Add haptic feedback
11:30: Write component tests
11:40: Create Storybook story
11:50: Integration check

**Wind-down** (11:50-12:00):
- Git commit with descriptive message
- Note: "Lu test needed - deployed to preview"
- Document tomorrow: add sound effects?
```

**Phoenix checkpoints** (every 5 min):
```
10:35: ✓ Component file created
10:40: ✓ Basic structure working
10:45: ✓ Styles applied
10:50: ✓ Tap target verified
... (file changes detected, no research spiral)
```

### 4. Building-With-NextJS (Implementation)

**Component code**:

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
  size = 'large'  // Lu's tired fingers need large default
}) => {
  const handleClick = () => {
    // Haptic feedback for mobile
    if ('vibrate' in navigator) {
      navigator.vibrate(50);
    }
    onClick();
  };

  return (
    <button
      onClick={handleClick}
      className={`${styles.ladybugButton} ${styles[size]}`}
      aria-label={typeof children === 'string' ? children : 'Ladybug button'}
    >
      <span className={styles.ladybugIcon} role="img" aria-label="ladybug">
        🐞
      </span>
      {children}
    </button>
  );
};
```

**Styles** (Lu's standards):

```css
/* LadybugButton.module.css */
.ladybugButton {
  /* LARGE tap target - Lu's tired fingers at 11 PM */
  min-width: 200px;
  min-height: 80px;

  /* CLEAR visual feedback - obvious it's tappable */
  background: linear-gradient(135deg, #ff6b6b 0%, #ee5a52 100%);
  color: white;
  border: 4px solid #c92a2a;
  border-radius: 16px;
  box-shadow: 0 4px 12px rgba(201, 42, 42, 0.3);

  /* OBVIOUS interaction - no ambiguity */
  font-size: 1.4rem;
  font-weight: bold;
  font-family: 'Comic Sans MS', 'Chalkboard SE', 'Arial Rounded MT Bold', sans-serif;

  /* One-handed friendly - thumb reach */
  padding: 20px 32px;
  margin: 12px;

  /* Touch optimization */
  cursor: pointer;
  user-select: none;
  -webkit-tap-highlight-color: transparent;

  /* Animation */
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.ladybugButton:active {
  /* Immediate visual feedback */
  transform: scale(0.95);
  box-shadow: 0 2px 6px rgba(201, 42, 42, 0.5);
}

.ladybugIcon {
  font-size: 2rem;
  margin-right: 8px;
  display: inline-block;
  animation: wiggle 2s ease-in-out infinite;
}

@keyframes wiggle {
  0%, 100% { transform: rotate(-5deg); }
  50% { transform: rotate(5deg); }
}

.small {
  min-width: 120px;
  min-height: 60px;
  font-size: 1.1rem;
  padding: 14px 20px;
}

.large {
  /* Default - already sized above */
}
```

### 5. Phoenix-Interrupting (Quality Monitoring)

**5-minute checkpoints during implementation**:

```markdown
t=0: Start implementation

t=5: CHECKPOINT 1
  Q: Files created? YES - LadybugButton.tsx exists
  Q: Researching? NO - writing code
  Q: Planning? NO - implementing
  Q: "Successfully analyzed"? NO - building
  ✓ Continue

t=10: CHECKPOINT 2
  Q: Files created? YES - .tsx + .module.css
  Q: Researching? NO - styling
  Q: Planning? NO - implementing
  Q: TODOs? NO - working code
  ✓ Continue

t=15: CHECKPOINT 3
  Q: Files created? YES - test file added
  Q: Researching? NO - testing
  Q: Planning? NO - verifying
  Q: Tests passing? YES
  ✓ Continue

t=20: CHECKPOINT 4
  Q: Files created? YES - 4 files total
  Q: Integration working? YES - deployed preview
  Q: Lu-ready? YES - meets standards
  ✓ Complete - ready for Lu approval
```

**No toxic patterns detected** - each checkpoint showed progress.

### 6. Deploying-To-Vercel (Testing)

**Deployment flow**:

```bash
# Local verification
npm run dev
# Test on localhost:3000
# Verify one-handed on phone emulator

# Commit
git add components/LadybugButton.*
git commit -m "feat: add ladybug button for Allie

Lu Testing Checklist:
✓ Large tap target (80px min height)
✓ One-handed thumb reach
✓ Clear visual feedback
✓ Haptic feedback on mobile
✓ Accessible (ARIA labels)
✓ Ladybug animation

Tested at 11 PM (tired-Lu scenario)
Ready for Lu approval 🐞"

# Push to preview branch
git push origin feature/ladybug-button

# Vercel automatically deploys preview
# URL: https://kids-git-feature-ladybug-button-pfin1s-projects.vercel.app

# Share with Lu on her phone
# "Try this tired, one-handed at 11 PM"
```

### 7. Expanding-Then-Compressing (Iteration)

**Lu's feedback** (next morning):

```markdown
Lu: "Button works but ladybug animation distracting during story time"
```

**Expand alternatives**:
```markdown
Option A: Remove animation entirely
Option B: Animation only on hover/tap
Option C: Animation only in menu, not during story
Option D: Subtle animation (less rotation)
```

**Compress to solution**:
```css
/* BEFORE: Always animated */
@keyframes wiggle {
  0%, 100% { transform: rotate(-5deg); }
  50% { transform: rotate(5deg); }
}

/* AFTER: Only animate on hover (Option B) */
.ladybugButton:hover .ladybugIcon {
  animation: wiggle 1s ease-in-out;
}

/* Static during normal use - Lu approved! */
```

**Result**: Lu approves ✓ → The Ladybug Standard 🐞 met

## Skills Integration Summary

```
Request: "Add ladybug button"
    ↓
evaluating-alpha-beta-gamma
    ↓ Focus on Alpha (today)
decomposing-into-orthogonal-tasks
    ↓ 4 independent tasks + 1 integration
midnight-building
    ↓ Focused 11 PM session
building-with-nextjs
    ↓ Implementation
phoenix-interrupting
    ↓ 5-min checkpoints (no drift)
deploying-to-vercel
    ↓ Preview for Lu testing
expanding-then-compressing
    ↓ Iterate on Lu feedback
    ↓
RESULT: Lu approves 🐞
```

## Lessons from This Example

### What Worked

1. **Lu-first testing**: Designed for tired, one-handed use
2. **Orthogonal tasks**: Could develop component, styles, tests simultaneously
3. **Phoenix monitoring**: Caught early when considering "button state management" (over-engineering)
4. **Quick iteration**: Preview → Lu feedback → fix → approve in 24 hours

### Lu's Actual Feedback

**After using for 3 days**:
```
Lu: "The button is perfect. Allie loves tapping the ladybug.
     I can use it one-handed while holding her.
     The haptic feedback makes it feel responsive even when I'm tired.

     This is the standard for all components."
```

**The Ladybug Standard achieved** ✓

### Skills That Prevented Problems

**`phoenix-interrupting`** prevented:
- Research spiral into "best button libraries"
- Over-engineering with complex state management
- Analysis paralysis on animation choices

**`evaluating-alpha-beta-gamma`** prevented:
- Building full component library before Lu approved basic button
- Premature accessibility features (Beta work)
- Theme system (Gamma work) before validating concept

**`midnight-building`** enabled:
- Focused 90-minute implementation
- No interruptions during evening work
- Clean handoff to next day (Lu testing)

## Code Quality Metrics

**MCTS Score**: 0.92/1.0
- ✓ 0.5 Completion (works perfectly)
- ✓ 0.3 Files created (all 4 files)
- ✓ 0.05 Tests (comprehensive)
- ✓ 0.05 Accessibility (ARIA labels)
- ✓ 0.05 Documentation (Storybook)
- -0.03 Minor penalty (animation initially distracting)

**Lu Score**: 10/10 (The only score that matters)

## Application Pattern

**For any Story Bridge feature**:

1. Check against Lu's standards (tired, one-handed, 11 PM)
2. Decompose into orthogonal files (component, styles, tests)
3. Use midnight building for focused implementation
4. Apply phoenix interrupts (prevent over-engineering)
5. Deploy preview immediately
6. Get Lu's approval before proceeding
7. Iterate based on real usage

**The Ladybug Standard** = Lu approves + Allie loves it + Peter can maintain it

**This button became the template for all Story Bridge components.**
