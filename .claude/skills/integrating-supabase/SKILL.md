---
name: integrating-supabase
description: Implement Supabase authentication, database queries, and real-time subscriptions. Use when setting up auth flows, creating database schemas, implementing row-level security, or building real-time features.
---

# Integrating Supabase

**Purpose**: Use Supabase as backend-as-a-service for authentication, database, and real-time features.

## When to Use

- Building authentication (signup, login, magic links)
- Creating and querying PostgreSQL database
- Implementing Row Level Security (RLS)
- Real-time data subscriptions
- File storage and CDN
- Serverless functions (Edge Functions)

## Setup and Configuration

### Install Supabase Client

```bash
npm install @supabase/supabase-js
```

### Environment Variables

```.env.local
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-key  # Server-side only
```

### Initialize Client

```tsx
// lib/supabase.ts
import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
```

## Authentication Patterns

### Email/Password Auth

```tsx
// Sign up
const { data, error } = await supabase.auth.signUp({
  email: 'user@example.com',
  password: 'secure-password',
});

// Sign in
const { data, error } = await supabase.auth.signInWithPassword({
  email: 'user@example.com',
  password: 'secure-password',
});

// Sign out
const { error } = await supabase.auth.signOut();

// Get current user
const { data: { user } } = await supabase.auth.getUser();
```

### Magic Link Auth

```tsx
const { data, error } = await supabase.auth.signInWithOtp({
  email: 'user@example.com',
  options: {
    emailRedirectTo: 'https://your-app.com/auth/callback',
  },
});
```

### Protected Routes in Next.js

```tsx
// middleware.ts
import { createMiddlewareClient } from '@supabase/auth-helpers-nextjs';
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export async function middleware(req: NextRequest) {
  const res = NextResponse.next();
  const supabase = createMiddlewareClient({ req, res });

  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session && req.nextUrl.pathname.startsWith('/dashboard')) {
    return NextResponse.redirect(new URL('/login', req.url));
  }

  return res;
}
```

## Database Operations

### Simple Queries

```tsx
// Select all
const { data, error } = await supabase
  .from('users')
  .select('*');

// Select with filter
const { data, error } = await supabase
  .from('users')
  .select('id, name, email')
  .eq('status', 'active')
  .order('created_at', { ascending: false })
  .limit(10);

// Insert
const { data, error } = await supabase
  .from('users')
  .insert({ name: 'John', email: 'john@example.com' });

// Update
const { data, error } = await supabase
  .from('users')
  .update({ status: 'inactive' })
  .eq('id', userId);

// Delete
const { data, error} = await supabase
  .from('users')
  .delete()
  .eq('id', userId);
```

### Joins and Relations

```tsx
// One-to-many
const { data, error } = await supabase
  .from('users')
  .select(`
    id,
    name,
    posts (
      id,
      title,
      created_at
    )
  `);

// Many-to-many
const { data, error } = await supabase
  .from('users')
  .select(`
    id,
    name,
    user_roles (
      roles (
        id,
        name
      )
    )
  `);
```

## Row Level Security (RLS)

### Enable RLS

```sql
-- In Supabase SQL Editor
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- Allow users to read their own data
CREATE POLICY "Users can read own data"
ON users FOR SELECT
USING (auth.uid() = id);

-- Allow users to update their own data
CREATE POLICY "Users can update own data"
ON users FOR UPDATE
USING (auth.uid() = id);

-- Allow anyone to read public data
CREATE POLICY "Public posts readable"
ON posts FOR SELECT
USING (is_public = true);
```

### Bypass RLS (Service Role)

```tsx
// For admin operations only
import { createClient } from '@supabase/supabase-js';

const supabaseAdmin = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!,  // Service role bypasses RLS
);

// Now queries bypass RLS
const { data } = await supabaseAdmin.from('users').select('*');
```

## Real-time Subscriptions

### Subscribe to Changes

```tsx
'use client';
import { useEffect, useState } from 'react';
import { supabase } from '@/lib/supabase';

export default function RealTimeComponent() {
  const [data, setData] = useState([]);

  useEffect(() => {
    // Initial fetch
    supabase.from('messages').select('*').then(({ data }) => setData(data));

    // Subscribe to changes
    const channel = supabase
      .channel('messages')
      .on('postgres_changes',
          { event: '*', schema: 'public', table: 'messages' },
          (payload) => {
            if (payload.eventType === 'INSERT') {
              setData(prev => [...prev, payload.new]);
            } else if (payload.eventType === 'UPDATE') {
              setData(prev => prev.map(item =>
                item.id === payload.new.id ? payload.new : item
              ));
            } else if (payload.eventType === 'DELETE') {
              setData(prev => prev.filter(item => item.id !== payload.old.id));
            }
          }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  return <div>{/* Render data */}</div>;
}
```

## Storage (Files)

### Upload File

```tsx
const { data, error } = await supabase.storage
  .from('avatars')
  .upload(`${userId}/avatar.png`, file, {
    cacheControl: '3600',
    upsert: true  // Overwrite if exists
  });
```

### Get Public URL

```tsx
const { data } = supabase.storage
  .from('avatars')
  .getPublicUrl(`${userId}/avatar.png`);

console.log(data.publicUrl);
```

### Delete File

```tsx
const { error } = await supabase.storage
  .from('avatars')
  .remove([`${userId}/avatar.png`]);
```

## Common Patterns

### Pattern 1: Auth + Database

```tsx
// components/AuthForm.tsx
'use client';
import { useState } from 'react';
import { supabase } from '@/lib/supabase';

export function AuthForm() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  async function handleSignUp() {
    const { data: authData, error: authError } = await supabase.auth.signUp({
      email,
      password,
    });

    if (authError) {
      console.error(authError);
      return;
    }

    // Create user profile in database
    const { error: profileError } = await supabase
      .from('profiles')
      .insert({ id: authData.user!.id, email });

    if (profileError) console.error(profileError);
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); handleSignUp(); }}>
      <input value={email} onChange={(e) => setEmail(e.target.value)} />
      <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      <button>Sign Up</button>
    </form>
  );
}
```

### Pattern 2: Server Actions with Supabase

```tsx
// app/actions.ts
'use server';
import { createServerActionClient } from '@supabase/auth-helpers-nextjs';
import { cookies } from 'next/headers';
import { revalidatePath } from 'next/cache';

export async function createPost(formData: FormData) {
  const supabase = createServerActionClient({ cookies });

  const { data: { user } } = await supabase.auth.getUser();
  if (!user) throw new Error('Not authenticated');

  const title = formData.get('title') as string;
  const content = formData.get('content') as string;

  const { error } = await supabase
    .from('posts')
    .insert({ title, content, user_id: user.id });

  if (error) throw error;

  revalidatePath('/posts');
}
```

## Checklist

- [ ] Supabase project created
- [ ] Environment variables configured
- [ ] Database schema created with RLS policies
- [ ] Authentication flow implemented
- [ ] Queries tested in SQL Editor first
- [ ] RLS policies tested with different user contexts
- [ ] Error handling implemented for all operations
- [ ] Real-time subscriptions cleaned up properly

## Integration with Other Skills

**Use with**:
- `building-with-nextjs` - Next.js integration patterns
- `deploying-to-vercel` - Environment variables deployment
- `story-bridge-development` - Auth and data for kids app
- `evaluating-alpha-beta-gamma` - Alpha (simple auth), Beta (RLS), Gamma (edge functions)

## Related Skills

- `building-with-nextjs` - Application framework
- `deploying-to-vercel` - Deployment with secrets
- `story-bridge-development` - Example implementation

## Advanced Topics

See resources in this skill folder:
- `advanced-1-edge-functions.md` - Serverless functions in Supabase
- `advanced-2-complex-rls.md` - Advanced RLS policies
- `advanced-3-migrations.md` - Database migration workflows
