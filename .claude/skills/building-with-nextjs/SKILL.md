---
name: building-with-nextjs
description: Implement Next.js applications following Peter's specific patterns and conventions. Use when creating new components, setting up routing, implementing server actions, or integrating with external APIs. Includes TypeScript patterns.
---

# Building with Next.js

**Purpose**: Build modern React applications with Next.js following established patterns.

## When to Use

- Creating new Next.js applications or features
- Implementing server-side rendering (SSR)
- Building API routes and server actions
- Setting up routing and navigation
- Optimizing performance with Next.js features
- Integrating third-party services

## Core Patterns

### App Router (Next.js 13+)

**File-based routing**:
```
app/
  layout.tsx          # Root layout (wraps all pages)
  page.tsx            # Home page (/)
  about/
    page.tsx          # About page (/about)
  api/
    users/
      route.ts        # API route (/api/users)
```

**Server vs Client Components**:
```tsx
// Server Component (default) - runs on server
export default async function Page() {
  const data = await fetch('https://api.example.com/data');
  return <div>{data.title}</div>;
}

// Client Component - runs in browser
'use client';
export default function InteractiveComponent() {
  const [count, setCount] = useState(0);
  return <button onClick={() => setCount(count + 1)}>{count}</button>;
}
```

### Server Actions

**Form handling without API routes**:
```tsx
// app/actions.ts
'use server';
export async function createUser(formData: FormData) {
  const name = formData.get('name');
  await db.users.create({ name });
  revalidatePath('/users');
}

// app/page.tsx
import { createUser } from './actions';
export default function Page() {
  return (
    <form action={createUser}>
      <input name="name" />
      <button type="submit">Create</button>
    </form>
  );
}
```

### Data Fetching

**Server-side fetching** (recommended):
```tsx
// Fetch on server (automatic caching)
async function getUsers() {
  const res = await fetch('https://api.example.com/users', {
    next: { revalidate: 60 } // Cache for 60 seconds
  });
  return res.json();
}

export default async function Page() {
  const users = await getUsers();
  return <UserList users={users} />;
}
```

**Client-side fetching** (for interactive data):
```tsx
'use client';
import { useEffect, useState } from 'react';

export default function DynamicData() {
  const [data, setData] = useState(null);

  useEffect(() => {
    fetch('/api/data')
      .then(res => res.json())
      .then(setData);
  }, []);

  return <div>{data?.value}</div>;
}
```

## Common Workflows

### Workflow 1: Create New Feature

```bash
# Create component file
mkdir -p app/components
touch app/components/FeatureName.tsx

# Implement component
# Use TypeScript interfaces
# Follow component pattern below

# Create page that uses component
touch app/feature/page.tsx

# Test locally
npm run dev  # http://localhost:3000
```

**Component Pattern**:
```tsx
// app/components/FeatureName.tsx
import { FC } from 'react';

interface FeatureNameProps {
  title: string;
  onAction?: () => void;
}

export const FeatureName: FC<FeatureNameProps> = ({ title, onAction }) => {
  return (
    <div className="feature">
      <h2>{title}</h2>
      <button onClick={onAction}>Action</button>
    </div>
  );
};
```

### Workflow 2: Create API Route

```tsx
// app/api/users/route.ts
import { NextRequest, NextResponse } from 'next/server';

export async function GET(request: NextRequest) {
  const users = await db.users.findMany();
  return NextResponse.json(users);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const user = await db.users.create({ data: body });
  return NextResponse.json(user, { status: 201 });
}
```

### Workflow 3: Add Middleware

```tsx
// middleware.ts (root level)
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  // Auth check
  const token = request.cookies.get('auth-token');
  if (!token && request.nextUrl.pathname.startsWith('/dashboard')) {
    return NextResponse.redirect(new URL('/login', request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: '/dashboard/:path*'
};
```

## Performance Optimization

### Image Optimization

```tsx
import Image from 'next/image';

export default function Page() {
  return (
    <Image
      src="/photo.jpg"
      alt="Description"
      width={500}
      height={300}
      priority  // Load immediately (above fold)
      // or
      loading="lazy"  // Lazy load (below fold)
    />
  );
}
```

### Dynamic Imports

```tsx
import dynamic from 'next/dynamic';

const HeavyComponent = dynamic(() => import('./HeavyComponent'), {
  loading: () => <p>Loading...</p>,
  ssr: false  // Client-side only
});
```

### Route Groups and Layouts

```
app/
  (marketing)/
    layout.tsx       # Marketing layout
    page.tsx         # Homepage
    about/page.tsx
  (dashboard)/
    layout.tsx       # Dashboard layout
    settings/page.tsx
```

## TypeScript Patterns

**Page Props**:
```tsx
interface PageProps {
  params: { id: string };
  searchParams: { [key: string]: string | string[] | undefined };
}

export default function Page({ params, searchParams }: PageProps) {
  return <div>User {params.id}</div>;
}
```

**Server Action Types**:
```tsx
'use server';
type ActionResult = { success: boolean; error?: string };

export async function submitForm(formData: FormData): Promise<ActionResult> {
  try {
    // Process form
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
}
```

## Integration with Other Skills

**Use with**:
- `deploying-to-vercel` - Deploy Next.js apps
- `integrating-supabase` - Backend for Next.js
- `story-bridge-development` - PWA with Next.js
- `managing-wsl-workflows` - Development environment

## Checklist

- [ ] TypeScript configured properly
- [ ] Server vs Client components understood
- [ ] Data fetching strategy chosen
- [ ] Images optimized with next/image
- [ ] API routes or server actions implemented
- [ ] Middleware configured if needed
- [ ] Environment variables in .env.local
- [ ] Build tested locally (npm run build)

## Related Skills

- `deploying-to-vercel` - Deployment
- `integrating-supabase` - Data layer
- `story-bridge-development` - Example application
- `expanding-then-compressing` - Try multiple approaches

## Advanced Topics

See resources in this skill folder:
- `advanced-1-streaming-ssr.md` - React Server Components patterns
- `advanced-2-caching-strategies.md` - Data caching optimization
- `advanced-3-seo-optimization.md` - Metadata and SEO
