const { Pool } = require('pg');

async function testConnection(name, connectionString) {
  console.log(`\nTesting ${name}...`);
  const pool = new Pool({
    connectionString,
    max: 1,
    connectionTimeoutMillis: 5000
  });

  try {
    const start = Date.now();
    const result = await pool.query('SELECT NOW()');
    const duration = Date.now() - start;
    console.log(`✅ ${name} - Connected in ${duration}ms`);
    console.log(`   Server time: ${result.rows[0].now}`);
    await pool.end();
    return true;
  } catch (error) {
    console.error(`❌ ${name} - Failed:`, error.message);
    await pool.end();
    return false;
  }
}

async function main() {
  // Test both ports
  const session = 'postgresql://postgres.rdobtpugtnmefxplgwyp:0rbZUh8y0Fsvdlry@aws-0-us-east-1.pooler.supabase.com:5432/postgres';
  const transaction = 'postgresql://postgres.rdobtpugtnmefxplgwyp:0rbZUh8y0Fsvdlry@aws-0-us-east-1.pooler.supabase.com:6543/postgres?pgbouncer=true';

  await testConnection('Session Mode (5432)', session);
  await testConnection('Transaction Mode (6543)', transaction);
  
  console.log('\n📝 Note: Vercel functions may need Transaction Mode (6543) for better connection handling.');
}

main().catch(console.error);